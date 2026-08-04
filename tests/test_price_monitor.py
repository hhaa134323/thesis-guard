"""安全边际监控单测（Stage 2 窗口 B / 任务 2）。

锁 acceptance：
- 价格 <= 阈值 → 产出 alert（8 键严格一致 + 值正确）
- 价格 > 阈值 → 无 alert
- 复杂估值字段（P/TBV / yield / DCF / 多倍数无价格）→ skip（不报错）
- Yahoo fetch 返空 → skip（R5 不编造价格）
- 多 card 遍历；无安全边际字段过滤；空 store → []
- trade 持仓周期 → alert_type=stop_loss；long/mid → safety_margin
- 阈值提取变体：380 / ≤ 380 / <= 380 / 加仓价 380 / $394

不触网：monkeypatch FetcherRegistry.get("yahoo_price") 单例的 fetch（与 test_filing_history
patch SecFetcher.fetch_history 同款）；store 走 :memory:（不污染真实 data/thesis.db，R9）。
"""
from __future__ import annotations

import datetime

import pytest

from thesis_watch.fetchers import FetcherRegistry
from thesis_watch.models import Confirmation, EntryAnchorData, FilerType, ThesisCard
from thesis_watch.price_monitor import _parse_safety_margin, load_all_cards, run_price_check
from thesis_watch.store import ThesisStore

_UTC = datetime.timezone.utc
_TS = datetime.datetime(2026, 8, 4, 16, 0, 0, tzinfo=_UTC)  # 固定时间戳断言

_ALERT_KEYS = {"ticker", "alert_type", "current_price", "threshold", "triggered",
               "condition_text", "position_type", "timestamp"}
_SKIP_KEYS = {"ticker", "skipped", "reason"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _card(ticker="MCO", *, note="加仓价 380", anchor_type="other",
          anchor_value=None, horizon="long", user_id="beta1"):
    return ThesisCard(
        user_id=user_id, ticker=ticker, filer_type=FilerType.OTHER,
        holding_reason_raw="看好壁垒",
        entry_anchor=EntryAnchorData(anchor_type=anchor_type,
                                     anchor_value=anchor_value, note=note),
        holding_horizon=horizon,
        confirmation=Confirmation(confirmed_by_user=True),
    )


def _store_with(*cards):
    s = ThesisStore(":memory:")
    s.seed_preset_users()
    for c in cards:
        s.upsert_card(c)
    return s


def _patch_price(monkeypatch, price_map, captures=None):
    """FetcherRegistry.get('yahoo_price').fetch(ticker) → [{current_price}] or []。
    captures 记录被调用的 ticker（验证复杂估值 card 不触 fetch）。"""
    def _fake(ticker, **kwargs):
        if captures is not None:
            captures.append(ticker)
        t = ticker.upper()
        if t in price_map:
            return [{"ticker": t, "current_price": price_map[t]}]
        return []
    monkeypatch.setattr(FetcherRegistry.get("yahoo_price"), "fetch", _fake)


# --------------------------------------------------------------------------- #
# _parse_safety_margin —— 阈值提取（纯函数单测）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("note,expected", [
    ("380", 380.0),
    ("≤ 380", 380.0),
    ("<= 380", 380.0),
    ("加仓价 380", 380.0),
    ("$394", 394.0),
    ("25x ≈ $394", 394.0),
    ("加仓价 380 元", 380.0),
])
def test_parse_extracts_price_variants(note, expected):
    text, threshold = _parse_safety_margin(
        EntryAnchorData(anchor_type="other", note=note))
    assert threshold == expected
    assert text == note


def test_parse_complex_valuation_returns_none():
    """P/TBV / yield / DCP 等比率或方法名 → threshold=None（v1 skip）。"""
    for note in ["P/TBV < 1.5", "owner-earnings yield > 10%", "reverse DCF",
                 "P/E 25 倍", "P/FCF < 20"]:
        _, threshold = _parse_safety_margin(
            EntryAnchorData(anchor_type="other", note=note))
        assert threshold is None, f"{note!r} 应判复杂估值 skip"


def test_parse_multiple_type_without_price_returns_none():
    """多倍数类型（ttm_gaap_pe）note='25x' 无货币价格 → None（v1 不比倍数）。"""
    _, threshold = _parse_safety_margin(
        EntryAnchorData(anchor_type="ttm_gaap_pe", anchor_value=25, note="25x"))
    assert threshold is None


def test_parse_multiple_type_with_price_in_note_extracts_price():
    """多倍数类型但 note 里有货币标记价格（25x ≈ $394）→ 提取价格 394（用户已换算）。"""
    _, threshold = _parse_safety_margin(
        EntryAnchorData(anchor_type="ttm_gaap_pe", anchor_value=25, note="25x ≈ $394"))
    assert threshold == 394.0


def test_parse_empty_anchor_returns_empty_text():
    """完全空的 entry_anchor → ('', None) → 调用方过滤（不产出 skip）。"""
    text, threshold = _parse_safety_margin(EntryAnchorData())
    assert text == ""
    assert threshold is None


def test_parse_anchor_value_fallback_when_note_empty():
    """note 空 + anchor_type=other + anchor_value=380 → 兜底取 380（裸价格）。"""
    _, threshold = _parse_safety_margin(
        EntryAnchorData(anchor_type="other", anchor_value=380, note=""))
    assert threshold == 380.0


# --------------------------------------------------------------------------- #
# run_price_check —— alert / skip / 过滤
# --------------------------------------------------------------------------- #

def test_price_below_threshold_produces_alert(monkeypatch):
    store = _store_with(_card(note="加仓价 380", horizon="long"))
    _patch_price(monkeypatch, {"MCO": 370.0})
    out = run_price_check(store, now=_TS)
    assert len(out) == 1
    a = out[0]
    assert set(a.keys()) == _ALERT_KEYS           # 8 键严格一致（notification 接口）
    assert a["ticker"] == "MCO"
    assert a["alert_type"] == "safety_margin"
    assert a["current_price"] == 370.0
    assert a["threshold"] == 380.0
    assert a["triggered"] is True
    assert a["condition_text"] == "加仓价 380"
    assert a["position_type"] == "长线"
    assert a["timestamp"] == "2026-08-04T16:00:00Z"


def test_price_equal_threshold_triggers(monkeypatch):
    """<= 阈值：等于也触发（spec：current_price <= 380）。"""
    store = _store_with(_card(note="加仓价 380"))
    _patch_price(monkeypatch, {"MCO": 380.0})
    out = run_price_check(store, now=_TS)
    assert len(out) == 1
    assert out[0]["triggered"] is True


def test_price_above_threshold_no_alert(monkeypatch):
    store = _store_with(_card(note="加仓价 380"))
    _patch_price(monkeypatch, {"MCO": 394.5})
    assert run_price_check(store, now=_TS) == []   # 未触发 → 无产出（无 alert 无 skip）


def test_complex_valuation_skipped(monkeypatch):
    captures = []
    store = _store_with(_card(note="P/TBV < 1.5", anchor_type="p_tbv"))
    _patch_price(monkeypatch, {}, captures=captures)
    out = run_price_check(store, now=_TS)
    assert len(out) == 1
    s = out[0]
    assert set(s.keys()) == _SKIP_KEYS
    assert s["ticker"] == "MCO"
    assert s["skipped"] is True
    assert s["reason"] == "complex valuation not supported in v1"
    assert captures == []                          # 复杂估值 → 不触 fetch（skip 在 fetch 前）


def test_multiple_without_price_skipped(monkeypatch):
    """多倍数类型 note='25x' 无价格 → skip（complex valuation not supported in v1）。"""
    store = _store_with(_card(note="25x", anchor_type="ttm_gaap_pe", anchor_value=25))
    _patch_price(monkeypatch, {"MCO": 100.0})      # 即便能拿到价，也不该比（倍数非价格）
    out = run_price_check(store, now=_TS)
    assert len(out) == 1
    assert out[0]["skipped"] is True
    assert out[0]["reason"] == "complex valuation not supported in v1"


def test_price_unavailable_skipped(monkeypatch):
    """Yahoo fetch 返空（yfinance 未装 / ticker 不存在）→ skip price unavailable（R5 不编造）。"""
    store = _store_with(_card(note="加仓价 380"))
    _patch_price(monkeypatch, {})                  # MCO 不在 price_map → fetch 返 []
    out = run_price_check(store, now=_TS)
    assert len(out) == 1
    s = out[0]
    assert s["ticker"] == "MCO"
    assert s["skipped"] is True
    assert s["reason"] == "price unavailable"


def test_multiple_cards_traversal(monkeypatch):
    """3 card：MCO 触发 / NVDA 未触发 / AAPL 复杂 skip → out = [MCO alert, AAPL skip]。"""
    store = _store_with(
        _card("MCO", note="加仓价 380", horizon="long"),
        _card("NVDA", note="加仓价 400", horizon="long"),
        _card("AAPL", note="P/E 25 倍", anchor_type="ttm_gaap_pe", horizon="mid"),
    )
    _patch_price(monkeypatch, {"MCO": 370.0, "NVDA": 500.0})  # MCO<=380 触发 / NVDA>400 未触发 / AAPL 复杂不 fetch
    out = run_price_check(store, now=_TS)
    assert len(out) == 2                            # NVDA 未触发不计入
    by_ticker = {e["ticker"]: e for e in out}
    assert "MCO" in by_ticker and "alert_type" in by_ticker["MCO"]
    assert by_ticker["MCO"]["alert_type"] == "safety_margin"
    assert by_ticker["MCO"]["triggered"] is True
    assert "AAPL" in by_ticker and by_ticker["AAPL"]["skipped"] is True


def test_no_entry_anchor_filtered_out(monkeypatch):
    """entry_anchor=None → 过滤（无产出，不产 skip）。"""
    card = ThesisCard(user_id="beta1", ticker="MCO", filer_type=FilerType.OTHER,
                      holding_reason_raw="看好壁垒", entry_anchor=None,
                      holding_horizon="long", confirmation=Confirmation(confirmed_by_user=True))
    store = _store_with(card)
    _patch_price(monkeypatch, {"MCO": 370.0})
    assert run_price_check(store, now=_TS) == []


def test_empty_store_returns_empty(monkeypatch):
    _patch_price(monkeypatch, {})
    assert run_price_check(_store_with(), now=_TS) == []


def test_trade_horizon_stop_loss(monkeypatch):
    """持仓周期=trade + 价格类止损 → alert_type=stop_loss，position_type=交易。"""
    store = _store_with(_card(note="止损 100", horizon="trade"))
    _patch_price(monkeypatch, {"MCO": 90.0})
    out = run_price_check(store, now=_TS)
    assert len(out) == 1
    assert out[0]["alert_type"] == "stop_loss"
    assert out[0]["position_type"] == "交易"
    assert out[0]["threshold"] == 100.0


def test_mid_horizon_safety_margin(monkeypatch):
    store = _store_with(_card(note="加仓价 380", horizon="mid"))
    _patch_price(monkeypatch, {"MCO": 370.0})
    out = run_price_check(store, now=_TS)
    assert out[0]["alert_type"] == "safety_margin"
    assert out[0]["position_type"] == "中线"


def test_unknown_horizon_label_unspecified(monkeypatch):
    store = _store_with(_card(note="加仓价 380", horizon=None))
    _patch_price(monkeypatch, {"MCO": 370.0})
    out = run_price_check(store, now=_TS)
    assert out[0]["alert_type"] == "safety_margin"   # 非 trade 默认 safety_margin
    assert out[0]["position_type"] == "未指定"


def test_load_all_cards_spans_users():
    """load_all_cards 跨所有 user（不局限于单 user）。"""
    store = _store_with(
        _card("MCO", user_id="beta1"),
        _card("NVDA", user_id="beta2"),
    )
    cards = load_all_cards(store)
    assert {c.ticker for c in cards} == {"MCO", "NVDA"}


def test_threshold_extraction_via_run_variants(monkeypatch):
    """端到端：不同写法的价格阈值，价格低于阈值均触发，且 threshold 字段正确。"""
    cases = [("380", 380.0), ("≤ 380", 380.0), ("<= 380", 380.0),
             ("加仓价 380", 380.0), ("$394", 394.0)]
    for note, expected in cases:
        store = _store_with(_card(note=note, anchor_type="other"))
        _patch_price(monkeypatch, {"MCO": expected - 5})
        out = run_price_check(store, now=_TS)
        assert len(out) == 1, f"{note!r} 应触发"
        assert out[0]["threshold"] == expected
        assert out[0]["triggered"] is True
