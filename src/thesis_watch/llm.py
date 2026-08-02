"""PydanticAI 模型适配层（v0.2）。

作者 2026-08-01 定：单次结构化调用，模型无关；端点+模型从 config 读，key 走 env。

DashScope 等 OpenAI 兼容端点偶发返回非标准 `finish_reason`（不在 openai SDK 的 Literal 枚举里）。
pydantic-ai 的 `_ChatCompletion`（openai.py 内部）只放宽了 `service_tier`，**漏了 `finish_reason`**，
导致 `_validate_completion` 抛 ValidationError → UnexpectedModelBehavior（glm-5.2-fast-preview gate 1/5）。

修复（SDK 层容错，**不动 schema / 不放宽 tool_choice / 不降 gate 门槛**）：
子类化 `OpenAIChatModel` 覆写 `_validate_completion`（pydantic-ai 设计的 hook，openai.py line 1123），
用放宽 `finish_reason` 的 `_LenientChatCompletion` 替换——与 pydantic-ai 放宽 `service_tier` 同模式。
结构化输出本身仍由 pydantic-ai 的 `output_type` 校验，本层只动响应元数据。
"""
from __future__ import annotations

from typing import Any

from openai.types.chat.chat_completion import ChatCompletion, Choice
from pydantic_ai.models.openai import OpenAIChatModel


class _LenientChoice(Choice):
    """放宽 finish_reason Literal——OpenAI 兼容 provider（DashScope/glm）偶发返回非标值。"""

    model_config = {"title": "Choice"}  # type: ignore[assignment]
    finish_reason: str | None = None  # type: ignore[reportIncompatibleVariableOverride]


class _LenientChatCompletion(ChatCompletion):
    """放宽 choices[].finish_reason + service_tier（补 pydantic-ai `_ChatCompletion` 漏的 finish_reason）。"""

    model_config = {"title": "ChatCompletion"}  # type: ignore[assignment]
    choices: list[_LenientChoice]  # type: ignore[reportIncompatibleVariableOverride]
    service_tier: str | None = None  # type: ignore[reportIncompatibleVariableOverride]


class LenientOpenAIChatModel(OpenAIChatModel):
    """`OpenAIChatModel` + 容错非标准 finish_reason（SDK 层）。

    用于 DashScope 等 OpenAI 兼容端点。覆写 `_validate_completion`：用 `_LenientChatCompletion`
    解析响应（finish_reason 放宽为 `str | None`）。不改 schema、不放宽 tool_choice、不降 gate 门槛。
    """

    def _validate_completion(self, response: ChatCompletion) -> Any:  # type: ignore[override]
        return _LenientChatCompletion.model_validate(response.model_dump())


__all__ = ["LenientOpenAIChatModel"]
