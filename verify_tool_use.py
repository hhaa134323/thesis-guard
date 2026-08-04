"""Phase 0: 验证 DeepSeek V4-Flash 多轮 tool calling（OpenAI Agents SDK + 百炼兼容端点）。

测试 3 个 case，看 LLM 能否：
  1) 据用户输入决定调哪个 tool（resolve_ticker / save_card）
  2) 用世界知识桥接中文→英文 ticker（汇丰 → HSBC）
  3) 在多轮对话中正确决定下一步（「确认」→ save_card，而不是再 resolve）

关键事实（从 config.yaml / 项目代码核对）：
  - API key 变量名 = llm.task_model.api_key_env = ``ANTHROPIC_AUTH_TOKEN``
    （任务 skeleton 写的 DASHSCOPE_API_KEY 是错的，已按 config 改正）
  - base_url = https://dashscope.aliyuncs.com/compatible-mode/v1（与 config 一致）
  - model = deepseek-v4-flash（任务指定；config 默认 task_model 是 glm-5.2-fast-preview，
    本验证覆盖。冒烟已确认该模型名在百炼合法、key 有效、且能返回标准 tool_calls。）
  - deepseek-v4-flash 是推理模型（响应含非标 ``reasoning_content`` 字段）。
    OpenAIChatCompletionsModel 有 ``should_replay_reasoning_content`` 形参专门处理它。
    先用默认 None 跑；若多轮 tool-call 因 reasoning 回放失败，再显式试验。

工具调用判定以本脚本内的 TOOL_CALLS 日志为准（直接记函数被调时的实参，
不依赖 agents SDK 的 RunResult 结构随版本变化）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

# Windows 控制台默认 GBK，Chinese 会乱码；强制 UTF-8 输出，便于读 transcript。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from openai import AsyncOpenAI
from agents import (
    Agent,
    ModelSettings,
    Runner,
    function_tool,
    OpenAIChatCompletionsModel,
    set_default_openai_api,
    set_tracing_disabled,
)

# 百炼走 Chat Completions API（不支持 Responses API）；关 OpenAI tracing（我们不用）。
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# 从 config.yaml llm.task_model.api_key_env 找到的正确变量名（非 DASHSCOPE_API_KEY）。
API_KEY_ENV = "ANTHROPIC_AUTH_TOKEN"
API_KEY = os.environ.get(API_KEY_ENV, "")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4-flash"

client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
model = OpenAIChatCompletionsModel(
    model=MODEL,
    openai_client=client,
    # deepseek-v4-flash 推理模型返回 reasoning_content；默认 None 走 SDK 自动判断。
    should_replay_reasoning_content=None,
)


# ---------- 工具调用日志：最权威来源（直接记函数被调时的实参） ----------
TOOL_CALLS: list[dict] = []
_SAVED: list[dict] = []


def _log(tool: str, **kw) -> dict:
    e = {"tool": tool, **kw}
    TOOL_CALLS.append(e)
    return e


# ---------- mock SEC ticker 表 ----------
# 仿 src/thesis_watch/fetchers/ticker_resolver.py 的真实语义：
#   只认整串精确英文 ticker（含点如 BRK.B）+ 英文公司名模糊；中文公司名 → NOT FOUND（宁缺勿猜）。
_SEC: dict[str, tuple[str, str, str]] = {
    "MCO": ("MCO", "Moody's Corporation", "0001059556"),
    "HSBC": ("HSBC", "HSBC Holdings plc", "0001328108"),  # NYSE ADR
    "FDS": ("FDS", "FactSet Research Systems Inc.", "0001013462"),
    "BRK.B": ("BRK.B", "Berkshire Hathaway Inc", "0001067983"),
}


@function_tool
def resolve_ticker(query: str) -> str:
    """在 SEC 官方表中查找股票代码/公司。

    只认英文 ticker（整串精确，含点如 BRK.B）和英文公司名（模糊匹配）。
    中文公司名查不到 SEC 英文 title → NOT FOUND（调用方须问用户，不猜）。
    """

    q = (query or "").strip()
    ql = q.upper()
    if ql in _SEC:  # 整串精确 ticker
        tk, name, cik = _SEC[ql]
        _log("resolve_ticker", query=q, result="FOUND", ticker=tk, company=name, cik=cik)
        return f'FOUND ticker={tk} company="{name}" cik={cik}'
    for tk, name, cik in _SEC.values():  # 英文公司名模糊
        if ql and ql in name.upper():
            _log("resolve_ticker", query=q, result="FOUND_BY_NAME", ticker=tk, company=name, cik=cik)
            return f'FOUND ticker={tk} (matched by company name "{name}") cik={cik}'
    _log("resolve_ticker", query=q, result="NOT_FOUND")
    return (
        f"NOT FOUND: '{q}' 不在 SEC 表中（只认英文 ticker / 英文公司名）。"
        "中文公司名请用户提供英文 ticker。"
    )


@function_tool
def save_card(ticker: str, reason: str) -> str:
    """把已确认的持仓 thesis 卡保存到本地数据库（ticker 须先经 resolve_ticker 确认）。"""

    rec = {"ticker": ticker, "reason": reason}
    _SAVED.append(rec)
    _log("save_card", ticker=ticker, reason=reason, saved_count=len(_SAVED))
    return f'SAVED ticker={ticker} reason="{reason}" (db now holds {len(_SAVED)} card(s))'


SYSTEM_PROMPT = """你是持仓录入助手。用户告诉你持有的股票和理由，你帮忙记录。

你有两个工具：

1. resolve_ticker(query): 在 SEC 表中查找股票代码。只认英文 ticker 和英文公司名。
2. save_card(ticker, reason): 保存到数据库。只有在 ticker 已确认后才能调用。

流程：

- 用户说"我持有XXX" → 你调 resolve_ticker 确认标的 → 告诉用户结果
- 用户说"确认" → 你调 save_card 保存
- 不要自己猜 ticker 是否正确，一定要先调 resolve_ticker 验证

红线：不给买卖建议、不预测涨跌、只整理条件不下结论。"""


agent = Agent(
    name="thesis_entry_assistant",
    instructions=SYSTEM_PROMPT,
    model=model,
    tools=[resolve_ticker, save_card],
    # 推理模型会消耗 reasoning tokens；给足预算，避免误触 finish_reason=length。
    model_settings=ModelSettings(max_tokens=8192),
)


def _item_summary(item) -> str:
    """版本无关地摘要一条 RunItem / ModelMessage（best-effort）。"""
    cls = type(item).__name__
    raw = getattr(item, "raw_item", None)
    try:
        if hasattr(raw, "model_dump"):
            blob = json.dumps(raw.model_dump(), ensure_ascii=False, default=str)
        elif raw is not None:
            blob = json.dumps(raw, ensure_ascii=False, default=str)
        else:
            blob = repr(item)
        return f"{cls}: {blob[:500]}"
    except Exception as e:  # noqa: BLE001
        return f"{cls}: <unprintable: {e}>"


def _dump_new(result) -> tuple[str, list]:
    for m in ("new_items", "new_messages"):
        fn = getattr(result, m, None)
        if callable(fn):
            try:
                return m, fn()
            except Exception:
                continue
    return "", []


async def run_turn(label: str, user_input: str, prev: list | None):
    base = prev or []
    inp = base + [{"role": "user", "content": user_input}]
    before = len(TOOL_CALLS)
    print("\n" + "=" * 72)
    print(f"[{label}]")
    print("=" * 72)
    print(f"[USER] {user_input}")
    try:
        result = await Runner.run(agent, inp)
    except Exception as e:  # noqa: BLE001
        print(f"[RUNNER ERROR] {type(e).__name__}: {str(e)[:900]}")
        calls = TOOL_CALLS[before:]
        print(f"[TOOL CALLS this turn ({len(calls)})]:")
        for c in calls:
            print("   -", c)
        return None
    calls = TOOL_CALLS[before:]
    print(f"[TOOL CALLS this turn ({len(calls)})]:")
    for c in calls:
        print("   -", c)
    print(f"[ASSISTANT final_output]\n{result.final_output}")
    mname, items = _dump_new(result)
    if mname:
        print(f"[{mname} ({len(items)})]:")
        for it in items:
            print("    -", _item_summary(it))
    try:
        return result.to_input_list()
    except Exception:  # noqa: BLE001
        return None


async def run_test():
    print(f"MODEL={MODEL}  BASE_URL={BASE_URL}")
    print(
        f"API key ({API_KEY_ENV}): "
        f"{'present (len=%d)' % len(API_KEY) if API_KEY else 'MISSING'}"
    )
    print("openai api=chat_completions  tracing=disabled  max_tokens=8192")
    if not API_KEY:
        print("!! 缺 API key，中止。")
        return

    # ---- Test 1 + Test 2：同一段连续会话 ----
    print("\n" + "#" * 72)
    print("# TEST 1：用户报英文 ticker MCO（期望调 resolve_ticker('MCO') 并命中）")
    print("#" * 72)
    ctx = await run_turn(
        "Test1 MCO",
        "我持有 MCO，理由是评级机构护城河深、评级垄断",
        prev=[],
    )

    print("\n" + "#" * 72)
    print("# TEST 2：同会话用户说「确认」（期望调 save_card，而非再 resolve_ticker）")
    print("#" * 72)
    await run_turn("Test2 confirm", "确认", prev=ctx)

    # ---- Test 3：全新会话，单测中文→英文桥接（不带 MCO 上下文） ----
    TOOL_CALLS.clear()
    print("\n" + "#" * 72)
    print("# TEST 3：全新会话用户报中文「汇丰」")
    print("# 关键观察：resolve_ticker 的 query 是 'HSBC'（LLM 世界知识桥接）")
    print("#          还是 '汇丰'（→ NOT FOUND，未桥接）？")
    print("#" * 72)
    ctx3 = await run_turn(
        "Test3 汇丰",
        "我持有汇丰，理由是亚洲银行业特许经营价值",
        prev=[],
    )
    print("\n--- Test3 追加「确认」观察完整 multi-turn loop ---")
    await run_turn("Test3b confirm", "确认", prev=ctx3)

    print("\n" + "=" * 72)
    print("ALL TOOL CALLS (chronological, this run):")
    print("=" * 72)
    for c in TOOL_CALLS:
        print(" -", c)
    print("\nSAVED CARDS:", _SAVED)


if __name__ == "__main__":
    asyncio.run(run_test())
