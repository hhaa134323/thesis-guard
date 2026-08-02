"""「无法确定」候选菜单生成（spec §3）——单次 PydanticAI 结构化调用。

与 entry_agent.extract **分离**：不动 W1 eval 的 extract()；菜单只在用户说「无法确定」时调。
模型无关（config task_model 驱动，与 extract 同一模型分工）；429 退避；
LenientOpenAIChatModel 容错非标 finish_reason（复用 llm.py）。

输出 MenuCandidates：candidate_assumptions（A，用户可能信的）+ candidate_mirrors（B，每条对应一个 A 假设）。
"""
from __future__ import annotations

import os
import time
from typing import Any

from pydantic import BaseModel, Field

MENU_PROMPT = """你是持仓条件录入助手。用户持有某只美股，说清了买入理由但说不清什么会让理由破产。
你生成候选清单帮用户挑（选一次填两槽）：

A. 候选关键假设（**必须 3 条、最多 4 条**，从这只票的基本面出发——moat / 财务 / 竞争 / 管理层 / 监管 / 行业地位等不同角度；即使用户理由里没明说，也给出他**可能**信的根据，帮他想清楚信的到底是什么）。**少于 3 条不合格**。
B. 候选镜像破条件（**必须 3 条、最多 4 条**，每条对应一个 A 假设）：出现什么**具体事件** = 该假设破产。
   必须能被一手公开披露击中（财报 / 公告 / 监管 / 新闻），不要价格图形型（均线 / 形态 / 突破）。

红线（不可违反）：不给买卖 / 仓位建议、不预测涨跌、不出现「看涨 / 看跌 / 建议关注」；
不编造，依据不足就少给（宁可 2 条也不凑数）。
只输出 MenuCandidates 的 tool call，不展开解释、不复述字段说明。"""


class MenuMirror(BaseModel):
    assumption: str = Field(description="对应 A 假设原文")
    mirror_text: str = Field(description="镜像破局条件（具体事件）")


class MenuCandidates(BaseModel):
    candidate_assumptions: list[str] = Field(default_factory=list)
    candidate_mirrors: list[MenuMirror] = Field(default_factory=list)


def build_menu_agent(cfg: dict, *, model_override: str | None = None) -> tuple[Any, str, str]:
    """构造菜单 Agent（output_type=MenuCandidates）。复用 extract 同款模型构建逻辑。"""
    from pydantic_ai import Agent

    from .config import get_task_model
    from .llm import LenientOpenAIChatModel

    task = get_task_model(cfg)
    if model_override:
        task = {**task, "model": model_override}
    provider = task.get("provider")
    base_url = task.get("base_url")
    api_key = os.environ.get(task.get("api_key_env", ""), "")
    model_name = task.get("model", "")
    if not (base_url and api_key and model_name):
        raise SystemExit(f"config llm.task_model 不全（provider/base_url/model/api_key_env）：{task}")

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key, base_url=base_url))
    elif provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider
        model = LenientOpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key, base_url=base_url))
    else:
        raise SystemExit(f"未知 provider: {provider}（仅 anthropic / openai）")
    return Agent(model, output_type=MenuCandidates, system_prompt=MENU_PROMPT), model_name, provider


def _is_429(e: Exception) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return "429" in s or "rate" in s or "ratelimit" in s


def generate_menu(agent: Any, ticker: str, reason: str, cfg: dict) -> dict:
    """单次结构化调用产候选菜单。返回 {ok, menu, dur_s, status, error}。"""
    from .config import get_llm_limits

    limits = get_llm_limits(cfg)
    user_input = f"持仓：{ticker}\n买入理由：{reason}\n请生成候选 A（假设）与 B（镜像破条件）清单。"
    t0 = time.perf_counter()
    retries = 0
    while True:
        try:
            r = agent.run_sync(user_input, model_settings={"max_tokens": limits["max_tokens"]})
            dt = time.perf_counter() - t0
            out = getattr(r, "output", None)
            if out is None:
                out = getattr(r, "data", None)
            ok = isinstance(out, MenuCandidates)
            return {"ok": ok, "menu": out, "dur_s": round(dt, 2),
                    "status": "pass" if ok else "validation", "error": None}
        except Exception as e:  # noqa: BLE001
            if _is_429(e) and retries < limits["max_retries_429"]:
                retries += 1
                time.sleep(min(limits["backoff_base_sec"] * (2 ** (retries - 1)), limits["backoff_cap_sec"]))
                continue
            return {"ok": False, "menu": None, "dur_s": round(time.perf_counter() - t0, 2),
                    "status": "other", "error": f"{type(e).__name__}: {str(e)[:300]}"}


__all__ = ["MENU_PROMPT", "MenuMirror", "MenuCandidates", "build_menu_agent", "generate_menu"]
