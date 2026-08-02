"""W2 eval harness（§2.5）：录入 loop 收敛后质量，三指标。

子命令：
  run       跑 loop（mode A：GT thesis text → start → 确认 → confirm）→ 测 平均澄清轮数/收敛失败率（auto）
            + 导出 converged cards 到 evals/w2_converged_cards.yaml（gitignored，可复现）。
  template  读 w2_converged_cards.yaml + load_input_text → 铺成 evals/blind_verdicts_w2.yaml 盲评模板
            （逐字段：case/ticker/reference_input/model_output/acceptable:null/reason:""）。单模型 mode A 无 pick。
  collect   读已填 blind_verdicts_w2.yaml → 算 收敛后接受率（acceptable=yes/total）+ _w2_result.json 的
            平均澄清轮数/收敛失败率 → 写 docs/eval-report.md §7.1。

盲评不在对话里口头做（作者 2026-08-02 定）：填评人只看 blind_verdicts_w2.yaml 一个文件（不用翻别处）。
每数字标模型 + 版本（见 [[eval-model-glm]]）。串行 + 429 退避。
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

from thesis_watch.config import load_config, get_task_model  # noqa: E402
from thesis_watch.entry_loop import new_session  # noqa: E402
from run_l1 import load_ground_truth, load_input_text  # noqa: E402  复用 W1 的 GT + 输入切片

CONVERGED_CARDS = ROOT / "evals" / "w2_converged_cards.yaml"
BLIND_VERDICTS = ROOT / "evals" / "blind_verdicts_w2.yaml"
W2_RESULT = ROOT / "evals" / "_w2_result.json"
EVAL_REPORT = ROOT / "docs" / "eval-report.md"


# ──────────────────────────── run ────────────────────────────
def run_case(gc: dict, cfg: dict, mode: str = "confirm") -> dict:
    ticker = gc["ticker"]
    text = load_input_text(ticker)
    if not text.strip():
        return {"ticker": ticker, "converged": False,
                "metrics": {"turns": 0, "clarification_rounds": 0, "converged": False},
                "error": "empty input text", "card": None}
    s = new_session("beta1", cfg)
    v = s.start(text, ticker_override=ticker)
    if s.card_draft is None:
        return {"ticker": ticker, "converged": False, "metrics": v.get("metrics", {}),
                "error": v.get("error") or "extract failed", "card": None}
    if mode == "confirm":
        s.turn({"text": "确认"})
        v3 = s.confirm()
        return {"ticker": ticker, "converged": v3["metrics"]["converged"],
                "metrics": v3["metrics"], "card": v3["card"], "error": None}
    return {"ticker": ticker, "converged": False, "metrics": v.get("metrics", {}),
            "error": f"unknown mode {mode}", "card": None}


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    if args.model:
        cfg.setdefault("llm", {}).setdefault("task_model", {})["model"] = args.model
    gt_cases = load_ground_truth()
    if args.tickers:
        want = {t.strip().upper() for t in args.tickers.split(",")}
        gt_cases = [c for c in gt_cases if c["ticker"].upper() in want]
    if args.limit > 0:
        gt_cases = gt_cases[: args.limit]
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
    print(f"  下一步：python evals/run_w2.py template --converged {args.out} 生成盲评模板")

    Path(args.out).write_text(
        yaml.safe_dump(converged_cards, allow_unicode=True, sort_keys=False), encoding="utf-8")
    Path(args.result).write_text(json.dumps({
        "model": model_name, "mode": args.mode, "n": n, "n_converged": n_conv,
        "avg_clarification_rounds": round(avg_clar, 4),
        "convergence_failure_rate": round(fail_rate, 4),
        "acceptance_rate": None,
        "results": [{"ticker": r["ticker"], "converged": r["converged"],
                     "metrics": r.get("metrics"), "error": r.get("error")} for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


# ──────────────────────────── template ────────────────────────────
def cmd_template(args) -> int:
    """读 converged cards + load_input_text → 铺盲评模板。"""
    conv = Path(args.converged)
    if not conv.exists():
        print(f"先跑 run 生成 {conv}")
        return 1
    data = yaml.safe_load(conv.read_text(encoding="utf-8")) or []
    out: list[dict] = []
    for i, item in enumerate(data, 1):
        ticker = item["ticker"]
        card = item["card"]
        mirrors = [bc for bc in (card.get("broken_conditions") or []) if bc.get("layer") == "mirror"]
        fields = []
        fields.append({"field": "holding_reason_raw", "model_output": card.get("holding_reason_raw", ""),
                       "acceptable": None, "reason": ""})
        for j, a in enumerate(card.get("key_assumptions") or []):
            fields.append({"field": f"key_assumptions[{j}]", "model_output": a.get("text", ""),
                           "acceptable": None, "reason": ""})
        for j, m in enumerate(mirrors):
            fields.append({"field": f"mirrors[{j}]", "model_output": m.get("text", ""),
                           "acceptable": None, "reason": ""})
        out.append({
            "case": i, "ticker": ticker,
            "reference_input": load_input_text(ticker),
            "fields": fields,
        })
    Path(args.out).write_text(
        yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=10000), encoding="utf-8")
    n_fields = sum(len(c["fields"]) for c in out)
    print(f"盲评模板 → {args.out}")
    print(f"  {len(out)} case / {n_fields} 字段。填 acceptable: yes/no（no 必填 reason 一句），no pick（单模型 mode A）。")
    print(f"  填完跑：python evals/run_w2.py collect --verdicts {args.out}")
    return 0


# ──────────────────────────── collect ────────────────────────────
def cmd_collect(args) -> int:
    """读已填盲评模板 → 算 收敛后接受率 + 写 eval-report §7.1。"""
    verdicts_path = Path(args.verdicts)
    if not verdicts_path.exists():
        print(f"盲评模板不存在 {verdicts_path}——先 template。")
        return 1
    data = yaml.safe_load(verdicts_path.read_text(encoding="utf-8")) or []
    total = 0
    accepted = 0
    unanswered = 0
    fails: list[str] = []
    for c in data:
        for f in c.get("fields") or []:
            total += 1
            raw = f.get("acceptable")
            if isinstance(raw, bool):
                acc = "yes" if raw else "no"
            elif raw is None:
                acc = ""
            else:
                acc = str(raw).strip().lower()
            if acc == "yes":
                accepted += 1
            elif acc == "no":
                reason = (f.get("reason") or "").strip()
                if not reason:
                    fails.append(f"{c['ticker']}/{f['field']}: no 但 reason 空")
            else:
                unanswered += 1
    if fails:
        print("⚠️ 以下 no 但 reason 未填，请补：")
        for x in fails:
            print(f"  {x}")
        return 1
    if total == 0:
        print("无字段可统计。")
        return 1
    acceptance = accepted / total

    # 平均澄清轮数 / 收敛失败率（从 result json）
    avg_clar = None
    fail_rate = None
    model = "?"
    result_path = Path(args.result)
    if result_path.exists():
        w2 = json.loads(result_path.read_text(encoding="utf-8"))
        avg_clar = w2.get("avg_clarification_rounds")
        fail_rate = w2.get("convergence_failure_rate")
        model = w2.get("model", "?")
    label = args.model_label or f"{model} · mode A"

    import datetime
    date = datetime.date.today().isoformat()
    block = f"""

### 7.1 collect 结果（{date}，`run_w2.py collect --verdicts {verdicts_path.name}`）

盲评模板 `{verdicts_path}`（{len(data)} case / {total} 字段，单模型 mode A，无 pick）已填。
**模型：{label}**

| 指标 | 值 |
|---|---|
| 平均澄清轮数 | {avg_clar} |
| 收敛失败率 | {fail_rate} |
| **收敛后接受率** | **{acceptance:.2%}**（{accepted}/{total} acceptable=yes；未答 {unanswered}） |

不接受明细见 `{verdicts_path}` 的 reason 字段。
"""
    report = EVAL_REPORT.read_text(encoding="utf-8") if EVAL_REPORT.exists() else ""
    if "### 7.1" in report and args.model_label is None:
        idx = report.index("### 7.1")
        report = report[:idx].rstrip() + "\n" + block
    else:
        report = report.rstrip() + "\n" + block
    EVAL_REPORT.write_text(report, encoding="utf-8")

    print(f"=== W2 collect ({label}) ===")
    print(f"  收敛后接受率 = {acceptance:.2%}（{accepted}/{total}，未答 {unanswered}）")
    print(f"  平均澄清轮数 = {avg_clar}")
    print(f"  收敛失败率   = {fail_rate}")
    print(f"  已写 → {EVAL_REPORT} §7.1")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="W2 eval：录入 loop 收敛后质量")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="跑 loop 收敛 → 三指标 + 导出 converged 卡")
    r.add_argument("--config", default="config.yaml")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--tickers")
    r.add_argument("--mode", choices=["confirm"], default="confirm")
    r.add_argument("--model", help="覆盖 task_model（如 glm-5.2-fast-preview，W2 接受率模型修正）")
    r.add_argument("--out", default=str(CONVERGED_CARDS), help="converged 卡输出路径")
    r.add_argument("--result", default=str(W2_RESULT), help="_w2_result json 路径")
    t = sub.add_parser("template", help="铺盲评模板")
    t.add_argument("--converged", default=str(CONVERGED_CARDS))
    t.add_argument("--out", default=str(BLIND_VERDICTS))
    c = sub.add_parser("collect", help="算接受率 + 写 eval-report §7.1")
    c.add_argument("--verdicts", default=str(BLIND_VERDICTS))
    c.add_argument("--result", default=str(W2_RESULT))
    c.add_argument("--model-label", default=None, help="§7.1 标注（如 glm-5.2-fast-preview · mode A）")
    args = ap.parse_args()
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "template":
        return cmd_template(args)
    if args.cmd == "collect":
        return cmd_collect(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
