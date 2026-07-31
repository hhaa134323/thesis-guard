"""破局条件两层逻辑测试（无网络）。"""
from __future__ import annotations

from thesis_watch.conditions import (
    build_card_conditions,
    default_redline_pack,
    is_price_pattern,
    judgeable,
    make_mirror,
    to_manual_check,
)
from thesis_watch.models import (
    Assumption,
    ConditionLayer,
    RedlineTemplate,
)


def test_price_pattern_detection():
    assert is_price_pattern("跌破60日均线") is True
    assert is_price_pattern("头肩顶成型") is True
    assert is_price_pattern("放量突破阻力位") is True
    assert is_price_pattern("服务收入同比转负") is False
    assert is_price_pattern("大额罚单") is False


def test_judgeable_mirror_nonprice():
    assert judgeable("服务收入同比转负") is True
    assert judgeable("跌破60日均线") is False


def test_make_mirror_structure():
    a = Assumption(text="服务收入持续高增")
    m = make_mirror(a, mirror_text="服务收入同比转负")
    assert m.layer == ConditionLayer.MIRROR
    assert m.source_assumption_id == a.id
    assert m.judgeable is True


def test_make_mirror_price_pattern_unjudgeable():
    a = Assumption(text="股价在均线上方运行")
    m = make_mirror(a, mirror_text="跌破60日均线")
    assert m.judgeable is False


def test_default_redline_pack_three():
    pack = default_redline_pack()
    assert len(pack) == 3
    templates = {c.template for c in pack}
    assert templates == {RedlineTemplate.LARGE_FINE, RedlineTemplate.EXEC_CHANGE,
                         RedlineTemplate.RESTATEMENT}
    assert all(c.layer == ConditionLayer.REDLINE for c in pack)
    assert all(c.judgeable for c in pack)


def test_redline_threshold_override():
    pack = default_redline_pack(thresholds={"large_fine": {"amount_usd": 5e7}})
    fine = next(c for c in pack if c.template == RedlineTemplate.LARGE_FINE)
    assert fine.threshold["amount_usd"] == 5e7
    # 其他模板阈值未动
    rest = next(c for c in pack if c.template == RedlineTemplate.EXEC_CHANGE)
    assert rest.threshold["roles"] == ["CEO", "CFO"]


def test_build_card_conditions_combines_layers():
    a = Assumption(text="服务收入持续高增")
    mirror = make_mirror(a, "服务收入同比转负")
    broken, manual = build_card_conditions(
        assumptions=[a], mirrors=[mirror],
    )
    assert len(broken) == 1 + 3  # 1 mirror + 3 redline defaults
    assert broken[0].layer == ConditionLayer.MIRROR
    assert {c.layer for c in broken[1:]} == {ConditionLayer.REDLINE}
    assert manual == []


def test_to_manual_check():
    m = to_manual_check("跌破60日均线")
    assert m.reason == "价格图形型"
    assert m.cadence == "monthly"


def test_historical_example_not_verified_by_default():
    pack = default_redline_pack()
    for c in pack:
        assert c.historical_example.verified is False  # 待网络恢复后补一手来源
        assert c.historical_example.event  # 占位描述在
