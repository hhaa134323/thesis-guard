"""SQLite 持久化测试（无网络，内存库）。"""
from __future__ import annotations

from thesis_watch.models import (
    Assumption,
    BrokenCondition,
    CheckResult,
    CondStatus,
    ConditionLayer,
    Confirmation,
    FilerType,
    ManualCheckItem,
    RedlineTemplate,
    ResolveAction,
    ThesisCard,
)
from thesis_watch.store import ThesisStore


def _card(user_id: str = "beta1") -> ThesisCard:
    a = Assumption(text="服务收入持续高增")
    return ThesisCard(
        user_id=user_id,
        ticker="AAPL",
        filer_type=FilerType.DOMESTIC_10K,
        holding_reason_raw="看好服务收入持续高增",
        key_assumptions=[a],
        broken_conditions=[
            BrokenCondition(layer=ConditionLayer.MIRROR, source_assumption_id=a.id,
                           text="服务收入同比转负", judgeable=True),
            BrokenCondition(layer=ConditionLayer.REDLINE, template=RedlineTemplate.LARGE_FINE,
                           text="大额罚单", judgeable=True, threshold={"amount_usd": 1e8}),
        ],
        manual_check_items=[ManualCheckItem(text="跌破60日均线")],
        confirmation=Confirmation(paraphrased=True, confirmed_by_user=True),
    )


def test_seed_preset_users():
    s = ThesisStore()
    assert s.seed_preset_users() == 5
    assert s.seed_preset_users() == 0  # 第二次幂等
    assert s.get_user("beta1") is not None
    assert s.get_user("ghost") is None


def test_card_roundtrip():
    s = ThesisStore()
    s.seed_preset_users()
    card = _card()
    s.upsert_card(card)
    got = s.get_card(card.card_id)
    assert got is not None
    assert got.ticker == "AAPL"
    assert got.filer_type == FilerType.DOMESTIC_10K
    assert len(got.broken_conditions) == 2
    assert got.broken_conditions[0].layer == ConditionLayer.MIRROR
    assert got.broken_conditions[1].template == RedlineTemplate.LARGE_FINE
    assert got.broken_conditions[0].source_assumption_id == got.key_assumptions[0].id
    assert got.confirmation.confirmed_by_user is True


def test_list_cards_by_user():
    s = ThesisStore()
    s.seed_preset_users()
    s.upsert_card(_card("beta1"))
    s.upsert_card(_card("beta1"))
    s.upsert_card(_card("beta2"))
    assert len(s.list_cards("beta1")) == 2
    assert len(s.list_cards("beta2")) == 1
    assert s.list_cards("beta3") == []


def test_check_result_persistence():
    s = ThesisStore()
    s.seed_preset_users()
    card = _card()
    s.upsert_card(card)
    cond = card.broken_conditions[0]
    s.save_check_result(CheckResult(
        card_id=card.card_id, cond_id=cond.id, status=CondStatus.TRIGGERED,
        resolve=ResolveAction.CONFIRMED_BROKEN,
    ))
    results = s.list_check_results(card.card_id)
    assert len(results) == 1
    assert results[0].status == CondStatus.TRIGGERED
    assert results[0].resolve == ResolveAction.CONFIRMED_BROKEN


def test_set_user_email():
    s = ThesisStore()
    s.seed_preset_users()
    s.set_user_email("beta1", "beta1@example.com")
    assert s.get_user("beta1")["email"] == "beta1@example.com"


def test_get_missing_card():
    s = ThesisStore()
    assert s.get_card("nope") is None
