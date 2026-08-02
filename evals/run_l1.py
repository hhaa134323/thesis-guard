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
from thesis_watch.condition_classify import classify_condition, is_v1_auto  # noqa: E402
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
OBJECTIVE_REQUIRED = ["filer_type"]                          # 手标 required 客观（null 须 open_questions）
OBJECTIVE_OPTIONAL = ["entry_anchor", "next_verdict"]         # 手标 optional（null 不强制 open_questions）
OBJECTIVE_DERIVED = ["manual_items"]                          # 规则推导（is_price_pattern, data-sources.md），不手标、不入 GT
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


def _split_conditions(text: str) -> list[str]:
    """粗粒度切分破条件（与 scripts/classify_conditions.py 同逻辑）。"""
    if not text:
        return []
    parts = re.split(r"[①②③④⑤⑥⑦⑧⑨⑩•；;\n]", text)
    return [p.strip(" -—·：:（）()，,。 \t") for p in parts if len(p.strip(" -—·：:（）()，,。 \t")) > 4]


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


def score_objective(ext: dict | None, gt: dict, break_conditions: str) -> dict:
    """客观字段评分。手标字段（filer_type/entry_anchor/next_verdict）GT null → ambiguous（剔除分母）；
    规则推导字段（manual_items）由 classify_condition(break_conditions) 推导 GT（非 is_price_pattern——
    is_price_pattern 判断方向错，见 condition_classify.py + docs/condition-classification.md），不手标。"""
    ext = ext or {}
    oqs = _oq_map(gt)
    fields: dict = {}
    ambiguous: dict = {}

    # filer_type: 精确
    gt_v = gt.get("filer_type")
    if gt_v is None:
        ambiguous["filer_type"] = oqs.get("filer_type", "(无说明)")
    else:
        fields["filer_type"] = ext.get("filer_type") == gt_v

    # manual_items: 规则推导 GT（condition_classify，不手标）。
    # ETF/fund → 全 manual（v1 不接 index/fund/price）；个股 → 任一破条件非 v1-auto（classify_condition）→ 期望 manual。
    a_mi = ext.get("manual_items", []) or []
    if gt.get("filer_type") == "etf_fund":
        expected = True
    else:
        expected = False
        for c in _split_conditions(break_conditions):
            info = classify_condition(c)
            if info is not None and not is_v1_auto(info):
                expected = True
                break
    fields["manual_items"] = (len(a_mi) > 0) == expected

    # entry_anchor: anchor_type 匹配
    gt_ea = gt.get("entry_anchor")
    if gt_ea is None:
        ambiguous["entry_anchor"] = oqs.get("entry_anchor", "(无说明)")
    else:
        a_ea = ext.get("entry_anchor")
        fields["entry_anchor"] = bool(a_ea) and _overlap(
            a_ea.get("anchor_type", "") if isinstance(a_ea, dict) else str(a_ea),
            gt_ea.get("anchor_type", "") if isinstance(gt_ea, dict) else str(gt_ea),
        )

    # next_verdict: event 匹配
    gt_nv = gt.get("next_verdict")
    if gt_nv is None:
        ambiguous["next_verdict"] = oqs.get("next_verdict", "(无说明)")
    else:
        a_nv = ext.get("next_verdict")
        fields["next_verdict"] = bool(a_nv) and _overlap(
            a_nv.get("event", "") if isinstance(a_nv, dict) else str(a_nv),
            gt_nv.get("event", "") if isinstance(gt_nv, dict) else str(gt_nv),
        )
    return {"fields": fields, "ambiguous": ambiguous}


def _aggregate(rows: list[dict]) -> dict:
    """逐字段客观一致率（scored 分母 = 非 null case）+ 模糊数。"""
    out = {"per_field": {}, "ambiguous_count": {}, "n_pass": 0}
    n_pass = [r for r in rows if r["status"] == "pass"]
    out["n_pass"] = len(n_pass)
    for f in OBJECTIVE_ALL:
        scored = [r for r in n_pass if f in r["fields"]]
        amb = [r for r in n_pass if f in r["ambiguous"]]
        denom = len(scored) or 1
        out["per_field"][f] = {
            "rate": round(sum(1 for r in scored if r["fields"][f]) / denom, 4),
            "matched": sum(1 for r in scored if r["fields"][f]),
            "denom": len(scored),
        }
        out["ambiguous_count"][f] = len(amb)
    return out


def cmd_run(args) -> int:
    check_snapshot_ref(args)
    cfg = load_config(str(ROOT / args.config))
    gt_cases = load_ground_truth()
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
            per_model_obj[m] = score_objective(ext_d, gc, break_conds)
            per_model_subj[m] = {f: (ext_d or {}).get(f) for f in SUBJECTIVE}
            obj_rows.append({
                "ticker": ticker, "exposure": gc.get("exposure"), "input_type": gc.get("input_type"),
                "model": m, **per_model_obj[m]["fields"], "ambiguous": per_model_obj[m]["ambiguous"],
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
        blank = [{"case": gc["ticker"], "fields": {f: {"pick": "", "reason": ""} for f in SUBJECTIVE}}
                 for gc in gt_cases]
        VERDICTS.write_text(yaml.safe_dump(blank, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"\n=== 客观一致率（逐模型 × exposure）===")
    for m, gs in summary["models"].items():
        for gname, agg in gs.items():
            print(f"  {m:22s} / {gname:6s}: { {k:v['rate'] for k,v in agg['per_field'].items()} } n_pass={agg['n_pass']}")
    print(f"\n盲评对照（作者看，隐藏来源）: {BLIND_PAIRS}")
    print(f"源映射（harness 内部）       : {SOURCE_MAP}")
    print(f"raw extractions              : {EXTRACTIONS}")
    print(f"L1 结果                      : {L1_RESULT}")
    print("\n下一步：作者填 evals/blind_verdicts.yaml（每 case 每主观字段 A/B/都不对 + 都不对理由）→ 再跑 collect。")
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
    accepted = 0
    both_wrong = 0
    win = {"qwen-turbo": 0, "glm-5.2-fast-preview": 0}
    fails = []
    for v in verdicts:
        case = v.get("case")
        for f in SUBJECTIVE:
            pick = v.get("fields", {}).get(f, {}).get("pick")  # "A" | "B" | "both_wrong"
            reason = v.get("fields", {}).get(f, {}).get("reason")
            total += 1
            sm = smap.get(case, {}).get("fields", {}).get(f, {})
            if pick in ("A", "B"):
                accepted += 1
                winner = sm.get(pick)
                if winner in win:
                    win[winner] += 1
            else:  # both_wrong 或非法
                both_wrong += 1
                fails.append({"case": case, "field": f, "reason": reason or "(无理由)"})

    acceptance = round(accepted / total, 4) if total else 0
    print(f"=== 主观字段盲评结果 ===")
    print(f"  总数 {total} | 接受(A或B) {accepted} | 都不对 {both_wrong}")
    print(f"  用户接受率 = {acceptance} (门槛 ≥0.85，§9.1)")
    for m, w in win.items():
        print(f"  {m:22s} 胜率 = {round(w/total,4) if total else 0} (被接受 {w}/{total})")
    if fails:
        print(f"\n  「都不对」明细（{len(fails)} 条，计入失败）:")
        for fl in fails:
            print(f"    {fl['case']} / {fl['field']}: {fl['reason']}")
    out = {"acceptance_rate": acceptance, "total": total, "accepted": accepted,
           "both_wrong": both_wrong, "win_rate": {m: round(w/total,4) if total else 0 for m,w in win.items()},
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
