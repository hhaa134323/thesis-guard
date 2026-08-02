"""录入 Agent CLI —— 输入 thesis 文本 → 输出 thesis-card JSON。不依赖会话上下文。

用法（PYTHONPATH=src 或装包后）：
  echo "thesis 文本" | python -m thesis_watch.entry_cli --ticker FDS
  python -m thesis_watch.entry_cli --ticker FDS --input thesis.txt
  --model X 覆盖 config task_model.model（run-config，不改 schema/prompt）
  --mode A|B（A 直接抽，B 自澄清 prefix；A/B 对照见 eval-plan §1）
  --config config.yaml（默认）

输出 JSON：{ticker, model, provider, mode, extraction: {EntryExtraction 字段 + position_cap_tier(规则查表)}, _metrics}。
position_cap_tier 不由 LLM 抽——按 ticker 查 tier_map（确定性，R8 精神：不交给模型猜）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .entry_agent import build_agent, extract
from .tier_map import lookup_tier


def main() -> int:
    ap = argparse.ArgumentParser(description="录入 Agent：thesis 文本 → thesis-card JSON")
    ap.add_argument("--ticker", required=True, help="持仓 ticker（决定 position_cap_tier 规则查表）")
    ap.add_argument("--input", help="thesis 文本文件；缺省读 stdin")
    ap.add_argument("--model", help="覆盖 config task_model.model（run-config）")
    ap.add_argument("--mode", choices=["A", "B"], default="A", help="A=直接抽（默认），B=自澄清 prefix")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    if args.input:
        text = Path(args.input).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    if not text.strip():
        print(json.dumps({"error": "empty input"}, ensure_ascii=False), file=sys.stderr)
        return 1

    cfg = load_config(args.config)
    agent, model_name, provider = build_agent(cfg, model_override=args.model)
    res = extract(agent, text, cfg, mode=args.mode)
    ext = res["extraction"]

    tier = lookup_tier(args.ticker)
    out: dict = {
        "ticker": args.ticker,
        "model": model_name,
        "provider": provider,
        "mode": args.mode,
        "_metrics": {
            "status": res.get("status"),
            "in_tok": res.get("in_tok"),
            "out_tok": res.get("out_tok"),
            "retries_429": res.get("retries_429"),
            "dur_s": res.get("dur_s"),
        },
    }
    if ext is not None:
        d = ext.model_dump()
        d["position_cap_tier"] = tier.value if tier else None  # 规则查表，非 LLM
        out["extraction"] = d
    else:
        out["extraction"] = None
        out["_metrics"]["error"] = res.get("error")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
