"""notification 单测（Stage 2 窗口 B / 任务 4）：Alert + Digest + S4。

mock NotifierRegistry.get("email").send，验证 to/subject/body。不触网不落盘
（THESIS_S4_LOG 未配 → 不写文件；S4 落盘测试用 tmp_path）。

锁 acceptance：
- send_alert(triggered) → 邮件含 ticker + 条件 + 值 + 一手链接
- send_alert(price alert) → 邮件含 current_price + threshold
- send_digest(多 check_results triggered/watch/untriggered) → digest 邮件含各 ticker + 命中条件 + 链接
- send_digest(0 触发) → digest 有「已检查 N 只 / 0 触发」行（S3 无事不空）
- request_s4_action(triggered) → 邮件含三选项（确认 / 误报 / 忽略）+ 误报数据落 JSONL
"""
from __future__ import annotations

from thesis_watch.notification import send_alert, send_digest, request_s4_action
from thesis_watch.notifiers.base import NotifierRegistry


class _FakeEmail:
    """假 email 渠道：记录每次 send 的 (to, subject, body)，返 True（已发）。"""
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to, subject, body, *, body_html=None, log=print):
        self.sent.append((to, subject, body))
        return True


def _patch_email(monkeypatch) -> _FakeEmail:
    fake = _FakeEmail()
    monkeypatch.setattr(NotifierRegistry, "get", lambda name: fake)
    return fake


# --- send_alert: check_agent triggered（命中破局条件）---
def test_send_alert_triggered_has_ticker_cond_value_urls(monkeypatch):
    fake = _patch_email(monkeypatch)
    send_alert("MCO", {"cond": "CEO 离职", "value": "8-K item 5.02",
                       "urls": ["https://www.sec.gov/x"]}, "a@b.com")
    assert len(fake.sent) == 1
    to, subject, body = fake.sent[0]
    assert to == "a@b.com"
    assert "MCO" in subject
    assert "MCO" in body
    assert "CEO 离职" in body           # 条件
    assert "8-K item 5.02" in body      # 值
    assert "https://www.sec.gov/x" in body  # 一手链接
    assert "收尾邮件已发" in body          # R6


# --- send_alert: price alert（safety_margin 到价）---
def test_send_alert_price_has_current_and_threshold(monkeypatch):
    fake = _patch_email(monkeypatch)
    pa = {"ticker": "MCO", "alert_type": "safety_margin", "current_price": 394.50,
          "threshold": 380.00, "triggered": True, "condition_text": "加仓价 380",
          "position_type": "长线", "timestamp": "2026-08-04T16:00:00Z"}
    send_alert("MCO", pa, "a@b.com")
    assert len(fake.sent) == 1
    to, subject, body = fake.sent[0]
    assert to == "a@b.com"
    assert "MCO" in subject
    assert "394.5" in body    # current_price
    assert "380" in body      # threshold
    assert "加仓价 380" in body  # condition_text
    assert "判断权归你" in body


# --- send_digest: 多 check_results（triggered / watch / untriggered）+ 无 alert ---
def test_send_digest_multiple_statuses(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [
        {"ticker": "MCO", "n_triggered": 1, "n_watch": 0, "n_untriggered": 1,
         "triggered": [{"cond": "CEO 离职", "urls": ["https://www.sec.gov/m"]}]},
        {"ticker": "NVDA", "n_triggered": 0, "n_watch": 1, "n_untriggered": 1},
        {"ticker": "HSBC", "n_triggered": 0, "n_watch": 0, "n_untriggered": 2},
    ]
    send_digest(crs, [], [], "a@b.com")
    assert len(fake.sent) == 1
    to, subject, body = fake.sent[0]
    assert to == "a@b.com"
    assert "MCO" in body and "NVDA" in body and "HSBC" in body
    assert "CEO 离职" in body
    assert "https://www.sec.gov/m" in body  # 一手链接
    assert "判断权归你" in body


# --- send_digest: 0 触发 → S3 无事行不空 ---
def test_send_digest_zero_triggered_s3_line(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [
        {"ticker": "MCO", "n_triggered": 0, "n_watch": 0, "n_untriggered": 2},
        {"ticker": "NVDA", "n_triggered": 0, "n_watch": 0, "n_untriggered": 1},
    ]
    send_digest(crs, [], [], "a@b.com")
    to, subject, body = fake.sent[0]
    assert "已检查 2 只 / 0 触发" in body   # S3 无事那行不许空
    assert "观察项：今日无 watch 变化" in body  # watch 占位已落地，无变化时如实说


# --- send_digest: 含 price_alerts → digest 列价格提醒（到价计入触发数）---
def test_send_digest_with_price_alerts(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [{"ticker": "MCO", "n_triggered": 0, "n_watch": 0, "n_untriggered": 1}]
    pa = {"ticker": "MCO", "alert_type": "safety_margin", "current_price": 370.0,
          "threshold": 380.0, "triggered": True, "level": "hit",
          "condition_text": "加仓价 380", "position_type": "长线",
          "timestamp": "2026-08-04T16:00:00Z"}
    send_digest(crs, [pa], [], "a@b.com")
    _to, _subject, body = fake.sent[0]
    assert "价格提醒" in body
    assert "到价" in body                 # hit 文案
    assert "370.0" in body and "380.0" in body
    assert "已检查 1 只 / 1 触发" in body   # 到价(price hit)计入触发数


# --- send_digest: 接近档文案与到价区分；接近不计入「触发」数 ---
def test_send_digest_approaching_distinct_and_not_counted(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [{"ticker": "MCO", "n_triggered": 0, "n_watch": 0, "n_untriggered": 1}]
    pa = {"ticker": "MCO", "alert_type": "safety_margin", "current_price": 400.0,
          "threshold": 380.0, "triggered": False, "level": "approaching",
          "condition_text": "加仓价 380", "position_type": "长线",
          "timestamp": "2026-08-04T16:00:00Z"}
    send_digest(crs, [pa], [], "a@b.com")
    _to, _subject, body = fake.sent[0]
    assert "价格提醒" in body
    assert "接近阈值" in body and "400.0" in body
    assert "到价" not in body              # 接近档不混入到价文案
    assert "已检查 1 只 / 0 触发" in body   # 接近档未真正到价，不计触发


# --- send_digest: skip dict 过滤（8c65773 不回归）：不渲染、不计触发 ---
def test_send_digest_skipped_price_filtered_out(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [{"ticker": "MCO", "n_triggered": 0, "n_watch": 0, "n_untriggered": 1}]
    skip_pa = {"ticker": "MCO", "skipped": True, "reason": "price unavailable"}
    send_digest(crs, [skip_pa], [], "a@b.com")
    _to, _subject, body = fake.sent[0]
    assert "价格提醒" not in body           # skip 不渲染价格段
    assert "price unavailable" not in body
    assert "已检查 1 只 / 0 触发" in body    # skip 不计触发


# --- send_digest: manual_items → 「需你自查」清单（S5）---
def test_send_digest_manual_items(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [{"ticker": "MCO", "n_triggered": 0, "n_watch": 0, "n_untriggered": 1}]
    mis = [{"text": "月线收盘价是否跌破 200 日均线", "reason": "价格图形型", "cadence": "monthly"}]
    send_digest(crs, [], mis, "a@b.com")
    _to, _subject, body = fake.sent[0]
    assert "需你自查" in body
    assert "200 日均线" in body


# --- send_digest: watch 较上次变化（读 check_results 的 changes，6 值映射）---
def test_send_digest_renders_watch_changes(monkeypatch):
    fake = _patch_email(monkeypatch)
    crs = [
        {"ticker": "MCO", "n_triggered": 0, "n_watch": 1, "n_untriggered": 0,
         "changes": {"c1": {"change": "new", "text": "营收增速跌破 5%"}}},
        {"ticker": "NVDA", "n_triggered": 0, "n_watch": 1, "n_untriggered": 0,
         "changes": {"c2": {"change": "worsened", "text": "CEO 离职风险"}}},
    ]
    send_digest(crs, [], [], "a@b.com")
    _to, _subject, body = fake.sent[0]
    assert "MCO 新增 watch：营收增速跌破 5%" in body
    assert "NVDA 恶化：CEO 离职风险" in body


def test_send_digest_watch_change_six_values(monkeypatch):
    """6 种 change 值的文案映射 + 空串（非 transition）不列。"""
    fake = _patch_email(monkeypatch)
    crs = [{"ticker": "MCO", "n_triggered": 0, "n_watch": 1, "n_untriggered": 0,
            "changes": {
                "c1": {"change": "new", "text": "T1"},
                "c2": {"change": "worsened", "text": "T2"},
                "c3": {"change": "improved", "text": "T3"},
                "c4": {"change": "unchanged", "text": "T4"},
                "c5": {"change": "resolved", "text": "T5"},
                "c6": {"change": "escalated", "text": "T6"},
                "c7": {"change": "", "text": "T7"},  # 非 transition → 不列
            }}]
    send_digest(crs, [], [], "a@b.com")
    _to, _subject, body = fake.sent[0]
    assert "MCO 新增 watch：T1" in body
    assert "MCO 恶化：T2" in body
    assert "MCO 改善：T3" in body
    assert "MCO 仍在 watch：T4（无变化）" in body
    assert "MCO 已解除：T5" in body
    assert "MCO 升级 triggered：T6" in body
    assert "T7" not in body  # 空串不列


# --- request_s4_action: 三选项 + 误报数据落 JSONL ---
def test_request_s4_action_has_three_options_and_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("THESIS_S4_LOG", str(tmp_path / "s4.jsonl"))
    fake = _patch_email(monkeypatch)
    request_s4_action("MCO", {"cond": "CEO 离职",
                              "urls": ["https://www.sec.gov/x"]}, "a@b.com")
    assert len(fake.sent) == 1
    to, subject, body = fake.sent[0]
    assert to == "a@b.com"
    assert "MCO" in body
    assert "CEO 离职" in body
    assert "确认" in body and "误报" in body and "忽略" in body  # 三选项
    # 误报数据沉淀 JSONL（v1 eval 队列）
    log_path = tmp_path / "s4.jsonl"
    assert log_path.exists()
    assert "MCO" in log_path.read_text(encoding="utf-8")
    assert "pending" in log_path.read_text(encoding="utf-8")


# --- request_s4_action: 未配 THESIS_S4_LOG → 不落盘，邮件照发 ---
def test_request_s4_action_no_log_path_still_sends(monkeypatch, tmp_path):
    monkeypatch.delenv("THESIS_S4_LOG", raising=False)
    fake = _patch_email(monkeypatch)
    request_s4_action("MCO", {"cond": "CEO 离职", "urls": []}, "a@b.com")
    assert len(fake.sent) == 1
    assert "确认" in fake.sent[0][2]
