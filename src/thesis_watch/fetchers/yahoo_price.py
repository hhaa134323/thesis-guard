"""Yahoo 行情 fetcher（Stage 2 安全边际监控用）。

yfinance.Ticker(ticker).info 取 regularMarketPrice / fiftyTwoWeekHigh /
fiftyTwoWeekLow / marketCap / currency，包成统一 list[dict]（BaseFetcher 接口）。
注册名 "yahoo_price"；调用方经 FetcherRegistry.get("yahoo_price") 取实例。

R5：查不到（yfinance 未装 / 异常 / ticker 不存在 / 无可用价）→ 返空 list，不抛错、不编造。
yfinance 为可选重依赖（pandas/numpy 等），故顶层 try-import：未装时模块仍可加载、注册仍
生效（fetch 返 []）；测试 monkeypatch yahoo_price.yfinance 即可离线跑（与 sec_edgar patch
sec_edgar.requests 同款），不依赖真实 yfinance 安装。

Fallback：yfinance 不可用（未装 / DLL 加载失败 / 异常 / 返空）时，用 requests 直接调
Yahoo chart API（query1.finance.yahoo.com）拿价格。绕过 yfinance 底层 curl_cffi
依赖，requests 已是项目标准依赖。
"""
from __future__ import annotations

import requests

from .base import BaseFetcher, FetcherRegistry

try:  # 可选重依赖：未装时模块仍加载，fetch 返 []（R5）
    import yfinance  # type: ignore
except ImportError:
    yfinance = None  # type: ignore

_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


class YahooPriceFetcher(BaseFetcher):
    """Yahoo 行情 fetcher（BaseFetcher subclass，注册名 "yahoo_price"）。

    fetch(ticker) 先试 yfinance.Ticker(ticker).info，拿不到则 fallback 到
    requests 直接调 Yahoo chart API。映射成
    [{ticker, current_price, week52_high, week52_low, market_cap, currency}]。
    空 = 查不到（yfinance + fallback 均失败），R5 不编造。
    """

    name = "yahoo_price"

    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        """取 ticker 当前行情。返回 list[dict]；空 = 查不到（不抛错，R5）。"""
        if not ticker:
            return []
        rows = self._fetch_via_yfinance(ticker)
        if rows:
            return rows
        return self._fetch_via_api(ticker)

    def _fetch_via_yfinance(self, ticker: str) -> list[dict]:
        """yfinance 路径。未装 / 异常 / 无价 → 返 []（R5）。"""
        if yfinance is None:
            return []
        try:
            info = yfinance.Ticker(ticker).info
        except Exception:
            return []
        if not info:
            return []
        price = info.get("regularMarketPrice")
        if price is None:
            return []
        return [{
            "ticker": ticker.upper(),
            "current_price": price,
            "week52_high": info.get("fiftyTwoWeekHigh"),
            "week52_low": info.get("fiftyTwoWeekLow"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency"),
        }]

    def _fetch_via_api(self, ticker: str) -> list[dict]:
        """Fallback：requests 直接调 Yahoo chart API。失败 → 返 []（R5）。"""
        try:
            resp = requests.get(
                _YAHOO_CHART_URL.format(ticker=ticker),
                headers=_YAHOO_HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        try:
            meta = data["chart"]["result"][0]["meta"]
        except (KeyError, IndexError, TypeError):
            return []
        price = meta.get("regularMarketPrice")
        if price is None:
            return []
        return [{
            "ticker": ticker.upper(),
            "current_price": price,
            "week52_high": meta.get("fiftyTwoWeekHigh"),
            "week52_low": meta.get("fiftyTwoWeekLow"),
            "market_cap": meta.get("marketCap"),
            "currency": meta.get("currency"),
        }]


FetcherRegistry.register("yahoo_price", YahooPriceFetcher)


__all__ = ["YahooPriceFetcher"]
