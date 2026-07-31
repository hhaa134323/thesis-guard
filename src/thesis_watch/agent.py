"""Agent harness 骨架（v0.1）。

这是本项目的核心交付——harness 本身。包含：
- 工具注册与分发（ToolRegistry）
- 抽取器可插拔（Extractor 协议）：mock（离线 demo/测试）或真实
  （Claude Agent SDK / SDK loop，待选型确认 + 网络）。接口不变即可替换。
- 证据自检契约（evidence.self_check，fetcher 可注入）
- 红线 guard（redline.guard，命中即 E8）
- 不可判定/价格图形型 → 降级人工自查

先用 mock extractor 跑通 harness 机制；真实 responder 接入后替换即可。
不依赖任何 LLM SDK，不触网。
"""
from __future__ import annotations

import dataclasses
import typing

from . import redline
from .conditions import (
    default_redline_pack,
    is_price_pattern,
    make_mirror,
    to_manual_check,
)
from .evidence import self_check as evidence_self_check
from .models import (
    Assumption,
    BrokenCondition,
    ConditionLayer,
    Confirmation,
    FilerType,
    ManualCheckItem,
    ThesisCard,
    to_dict,
)

# --------------------------------------------------------------------------- #
# 工具注册与分发
# --------------------------------------------------------------------------- #

Tool = typing.Callable[..., typing.Any]


class ToolRegistry:
    """核对/录入 Agent 可用工具的注册表。真实 responder 经此调用工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, fn: Tool) -> "ToolRegistry":
        self._tools[name] = fn
        return self

    def call(self, name: str, args: dict) -> typing.Any:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name](**args)

    def names(self) -> list[str]:
        return list(self._tools)


def default_tools(user_thresholds: dict | None = None) -> ToolRegistry:
    """录入/核对共用工具集（数据层部分；fetchers 待 B1 解除后接入）。"""
    reg = ToolRegistry()
    reg.register("lookup_filer_type", lambda ticker: FilerType.OTHER.value)  # TODO: 基于 EDGAR
    reg.register("default_redline_pack",
                lambda: [to_dict(c) for c in default_redline_pack(user_thresholds)])
    reg.register("is_price_pattern", lambda text: is_price_pattern(text))
    reg.register("evidence_self_check",
                lambda url, excerpt, fetcher=None: dataclasses.asdict(
                    evidence_self_check(url, excerpt, fetcher)))
    return reg


# --------------------------------------------------------------------------- #
# 抽取器（可插拔）
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class ExtractionResult:
    """抽取器从对话中结构化的内容。"""
    holding_reason_raw: str = ""
    assumptions: list[Assumption] = dataclasses.field(default_factory=list)
    mirrors: list[dict[str, str]] = dataclasses.field(default_factory=list)  # {"assumption_id","text"}
    manual_items: list[str] = dataclasses.field(default_factory=list)


Extractor = typing.Callable[[list[dict]], ExtractionResult]


def _find(assumptions: list[Assumption], aid: str) -> Assumption | None:
    return next((a for a in assumptions if a.id == aid), None)


def build_card(user_id: str, ticker: str, filer_type: FilerType,
              conversation: list[dict], extractor: Extractor,
              user_thresholds: dict | None = None) -> ThesisCard:
    """对话 → thesis 卡（未确认状态；确认是后续用户动作）。

    流程：extractor 抽取 → 镜像(L1) + 红线包(L2) + 人工自查(价格图形) → 组装。
    抽取器产出的镜像/红线条目经 redline.guard 校验（系统生成内容不得踩红线）。
    """
    ext = extractor(conversation)

    broken: list[BrokenCondition] = []
    for m in ext.mirrors:
        a = _find(ext.assumptions, m.get("assumption_id", ""))
        if a is None:
            continue
        # 镜像文本是系统生成内容，guard 之（R3）
        redline.guard(m.get("text", ""))
        broken.append(make_mirror(a, m["text"]))

    broken.extend(default_redline_pack(user_thresholds))

    manual: list[ManualCheckItem] = [to_manual_check(t) for t in ext.manual_items]

    return ThesisCard(
        user_id=user_id,
        ticker=ticker,
        filer_type=filer_type,
        holding_reason_raw=ext.holding_reason_raw,
        key_assumptions=ext.assumptions,
        broken_conditions=broken,
        manual_check_items=manual,
        confirmation=Confirmation(paraphrased=False, confirmed_by_user=False),
    )


def render_summary(card: ThesisCard) -> str:
    """复述卡片供用户确认。只呈现条件，不下结论（R6）；输出经 redline.guard。"""
    lines: list[str] = []
    lines.append(f"你持有 {card.ticker} 的理由（原话）：「{card.holding_reason_raw}」")
    if card.key_assumptions:
        lines.append("关键假设：")
        for i, a in enumerate(card.key_assumptions, 1):
            lines.append(f"  {i}) {a.text}")
    lines.append("破局条件（两层）：")
    for c in card.broken_conditions:
        tag = "镜像" if c.layer == ConditionLayer.MIRROR else "红线"
        extra = ""
        if c.layer == ConditionLayer.REDLINE and c.threshold.get("amount_usd"):
            extra = f"（阈值：>= {c.threshold['amount_usd']:.1f} 美元）"
        elif c.layer == ConditionLayer.REDLINE:
            extra = ""
        lines.append(f"  [{tag}] {c.text}{extra}")
    if card.manual_check_items:
        lines.append("人工自查项（每月提醒，系统不接行情）：")
        for m in card.manual_check_items:
            lines.append(f"  - {m.text}")
    lines.append("请确认或修改后入库。")
    text = "\n".join(lines)
    return redline.guard(text)


# --------------------------------------------------------------------------- #
# Mock extractor（离线 demo / 测试）
# --------------------------------------------------------------------------- #

def mock_extractor(conversation: list[dict]) -> ExtractionResult:
    """脚本化抽取器：把样例对话结构化为 thesis 卡输入。

    真实 responder 接入后替换为：LLM 读对话 → 输出 ExtractionResult（工具调用）。
    """
    # 把对话拼成原话（真实场景由 LLM 抽取；这里取首条用户消息）
    user_msgs = [m.get("text", "") for m in conversation if m.get("role") == "user"]
    raw = "；".join(user_msgs) if user_msgs else ""

    a = Assumption(text="服务收入持续高增")
    return ExtractionResult(
        holding_reason_raw=raw,
        assumptions=[a],
        mirrors=[{"assumption_id": a.id, "text": "服务收入同比转负"}],
        manual_items=["跌破60日均线"],
    )


_DEMO_CONVERSATION = [
    {"role": "user", "text": "持有 AAPL，看好服务收入持续高增。"},
    {"role": "user", "text": "破的话就看服务收入同比转负；另外我盯着60日线。"},
]


def demo() -> None:
    card = build_card(
        user_id="beta1", ticker="AAPL", filer_type=FilerType.DOMESTIC_10K,
        conversation=_DEMO_CONVERSATION, extractor=mock_extractor,
    )
    print(render_summary(card))
    print("\n--- card_json ---")
    import json
    print(json.dumps(to_dict(card), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    demo()
