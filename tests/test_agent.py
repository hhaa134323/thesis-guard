"""agent.py 测试（Phase 2 重写：harness 骨架已删，测 build_card_from_extraction + render_summary）。

旧 test_agent 测 ToolRegistry/build_card/mock_extractor（已删）；现测 build_card_from_extraction
（EntryExtraction → ThesisCard 草稿 + rejected_mirrors）+ render_summary（R6 + redline.clean）。
"""
from __future__ import annotations

import pytest

from thesis_watch.agent import build_card_from_extraction, render_summary
from thesis_watch.models import ConditionLayer, RedlineTemplate
from thesis_watch.schema import Assumption, EntryExtraction, ManualCheckItem, MirrorSpec


def _ext(holding="看好服务收入持续高增",
         assumptions=("切换成本锁定客户，竞品难蚕食份额",),
         mirrors=(("切换成本锁定客户", "服务收入同比转负",
                   {"metric": "rev_yoy", "operator": "<", "value": 0}, "sec_filing_field"),),
         manual=()):
    return EntryExtraction(
        holding_reason_raw=holding,
        key_assumptions=[Assumption(text=t) for t in assumptions],
        mirrors=[MirrorSpec(assumption_text=a, mirror_text=m, threshold=t, source_type=s)
                 for (a, m, t, s) in mirrors],
        manual_items=[ManualCheckItem(text=x) for x in manual],
    )


def test_build_card_from_extraction_produces_two_layers():
    card, rejected = build_card_from_extraction(_ext(), user_id="beta1", ticker="AAPL", tier=None)
    layers = {c.layer for c in card.broken_conditions}
    assert layers == {ConditionLayer.MIRROR, ConditionLayer.REDLINE}
    assert len(card.broken_conditions) == 1 + 3   # 1 mirror + 3 redline defaults
    assert card.broken_conditions[0].layer == ConditionLayer.MIRROR
    assert {c.template for c in card.broken_conditions[1:]} == {
        RedlineTemplate.LARGE_FINE, RedlineTemplate.EXEC_CHANGE, RedlineTemplate.RESTATEMENT
    }
    assert rejected == []


def test_build_card_from_extraction_rejects_mirror_missing_threshold():
    """P3：mirror 缺 threshold → make_mirror 返 None → 进 rejected（不进 broken_conditions）。"""
    ext = _ext(mirrors=(("切换成本锁定客户", "服务收入同比转负", None, "sec_filing_field"),))
    card, rejected = build_card_from_extraction(ext, user_id="beta1", ticker="AAPL", tier=None)
    assert all(c.layer == ConditionLayer.REDLINE for c in card.broken_conditions)  # 只剩红线包
    assert len(rejected) == 1
    assert "P3" in rejected[0]["reason"]


def test_build_card_from_extraction_price_pattern_to_manual():
    """holding_reason_raw 含价格图形 → 降 manual_check_items（每月提醒）。"""
    ext = _ext(holding="看好AAPL，盯60日均线", mirrors=())
    card, _ = build_card_from_extraction(ext, user_id="beta1", ticker="AAPL", tier=None)
    assert len(card.manual_check_items) == 1
    assert card.manual_check_items[0].reason == "价格图形型"
    assert card.manual_check_items[0].cadence == "monthly"


def test_build_card_from_extraction_not_confirmed():
    card, _ = build_card_from_extraction(_ext(), user_id="beta1", ticker="AAPL", tier=None)
    assert card.confirmation.confirmed_by_user is False


def test_render_summary_clean_and_complete():
    card, _ = build_card_from_extraction(_ext(), user_id="beta1", ticker="AAPL", tier=None)
    text = render_summary(card)
    assert "AAPL" in text
    assert "服务收入同比转负" in text
    assert "请确认或修改后入库" in text


def test_dirty_mirror_text_triggers_guard():
    """系统生成的镜像文本踩红线 → redline.guard 阻断（R3）。"""
    ext = _ext(mirrors=(("切换成本锁定客户", "建议关注收入转负",
                         {"metric": "x"}, "sec_filing_field"),))
    with pytest.raises(Exception):
        build_card_from_extraction(ext, user_id="beta1", ticker="AAPL", tier=None)
