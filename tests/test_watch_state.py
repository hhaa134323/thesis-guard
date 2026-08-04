"""watch 记忆单测（Stage 2 窗口 C / 任务 5）。

锁 acceptance：
- 新 watch item → change=new
- 距离阈值更近 → change=worsened（需 distance_to_threshold）
- MCO 连续 2 季 watch → 第 3 季 change=unchanged（history len 3）
- 不再 watch（untriggered）→ change=resolved
- 触发毕业线（distance<=0）/ triggered → change=escalated，current_status=escalated
- get_active_watch_states() 返回所有 active（不含 resolved/escalated）
- 季频复盘：卡 next_verdict.date 到期 → 返需复查项 + quarters_on_watch；未到期 / 无日期 → []
- 不自动过期：>365 天仍 active 不删除
- 双模式：aggregate（card_id）→ 经 card + check_results 表展开（scheduler 集成路径）

不触网：monkeypatch watch_state._get_store 返 :memory: store（不污染真实 data/thesis.db，R9）。
"""
from __future__ import annotations

import datetime

import pytest

from thesis_watch import watch_state
from thesis_watch.models import (
    BrokenCondition,
    CheckResult,
    CondStatus,
    ConditionLayer,
    Confirmation,
    FilerType,
    NextVerdictData,
    ThesisCard,
)
from thesis_watch.store import ThesisStore
from thesis_watch.watch_state import (
    check_quarterly_review,
    get_active_watch_states,
    update_watch_states,
)

_T = datetime.timezone.utc


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _store() -> ThesisStore:
    s = ThesisStore(":memory:")
    s.seed_preset_users()
    return s


def _patch_store(monkeypatch, store):
    monkeypatch.setattr(watch_state, "_get_store", lambda: store)


def _cr(ticker="MCO", cid="c1", status="watch", *, value=None, distance=None,
        grad=None, checked_at=None, cond_text="营收增速跌破 5%") -> dict:
    d: dict = {"ticker": ticker, "condition_id": cid, "status": status, "condition_text": cond_text}
    if value is not None:
        d["value"] = value
    if distance is not None:
        d["distance_to_threshold"] = distance
    if grad is not None:
        d["graduation_line"] = grad
    if checked_at is not None:
        d["checked_at"] = checked_at
    return d


def _card(ticker="MCO", *, cond_ids=("c1",), next_verdict_date=None) -> ThesisCard:
    broken = [BrokenCondition(id=c, layer=ConditionLayer.MIRROR, text=f"cond {c}",
                              threshold={"metric": "x", "operator": "<", "value": 0},
                              source_type="sec_filing_field") for c in cond_ids]
    nv = NextVerdictData(event="Q3 财报", date=next_verdict_date) if next_verdict_date else None
    return ThesisCard(user_id="beta1", ticker=ticker, filer_type=FilerType.OTHER,
                      holding_reason_raw="看好壁垒", broken_conditions=broken,
                      next_verdict=nv, confirmation=Confirmation(confirmed_by_user=True))


# --------------------------------------------------------------------------- #
# _process_one（per-condition 比对）—— spec acceptance
# --------------------------------------------------------------------------- #

def test_new_watch_item(monkeypatch):
    _patch_store(monkeypatch, _store())
    out = update_watch_states([_cr(distance=5.0, checked_at="2026-05-01T00:00:00Z")])
    assert len(out) == 1
    a = out[0]
    assert a["change"] == "new"
    assert a["current_status"] == "active"
    assert a["first_seen_date"] == "2026-05-01T00:00:00Z"
    assert a["last_checked_date"] == "2026-05-01T00:00:00Z"
    assert a["condition_text"] == "营收增速跌破 5%"
    assert a["status"] == "active"  # 别名（notification 读 status）


def test_worsened_closer_to_threshold(monkeypatch):
    store = _store()
    _patch_store(monkeypatch, store)
    update_watch_states([_cr(distance=5.0, checked_at="2026-05-01T00:00:00Z")])  # new
    out = update_watch_states([_cr(distance=2.0, checked_at="2026-08-01T00:00:00Z")])  # 距离 5→2 变近
    assert out[0]["change"] == "worsened"
    assert out[0]["current_status"] == "active"
    assert out[0]["first_seen_date"] == "2026-05-01T00:00:00Z"  # 延续，保留首次发现日


def test_three_quarters_unchanged(monkeypatch):
    """MCO 连续 2 季 watch → 第 3 季 change=unchanged，history len 3（仍在 watch，较上次无变化）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    update_watch_states([_cr(distance=5.0, checked_at="2026-02-01T00:00:00Z")])  # Q1 new
    update_watch_states([_cr(distance=5.0, checked_at="2026-05-01T00:00:00Z")])  # Q2 unchanged
    out = update_watch_states([_cr(distance=5.0, checked_at="2026-08-01T00:00:00Z")])  # Q3 unchanged
    assert out[0]["change"] == "unchanged"
    assert out[0]["current_status"] == "active"
    assert out[0]["first_seen_date"] == "2026-02-01T00:00:00Z"  # 首次发现日不变
    ws = store.get_watch_state("MCO", "c1")
    assert len(ws["history"]) == 3  # 第 3 季


def test_resolved_no_longer_watch(monkeypatch):
    store = _store()
    _patch_store(monkeypatch, store)
    update_watch_states([_cr(distance=5.0, checked_at="2026-05-01T00:00:00Z")])  # new (active)
    out = update_watch_states([_cr(status="untriggered", checked_at="2026-08-01T00:00:00Z")])
    assert out[0]["change"] == "resolved"
    assert out[0]["current_status"] == "resolved"
    # resolved 的 state 不在 active 列表
    assert get_active_watch_states() == []


def test_escalated_via_triggered(monkeypatch):
    """watch 项 → triggered（check_agent 判破）→ escalated。"""
    store = _store()
    _patch_store(monkeypatch, store)
    update_watch_states([_cr(distance=5.0, checked_at="2026-05-01T00:00:00Z")])  # new (active)
    out = update_watch_states([_cr(status="triggered", checked_at="2026-08-01T00:00:00Z")])
    assert out[0]["change"] == "escalated"
    assert out[0]["current_status"] == "escalated"


def test_escalated_via_graduation_line(monkeypatch):
    """watch 项 distance<=0（触发毕业线）→ escalated（即使 check_agent 仍判 watch）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    update_watch_states([_cr(distance=5.0, checked_at="2026-05-01T00:00:00Z")])  # new (active)
    out = update_watch_states([_cr(status="watch", distance=-0.5,
                                   checked_at="2026-08-01T00:00:00Z")])  # 距离转负 = 触发
    assert out[0]["change"] == "escalated"
    assert out[0]["current_status"] == "escalated"


def test_triggered_from_start_no_prev_skipped(monkeypatch):
    """triggered 无 active watch 前史 → 非 watch transition，不产出（不算 watch state）。"""
    _patch_store(monkeypatch, _store())
    out = update_watch_states([_cr(status="triggered")])
    assert out == []


def test_untriggered_no_prev_skipped(monkeypatch):
    """untriggered 从未 active → 不产出。"""
    _patch_store(monkeypatch, _store())
    out = update_watch_states([_cr(status="untriggered")])
    assert out == []


def test_cond_id_fallback(monkeypatch):
    """check_result 用 cond_id（非 condition_id）也能匹配。"""
    _patch_store(monkeypatch, _store())
    out = update_watch_states([{"ticker": "MCO", "cond_id": "c9", "status": "watch", "distance": 5.0}])
    assert out[0]["condition_id"] == "c9"
    assert out[0]["change"] == "new"


def test_missing_pk_skipped(monkeypatch):
    """无 ticker / 无 condition_id → 跳过（不崩）。"""
    _patch_store(monkeypatch, _store())
    assert update_watch_states([{"status": "watch"}]) == []
    assert update_watch_states([{"ticker": "MCO", "status": "watch"}]) == []


def test_condition_text_preserved_across_updates(monkeypatch):
    """cond_text 首次写入，后续 update 缺 cond_text 时保留旧值。"""
    store = _store()
    _patch_store(monkeypatch, store)
    update_watch_states([_cr(cond_text="营收增速跌破 5%", distance=5.0,
                             checked_at="2026-05-01T00:00:00Z")])
    out = update_watch_states([_cr(cond_text="", distance=5.0,
                                   checked_at="2026-08-01T00:00:00Z")])  # 不带 cond_text
    assert out[0]["condition_text"] == "营收增速跌破 5%"


def test_empty_check_results(monkeypatch):
    _patch_store(monkeypatch, _store())
    assert update_watch_states([]) == []


# --------------------------------------------------------------------------- #
# get_active_watch_states
# --------------------------------------------------------------------------- #

def test_get_active_watch_states_filters_status(monkeypatch):
    """只返 active（不含 resolved / escalated）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "a",
                              "first_seen_date": "2026-01-01", "last_checked_date": "2026-05-01",
                              "status": "active", "history": []})
    store.upsert_watch_state({"ticker": "NVDA", "condition_id": "c2", "condition_text": "b",
                              "first_seen_date": "2026-01-01", "last_checked_date": "2026-05-01",
                              "status": "active", "history": []})
    store.upsert_watch_state({"ticker": "AAPL", "condition_id": "c3", "condition_text": "c",
                              "first_seen_date": "2026-01-01", "last_checked_date": "2026-05-01",
                              "status": "resolved", "history": []})
    store.upsert_watch_state({"ticker": "TSLA", "condition_id": "c4", "condition_text": "d",
                              "first_seen_date": "2026-01-01", "last_checked_date": "2026-05-01",
                              "status": "escalated", "history": []})
    active = get_active_watch_states()
    assert {a["ticker"] for a in active} == {"MCO", "NVDA"}
    assert all(a["status"] == "active" for a in active)


# --------------------------------------------------------------------------- #
# 不自动过期（>365 天仍 active 不删除）
# --------------------------------------------------------------------------- #

def test_no_auto_expiry_over_365_days(monkeypatch):
    """超过 365 天仍 active → 不删除（update / get_active / quarterly 都不删）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    old = (datetime.date.today() - datetime.timedelta(days=400)).isoformat()
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "老 watch",
                              "first_seen_date": old, "last_checked_date": old,
                              "status": "active",
                              "history": [{"date": old, "value": None, "distance_to_threshold": 3.0,
                                           "status_change": "new"}]})
    # update 空 check_results → 不动旧 state
    assert update_watch_states([]) == []
    assert store.get_watch_state("MCO", "c1") is not None  # 仍在
    assert any(a["ticker"] == "MCO" for a in get_active_watch_states())  # 仍在 active


# --------------------------------------------------------------------------- #
# 季频复盘 check_quarterly_review
# --------------------------------------------------------------------------- #

def test_quarterly_review_due_returns_items(monkeypatch):
    """卡 next_verdict.date 到期 → 返需复查的 active watch 项 + quarters_on_watch。"""
    store = _store()
    _patch_store(monkeypatch, store)
    today = datetime.date.today().isoformat()
    store.upsert_card(_card("MCO", next_verdict_date=today))  # 到期
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "营收 watch",
                              "first_seen_date": "2026-02-01", "last_checked_date": "2026-08-01",
                              "status": "active",
                              "history": [{"date": "2026-02-01", "value": None,
                                           "distance_to_threshold": 5.0, "status_change": "new"},
                                          {"date": "2026-05-01", "value": None,
                                           "distance_to_threshold": 5.0, "status_change": "unchanged"},
                                          {"date": "2026-08-01", "value": None,
                                           "distance_to_threshold": 5.0, "status_change": "unchanged"}]})
    out = check_quarterly_review()
    assert len(out) == 1
    assert out[0]["ticker"] == "MCO"
    assert out[0]["condition_id"] == "c1"
    assert out[0]["quarters_on_watch"] == 3  # len(history)
    assert out[0]["first_seen_date"] == "2026-02-01"


def test_quarterly_review_not_due_returns_empty(monkeypatch):
    """卡 next_verdict.date 未来 → 未到期 → []。"""
    store = _store()
    _patch_store(monkeypatch, store)
    future = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
    store.upsert_card(_card("MCO", next_verdict_date=future))
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "x",
                              "first_seen_date": "2026-02-01", "last_checked_date": "2026-08-01",
                              "status": "active", "history": []})
    assert check_quarterly_review() == []


def test_quarterly_review_no_next_verdict_returns_empty(monkeypatch):
    """卡无 next_verdict（date=None）→ []（无复盘日，不催）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    store.upsert_card(_card("MCO", next_verdict_date=None))
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "x",
                              "first_seen_date": "2026-02-01", "last_checked_date": "2026-08-01",
                              "status": "active", "history": []})
    assert check_quarterly_review() == []


def test_quarterly_review_resolved_not_returned(monkeypatch):
    """resolved / escalated 的 watch state 不进复查列表（只 active）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    today = datetime.date.today().isoformat()
    store.upsert_card(_card("MCO", next_verdict_date=today))
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "已解决",
                              "first_seen_date": "2026-02-01", "last_checked_date": "2026-08-01",
                              "status": "resolved", "history": []})
    assert check_quarterly_review() == []


def test_quarterly_review_past_date_due(monkeypatch):
    """复盘日已过（past）→ 仍 due（逾期复查）。"""
    store = _store()
    _patch_store(monkeypatch, store)
    past = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    store.upsert_card(_card("MCO", next_verdict_date=past))
    store.upsert_watch_state({"ticker": "MCO", "condition_id": "c1", "condition_text": "x",
                              "first_seen_date": "2026-02-01", "last_checked_date": "2026-08-01",
                              "status": "active", "history": [{"date": "2026-02-01", "value": None,
                                                               "distance_to_threshold": 5.0,
                                                               "status_change": "new"}]})
    out = check_quarterly_review()
    assert len(out) == 1 and out[0]["ticker"] == "MCO"


# --------------------------------------------------------------------------- #
# 双模式：aggregate（scheduler 集成路径）
# --------------------------------------------------------------------------- #

def test_aggregate_expand_via_check_results_table(monkeypatch):
    """scheduler 传 aggregate（card_id 无 condition_id）→ 经 card + check_results 表展开成 per-condition。"""
    store = _store()
    _patch_store(monkeypatch, store)
    card = _card("MCO", cond_ids=("c1", "c2"))
    store.upsert_card(card)
    # check_agent 存的 per-condition CheckResult（c1=watch, c2=untriggered）
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c1",
                                        status=CondStatus.WATCH, checked_at="2026-08-01T00:00:00Z"))
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c2",
                                        status=CondStatus.UNTRIGGERED, checked_at="2026-08-01T00:00:00Z"))
    agg = {"card_id": card.card_id, "ticker": "MCO", "n_watch": 1, "n_triggered": 0,
           "n_untriggered": 1, "triggered": []}
    out = update_watch_states([agg])
    # c1（watch 无前史）→ new；c2（untriggered 无前史）→ 跳过
    assert len(out) == 1
    assert out[0]["condition_id"] == "c1"
    assert out[0]["change"] == "new"
    assert out[0]["current_status"] == "active"
    assert out[0]["condition_text"] == "cond c1"  # 从 card 的 broken_condition.text 取


def test_aggregate_expand_escalated_via_triggered(monkeypatch):
    """aggregate 展开 + 上次 active watch + 这次 triggered → escalated。"""
    store = _store()
    _patch_store(monkeypatch, store)
    card = _card("MCO", cond_ids=("c1",))
    store.upsert_card(card)
    # 上次跑：c1 watch（建 active watch state）
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c1",
                                        status=CondStatus.WATCH, checked_at="2026-05-01T00:00:00Z"))
    update_watch_states([{"card_id": card.card_id, "ticker": "MCO", "n_watch": 1,
                          "n_triggered": 0, "n_untriggered": 0, "triggered": []}])
    # 这次跑：c1 triggered
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c1",
                                        status=CondStatus.TRIGGERED, checked_at="2026-08-01T00:00:00Z"))
    out = update_watch_states([{"card_id": card.card_id, "ticker": "MCO", "n_watch": 0,
                                "n_triggered": 1, "n_untriggered": 0,
                                "triggered": [{"cond": "cond c1", "urls": []}]}])
    assert out[0]["change"] == "escalated"
    assert out[0]["current_status"] == "escalated"


def test_aggregate_no_card_skipped(monkeypatch):
    """aggregate 的 card_id 不存在 → []。"""
    _patch_store(monkeypatch, _store())
    out = update_watch_states([{"card_id": "no-such-card", "ticker": "MCO", "n_watch": 1}])
    assert out == []
