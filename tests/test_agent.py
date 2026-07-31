"""Agent harness 骨架测试（mock extractor，无网络）。"""
from __future__ import annotations

import pytest

from thesis_watch.agent import (
    ExtractionResult,
    ToolRegistry,
    build_card,
    default_tools,
    mock_extractor,
    render_summary,
)
from thesis_watch.models import Assumption, ConditionLayer, FilerType, RedlineTemplate


def _conv() -> list[dict]:
    return [
        {"role": "user", "text": "持有 AAPL，看好服务收入持续高增。"},
        {"role": "user", "text": "破的话看收入同比转负；盯60日线。"},
    ]


def test_build_card_produces_two_layers():
    card = build_card("beta1", "AAPL", FilerType.DOMESTIC_10K, _conv(), mock_extractor)
    layers = {c.layer for c in card.broken_conditions}
    assert layers == {ConditionLayer.MIRROR, ConditionLayer.REDLINE}
    assert len(card.broken_conditions) == 1 + 3   # 1 mirror + 3 redline defaults
    assert card.broken_conditions[0].layer == ConditionLayer.MIRROR
    assert {c.template for c in card.broken_conditions[1:]} == {
        RedlineTemplate.LARGE_FINE, RedlineTemplate.EXEC_CHANGE, RedlineTemplate.RESTATEMENT
    }


def test_build_card_manual_check_price_pattern():
    card = build_card("beta1", "AAPL", FilerType.DOMESTIC_10K, _conv(), mock_extractor)
    assert len(card.manual_check_items) == 1
    assert card.manual_check_items[0].reason == "价格图形型"
    assert card.manual_check_items[0].cadence == "monthly"


def test_build_card_not_confirmed_until_user():
    card = build_card("beta1", "AAPL", FilerType.DOMESTIC_10K, _conv(), mock_extractor)
    assert card.confirmation.confirmed_by_user is False
    assert card.confirmation.paraphrased is False


def test_render_summary_is_redline_clean():
    card = build_card("beta1", "AAPL", FilerType.DOMESTIC_10K, _conv(), mock_extractor)
    text = render_summary(card)
    assert "AAPL" in text
    assert "服务收入同比转负" in text
    assert "请确认或修改后入库" in text


def test_dirty_mirror_text_triggers_guard():
    """系统生成的镜像文本若踩红线，guard 应阻断（R3）。"""
    a = Assumption(text="收入增长")

    def dirty_extractor(_conv):
        return ExtractionResult(
            holding_reason_raw="看好收入增长",
            assumptions=[a],
            mirrors=[{"assumption_id": a.id, "text": "建议关注收入转负"}],
        )
    with pytest.raises(Exception):
        build_card("beta1", "AAPL", FilerType.DOMESTIC_10K, _conv(), dirty_extractor)


def test_tool_registry_dispatch():
    tools = default_tools()
    assert "is_price_pattern" in tools.names()
    assert tools.call("is_price_pattern", {"text": "跌破60日均线"}) is True
    assert tools.call("is_price_pattern", {"text": "大额罚单"}) is False


def test_tool_registry_unknown_raises():
    tools = default_tools()
    with pytest.raises(KeyError):
        tools.call("nope", {})
