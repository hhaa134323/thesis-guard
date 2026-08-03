"""models serde 与结构测试（无网络）。"""
from __future__ import annotations

import json

from thesis_watch.models import (
    Assumption,
    BrokenCondition,
    ConditionLayer,
    CondStatus,
    Confirmation,
    Evidence,
    FilerType,
    HistoricalExample,
    ManualCheckItem,
    RedlineTemplate,
    ResolveAction,
    ThesisCard,
    CheckResult,
    from_dict,
    to_dict,
    to_json,
)


def _make_card() -> ThesisCard:
    a = Assumption(text="服务收入持续高增")
    mirror = BrokenCondition(
        layer=ConditionLayer.MIRROR,
        source_assumption_id=a.id,
        text="服务收入同比转负",
        judgeable=True,
        historical_example=HistoricalExample(
            event="某发行人服务收入同比转负（待补一手来源）",
            verified=False,
        ),
    )
    redline = BrokenCondition(
        layer=ConditionLayer.REDLINE,
        template=RedlineTemplate.LARGE_FINE,
        text="大额罚单",
        judgeable=True,
        threshold={"amount_usd": 1e8},
    )
    return ThesisCard(
        user_id="beta1",
        ticker="AAPL",
        filer_type=FilerType.DOMESTIC_10K,
        holding_reason_raw="看好服务收入持续高增",
        key_assumptions=[a],
        broken_conditions=[mirror, redline],
        manual_check_items=[ManualCheckItem(text="跌破60日均线")],
        confirmation=Confirmation(paraphrased=True, confirmed_at="2026-07-31",
                                  confirmed_by_user=True),
    )


def test_to_dict_enum_to_value():
    d = to_dict(_make_card())
    assert d["filer_type"] == "domestic_10k"
    assert d["broken_conditions"][0]["layer"] == "mirror"
    assert d["broken_conditions"][1]["template"] == "large_fine"
    assert d["manual_check_items"][0]["reason"] == "价格图形型"


def test_roundtrip_preserves_enums_and_links():
    card = _make_card()
    card2 = from_dict(ThesisCard, to_dict(card))
    assert card2.filer_type == FilerType.DOMESTIC_10K
    assert card2.broken_conditions[0].layer == ConditionLayer.MIRROR
    assert card2.broken_conditions[0].source_assumption_id == card.key_assumptions[0].id
    assert card2.broken_conditions[1].template == RedlineTemplate.LARGE_FINE
    assert card2.broken_conditions[1].threshold == {"amount_usd": 1e8}
    assert card2.manual_check_items[0].text == "跌破60日均线"
    assert card2.confirmation.confirmed_by_user is True
    assert card2.broken_conditions[0].historical_example.verified is False


def test_checkresult_roundtrip_with_resolve():
    r = CheckResult(
        card_id="c1", cond_id="cond1", status=CondStatus.TRIGGERED,
        evidence=[Evidence(url="https://sec.gov/x", excerpt="big fine")],
        refusal_code=None,
        resolve=ResolveAction.CONFIRMED_BROKEN,
    )
    r2 = from_dict(CheckResult, to_dict(r))
    assert r2.status == CondStatus.TRIGGERED
    assert r2.resolve == ResolveAction.CONFIRMED_BROKEN
    assert r2.evidence[0].url == "https://sec.gov/x"


def test_to_json_is_valid_json():
    s = to_json(_make_card())
    assert isinstance(json.loads(s), dict)


def test_roundtrip_stable_id():
    card = _make_card()
    card2 = from_dict(ThesisCard, to_dict(card))
    assert card2.card_id == card.card_id
    assert card2.key_assumptions[0].id == card.key_assumptions[0].id


def test_holding_horizon_roundtrip():
    """P5：持仓周期字段（long/mid/trade，用户自报）serde。"""
    card = ThesisCard(user_id="beta1", ticker="MCO",
                      holding_reason_raw="评级双寡头", holding_horizon="long")
    d = to_dict(card)
    assert d["holding_horizon"] == "long"
    card2 = from_dict(ThesisCard, d)
    assert card2.holding_horizon == "long"
    # 缺省 None
    assert to_dict(ThesisCard(user_id="b", ticker="X", holding_reason_raw="r"))["holding_horizon"] is None
