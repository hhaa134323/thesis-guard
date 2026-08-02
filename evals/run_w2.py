"""W2 eval harness（§2.5）：测录入 loop 的收敛后质量，三指标。

- **平均澄清轮数**（auto）：loop.metrics['clarification_rounds'] 均值。
- **收敛失败率**（auto）：1 - converged/total（extract 失败 / 卡片缺失等未达 confirmed）。
- **收敛后接受率**（author blind-eval，pending）：导出 converged cards 到
  `evals/w2_converged_cards.yaml`，作者盲评（同 W1 blind_verdicts 流程）。

mode A（默认）：GT thesis text → start → 「确认」→ confirm（rich input，0 clarification）——
  自然路径；菜单路径（mode B，1 clarification）已在 §2.1 HSBC 演练，系统化测量列 W2.5 后续。
串行 + 429 退避（loop 内 extract 已退避；不并发，工程纪律）。
每数字标模型 + 版本（见 [[eval-model-glm]]）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

import yaml  # noqa: E402

from thesis_watch.config import load_config  # noqa: E402
from thesis_watch.entry_loop import new_session  # noqa: E402
from run_l1 import load_ground_truth, load_input_text  # noqa: E402  复用 W1 的 GT + 输入切片


def run_case(gc: dict, cfg: dict, mode: str = "confirm") -> dict:
    """跑一个 case 的 loop：start(thesis text) → 确认 → confirm。返回 metrics + converged card。"""
    ticker = gc["ticker"]
    text = load_input_text(ticker)
    if not text.strip():
        return {"ticker": ticker, "converged": False, "metrics": {"turns": 0, "clarification_rounds": 0, "converged": False},
                "error": "empty input text", "card": None}
    s = new_session("beta1", ticker, cfg)
    v = s.start(text)
    if s.card_draft is None:
        return {"ticker": ticker, "converged": False, "metrics": v.get("metrics", {}),
                "error": v.get("error") or "extract failed", "card": None}
    if mode == "confirm":
        s.turn({"text": "确认"})       # S_EXTRACTED → S_CONFIRM
        v3 = s.confirm()               # S_CONFIRM → S_CONFIRMED
        return {"ticker": ticker, "converged": v3["metrics"]["converged"],
                "metrics": v3["metrics"], "card": v3["card"], "error": None}
    return {"ticker": ticker, "converged": False, "metrics": v.get("metrics", {}),
            "error": f"unknown mode {mode}", "card": None}


def main() -> int:
    ap = argparse.ArgumentParser(description="W2 eval：录入 loop 收敛后质量")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--limit", type=int, default=0, help="0=all GT；>0 取前 N")
    ap.add_argument("--tickers", help="逗号分隔 ticker 子集")
    ap.add_argument("--mode", choices=["confirm"], default="confirm")
    ap.add_argument("--out", default=str(ROOT / "evals" / "w2_converged_cards.yaml"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    gt_cases = load_ground_truth()
    if args.tickers:
        want = {t.strip().upper() for t in args.tickers.split(",")}
        gt_cases = [c for c in gt_cases if c["ticker"].upper() in want]
    if args.limit > 0:
        gt_cases = gt_cases[: args.limit]

    from thesis_watch.config import get_task_model
    model_name = get_task_model(cfg).get("model", "?")

    results: list[dict] = []
    converged_cards: list[dict] = []
    for gc in gt_cases:
        print(f"--- {gc['ticker']} ---", flush=True)
        r = run_case(gc, cfg, mode=args.mode)
        results.append(r)
        if r["converged"] and r["card"]:
            converged_cards.append({"ticker": r["ticker"], "card": r["card"], "metrics": r["metrics"]})
        m = r.get("metrics", {}) or {}
        print(f"  converged={r['converged']} turns={m.get('turns')} clar={m.get('clarification_rounds')} err={r.get('error')}")
        print(flush=True)

    n = len(results)
    n_conv = sum(1 for r in results if r["converged"])
    avg_clar = sum((r.get("metrics") or {}).get("clarification_rounds", 0) for r in results) / n if n else 0
    fail_rate = 1 - n_conv / n if n else 0

    print(f"\n=== W2 eval (model={model_name}, mode={args.mode}, n={n}) ===")
    print(f"  平均澄清轮数 = {avg_clar:.2f}")
    print(f"  收敛失败率   = {fail_rate:.2%}（{n - n_conv}/{n} 未收敛）")
    print(f"  收敛后接受率 = author blind-eval pending（导出 {len(converged_cards)} 张 converged 卡 → {args.out}）")

    Path(args.out).write_text(
        yaml.safe_dump(converged_cards, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (ROOT / "evals" / "_w2_result.json").write_text(json.dumps({
        "model": model_name, "mode": args.mode, "n": n, "n_converged": n_conv,
        "avg_clarification_rounds": round(avg_clar, 4),
        "convergence_failure_rate": round(fail_rate, 4),
        "acceptance_rate": None,  # author blind-eval pending
        "results": [{"ticker": r["ticker"], "converged": r["converged"],
                     "metrics": r.get("metrics"), "error": r.get("error")} for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  结果 → evals/_w2_result.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
