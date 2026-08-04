"""Phase 1 demo —— 验收 Case 1-4（docs/eval-refactor.md 第一层：讨论式 vs 抽取式）。

跑法（仓库根）：
  PYTHONUTF8=1 python scripts/demo_phase1.py          # 全部 4 case
  PYTHONUTF8=1 python scripts/demo_phase1.py 3 4      # 只跑 Case 3-4

终端看 agent 每轮回复 + tool 调用 trace（验证 agent 真调 extract_card / G3 触发）。
依赖：openai-agents + DeepSeek V4-Flash（DashScope）+ SEC EDGAR 网络。
extract_card 走 OpenAI Agents SDK + deepseek（Phase 5 移植自 entry_agent，pydantic-ai 已删）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agents import Runner  # noqa: E402

from thesis_watch.config import get_agent_model, load_config  # noqa: E402
from thesis_watch.orchestrator import agent  # noqa: E402

MAX_TURNS = 8


def _tool_trace(result) -> list[str]:
    """从 RunResult.new_items 提取 tool 调用 + 输出（验证 extract_card 真被调 + G3 输出）。
    兼容 Responses / chat_completions 两式 raw_item（getattr + dict 双兜底）。"""
    lines: list[str] = []
    for it in getattr(result, "new_items", []) or []:
        tname = type(it).__name__
        if "Tool" not in tname:
            continue
        raw = getattr(it, "raw_item", None)
        name = args = out = None
        for n in ("name", "tool_name"):
            v = getattr(raw, n, None) if raw is not None else None
            if v:
                name = v
                break
        if name is None and isinstance(raw, dict):
            name = raw.get("name") or raw.get("tool_name")
        for a in ("arguments", "args", "input"):
            v = getattr(raw, a, None) if raw is not None else None
            if v is not None:
                args = v
                break
        if args is None and isinstance(raw, dict):
            args = raw.get("arguments") or raw.get("input")
        for o in ("output", "result", "content"):
            v = getattr(raw, o, None) if raw is not None else None
            if v is not None:
                out = v
                break
        if out is None and isinstance(raw, dict):
            out = raw.get("output") or raw.get("content")
        parts = [tname]
        if name:
            parts.append(f"tool={name}")
        if args:
            parts.append(f"args={str(args)[:80]}")
        if out is not None:
            parts.append(f"out={str(out)[:600]}")
        lines.append("  " + " | ".join(parts))
    return lines


def run_case(name: str, turns: list[str]) -> None:
    print("\n" + "=" * 72)
    print(f"  {name}")
    print("=" * 72)
    history: list | None = None
    for i, user_msg in enumerate(turns, 1):
        print(f"\n[用户 turn {i}] {user_msg}")
        input_items = user_msg if history is None else history + [{"role": "user", "content": user_msg}]
        try:
            result = Runner.run_sync(agent, input_items, max_turns=MAX_TURNS)
        except Exception as e:  # noqa: BLE001 —— demo 要稳：guardrail trip / MaxTurns / 网络都打印不崩
            ename = type(e).__name__
            tag = ("[guardrail 拦截]" if "Tripwire" in ename
                   else "[超 MaxTurns]" if "MaxTurns" in ename
                   else "[异常]")
            print(f"{tag} {ename}: {str(e)[:300]}")
            break
        trace = _tool_trace(result)
        if trace:
            print("[tool 调用]")
            for line in trace:
                print(line)
        print(f"[ThesisGuard] {result.final_output}")
        history = result.to_input_list()


CASES: list[tuple[str, list[str]]] = [
    ("Case 1: 探针仓启动（应问「为什么关注」，不问持仓量、不假设已建仓）",
     ["我开始关注 MCO"]),
    ("Case 2: 已建仓启动（应问「为什么持有」，仍完整讨论 5 字段）",
     ["我持有 MCO"]),
    ("Case 3: 逐字段引导（只给 thesis，应一次问一个，不一气全问）",
     ["我持有 MCO",
      "看好信用评级壁垒"]),
    ("Case 4: key_assumptions 用户确认（呈现假设→用户改→才生成破局条件）",
     ["我持有 MCO",
      "看好信用评级壁垒，评级行业壁垒深、客户切换成本高",
      "第2条不对，客户切换成本不是我的核心假设"]),
]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(str(repo_root / "config.yaml"))
    print(f"Thesis Guard —— Phase 1 demo | agent={agent.name} "
          f"| model={get_agent_model(cfg).get('model')!r} (DashScope)")
    print(f"tools={[t.name for t in agent.tools]}")
    want = {int(x) for x in sys.argv[1:]} if len(sys.argv) > 1 else set()
    for idx, (name, turns) in enumerate(CASES, 1):
        if want and idx not in want:
            continue
        run_case(name, turns)
    print("\n" + "=" * 72)
    print("  demo 结束 —— 对照 docs/eval-refactor.md Case 验收点判断 agent 行为")
    print("=" * 72)


if __name__ == "__main__":
    main()
