"""agent.py —— 录入卡组装（Phase 2：harness 骨架已删，仅留 build_card_from_extraction + render_summary）。

harness 骨架（ToolRegistry / build_card / mock_extractor / HSBC demo）已删——agent loop
（orchestrator.py）接管对话流程，不再需要 harness；entry_loop 复用 build_card_from_extraction
把 extract_card 工具的输出落成 ThesisCard 草稿（make_mirror + redline 默认包，不重复 G3）。
"""
from __future__ import annotations

from . import redline
from .conditions import (
    default_redline_pack,
    is_price_pattern,
    make_mirror,
    to_manual_check,
)
from .models import (
    Assumption,
    BrokenCondition,
    ConditionLayer,
    Confirmation,
    EntryAnchorData,
    FilerType,
    ManualCheckItem,
    NextVerdictData,
    ThesisCard,
)


def build_card_from_extraction(ext, *, user_id: str, ticker: str,
                               tier, filer_type=None,
                               user_thresholds: dict | None = None,
                               enabled_redlines: list[str] | None = None
                               ) -> tuple[ThesisCard, list[dict]]:
    """EntryExtraction（pydantic LLM 输出，schema.py）→ (ThesisCard, rejected_mirrors)。

    录入 loop 把单次 extract() 的结构化输出落成卡片：
    - 镜像文本经 redline.guard（R3：系统生成内容）；
    - **P3：mirror 缺 threshold/source_type → make_mirror 返 None，不进 broken_conditions，
      收进 rejected_mirrors 返回，由 entry_loop 转 open_questions（不生成 threshold:null 镜像）**；
    - Layer 2 红线默认包叠加（conditions.default_redline_pack，可去重）；
    - 价格图形型兜底进 manual_check_items（is_price_pattern）；
    - entry_anchor / next_verdict / position_cap_tier 落确认卡字段；
    - confirmation 置未确认（用户复述确认后才 True，由 loop 改）。
    """
    raw = (ext.holding_reason_raw or "") if ext is not None else ""
    assumptions = [Assumption(text=a.text, judgeable=a.judgeable)
                  for a in (ext.key_assumptions or [])] if ext is not None else []

    broken: list[BrokenCondition] = []
    rejected: list[dict] = []  # P3：缺 threshold/source_type 的镜像 → open_question
    for m in (ext.mirrors or []) if ext is not None else []:
        a = next((x for x in assumptions if x.text == m.assumption_text), None)
        if a is None:
            a = Assumption(text=m.assumption_text)
            assumptions.append(a)
        redline.guard(m.mirror_text)
        m_obj = make_mirror(a, m.mirror_text,
                            threshold=m.threshold, source_type=m.source_type)
        if m_obj is not None:
            broken.append(m_obj)
        else:
            rejected.append({"field": "mirrors",
                "reason": "缺 threshold/source_type，镜像不可判定（P3）",
                "text": m.mirror_text})
    broken.extend(default_redline_pack(user_thresholds, enabled_redlines))

    manual = [ManualCheckItem(text=m.text, reason=m.reason, cadence=m.cadence)
              for m in (ext.manual_items or [])] if ext is not None else []
    if ext is not None and is_price_pattern(raw) and not any(is_price_pattern(m.text) for m in manual):
        manual.append(to_manual_check(raw))

    ft = filer_type if filer_type is not None else FilerType.OTHER
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

    card = ThesisCard(
        user_id=user_id, ticker=ticker, filer_type=ft,
        holding_reason_raw=raw,
        key_assumptions=assumptions,
        broken_conditions=broken,
        manual_check_items=manual,
        entry_anchor=ea, next_verdict=nv,
        position_cap_tier=tier.value if tier is not None else None,
        confirmation=Confirmation(paraphrased=True, confirmed_by_user=False),
    )
    return card, rejected


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


__all__ = ["build_card_from_extraction", "render_summary"]
