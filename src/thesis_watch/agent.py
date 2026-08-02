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
    EntryAnchorData,
    NextVerdictData,
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
              user_thresholds: dict | None = None,
              enabled_redlines: list[str] | None = None) -> ThesisCard:
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

    broken.extend(default_redline_pack(user_thresholds, enabled_redlines))

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


def build_card_from_extraction(ext, *, user_id: str, ticker: str,
                               tier, filer_type=None,
                               user_thresholds: dict | None = None,
                               enabled_redlines: list[str] | None = None) -> ThesisCard:
    """EntryExtraction（pydantic LLM 输出，schema.py）→ ThesisCard（dataclass 存储，models.py）。

    录入 loop 把单次 extract() 的结构化输出落成卡片：
    - 镜像文本经 redline.guard（R3：系统生成内容）；
    - Layer 2 红线默认包叠加（conditions.default_redline_pack，可去重）；
    - 价格图形型兜底进 manual_check_items（is_price_pattern）；
    - entry_anchor / next_verdict / position_cap_tier 落确认卡字段；
    - confirmation 置未确认（用户复述确认后才 True，由 loop 改）。
    """
    raw = (ext.holding_reason_raw or "") if ext is not None else ""
    assumptions = [Assumption(text=a.text, judgeable=a.judgeable)
                  for a in (ext.key_assumptions or [])] if ext is not None else []

    broken: list[BrokenCondition] = []
    for m in (ext.mirrors or []) if ext is not None else []:
        a = next((x for x in assumptions if x.text == m.assumption_text), None)
        if a is None:
            a = Assumption(text=m.assumption_text)
            assumptions.append(a)
        redline.guard(m.mirror_text)
        broken.append(make_mirror(a, m.mirror_text))
    broken.extend(default_redline_pack(user_thresholds, enabled_redlines))

    manual = [ManualCheckItem(text=m.text, reason=m.reason, cadence=m.cadence)
              for m in (ext.manual_items or [])] if ext is not None else []
    if ext is not None and is_price_pattern(raw) and not any(is_price_pattern(m.text) for m in manual):
        manual.append(to_manual_check(raw))

    ft = filer_type if filer_type is not None else (
        FilerType(ext.filer_type.value) if ext is not None and ext.filer_type else FilerType.OTHER)
    ea = None
    if ext is not None and ext.entry_anchor:
        ea = EntryAnchorData(anchor_type=ext.entry_anchor.anchor_type,
                             anchor_value=ext.entry_anchor.anchor_value,
                             note=ext.entry_anchor.note)
    nv = None
    if ext is not None and ext.next_verdict:
        nv = NextVerdictData(event=ext.next_verdict.event,
                             date=ext.next_verdict.date,
                             source_note=ext.next_verdict.source_note)

    return ThesisCard(
        user_id=user_id, ticker=ticker, filer_type=ft,
        holding_reason_raw=raw,
        key_assumptions=assumptions,
        broken_conditions=broken,
        manual_check_items=manual,
        entry_anchor=ea, next_verdict=nv,
        position_cap_tier=tier.value if tier is not None else None,
        confirmation=Confirmation(paraphrased=True, confirmed_by_user=False),
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


# --------------------------------------------------------------------------- #
# HSBC 演练 transcript demo（W1：glm-5.2 内联抽取固化；生产 API responder 见 W2）
# 基线 transcript：assets/onboarding_dryrun_0731.md（6 轮对话 + 8 条设计发现）
# --------------------------------------------------------------------------- #

# transcript 6 轮对话摘要（round 1–4 关键产出；完整原文见 assets/onboarding_dryrun_0731.md）。
HSBC_TRANSCRIPT: list[dict] = [
    {"role": "user", "text": "HSBC，因为按照年来看，它的股价表现稳健上升的形状"},
    {"role": "assistant", "text": "追问：信图形还是公司？什么算「形状破了」？"},
    {"role": "user", "text": "1、公司  2、无法确定，那得想想什么会让这家公司变得让人无法信任"},
    {"role": "assistant", "text": "候选菜单 A（假设）/ B（破条件镜像）；价格形状→人工自查"},
    {"role": "user", "text": "1、A4  2、B6？"},
    {"role": "assistant", "text": "确认卡：A4 镜像①② + 通用红线③罚单 + 人工自查价格形状"},
    {"role": "user", "text": "确认。大多数情况下不会触发对吗"},
]


def hsbc_glm52_extractor(conversation: list[dict]) -> ExtractionResult:
    """glm-5.2 读 onboarding_dryrun_0731.md HSBC transcript 产出的 ExtractionResult（固化）。

    生产用 API responder（W2）替换本函数为 headless 自动调 glm-5.2；
    本函数是 W1 的「模型内联」产出，证明 harness 跑通 + 供 eval 基线。
    镜像文本经 build_card 内 redline.guard 校验（R3）。
    """
    a = Assumption(text="管理层战略清晰，重组聚焦见效")
    return ExtractionResult(
        holding_reason_raw="按照年来看，它的股价表现稳健上升的形状",
        assumptions=[a],
        mirrors=[
            {"assumption_id": a.id, "text": "宣布战略转向、重组叫停，或亚洲核心资产被剥离"},
            {"assumption_id": a.id, "text": "CEO / CFO 突然离职"},
        ],
        manual_items=["价格「形状」：年线"],
    )


def run_entry_agent_demo() -> ThesisCard:
    """跑 HSBC transcript 通过 harness，产出确认卡 + 复述（经 redline.guard）。

    - filer_type=FOREIGN_ISSUER_20F_6K（HSBC 是 20-F/6-K 申报方，6-K 主渠道，发现 7）
    - user_thresholds large_fine=5e7（贴合 transcript round-4 的 5000 万阈值）
    - enabled_redlines=["large_fine"]（mirror②已覆盖 CEO/CFO 离职，关停 exec_change 去重，发现 1）
    - manual_check = 价格形状年线（发现 5）
    """
    card = build_card(
        user_id="beta1",
        ticker="HSBC",
        filer_type=FilerType.FOREIGN_ISSUER_20F_6K,
        conversation=HSBC_TRANSCRIPT,
        extractor=hsbc_glm52_extractor,
        user_thresholds={"large_fine": {"amount_usd": 5e7}},
        enabled_redlines=["large_fine"],
    )
    print(render_summary(card))
    print("\n--- card_json ---")
    import json
    print(json.dumps(to_dict(card), ensure_ascii=False, indent=2))
    return card


if __name__ == "__main__":
    run_entry_agent_demo()
