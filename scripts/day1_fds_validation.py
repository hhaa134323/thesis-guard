"""Day-1 结构化输出 gate（Phase 5 移植：pydantic_ai+glm → OpenAI Agents SDK+deepseek）。

用 FDS（台账字段最全的一行）连跑 5 次 extract，确认 deepseek 能稳定返回符合 schema 的
EntryExtraction 对象（经 submit_extraction tool call 提交，非 output_type——避 B4 thinking 冲突）。
通过条件：5 次全 pass（ok=True 且 extraction 非 None）。任一失败 → 退出码 1，停下告诉作者；
不自换方案、不改 schema 迁就模型。

每调用记录：模型名、in/out token、429 重试次数、耗时、status、error。
模型/端点从 config.yaml 的 agent_model 读（deepseek-v4-flash）；--model 覆盖；key 走 env。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# 让 src 可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thesis_watch.config import get_llm_limits, load_config  # noqa: E402
from thesis_watch.orchestrator import build_extract_agent, extract  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FDS_PATH = ROOT / "assets" / "notion" / "thesis" / "FDS.md"
CONFIG_PATH = ROOT / "config.yaml"
RESULT_JSON = ROOT / "scripts" / "_last_gate_result.json"
RUNS = 5


def load_fds_input() -> str:
    text = FDS_PATH.read_text(encoding="utf-8")

    def section(header: str) -> str:
        i = text.find(header)
        if i < 0:
            return ""
        start = i + len(header)
        j = text.find("\n## ", start)
        return text[start: j if j > 0 else len(text)].strip()

    return (
        "持仓：FDS\n\n"
        f"【Thesis · 为什么买】\n{section('## Thesis · 为什么买')}\n\n"
        f"【Thesis 破的条件】\n{section('## Thesis 破的条件')}\n\n"
        f"【加仓价 / 安全边际】\n{section('## 加仓价 / 安全边际')}\n"
    )


def main() -> int:
    # --model <name>：覆盖 config agent_model.model（仅 run-config；schema/prompt 不变）
    model_override = None
    args = sys.argv[1:]
    if "--model" in args:
        i = args.index("--model")
        model_override = args[i + 1] if i + 1 < len(args) else None
    cfg = load_config(str(CONFIG_PATH))
    limits = get_llm_limits(cfg)
    interval = limits["request_interval_sec"]

    agent, model_name, provider = build_extract_agent(cfg, model_override=model_override)
    user_input = load_fds_input()
    print(f"=== FDS day-1 gate · {RUNS} runs · agent_model={model_name} ({provider}) ===")
    print(f"input length: {len(user_input)} chars\n")

    rows: list[dict] = []
    for i in range(1, RUNS + 1):
        res = extract(agent, user_input, cfg)
        ext = res["extraction"]
        rows.append({
            "run": i, "model": model_name, "status": res.get("status"), "ok": res["ok"],
            "in_tok": res.get("in_tok"), "out_tok": res.get("out_tok"),
            "dur_s": res.get("dur_s"), "retries_429": res.get("retries_429"),
            "holding": (ext.holding_reason_raw[:30] if (ext and ext.holding_reason_raw) else None),
            "nmirrors": (len(ext.mirrors) if ext else None),
            "anchor": (ext.entry_anchor.anchor_type if (ext and ext.entry_anchor) else None),
            "verdict": (ext.next_verdict.event if (ext and ext.next_verdict) else None),
            "error": res.get("error"),
        })
        r = rows[-1]
        print(f"run {i}: {r['status']} dur={r['dur_s']}s in={r['in_tok']} out={r['out_tok']} "
              f"retries429={r['retries_429']} nmirrors={r['nmirrors']} anchor={r['anchor']} verdict={r['verdict']}"
              + (f"  err={r['error'][:120]}" if r['error'] else ""))
        if i < RUNS:
            time.sleep(interval)

    passed = sum(1 for r in rows if r["ok"])
    durs = [r["dur_s"] for r in rows if r["ok"] and r["dur_s"] is not None]
    outs = [r["out_tok"] for r in rows if r["ok"] and r["out_tok"]]
    fail_breakdown: dict = {}
    for r in rows:
        if not r["ok"]:
            fail_breakdown[r["status"]] = fail_breakdown.get(r["status"], 0) + 1
    summary = {
        "model": model_name, "provider": provider,
        "passed": passed, "total": RUNS,
        "pass_rate": round(passed / RUNS, 4),
        "avg_dur_pass_s": round(sum(durs) / len(durs), 2) if durs else None,
        "avg_out_tok_pass": round(sum(outs) / len(outs)) if outs else None,
        "fail_breakdown": fail_breakdown or None,
        "rows": rows,
    }
    print(f"\n=== RESULT: {passed}/{RUNS} passed ===")
    if durs:
        print(f"  pass dur: min={min(durs)}s max={max(durs)}s avg={summary['avg_dur_pass_s']}s")
    if outs:
        print(f"  pass out_tok: min={min(outs)} max={max(outs)} avg={summary['avg_out_tok_pass']}")
    if fail_breakdown:
        print(f"  fail breakdown: {fail_breakdown}")

    RESULT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  result json: {RESULT_JSON}")

    if passed == RUNS:
        print("GATE PASSED — deepseek 结构化抽取稳定")
        return 0
    print("GATE FAILED — 停下告诉作者；不自换方案、不改 schema 迁就模型")
    return 1


if __name__ == "__main__":
    sys.exit(main())
