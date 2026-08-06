"""scheduler 单测（Stage 2 窗口 C / 任务 3）：daily check 胶水层。

mock price_monitor / check_agent / notification，验证 daily flow 顺序 +
alert/S4/digest 调用 + 重试 + env 配置 + 季频复盘（stateless 查 check_results）。不触网不落盘
（time.sleep mock 掉；store :memory:）。
"""
from __future__ import annotations

import asyncio
import datetime

import pytest

from thesis_watch import scheduler
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


class _Fake:
    """记录所有组件调用 (name, args)，返 configurable returns。"""
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.price_alerts: list[dict] = []
        self.check_results: list[dict] = []
        self.price_error: Exception | None = None
        self.check_error: Exception | None = None

    def rec(self, name, *args):
        self.calls.append((name, args))


def _patch(monkeypatch, fake: _Fake):
    # price_monitor.run_price_check → fake.price_alerts（或 raise）
    def _run_price_check(store=None, **kw):
        fake.rec("price_monitor.run_price_check", store)
        if fake.price_error is not None:
            raise fake.price_error
        return fake.price_alerts
    monkeypatch.setattr(scheduler.price_monitor, "run_price_check", _run_price_check)
    # price_monitor.load_all_cards → []（不让 _collect_manual_items 触 DB）
    monkeypatch.setattr(scheduler.price_monitor, "load_all_cards", lambda store: [])

    # check_agent.run_all → fake.check_results for beta1，[] else（或 raise）
    def _run_all(uid, cfg, store, **kw):
        fake.rec("check_agent.run_all", uid)
        if fake.check_error is not None:
            raise fake.check_error
        return fake.check_results if uid == "beta1" else []
    monkeypatch.setattr(scheduler.check_agent, "run_all", _run_all)

    # notification
    monkeypatch.setattr(scheduler.notification, "send_alert",
                        lambda ticker, alert_data, to_email: (fake.rec("notification.send_alert", ticker, alert_data, to_email) or True))
    monkeypatch.setattr(scheduler.notification, "send_digest",
                        lambda crs, pas, mis, to_email: (fake.rec("notification.send_digest", crs, pas, mis, to_email) or True))
    monkeypatch.setattr(scheduler.notification, "request_s4_action",
                        lambda ticker, td, to_email: (fake.rec("notification.request_s4_action", ticker, td, to_email) or True))

    # _send_email（错误通知 / 复盘提醒）— 记录 + no-op
    monkeypatch.setattr(scheduler, "_send_email",
                        lambda subject, body: (fake.rec("_send_email", subject, body) or True))
    # time.sleep — no-op（重试不睡）
    monkeypatch.setattr(scheduler.time, "sleep", lambda s: None)


def _run(fake: _Fake):
    """run_daily_check 一次（:memory: store + 空 cfg，log 静音）。"""
    store = ThesisStore(":memory:")
    return asyncio.run(scheduler.run_daily_check(store=store, cfg={}, log=lambda *a: None))


def _names(fake: _Fake):
    return [c[0] for c in fake.calls]


_PRICE_ALERT = {"ticker": "MCO", "current_price": 370.0, "threshold": 380,
                "triggered": True, "level": "hit", "condition_text": "加仓价 380",
                "position_type": "长线", "alert_type": "safety_margin",
                "timestamp": "2026-08-04T16:00:00Z"}
_TRIGGERED_CR = {"ticker": "NVDA", "n_triggered": 1, "n_watch": 0, "n_untriggered": 0,
                 "triggered": [{"cond": "CEO 离职", "urls": ["https://www.sec.gov/x"]}]}
_UNTRIGGERED_CR = {"ticker": "HSBC", "n_triggered": 0, "n_watch": 0, "n_untriggered": 2}


# --- flow 顺序 ---
def test_flow_order(monkeypatch):
    fake = _Fake()
    fake.price_alerts = [_PRICE_ALERT]
    fake.check_results = [_TRIGGERED_CR]
    _patch(monkeypatch, fake)
    _run(fake)
    names = _names(fake)
    assert names.index("price_monitor.run_price_check") < names.index("check_agent.run_all")
    assert names.index("check_agent.run_all") < names.index("notification.send_digest")


# --- price alert 不再单独发邮件（2026-08-06 设计调整：并入 digest）---
def test_price_alert_only_in_digest_not_separately_sent(monkeypatch):
    """价格提醒不再调 send_alert：只进 digest（破局 triggered 的 send_alert 逻辑不变，
    见 test_triggered_sends_alert_and_s4）。"""
    fake = _Fake()
    fake.price_alerts = [_PRICE_ALERT]
    _patch(monkeypatch, fake)
    _run(fake)
    alert_calls = [c for c in fake.calls if c[0] == "notification.send_alert"]
    # 价格 alert 不再单独发邮件 → 无以 MCO 为 ticker 的 send_alert 调用
    assert not any(c[1][0] == "MCO" for c in alert_calls)
    # 价格 alert 进了 digest（send_digest 收到 price_alerts）
    digest_calls = [c for c in fake.calls if c[0] == "notification.send_digest"]
    assert len(digest_calls) == 1
    _crs, pas, _mis, _to = digest_calls[0][1]
    assert len(pas) == 1 and pas[0]["ticker"] == "MCO"


# --- skip dict 在 scheduler 层过滤（8c65773 不回归）：不进 digest、不计 price_alerts ---
def test_price_skip_filtered_before_digest(monkeypatch):
    fake = _Fake()
    fake.price_alerts = [{"ticker": "MCO", "skipped": True, "reason": "price unavailable"}]
    _patch(monkeypatch, fake)
    result = _run(fake)
    digest_calls = [c for c in fake.calls if c[0] == "notification.send_digest"]
    _crs, pas, _mis, _to = digest_calls[0][1]
    assert pas == []                         # skip 被过滤掉，不进 digest
    assert result["price_alerts"] == 0       # 计数也排除了 skip


# --- triggered → send_alert + request_s4_action ---
def test_triggered_sends_alert_and_s4(monkeypatch):
    fake = _Fake()
    fake.check_results = [_TRIGGERED_CR]
    _patch(monkeypatch, fake)
    _run(fake)
    alert_calls = [c for c in fake.calls if c[0] == "notification.send_alert"]
    s4_calls = [c for c in fake.calls if c[0] == "notification.request_s4_action"]
    assert any(c[1][0] == "NVDA" for c in alert_calls)
    assert any(c[1][0] == "NVDA" for c in s4_calls)


# --- 无触发 → send_digest 被调 ---
def test_no_trigger_sends_digest(monkeypatch):
    fake = _Fake()
    fake.check_results = [_UNTRIGGERED_CR]
    _patch(monkeypatch, fake)
    result = _run(fake)
    digest_calls = [c for c in fake.calls if c[0] == "notification.send_digest"]
    assert len(digest_calls) == 1
    crs, pas, mis, to = digest_calls[0][1]
    assert len(crs) == 1
    assert pas == []
    assert result["price_alerts"] == 0
    assert result["errors"] == []   # 无错 → 无错误通知邮件


# --- price_monitor 一直报错 → 3 次重试 + 错误通知邮件 ---
def test_price_error_retries_and_notifies(monkeypatch):
    fake = _Fake()
    fake.price_error = ConnectionError("net down")
    _patch(monkeypatch, fake)
    result = _run(fake)
    assert result["price_alerts"] == 0
    assert any("price_monitor" in e for e in result["errors"])
    pm_calls = [c for c in fake.calls if c[0] == "price_monitor.run_price_check"]
    assert len(pm_calls) == 3   # 3 次重试
    err_emails = [c for c in fake.calls if c[0] == "_send_email" and "调度错误" in c[1][0]]
    assert len(err_emails) == 1


# --- check_agent 一直报错 → 每用户 3 次重试 + 错误通知 ---
def test_check_error_retries_and_notifies(monkeypatch):
    fake = _Fake()
    fake.check_error = RuntimeError("429 rate limit")
    _patch(monkeypatch, fake)
    result = _run(fake)
    assert any("check_agent:" in e for e in result["errors"])
    ca_calls = [c for c in fake.calls if c[0] == "check_agent.run_all"]
    assert len(ca_calls) == 3 * len(scheduler.PRESET_USERS)  # 每预置用户 3 次
    err_emails = [c for c in fake.calls if c[0] == "_send_email" and "调度错误" in c[1][0]]
    assert len(err_emails) == 1


# --- _retry：前两次 transient 错，第三次成功 ---
def test_retry_transient_then_success(monkeypatch):
    monkeypatch.setattr(scheduler.time, "sleep", lambda s: None)
    calls = []
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("transient")
        return "ok"
    result = scheduler._retry(fn, attempts=3)
    assert result == "ok"
    assert len(calls) == 3


# --- 调度器配置从 env 读 ---
def test_scheduler_config_from_env(monkeypatch):
    monkeypatch.setenv("THESIS_CHECK_TIME", "17:30")
    monkeypatch.setenv("THESIS_TZ", "Asia/Shanghai")
    cfg = scheduler._scheduler_config()
    assert cfg["check_time"] == "17:30"
    assert cfg["tz"] == "Asia/Shanghai"
    assert cfg["hour"] == 17
    assert cfg["minute"] == 30


def test_scheduler_config_defaults(monkeypatch):
    monkeypatch.delenv("THESIS_CHECK_TIME", raising=False)
    monkeypatch.delenv("THESIS_TZ", raising=False)
    cfg = scheduler._scheduler_config()
    assert cfg["check_time"] == "16:00"
    assert cfg["tz"] == "America/New_York"


# --- build_scheduler 用 env 配置（mock apscheduler）---
def test_build_scheduler_uses_env_config(monkeypatch):
    monkeypatch.setenv("THESIS_CHECK_TIME", "17:30")
    monkeypatch.setenv("THESIS_TZ", "Asia/Shanghai")

    class _FakeSched:
        def __init__(self):
            self.jobs = []
        def add_job(self, fn, trigger, **kw):
            self.jobs.append((fn, trigger, kw))
        def start(self):
            self.started = True
    monkeypatch.setattr(scheduler, "AsyncIOScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "_HAS_APSCHEDULER", True)

    sched = scheduler.build_scheduler()
    assert sched is not None
    assert len(sched.jobs) == 1
    fn, trigger, kw = sched.jobs[0]
    assert fn is scheduler.run_daily_check
    assert trigger == "cron"
    assert kw["hour"] == 17
    assert kw["minute"] == 30
    assert kw["timezone"] == "Asia/Shanghai"


def test_build_scheduler_no_apscheduler_returns_none(monkeypatch):
    monkeypatch.setattr(scheduler, "_HAS_APSCHEDULER", False)
    monkeypatch.setattr(scheduler, "AsyncIOScheduler", None)
    assert scheduler.build_scheduler() is None


# --------------------------------------------------------------------------- #
# 季频复盘：stateless，查 check_results 最近 N 次 watch（替代 watch_state.check_quarterly_review）
# --------------------------------------------------------------------------- #

def _nv_card(ticker="MCO", cond_ids=("c1",), next_verdict_date=None,
             confirmed=True) -> ThesisCard:
    broken = [BrokenCondition(id=c, layer=ConditionLayer.MIRROR, text=f"cond {c}")
              for c in cond_ids]
    nv = NextVerdictData(event="Q3 财报", date=next_verdict_date) if next_verdict_date else None
    return ThesisCard(user_id="beta1", ticker=ticker, filer_type=FilerType.DOMESTIC_10K,
                      holding_reason_raw="x", broken_conditions=broken, next_verdict=nv,
                      confirmation=Confirmation(confirmed_by_user=confirmed))


def _save_n(store, card, cid, status, n, checked_at="2026-08-01T00:00:00Z"):
    for _ in range(n):
        store.save_check_result(CheckResult(card_id=card.card_id, cond_id=cid,
                                            status=status, checked_at=checked_at))


def test_quarterly_review_due_recent_watch_returns_items():
    """卡 next_verdict.date 到期 + cond 最近 N 次全 watch → 返复查项（stateless）。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    today = datetime.date.today().isoformat()
    card = _nv_card("MCO", ("c1",), next_verdict_date=today)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N)
    out = scheduler._quarterly_review_items(store)
    assert len(out) == 1
    assert out[0]["ticker"] == "MCO"
    assert out[0]["condition_text"] == "cond c1"
    assert out[0]["n_watch"] == scheduler._QUARTERLY_WATCH_N


def test_quarterly_review_not_due_returns_empty():
    """卡 next_verdict.date 未来 → 未到期 → []。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    future = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
    card = _nv_card("MCO", ("c1",), next_verdict_date=future)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N)
    assert scheduler._quarterly_review_items(store) == []


def test_quarterly_review_no_next_verdict_returns_empty():
    """卡无 next_verdict（date=None）→ []（无复盘日，不催）。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    card = _nv_card("MCO", ("c1",), next_verdict_date=None)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N)
    assert scheduler._quarterly_review_items(store) == []


def test_quarterly_review_insufficient_history_returns_empty():
    """cond 最近核对次数 < N → 不算持续 watch → []。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    today = datetime.date.today().isoformat()
    card = _nv_card("MCO", ("c1",), next_verdict_date=today)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N - 1)
    assert scheduler._quarterly_review_items(store) == []


def test_quarterly_review_recent_has_untriggered_returns_empty():
    """最近 N 次含 untriggered（非全 watch）→ []。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    today = datetime.date.today().isoformat()
    card = _nv_card("MCO", ("c1",), next_verdict_date=today)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N - 1,
            checked_at="2026-08-01T00:00:00Z")
    # 最新一次为 untriggered → 最近 N 次非全 watch
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c1",
                                        status=CondStatus.UNTRIGGERED,
                                        checked_at="2026-08-02T00:00:00Z"))
    assert scheduler._quarterly_review_items(store) == []


def test_quarterly_review_unconfirmed_card_skipped():
    """未确认卡（confirmed_by_user=False）→ 跳过（不进复查）。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    today = datetime.date.today().isoformat()
    card = _nv_card("MCO", ("c1",), next_verdict_date=today, confirmed=False)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N)
    assert scheduler._quarterly_review_items(store) == []


def test_quarterly_review_past_date_due():
    """复盘日已过（past）→ 仍 due（逾期复查），返项。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    past = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    card = _nv_card("MCO", ("c1",), next_verdict_date=past)
    store.upsert_card(card)
    _save_n(store, card, "c1", CondStatus.WATCH, scheduler._QUARTERLY_WATCH_N)
    out = scheduler._quarterly_review_items(store)
    assert len(out) == 1 and out[0]["ticker"] == "MCO"
