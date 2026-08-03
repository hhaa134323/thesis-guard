"""话术生成层（2026-08-02 补充）：每轮对话文案 LLM 生成，不再纯模板。

输入：状态机状态 + 抽取结果（EntryExtraction）+ 红线约束。
风格：追问与拒判处**说透为什么**——锐利、有解释力（这条条件为什么核不了、能改成什么样才核得了），
其余处克制；不给买卖/仓位建议、不预测涨跌、不黑名单措辞，输出由调用方过 redline.guard。
**复述确认段保持模板逐字保真**（确认卡文字须与入库内容一致）——本模块不生成复述确认文案。
抽取 schema / EntryExtraction 契约 / 状态机结构不变；抽取仍单次结构化调用，话术是**独立**的呈现层调用。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from pydantic import BaseModel, Field

DIALOGUE_PROMPT = """你是持仓条件录入助手的「话术层」。根据【状态机状态 + 抽取结果 + 红线约束】生成这一轮对用户说的话。

风格铁律：
- 追问与拒判处**说透为什么**——锐利、有解释力：告诉用户这条条件**为什么核不了**（如价格图形型系统不接行情 / 跨主体取数 / 不可判定），**能改成什么样才核得了**（改成能被一手公开披露击中的具体事件）。
- 其余处克制：不复述字段说明、不长篇。
- 红线：不给买卖/仓位建议、不预测涨跌、不出现「看涨/看跌/建议关注/目标价/据传」等；不编造，依据不足就少说。
- 用户买入逻辑原话**逐字引用**（不改写/摘要）。

只输出这一轮要对用户说的话（纯文本，中文），不复述本说明。"""


class DialogueText(BaseModel):
    text: str = Field(description="这一轮对用户说的话（中文纯文本）")


def build_dialogue_agent(cfg: dict, *, model_override: str | None = None) -> tuple[Any, str, str]:
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
    return Agent(model, output_type=DialogueText, system_prompt=DIALOGUE_PROMPT), model_name, provider


def _is_429(e: Exception) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return "429" in s or "rate" in s or "ratelimit" in s


def generate_dialogue(agent: Any, ctx: dict, cfg: dict) -> dict:
    """单次调用生成本轮文案。返回 {ok, text, dur_s, status, error}。失败时 ok=False（调用方兜底模板）。"""
    from .config import get_llm_limits

    limits = get_llm_limits(cfg)
    user_input = json.dumps(ctx, ensure_ascii=False, indent=2)
    t0 = time.perf_counter()
    retries = 0
    while True:
        try:
            r = agent.run_sync(user_input, model_settings={"max_tokens": limits["max_tokens"]})
            dt = time.perf_counter() - t0
            out = getattr(r, "output", None) or getattr(r, "data", None)
            ok = isinstance(out, DialogueText)
            return {"ok": ok, "text": (out.text if ok else ""), "dur_s": round(dt, 2),
                    "status": "pass" if ok else "validation", "error": None if ok else "not DialogueText"}
        except Exception as e:  # noqa: BLE001
            if _is_429(e) and retries < limits["max_retries_429"]:
                retries += 1
                time.sleep(min(limits["backoff_base_sec"] * (2 ** (retries - 1)), limits["backoff_cap_sec"]))
                continue
            return {"ok": False, "text": "", "dur_s": round(time.perf_counter() - t0, 2),
                    "status": "other", "error": f"{type(e).__name__}: {str(e)[:200]}"}


__all__ = ["DIALOGUE_PROMPT", "DialogueText", "build_dialogue_agent", "generate_dialogue",
           "classify_confirm_intent", "is_factual_fetchable"]


# --------------------------------------------------------------------------- #
# P1（2026-08-03）：confirm 阶段 intent 分流
# --------------------------------------------------------------------------- #
# 复述确认段逐字保真的代价是这个阶段整段不过 LLM，听不懂任何提问 → 答非所问原样返模板。
# 加一层 intent 分类把提问/修改导出去，仅「确认类」走模板逐字保真。
# 关键词分类（确定性，不经 LLM）：宁可错判为 question（应答）也不错判为 confirm（套模板）。

_MODIFY_HINTS = ("改成", "改为", "换成", "换为", "改一下", "修改", "更改为", "改成：", "改成:")
_CONFIRM_HINTS = ("对", "没问题", "入库", "确认", "可以", "好的", "没错", "行，", "ok", "OK")
_QUESTION_HINTS = ("？", "?", "什么时候", "怎么", "为什么", "是否", "吗", "如何", "多少",
                   "哪个", "哪些", "哪天", "几号", "什么意思", "是什么", "是不是", "能不能")
# 一手披露可得的事实（→ 须 sec_edgar 实取附链接，R5；不许 LLM 记忆答）
_FACTUAL_FETCHABLE_HINTS = ("财报", "季报", "年报", "filing", "10-K", "10-Q", "20-F",
                            "6-K", "8-K", "下次", "最近一份", "最近", "披露", "申报", "财报日")


def classify_confirm_intent(text: str) -> str:
    """confirm 阶段用户文本 → 'confirm' | 'modify' | 'question'。

    顺序：modify（最具体）→ question（问句标记）→ confirm（确认词）→ 默认 question。
    默认 question：宁可应答也不套模板——修 P1「答非所问」的核心。
    """
    t = (text or "").strip()
    if not t:
        return "confirm"
    if any(h in t for h in _MODIFY_HINTS):
        return "modify"
    if any(h in t for h in _QUESTION_HINTS):
        return "question"
    if any(h in t for h in _CONFIRM_HINTS):
        return "confirm"
    return "question"


def is_factual_fetchable(text: str) -> bool:
    """问题是否关于一手披露可得的事实（下次财报 / 最近 filing 等）。

    是 → 调用方须走 fetchers/sec_edgar.py 实取并附一手链接（R5），取不到明说「查不到」，
    不允许用模型记忆回答（LLM 给不出 SEC 一手链接）。
    """
    return any(h in (text or "") for h in _FACTUAL_FETCHABLE_HINTS)
