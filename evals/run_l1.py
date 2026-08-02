"""L1 eval harness v2（客观/主观拆分 + 盲评；eval-plan §9）。

🚨 R8：ground truth（仅客观字段）必须由作者手工标注（`evals/ground_truth.yaml`）。
文件缺失、或 required 客观字段 null 无 open_questions → 报错退出，不用模型输出兜底。

两个子命令：
  run     作者填完 GT 后跑：两模型（qwen-turbo + glm-5.2-fast-preview）跑 15 case →
          客观字段一致率（filer_type/entry_anchor/next_verdict/manual_items，逐字段，exposure 三数）
          + 导出盲评对照（evals/blind_pairs.yaml 隐藏来源随机左右 + evals/_blind_source_map.yaml 源映射）
          + raw extractions（evals/_extractions.json）。
  collect 作者做完盲评后跑：读 evals/blind_verdicts.yaml（A/B/都不对 + 都不对理由）
          + 源映射 → 算主观用户接受率 + 两模型胜率 → 写 eval-report 数据。

客观字段一致率门槛 ≥85%；主观用户接受率门槛 ≥85%（§9.1 预注册，分开报不合并）。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from thesis_watch.config import load_config  # noqa: E402
from thesis_watch.condition_classify import (  # noqa: E402
    _split_conditions,
    classify_condition,
    is_v1_auto,
)
from thesis_watch.entry_agent import build_agent, extract  # noqa: E402
from thesis_watch.tier_map import lookup_tier  # noqa: E402

GT_PATH = ROOT / "evals" / "ground_truth.yaml"
THESIS_DIR = ROOT / "assets" / "notion" / "thesis"
BLIND_PAIRS = ROOT / "evals" / "blind_pairs.yaml"           # 作者看（隐藏来源）
SOURCE_MAP = ROOT / "evals" / "_blind_source_map.yaml"       # harness 内部（源映射）
VERDICTS = ROOT / "evals" / "blind_verdicts.yaml"            # 作者填裁决
EXTRACTIONS = ROOT / "evals" / "_extractions.json"           # raw 输出
L1_RESULT = ROOT / "evals" / "_l1_result.json"
MODELS = ["qwen-turbo", "glm-5.2-fast-preview"]              # 两模型分工（§9.3/§9.4）
OBJECTIVE_REQUIRED = []                                         # 无 required 客观字段（filer_type 从 lookup 自动，entry_anchor/next_verdict optional 手标）
OBJECTIVE_OPTIONAL = ["entry_anchor", "next_verdict"]         # 手标 optional（null 不强制 open_questions）
OBJECTIVE_DERIVED = ["manual_items", "filer_type"]            # 规则/脚本推导（manual_items=classify_condition; filer_type=filer_type_lookup.yaml）
OBJECTIVE_ALL = OBJECTIVE_REQUIRED + OBJECTIVE_OPTIONAL + OBJECTIVE_DERIVED
SUBJECTIVE = ["holding_reason_raw", "key_assumptions", "mirrors"]


def _is_empty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, list):
        return len(v) == 0
    return False


def load_ground_truth() -> list[dict]:
    if not GT_PATH.exists():
        sys.exit(
            f"R8: ground truth 不存在 {GT_PATH}\n→ 拷 evals/ground_truth.template.yaml → ground_truth.yaml，"
            "由作者手工填客观字段，harness 不兜底。"
        )
    data = yaml.safe_load(GT_PATH.read_text(encoding="utf-8"))
    cases = (data or {}).get("cases", [])
    if not cases:
        sys.exit("R8: ground_truth.yaml 无 cases——作者未标注，退出（不兜底）。")
    for c in cases:
        t = c.get("ticker", "?")
        if c.get("exposure") not in ("seen", "clean"):
            sys.exit(f"R8: {t} exposure 缺失或非法（须 seen/clean）")
        if c.get("input_type") not in ("ai_polished", "raw"):
            sys.exit(f"R8: {t} input_type 缺失或非法（须 ai_polished/raw）")
        oqs = {q.get("field") for q in (c.get("open_questions") or []) if isinstance(q, dict)}
        for f in OBJECTIVE_REQUIRED:
            v = c.get(f)
            if v is None and f not in oqs:
                sys.exit(f"R8: {t} 必填客观字段 {f}=null 但无 open_questions——须填值或解释，不兜底")
            if _is_empty(v):
                sys.exit(f"R8: {t} 必填客观字段 {f} 为空——须填值（或 null+open_questions），不兜底")
    return cases


def check_snapshot_ref(args) -> None:
    """校验当前 assets/ git ref 与 GT snapshot_ref；不一致 → 警告，需 --allow-stale-gt 才继续。
    防 assets/ 重新拉取后拿旧 GT 跑出假的不一致率。"""
    if not GT_PATH.exists():
        return  # R8（load_ground_truth）会先报错
    data = yaml.safe_load(GT_PATH.read_text(encoding="utf-8")) or {}
    gt_ref = data.get("snapshot_ref")
    if not gt_ref:
        print("⚠️ ground_truth.yaml 无 snapshot_ref——跳过快照校验（建议补 snapshot_ref 锁版本）")
        return
    import subprocess
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%H", "--", "assets/"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=10)
        current_ref = r.stdout.strip()
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 无法获取 assets/ git ref（{e}）——跳过快照校验")
        return
    if current_ref and current_ref != gt_ref:
        msg = (f"⚠️ 快照版本不一致：GT snapshot_ref={gt_ref[:12]}，当前 assets/={current_ref[:12]}。\n"
               "  GT 可能基于旧快照，跑出假的不一致率。重新核对 GT 或加 --allow-stale-gt 跳过本检查。")
        if not getattr(args, "allow_stale_gt", False):
            sys.exit(msg)
        print(msg + "\n  (--allow-stale-gt 已给，继续)")


def load_input_text(ticker: str) -> str:
    p = THESIS_DIR / f"{ticker}.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
        h = "## Thesis · 为什么买"
        i = text.find(h)
        if i < 0:
            return text.strip()
        start = i + len(h)
        j = text.find("\n## ", start)
        return text[start: j if j > 0 else len(text)].strip()
    schema = THESIS_DIR / "00_schema_and_small_rows.md"
    if not schema.exists():
        sys.exit(f"台账快照缺失：{p} 与 {schema} 都没有")
    s = schema.read_text(encoding="utf-8")
    i = s.find(f"## {ticker}")
    if i < 0:
        return ""
    j = s.find("\n## ", i + 3)
    sec = s[i: j if j > 0 else len(s)]
    m = re.search(r"\*\*Thesis · 为什么买\*\*：(.+?)(\n- \*\*|\Z)", sec, re.S)
    return m.group(1).strip() if m else sec.strip()


def load_break_conditions(ticker: str) -> str:
    """从台账快照读「Thesis 破的条件」段（manual_items GT 规则推导用）。"""
    p = THESIS_DIR / f"{ticker}.md"
    if p.exists():
        text = p.read_text(encoding="utf-8")
    else:
        schema = THESIS_DIR / "00_schema_and_small_rows.md"
        if not schema.exists():
            return ""
        s = schema.read_text(encoding="utf-8")
        i = s.find(f"## {ticker}")
        if i < 0:
            return ""
        j = s.find("\n## ", i + 3)
        text = s[i: j if j > 0 else len(s)]
    h = "## Thesis 破的条件"
    i = text.find(h)
    if i < 0:
        return ""
    start = i + len(h)
    j = text.find("\n## ", start)
    return text[start: j if j > 0 else len(text)].strip()





def _bigrams(text: str) -> set[str]:
    t = re.sub(r"\s+", "", text or "")
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _overlap(a: str, b: str) -> bool:
    ba, bb = _bigrams(a), _bigrams(b)
    return bool(ba and bb and len(ba & bb) >= 2)


def _oq_map(gt: dict) -> dict:
    return {q.get("field"): q.get("reason", "") for q in (gt.get("open_questions") or []) if isinstance(q, dict)}


def _date_match(gt_date: str, a_date: str) -> bool:
    """比 date：归一到 (year, month_int)；季度→中月(Q1=2/Q2=5/Q3=8/Q4=11)。
    GT 月精度(YYYY-MM) → ±1 月命中；GT 季度精度(YYYY-Qn) → 精确(±0)。
    【九】修正：原 _overlap 比中文 event 文本（「财报」二字即命中，季度错了也算对）。"""
    def to_ym(d):
        m = re.match(r"(\d{4})-(\d{2})", d or "")
        if m:
            return (int(m.group(1)), int(m.group(2)), "month")
        m = re.match(r"(\d{4})-Q(\d)", d or "", re.I)
        if m:
            q = int(m.group(2))
            return (int(m.group(1)), q * 3 - 1, "quarter")  # Q1→2, Q2→5, Q3→8, Q4→11
        m = re.match(r"(\d{4})", d or "")
        if m:
            return (int(m.group(1)), None, "year")
        return None
    g, a = to_ym(gt_date), to_ym(a_date)
    if not g or not a:
        return False
    if g[2] == "year" or a[2] == "year":
        return g[0] == a[0]
    gi = g[0] * 12 + g[1]
    ai = a[0] * 12 + a[1]
    tol = 1 if g[2] == "month" else 0  # GT 月精度 → ±1 月
    return abs(gi - ai) <= tol


def score_objective(ext: dict | None, gt: dict, break_conditions: str, filer_lookup: dict) -> dict:
    """客观字段评分。filer_type 从 filer_type_lookup.yaml 读（【十一】移出 GT）；
    manual_items 由 classify_condition 推导；entry_anchor/next_verdict 从 GT（手标）。"""
    ext = ext or {}
    oqs = _oq_map(gt)
    fields: dict = {}
    ambiguous: dict = {}

    # filer_type: 从 filer_type_lookup.yaml 读（不从 GT 手标；缺失→sys.exit 不兜底）
    ticker = gt.get("ticker", "")
    gt_ft = filer_lookup.get(ticker)
    if gt_ft is None:
        sys.exit(f"R8: filer_type_lookup.yaml 缺 {ticker}——跑 scripts/fetch_filer_type.py 补齐，不兜底")
    fields["filer_type"] = ext.get("filer_type") == gt_ft

    # manual_items: 规则推导 GT（condition_classify，不手标）。
    # ETF/fund → 全 manual（v1 不接 index/fund/price）；个股 → 任一破条件非 v1-auto（classify_condition）→ 期望 manual。
    a_mi = ext.get("manual_items", []) or []
    if gt_ft == "etf_fund":
        expected = True
    else:
        expected = False
        for c, _ in _split_conditions(break_conditions):
            labels = classify_condition(c)
            if labels and not is_v1_auto(labels):
                expected = True
                break
    fields["manual_items"] = (len(a_mi) > 0) == expected

    # entry_anchor: anchor_type 精确枚举匹配 + anchor_value 相对误差 ≤5%（分开报，不合并）
    # 【九】修正：原 _overlap bigram 让 P/E 家族互相误命中（ttm_gaap_pe vs forward_non_gaap_pe 共享 6 bigram）→ 虚高
    gt_ea = gt.get("entry_anchor")
    if gt_ea is None:
        ambiguous["entry_anchor_type"] = oqs.get("entry_anchor", "(无说明)")
        ambiguous["entry_anchor_value"] = oqs.get("entry_anchor", "(无说明)")
    else:
        a_ea = ext.get("entry_anchor")
        gt_type = (gt_ea.get("anchor_type") if isinstance(gt_ea, dict) else None) or ""
        a_type = (a_ea.get("anchor_type") if isinstance(a_ea, dict) else None) or ""
        fields["entry_anchor_type"] = bool(gt_type) and (gt_type == a_type)
        gt_val = gt_ea.get("anchor_value") if isinstance(gt_ea, dict) else None
        a_val = a_ea.get("anchor_value") if isinstance(a_ea, dict) else None
        if gt_val is None or a_val is None:
            ambiguous["entry_anchor_value"] = "GT 或输出 value 为 null"
        else:
            try:
                gv, av = float(gt_val), float(a_val)
                fields["entry_anchor_value"] = (abs(av - gv) / abs(gv) <= 0.05) if gv != 0 else (av == 0)
            except (TypeError, ValueError):
                ambiguous["entry_anchor_value"] = "value 非数值"

    # next_verdict: 比 date（YYYY-Qn 精确；GT 月精度 → ±1 月命中）；event 文本不参与判定，仅 case 明细打印
    # 【九】修正：原 _overlap 比中文 event 文本（「财报」二字即命中，季度错也算对）→ 虚高
    gt_nv = gt.get("next_verdict")
    if gt_nv is None:
        ambiguous["next_verdict"] = oqs.get("next_verdict", "(无说明)")
    else:
        a_nv = ext.get("next_verdict")
        gt_date = (gt_nv.get("date") if isinstance(gt_nv, dict) else None) or ""
        a_date = (a_nv.get("date") if isinstance(a_nv, dict) else None) or ""
        if not gt_date or not a_date:
            ambiguous["next_verdict"] = "GT 或输出 date 缺失"
        else:
            fields["next_verdict"] = _date_match(gt_date, a_date)
    return {"fields": fields, "ambiguous": ambiguous}


def _aggregate(rows: list[dict]) -> dict:
    """逐字段客观一致率（scored 分母 = 非 null case）+ 模糊数。"""
    out = {"per_field": {}, "ambiguous_count": {}, "n_pass": 0}
    n_pass = [r for r in rows if r["status"] == "pass"]
    out["n_pass"] = len(n_pass)
    for f in OBJECTIVE_ALL:
        scored = [r for r in n_pass if f in r["fields"]]
        amb = [r for r in n_pass if f in r["ambiguous"]]
        denom = len(scored)
        if denom == 0:
            out["per_field"][f] = {"rate": None, "matched": 0, "denom": 0, "note": "无有效样本（全 null/ambiguous）"}
        else:
            out["per_field"][f] = {
                "rate": round(sum(1 for r in scored if r["fields"][f]) / denom, 4),
                "matched": sum(1 for r in scored if r["fields"][f]),
                "denom": denom,
            }
        out["ambiguous_count"][f] = len(amb)
    return out


def cmd_run(args) -> int:
    check_snapshot_ref(args)
    cfg = load_config(str(ROOT / args.config))
    gt_cases = load_ground_truth()
    # filer_type 从 filer_type_lookup.yaml 读（【十一】移出 GT；缺失→sys.exit 不兜底）
    lookup_path = ROOT / "evals" / "filer_type_lookup.yaml"
    if not lookup_path.exists():
        sys.exit(f"R8: filer_type_lookup.yaml 不存在 {lookup_path}——跑 scripts/fetch_filer_type.py 生成，不兜底")
    _lookup_data = yaml.safe_load(lookup_path.read_text(encoding="utf-8")) or {}
    filer_lookup = {t: v.get("filer_type") for t, v in ((_lookup_data.get("tickers") or {}).items())}
    rng = random.Random(20260802)  # 确定性随机（无 Math.random 限制——这是 stdlib，可用）

    agents = {}
    for m in MODELS:
        agents[m], _, _ = build_agent(cfg, model_override=m)

    extractions: dict = {}   # {ticker: {model: {extraction dict, metrics}}}
    obj_rows: list = []
    blind_pairs: list = []
    source_map: list = []

    for gc in gt_cases:
        ticker = gc["ticker"]
        text = load_input_text(ticker)
        break_conds = load_break_conditions(ticker)
        extractions[ticker] = {}
        per_model_obj = {}
        per_model_subj = {}
        for m in MODELS:
            res = extract(agents[m], text, cfg, mode="A")  # §9.6 A/B 暂缓，只跑 A
            ext = res["extraction"]
            ext_d = ext.model_dump() if ext else None
            extractions[ticker][m] = {"extraction": ext_d, "metrics": {
                "status": res.get("status"), "dur_s": res.get("dur_s"),
                "in_tok": res.get("in_tok"), "out_tok": res.get("out_tok"),
                "retries_429": res.get("retries_429"), "error": res.get("error"),
            }}
            per_model_obj[m] = score_objective(ext_d, gc, break_conds, filer_lookup)
            per_model_subj[m] = {f: (ext_d or {}).get(f) for f in SUBJECTIVE}
            obj_rows.append({
                "ticker": ticker, "exposure": gc.get("exposure"), "input_type": gc.get("input_type"),
                "model": m, "fields": per_model_obj[m]["fields"], "ambiguous": per_model_obj[m]["ambiguous"],
                "status": res.get("status"),
            })
            print(f"{ticker:8s} {gc.get('exposure'):5s} {m:22s} {res.get('status'):8s} "
                  f"obj={ {k:v for k,v in per_model_obj[m]['fields'].items() if isinstance(v,bool)} }")

        # 盲评对照：每个主观字段随机左右、隐藏来源
        pair = {"case": ticker, "fields": {}}
        smap = {"case": ticker, "fields": {}}
        for f in SUBJECTIVE:
            left_m, right_m = ("qwen-turbo", "glm-5.2-fast-preview") if rng.random() < 0.5 else ("glm-5.2-fast-preview", "qwen-turbo")
            pair["fields"][f] = {"A": per_model_subj[left_m].get(f), "B": per_model_subj[right_m].get(f)}
            smap["fields"][f] = {"A": left_m, "B": right_m}
        blind_pairs.append(pair)
        source_map.append(smap)

    # 客观一致率（逐模型 × exposure 三数）
    summary = {"models": {}}
    for m in MODELS:
        mrows = [r for r in obj_rows if r["model"] == m]
        summary["models"][m] = {
            "总体": _aggregate(mrows),
            "clean": _aggregate([r for r in mrows if r.get("exposure") == "clean"]),
            "seen": _aggregate([r for r in mrows if r.get("exposure") == "seen"]),
        }

    L1_RESULT.write_text(json.dumps({
        "summary": summary, "obj_rows": obj_rows, "extractions": extractions,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    BLIND_PAIRS.write_text(yaml.safe_dump(blind_pairs, allow_unicode=True, sort_keys=False), encoding="utf-8")
    SOURCE_MAP.write_text(yaml.safe_dump(source_map, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # 生成空白盲评裁决模板（作者填 pick: A/B/both_wrong + 都不对理由）；不覆盖已填的
    if not VERDICTS.exists():
        blank = [{"case": gc["ticker"], "fields": {f: {"pick": "", "acceptable": "", "reason": ""} for f in SUBJECTIVE}}
                 for gc in gt_cases]
        VERDICTS.write_text(yaml.safe_dump(blank, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"\n=== 客观一致率（逐模型 × exposure）===")
    for m, gs in summary["models"].items():
        for gname, agg in gs.items():
            print(f"  {m:22s} / {gname:6s}: { {k:v['rate'] for k,v in agg['per_field'].items()} } n_pass={agg['n_pass']}")
    print(f"\n盲评对照（作者看，隐藏来源）: {BLIND_PAIRS}")
    print(f"源映射（harness 内部）       : {SOURCE_MAP}")
    print(f"L1 结果（含 extractions）    : {L1_RESULT}")
    print("\n下一步：作者填 evals/blind_verdicts.yaml（每 case 每主观字段 pick A/B + acceptable yes/no + 不接受理由）→ 再跑 collect。")
    return 0


def cmd_collect(args) -> int:
    if not VERDICTS.exists():
        sys.exit(f"盲评裁决不存在 {VERDICTS}——作者填 blind_verdicts.yaml 后再跑 collect。")
    if not SOURCE_MAP.exists():
        sys.exit(f"源映射不存在 {SOURCE_MAP}——先跑 run。")
    verdicts = yaml.safe_load(VERDICTS.read_text(encoding="utf-8")) or []
    smap = {s["case"]: s for s in (yaml.safe_load(SOURCE_MAP.read_text(encoding="utf-8")) or [])}
    if not verdicts:
        sys.exit("blind_verdicts.yaml 无裁决——作者填完再跑 collect。")

    total = 0
    accepted = 0  # acceptable=yes
    win = {"qwen-turbo": 0, "glm-5.2-fast-preview": 0}  # pick
    fails = []
    for v in verdicts:
        case = v.get("case")
        for f in SUBJECTIVE:
            fv = v.get("fields", {}).get(f, {})
            pick = fv.get("pick")           # "A" | "B"
            acceptable = fv.get("acceptable")  # "yes" | "no"
            reason = fv.get("reason")
            total += 1
            sm = smap.get(case, {}).get("fields", {}).get(f, {})
            if pick in ("A", "B"):
                winner = sm.get(pick)
                if winner in win:
                    win[winner] += 1
            if acceptable == "yes":
                accepted += 1
            else:  # no / both_wrong / 非法
                fails.append({"case": case, "field": f, "pick": pick, "reason": reason or "(无理由)"})

    acceptance = round(accepted / total, 4) if total else 0
    print(f"=== 主观字段盲评结果（【九】拆偏好与接受两问）===")
    print(f"  总数 {total} | 接受(acceptable=yes) {accepted} | 不接受 {total - accepted}")
    print(f"  用户接受率 = {acceptance} (门槛 ≥0.85，§9.1)")
    for m, w in win.items():
        print(f"  {m:22s} 胜率 = {round(w/total,4) if total else 0} (被 pick {w}/{total}，仅选型不设门槛)")
    if fails:
        print(f"\n  不接受明细（{len(fails)} 条）:")
        for fl in fails:
            print(f"    {fl['case']} / {fl['field']} (pick={fl['pick']}): {fl['reason']}")
    out = {"acceptance_rate": acceptance, "total": total, "accepted": accepted,
           "win_rate": {m: round(w/total,4) if total else 0 for m, w in win.items()},
           "fails": fails}
    (ROOT / "evals" / "_blind_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  结果: evals/_blind_result.json")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="L1 eval harness v2（客观一致率 + 主观盲评）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="两模型跑 case → 客观一致率 + 导出盲评对照")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--allow-stale-gt", action="store_true", help="assets/ git ref 与 GT snapshot_ref 不一致时仍继续（GT 可能过时）")
    sub.add_parser("collect", help="读盲评裁决 → 接受率 + 胜率")
    args = ap.parse_args()
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "collect":
        return cmd_collect(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
