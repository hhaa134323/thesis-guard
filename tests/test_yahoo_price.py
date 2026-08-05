"""YahooPriceFetcher 单测（Stage 2 行情数据源）。

锁 acceptance：
- FetcherRegistry.get("yahoo_price") 返回 YahooPriceFetcher 实例（BaseFetcher subclass，name="yahoo_price"）
- fetch("MCO") 返价格 dict（ticker + current_price/week52_high/week52_low/market_cap/currency，字段名+值对）
- fetch("INVALID") / yfinance 异常 / 无 regularMarketPrice → 返 []（R5 不编造）
- yfinance 不可用时 fallback 到 Yahoo chart API（requests 直接调）
不触网：monkeypatch yahoo_price.yfinance + yahoo_price.requests（与 test_fetcher_registry patch sec_edgar.requests 同款）。
yfinance 未装亦可跑：yahoo_price 顶层 try-import（None 时 fetch 返 []），此处 patch 成 fake。
"""
from __future__ import annotations

import types

from thesis_watch.fetchers import yahoo_price
from thesis_watch.fetchers.base import BaseFetcher, FetcherRegistry
from thesis_watch.fetchers.yahoo_price import YahooPriceFetcher


_MCO_INFO = {
    "regularMarketPrice": 394.50,
    "fiftyTwoWeekHigh": 480.00,
    "fiftyTwoWeekLow": 350.00,
    "marketCap": 71000000000,
    "currency": "USD",
}

_MCO_API_META = {
    "regularMarketPrice": 394.50,
    "fiftyTwoWeekHigh": 480.00,
    "fiftyTwoWeekLow": 350.00,
    "marketCap": 71000000000,
    "currency": "USD",
}


def _fake_yfinance(info=None, exc=None):
    """构造假 yfinance 模块：Ticker(ticker).info → info（或抛 exc）。"""
    def _ticker(_ticker):
        if exc is not None:
            raise exc
        return types.SimpleNamespace(info=info)
    return types.SimpleNamespace(Ticker=_ticker)


def _patch_yf(monkeypatch, info=None, exc=None):
    monkeypatch.setattr(yahoo_price, "yfinance", _fake_yfinance(info=info, exc=exc))


def _fake_api_response(meta=None, status_code=200, exc=None):
    """构造假 requests.get response。"""
    if exc is not None:
        raise exc
    data = {}
    if meta is not None:
        data = {"chart": {"result": [{"meta": meta}]}}
    def _raise_for_status():
        if status_code >= 400:
            raise RuntimeError(f"HTTP {status_code}")
    return types.SimpleNamespace(
        json=lambda: data,
        status_code=status_code,
        raise_for_status=_raise_for_status,
    )


def _patch_api(monkeypatch, meta=None, status_code=200, exc=None):
    """Patch yahoo_price.requests.get 返回假 API response。"""
    def _get(url, headers=None, timeout=None):
        return _fake_api_response(meta=meta, status_code=status_code, exc=exc)
    monkeypatch.setattr(yahoo_price.requests, "get", _get)


def _patch_api_fail(monkeypatch):
    """Patch requests.get to raise → fallback returns []（R5）。"""
    def _raise(*a, **kw):
        raise ConnectionError("test")
    monkeypatch.setattr(yahoo_price.requests, "get", _raise)


# ── yfinance 路径（原有测试） ──

def test_registry_get_yahoo_price_returns_instance():
    fetcher = FetcherRegistry.get("yahoo_price")
    assert isinstance(fetcher, YahooPriceFetcher)
    assert isinstance(fetcher, BaseFetcher)
    assert fetcher.name == "yahoo_price"


def test_fetch_parses_all_fields(monkeypatch):
    _patch_yf(monkeypatch, info=_MCO_INFO)
    _patch_api_fail(monkeypatch)  # yfinance 成功 → fallback 不应被调用
    rows = YahooPriceFetcher().fetch("MCO")
    assert rows == [{
        "ticker": "MCO",
        "current_price": 394.50,
        "week52_high": 480.00,
        "week52_low": 350.00,
        "market_cap": 71000000000,
        "currency": "USD",
    }]


def test_registry_get_fetch_mco_returns_price(monkeypatch):  # acceptance
    _patch_yf(monkeypatch, info=_MCO_INFO)
    _patch_api_fail(monkeypatch)
    rows = FetcherRegistry.get("yahoo_price").fetch("MCO")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "MCO"
    assert rows[0]["current_price"] == 394.50
    assert rows[0]["currency"] == "USD"


def test_fetch_invalid_ticker_returns_empty(monkeypatch):  # acceptance: INVALID
    _patch_yf(monkeypatch, info={})  # yfinance 返空 → fallback
    _patch_api_fail(monkeypatch)  # fallback 也失败 → []
    assert FetcherRegistry.get("yahoo_price").fetch("INVALID") == []


def test_fetch_yfinance_exception_returns_empty(monkeypatch):  # R5：异常不抛错
    _patch_yf(monkeypatch, exc=RuntimeError("network down"))
    _patch_api_fail(monkeypatch)
    assert FetcherRegistry.get("yahoo_price").fetch("MCO") == []


def test_fetch_missing_price_returns_empty(monkeypatch):  # R5：无可用价不编造
    _patch_yf(monkeypatch, info={"fiftyTwoWeekHigh": 480.0, "currency": "USD"})
    _patch_api_fail(monkeypatch)
    assert FetcherRegistry.get("yahoo_price").fetch("MCO") == []


def test_fetch_uppercases_ticker(monkeypatch):
    _patch_yf(monkeypatch, info=_MCO_INFO)
    _patch_api_fail(monkeypatch)
    rows = YahooPriceFetcher().fetch("mco")  # 小写输入 → 归一化大写
    assert rows[0]["ticker"] == "MCO"


# ── fallback API 路径（新增测试） ──

def test_fallback_when_yfinance_none(monkeypatch):
    """yfinance 未装 → fallback 到 API。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    _patch_api(monkeypatch, meta=_MCO_API_META)
    rows = YahooPriceFetcher().fetch("MCO")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "MCO"
    assert rows[0]["current_price"] == 394.50


def test_fallback_when_yfinance_empty(monkeypatch):
    """yfinance 返空 → fallback 到 API。"""
    _patch_yf(monkeypatch, info={})
    _patch_api(monkeypatch, meta=_MCO_API_META)
    rows = YahooPriceFetcher().fetch("MCO")
    assert len(rows) == 1
    assert rows[0]["current_price"] == 394.50


def test_fallback_when_yfinance_exception(monkeypatch):
    """yfinance 异常 → fallback 到 API。"""
    _patch_yf(monkeypatch, exc=RuntimeError("DLL load failed"))
    _patch_api(monkeypatch, meta=_MCO_API_META)
    rows = YahooPriceFetcher().fetch("MCO")
    assert len(rows) == 1
    assert rows[0]["current_price"] == 394.50


def test_fallback_api_parses_all_fields(monkeypatch):
    """fallback API 正确解析所有字段。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    _patch_api(monkeypatch, meta=_MCO_API_META)
    rows = YahooPriceFetcher().fetch("MCO")
    assert rows == [{
        "ticker": "MCO",
        "current_price": 394.50,
        "week52_high": 480.00,
        "week52_low": 350.00,
        "market_cap": 71000000000,
        "currency": "USD",
    }]


def test_fallback_api_exception_returns_empty(monkeypatch):  # R5
    """fallback API 异常 → 返 []（R5）。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    _patch_api(monkeypatch, exc=ConnectionError("network down"))
    assert YahooPriceFetcher().fetch("MCO") == []


def test_fallback_api_rate_limited_returns_empty(monkeypatch):  # R5
    """fallback API 429 限流 → 返 []（R5）。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    _patch_api(monkeypatch, status_code=429)
    assert YahooPriceFetcher().fetch("MCO") == []


def test_fallback_api_missing_price_returns_empty(monkeypatch):  # R5
    """fallback API 无 regularMarketPrice → 返 []（R5）。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    _patch_api(monkeypatch, meta={"fiftyTwoWeekHigh": 480.0, "currency": "USD"})
    assert YahooPriceFetcher().fetch("MCO") == []


def test_fallback_api_bad_json_returns_empty(monkeypatch):  # R5
    """fallback API 返回非预期 JSON 结构 → 返 []（R5）。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    monkeypatch.setattr(
        yahoo_price.requests, "get",
        lambda url, headers=None, timeout=None: types.SimpleNamespace(
            json=lambda: {"unexpected": "format"},
            status_code=200,
            raise_for_status=lambda: None,
        )
    )
    assert YahooPriceFetcher().fetch("MCO") == []


def test_yfinance_success_skips_fallback(monkeypatch):
    """yfinance 成功 → 不调 fallback API。"""
    _patch_yf(monkeypatch, info=_MCO_INFO)
    api_called = []
    def _spy_get(url, headers=None, timeout=None):
        api_called.append(url)
        return _fake_api_response()
    monkeypatch.setattr(yahoo_price.requests, "get", _spy_get)
    rows = YahooPriceFetcher().fetch("MCO")
    assert len(rows) == 1
    assert rows[0]["current_price"] == 394.50
    assert api_called == []  # fallback 未被调用


def test_fallback_uppercases_ticker(monkeypatch):
    """fallback 路径也归一化 ticker 大写。"""
    monkeypatch.setattr(yahoo_price, "yfinance", None)
    _patch_api(monkeypatch, meta=_MCO_API_META)
    rows = YahooPriceFetcher().fetch("mco")
    assert rows[0]["ticker"] == "MCO"
