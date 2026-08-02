"""L1 抽取一致率 eval harness。

🚨 R8：ground truth 必须由作者手工标注（`evals/ground_truth.yaml`）。
文件缺失、或 required 字段 null 但无 open_questions 说明 → 报错退出，**绝不用模型输出兜底**。

数据结构用 pydantic-evals Dataset/Case 承载；评分（逐字段一致率 + under-fill + A/B + exposure 分组）自实现，
输出 case 明细 + 逐字段一致率（总体/clean/seen 三数）+ 台账模糊字段数 + under-fill + A/B 对比。

规则（eval-plan §8）：
- exposure: seen（FDS/HSBC，曝光过，仅参考）/ clean（其余，进 85% 判定）。一致率报三个数，clean 组为准。
- null + open_questions = 台账信息不足 → 从该字段分母剔除，单独统计「台账模糊字段数」（产品发现）。
- required 字段 null 无 open_questions → R8 报错退出。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402
from pydantic_evals import Case, Dataset  # noqa: E402

from thesis_watch.config import load_config  # noqa: E402
from thesis_watch.entry_agent import build_agent, extract  # noqa: E402
from thesis_watch.tier_map import lookup_tier  # noqa: E402

GT_PATH = ROOT / "evals" / "ground_truth.yaml"
THESIS_DIR = ROOT / "assets" / "notion" / "thesis"
REQUIRED = ["holding_reason_raw", "key_assumptions", "mirrors", "filer_type"]
SCORED_FIELDS = ["holding_reason", "key_assumption", "破条件", "filer_type"]
# GT 字段名 → 评分字段名映射
GT_TO_SCORE = {
    "holding_reason_raw": "holding_reason",
    "key_assumptions": "key_assumption",
    "mirrors": "破条件",
    "filer_type": "filer_type",
}


def _is_empty(v) -> bool:
    if v is None:
        return False  # null 走 open_questions 逻辑，不算 empty
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, list):
        return len(v) == 0
    return False


def load_ground_truth() -> list[dict]:
    """R8：读 ground_truth.yaml；缺失 / required 字段 null 无 open_questions / required 字段 empty → sys.exit。"""
    if not GT_PATH.exists():
        sys.exit(
            f"R8: ground truth 文件不存在 {GT_PATH}\n"
            "→ 拷 evals/ground_truth.template.yaml → ground_truth.yaml，由作者手工填全，harness 不兜底。"
        )
    data = yaml.safe_load(GT_PATH.read_text(encoding="utf-8"))
    cases = (data or {}).get("cases", [])
    if not cases:
        sys.exit("R8: ground_truth.yaml 无 cases——作者未标注，退出（不兜底）。")
    for c in cases:
        ticker = c.get("ticker", "?")
        if c.get("exposure") not in ("seen", "clean"):
            sys.exit(f"R8: {ticker} exposure 缺失或非法（须 seen / clean）")
        oqs = {q.get("field") for q in (c.get("open_questions") or []) if isinstance(q, dict)}
        for f in REQUIRED:
            v = c.get(f)
            if v is None:  # null
                if f not in oqs:
                    sys.exit(
                        f"R8: {ticker} 必填字段 {f}=null 但无 open_questions 说明——须填值或解释，不兜底"
                    )
                # else: 台账信息不足，ambiguous，OK
            elif _is_empty(v):
                sys.exit(
                    f"R8: {ticker} 必填字段 {f} 为空——须填值（或 null+open_questions），不兜底"
                )
    return cases


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


def _bigrams(text: str) -> set[str]:
    """2-gram 集合（去空白）；中文复述匹配比 3+ 字精确 token 宽松。"""
    t = re.sub(r"\s+", "", text or "")
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _overlap(a: str, b: str) -> bool:
    """至少共享 2 个双字 bigram 判为匹配（容忍中文复述）。"""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return False
    return len(ba & bb) >= 2


def _oq_map(gt: dict) -> dict:
    return {q.get("field"): q.get("reason", "") for q in (gt.get("open_questions") or []) if isinstance(q, dict)}


def score_case(extraction: dict | None, gt: dict) -> dict:
    """逐字段评分。null GT 字段 → ambiguous（剔除分母）；非 null → 评分。"""
    ext = extraction or {}
    oqs = _oq_map(gt)
    fields: dict = {}
    ambiguous: dict = {}

    # holding_reason_raw
    gt_hr = gt.get("holding_reason_raw")
    if gt_hr is None:
        ambiguous["holding_reason"] = oqs.get("holding_reason_raw", "(无说明)")
    else:
        fields["holding_reason"] = _overlap(ext.get("holding_reason_raw", ""), gt_hr)

    # key_assumptions: GT 假设被 agent 覆盖数 / GT 总数
    gt_as = gt.get("key_assumptions")
    if gt_as is None:
        ambiguous["key_assumption"] = oqs.get("key_assumptions", "(无说明)")
    else:
        a_as = ext.get("key_assumptions", []) or []
        a_as_t = [x.get("text", "") if isinstance(x, dict) else str(x) for x in a_as]
        as_matched = sum(1 for g in gt_as if any(_overlap(g.get("text", ""), at) for at in a_as_t))
        fields["key_assumption"] = as_matched >= max(1, len(gt_as))
        fields["key_assumption_coverage"] = f"{as_matched}/{len(gt_as)}"

    # mirrors: GT 镜像被 agent 覆盖数 / GT 总数
    gt_mr = gt.get("mirrors")
    if gt_mr is None:
        ambiguous["破条件"] = oqs.get("mirrors", "(无说明)")
    else:
        a_mr = ext.get("mirrors", []) or []
        a_mr_t = [x.get("mirror_text", "") if isinstance(x, dict) else str(x) for x in a_mr]
        mr_matched = sum(1 for g in gt_mr if any(_overlap(g.get("mirror_text", ""), at) for at in a_mr_t))
        fields["破条件"] = mr_matched >= max(1, len(gt_mr))
        fields["mirror_coverage"] = f"{mr_matched}/{len(gt_mr)}"

    # filer_type: 精确
    gt_ft = gt.get("filer_type")
    if gt_ft is None:
        ambiguous["filer_type"] = oqs.get("filer_type", "(无说明)")
    else:
        fields["filer_type"] = ext.get("filer_type") == gt_ft

    underfill = {
        "holding_reason_chars": len(ext.get("holding_reason_raw", "") or ""),
        "n_assumptions": len(ext.get("key_assumptions", []) or []),
        "n_mirrors": len(ext.get("mirrors", []) or []),
        "n_manual_items": len(ext.get("manual_items", []) or []),
        "anchor_present": ext.get("entry_anchor") is not None,
        "verdict_present": ext.get("next_verdict") is not None,
        "position_cap_tier_rule": (lookup_tier(gt.get("ticker", "")).value if lookup_tier(gt.get("ticker", "")) else None),
    }
    return {"fields": fields, "ambiguous": ambiguous, "underfill": underfill}


def _aggregate(rows: list[dict]) -> dict:
    """逐字段一致率（scored 分母 = 非 null case）+ 台账模糊字段数 + under-fill。"""
    out = {"per_field_consistency": {}, "ambiguous_count": {}, "underfill": {}}
    n_pass = [r for r in rows if r["status"] == "pass"]
    for sf in SCORED_FIELDS:
        scored = [r for r in n_pass if sf in r["fields"]]  # 非 null（有 fields[sf]）
        amb = [r for r in n_pass if sf in r["ambiguous"]]
        denom = len(scored) or 1
        rate = round(sum(1 for r in scored if r["fields"][sf]) / denom, 4)
        out["per_field_consistency"][sf] = {"rate": rate, "matched": sum(1 for r in scored if r["fields"][sf]), "denom": len(scored)}
        out["ambiguous_count"][sf] = len(amb)
    # under-fill
    n = len(n_pass) or 1
    out["underfill"] = {
        "avg_holding_chars": round(sum(r["underfill"]["holding_reason_chars"] for r in n_pass) / n),
        "avg_n_assumptions": round(sum(r["underfill"]["n_assumptions"] for r in n_pass) / n, 2),
        "avg_n_mirrors": round(sum(r["underfill"]["n_mirrors"] for r in n_pass) / n, 2),
        "anchor_present_rate": round(sum(1 for r in n_pass if r["underfill"]["anchor_present"]) / n, 4),
        "verdict_present_rate": round(sum(1 for r in n_pass if r["underfill"]["verdict_present"]) / n, 4),
    }
    out["n_pass"] = len(n_pass)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="L1 抽取一致率 eval")
    ap.add_argument("--model", help="覆盖任务模型（glm-5.2-fast-preview 做基线时用）")
    ap.add_argument("--modes", default="A,B", help="跑哪些模式，逗号分隔（默认 A,B）")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--out", default="evals/_l1_result.json")
    args = ap.parse_args()

    cfg = load_config(str(ROOT / args.config))
    agent, model_name, provider = build_agent(cfg, model_override=args.model)
    gt_cases = load_ground_truth()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]

    cases = [Case(name=c["ticker"], inputs=c["ticker"], expected_output=c) for c in gt_cases]
    ds = Dataset(name=f"L1-extraction-{model_name}", cases=cases)

    rows = []
    for case in ds.cases:
        ticker = case.inputs
        gt = case.expected_output
        text = load_input_text(ticker)
        for mode in modes:
            res = extract(agent, text, cfg, mode=mode)
            ext = res["extraction"]
            ext_d = ext.model_dump() if ext else None
            sc = score_case(ext_d, gt)
            row = {
                "ticker": ticker, "exposure": gt.get("exposure"),
                "model": model_name, "mode": mode,
                "status": res.get("status"), "dur_s": res.get("dur_s"),
                "in_tok": res.get("in_tok"), "out_tok": res.get("out_tok"),
                "retries_429": res.get("retries_429"),
                "fields": sc["fields"], "ambiguous": sc["ambiguous"],
                "underfill": sc["underfill"], "error": res.get("error"),
            }
            rows.append(row)
            amb_str = ",".join(sc["ambiguous"].keys()) or "-"
            print(
                f"{ticker:8s} {gt.get('exposure'):5s} {mode} {row['status']:8s} dur={row['dur_s']}s "
                f"fields={ {k:v for k,v in sc['fields'].items() if isinstance(v,bool)} } amb=[{amb_str}]"
            )

    # 按 mode × exposure 聚合（总体 / clean / seen 三数）
    summary = {"model": model_name, "modes": {}}
    for mode in modes:
        mrows = [r for r in rows if r["mode"] == mode]
        summary["modes"][mode] = {
            "总体": _aggregate(mrows),
            "clean": _aggregate([r for r in mrows if r.get("exposure") == "clean"]),
            "seen": _aggregate([r for r in mrows if r.get("exposure") == "seen"]),
        }

    out = {"summary": summary, "rows": rows}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== {model_name} ===")
    for mode, groups in summary["modes"].items():
        for gname, agg in groups.items():
            pfc = {k: v["rate"] for k, v in agg["per_field_consistency"].items()}
            print(f"  mode {mode} / {gname:6s}: per-field {pfc} amb={agg['ambiguous_count']} n_pass={agg['n_pass']}")
        print(f"           underfill {groups['总体']['underfill']}")
    print(f"  85% 判定看 mode A / clean 组的 per-field。结果: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
