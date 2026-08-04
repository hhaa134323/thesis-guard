"""YahooPriceFetcher 单测（Stage 2 行情数据源）。

锁 acceptance：
- FetcherRegistry.get("yahoo_price") 返回 YahooPriceFetcher 实例（BaseFetcher subclass，name="yahoo_price"）
- fetch("MCO") 返价格 dict（ticker + current_price/week52_high/week52_low/market_cap/currency，字段名+值对）
- fetch("INVALID") / yfinance 异常 / 无 regularMarketPrice → 返 []（R5 不编造）
不触网：monkeypatch yahoo_price.yfinance（与 test_fetcher_registry patch sec_edgar.requests 同款）。
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


def _fake_yfinance(info=None, exc=None):
    """构造假 yfinance 模块：Ticker(ticker).info → info（或抛 exc）。"""
    def _ticker(_ticker):
        if exc is not None:
            raise exc
        return types.SimpleNamespace(info=info)
    return types.SimpleNamespace(Ticker=_ticker)


def _patch_yf(monkeypatch, info=None, exc=None):
    monkeypatch.setattr(yahoo_price, "yfinance", _fake_yfinance(info=info, exc=exc))


def test_registry_get_yahoo_price_returns_instance():
    fetcher = FetcherRegistry.get("yahoo_price")
    assert isinstance(fetcher, YahooPriceFetcher)
    assert isinstance(fetcher, BaseFetcher)
    assert fetcher.name == "yahoo_price"


def test_fetch_parses_all_fields(monkeypatch):
    _patch_yf(monkeypatch, info=_MCO_INFO)
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
    rows = FetcherRegistry.get("yahoo_price").fetch("MCO")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "MCO"
    assert rows[0]["current_price"] == 394.50
    assert rows[0]["currency"] == "USD"


def test_fetch_invalid_ticker_returns_empty(monkeypatch):  # acceptance: INVALID
    _patch_yf(monkeypatch, info={})  # 不存在 ticker → yfinance 返空 info
    assert FetcherRegistry.get("yahoo_price").fetch("INVALID") == []


def test_fetch_yfinance_exception_returns_empty(monkeypatch):  # R5：异常不抛错
    _patch_yf(monkeypatch, exc=RuntimeError("network down"))
    assert FetcherRegistry.get("yahoo_price").fetch("MCO") == []


def test_fetch_missing_price_returns_empty(monkeypatch):  # R5：无可用价不编造
    _patch_yf(monkeypatch, info={"fiftyTwoWeekHigh": 480.0, "currency": "USD"})
    assert FetcherRegistry.get("yahoo_price").fetch("MCO") == []


def test_fetch_uppercases_ticker(monkeypatch):
    _patch_yf(monkeypatch, info=_MCO_INFO)
    rows = YahooPriceFetcher().fetch("mco")  # 小写输入 → 归一化大写
    assert rows[0]["ticker"] == "MCO"
