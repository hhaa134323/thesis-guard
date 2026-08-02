"""录入 Agent —— PydanticAI 单次结构化调用（v0.2）。

输入 thesis 文本 → 输出 EntryExtraction。模型无关（config.yaml task_model 驱动），
不依赖会话上下文。CLI / harness / gate 共用本模块。

作者 2026-08-01 定：
- 单次调用 + 结构化输出（不用多 agent / handoff）。
- 模型分工：qwen-turbo 日常迭代；glm-5.2-fast-preview 质量基线（--model 覆盖）。
- A/B 对照：A=直接抽（默认），B=带自澄清 reasoning prefix（批 eval 的澄清价值代理）。
- per-call 记指标：model / in_tok / out_tok / retries_429 / dur / status。
- 429 退避重试；429 与其它错误分开计数。
- OpenAI 兼容端点用 `LenientOpenAIChatModel` 容错非标 finish_reason（见 llm.py）。
"""
from __future__ import annotations

import os
import time
from typing import Any

from pydantic import ValidationError

from .config import get_llm_limits, get_task_model
from .schema import EntryExtraction

SYSTEM_PROMPT = """你是持仓条件录入助手。从用户给的 thesis 描述抽取结构化信息，输出 EntryExtraction 对象。

红线（不可违反）：
- 不给买卖/仓位建议、不预测涨跌、不出现「看涨/看跌/建议关注」。
- 每条事实须有源；文本里没有的不要编造，宁可留空或 None。
- 只整理条件，不下投资结论。

字段：
- holding_reason_raw：用户原话买它的理由。
- key_assumptions：关键假设（moat + 不被颠覆的理由）。
- mirrors：每条假设对应的镜像破局条件（assumption_text 关联对应假设原文，mirror_text 写破局事件）。
- manual_items：价格图形型等不可自动核对项。
- filer_type：申报方类型（美国本土 10-K → domestic_10k；20-F/6-K 外国发行人 → foreign_issuer_20f_6k；ETF/ETN/基金/信托 → etf_fund）。
- ETF/基金类（etf_fund）：无公司层面 10-K/20-F，破条件依赖指数成分/基金公告/价格规模数据，v1 数据源不覆盖 → 所有破条件记为 manual_items（人工自查），不进自动核对。
- next_verdict：下一个能证伪 thesis 的事件+日期（财报日等）；不等于下次复盘日。
- entry_anchor：录入估值锚（如 TTM GAAP P/E）；无数据时 value 留 None。

注意：position_cap_tier 不在输出里——仓位档位由系统按 ticker 查表填（tier_map），你不用输出。
只输出 EntryExtraction 对应的 tool call，不要复述字段说明、不要展开解释。
"""

_VALID_FINISH = {"stop", "length", "tool_calls", "content_filter", "function_call"}


def _is_429(e: Exception) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return "429" in s or "rate" in s or "ratelimit" in s


def _classify(e: Exception | None) -> str:
    if e is None:
        return "pass"
    s = (str(e) + " " + type(e).__name__).lower()
    if "429" in s or "rate" in s:
        return "429"
    if "token limit" in s or "max_tokens" in s or "finish_reason" in s:
        return "length"
    if "validation" in s or isinstance(e, ValidationError):
        return "validation"
    return "other"


def build_agent(cfg: dict, *, model_override: str | None = None) -> tuple[Any, str, str]:
    """构造 PydanticAI Agent。读 config 的 task_model；model_override 覆盖模型名（run-config，不改 schema/prompt）。
    返回 (agent, model_name, provider)。
    """
    from pydantic_ai import Agent

    task = get_task_model(cfg)
    if model_override:
        task = {**task, "model": model_override}
    provider = task.get("provider")
    base_url = task.get("base_url")
    api_key = os.environ.get(task.get("api_key_env", ""), "")
    model_name = task.get("model", "")
    if not base_url or not api_key or not model_name:
        raise SystemExit(f"config llm.task_model 不全（provider/base_url/model/api_key_env）：{task}")

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key, base_url=base_url))
    elif provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider
        from .llm import LenientOpenAIChatModel
        model = LenientOpenAIChatModel(
            model_name, provider=OpenAIProvider(api_key=api_key, base_url=base_url)
        )
    else:
        raise SystemExit(f"未知 provider: {provider}（仅支持 anthropic / openai）")
    return Agent(model, output_type=EntryExtraction, system_prompt=SYSTEM_PROMPT), model_name, provider


def extract(agent: Any, text: str, cfg: dict, *, mode: str = "A") -> dict:
    """单次结构化调用。mode A=直接抽（默认），B=带自澄清 reasoning prefix。
    返回 {ok, extraction, model_status, in_tok, out_tok, retries_429, dur_s, status, error}。
    """
    limits = get_llm_limits(cfg)
    if mode == "B":
        user_input = (
            "先在内心做一步澄清：列出这条 thesis 的关键 moat 与「什么具体事件出现 = thesis 破了」，"
        "再据此输出 EntryExtraction。\n\n" + text
        )
    else:
        user_input = text

    t0 = time.perf_counter()
    retries = 0
    while True:
        try:
            r = agent.run_sync(user_input, model_settings={"max_tokens": limits["max_tokens"]})
            dt = time.perf_counter() - t0
            ext = getattr(r, "output", None)
            if ext is None:
                ext = getattr(r, "data", None)
            it = ot = None
            try:
                usage = r.usage
                it = getattr(usage, "request_tokens", None) or getattr(usage, "input_tokens", None)
                ot = getattr(usage, "response_tokens", None) or getattr(usage, "output_tokens", None)
            except Exception:
                pass
            ok = isinstance(ext, EntryExtraction)
            return {
                "ok": ok, "extraction": ext,
                "in_tok": it, "out_tok": ot,
                "retries_429": retries, "dur_s": round(dt, 2),
                "status": "pass" if ok else "validation", "error": None,
            }
        except ValidationError as e:
            return {
                "ok": False, "extraction": None, "in_tok": None, "out_tok": None,
                "retries_429": retries, "dur_s": round(time.perf_counter() - t0, 2),
                "status": "validation", "error": f"ValidationError: {str(e)[:300]}",
            }
        except Exception as e:  # noqa: BLE001
            if _is_429(e) and retries < limits["max_retries_429"]:
                retries += 1
                time.sleep(min(limits["backoff_base_sec"] * (2 ** (retries - 1)), limits["backoff_cap_sec"]))
                continue
            return {
                "ok": False, "extraction": None, "in_tok": None, "out_tok": None,
                "retries_429": retries, "dur_s": round(time.perf_counter() - t0, 2),
                "status": _classify(e), "error": f"{type(e).__name__}: {str(e)[:300]}",
            }


__all__ = ["SYSTEM_PROMPT", "build_agent", "extract"]
