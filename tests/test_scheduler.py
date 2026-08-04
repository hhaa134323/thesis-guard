"""scheduler 单测（Stage 2 窗口 C / 任务 3）：daily check 胶水层。

mock price_monitor / check_agent / watch_state / notification，验证 daily flow 顺序 +
alert/S4/digest 调用 + 重试 + env 配置。不触网不落盘（time.sleep mock 掉；store :memory:）。
"""
from __future__ import annotations

import asyncio
import types

import pytest

from thesis_watch import scheduler
from thesis_watch.store import ThesisStore


class _Fake:
    """记录所有组件调用 (name, args)，返 configurable returns。"""
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.price_alerts: list[dict] = []
        self.check_results: list[dict] = []
        self.watch_changes: list[dict] = []
        self.review_items: list[dict] = []
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

    # watch_state → fake module（patch scheduler.watch_state）
    def _update_ws(crs):
        fake.rec("watch_state.update_watch_states", crs)
        return fake.watch_changes
    def _review():
        fake.rec("watch_state.check_quarterly_review")
        return fake.review_items
    monkeypatch.setattr(scheduler, "watch_state", types.SimpleNamespace(
        update_watch_states=_update_ws,
        check_quarterly_review=_review,
    ))

    # notification
    monkeypatch.setattr(scheduler.notification, "send_alert",
                        lambda ticker, alert_data, to_email: (fake.rec("notification.send_alert", ticker, alert_data, to_email) or True))
    monkeypatch.setattr(scheduler.notification, "send_digest",
                        lambda crs, pas, wcs, mis, to_email: (fake.rec("notification.send_digest", crs, pas, wcs, mis, to_email) or True))
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


_PRICE_ALERT = {"ticker": "MCO", "current_price": 394.5, "threshold": 380,
                "triggered": True, "condition_text": "加仓价 380",
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
    fake.watch_changes = [{"ticker": "MCO", "change": "unchanged"}]
    _patch(monkeypatch, fake)
    _run(fake)
    names = _names(fake)
    assert names.index("price_monitor.run_price_check") < names.index("check_agent.run_all")
    assert names.index("check_agent.run_all") < names.index("watch_state.update_watch_states")
    assert names.index("watch_state.update_watch_states") < names.index("notification.send_digest")
    assert names.index("notification.send_digest") < names.index("watch_state.check_quarterly_review")


# --- price alert → send_alert ---
def test_price_alert_sends_alert(monkeypatch):
    fake = _Fake()
    fake.price_alerts = [_PRICE_ALERT]
    _patch(monkeypatch, fake)
    _run(fake)
    alert_calls = [c for c in fake.calls if c[0] == "notification.send_alert"]
    assert any(c[1][0] == "MCO" for c in alert_calls)


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
    crs, pas, wcs, mis, to = digest_calls[0][1]
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
