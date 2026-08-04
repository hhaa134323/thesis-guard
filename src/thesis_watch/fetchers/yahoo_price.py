"""Yahoo 行情 fetcher（Stage 2 安全边际监控用）。

yfinance.Ticker(ticker).info 取 regularMarketPrice / fiftyTwoWeekHigh /
fiftyTwoWeekLow / marketCap / currency，包成统一 list[dict]（BaseFetcher 接口）。
注册名 "yahoo_price"；调用方经 FetcherRegistry.get("yahoo_price") 取实例。

R5：查不到（yfinance 未装 / 异常 / ticker 不存在 / 无可用价）→ 返空 list，不抛错、不编造。
yfinance 为可选重依赖（pandas/numpy 等），故顶层 try-import：未装时模块仍可加载、注册仍
生效（fetch 返 []）；测试 monkeypatch yahoo_price.yfinance 即可离线跑（与 sec_edgar patch
sec_edgar.requests 同款），不依赖真实 yfinance 安装。
"""
from __future__ import annotations

from .base import BaseFetcher, FetcherRegistry

try:  # 可选重依赖：未装时模块仍加载，fetch 返 []（R5）
    import yfinance  # type: ignore
except ImportError:
    yfinance = None  # type: ignore


class YahooPriceFetcher(BaseFetcher):
    """Yahoo 行情 fetcher（BaseFetcher subclass，注册名 "yahoo_price"）。

    fetch(ticker) 取 yfinance.Ticker(ticker).info，映射成
    [{ticker, current_price, week52_high, week52_low, market_cap, currency}]。
    空 = 查不到（yfinance 未装 / 异常 / ticker 不存在 / 无 regularMarketPrice），R5 不编造。
    """

    name = "yahoo_price"

    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        """取 ticker 当前行情。返回 list[dict]；空 = 查不到（不抛错，R5）。"""
        if yfinance is None:  # 未装 yfinance → 查不到（R5）
            return []
        if not ticker:
            return []
        try:
            info = yfinance.Ticker(ticker).info
        except Exception:
            return []  # 网络错误 / yfinance 异常 → 返空（R5，不抛错）
        if not info:  # 空 dict（ticker 不存在 / 无数据）→ 返空（R5 不编造）
            return []
        price = info.get("regularMarketPrice")
        if price is None:  # 无可用价 → 不返半空行编造（R5）
            return []
        return [{
            "ticker": ticker.upper(),
            "current_price": price,
            "week52_high": info.get("fiftyTwoWeekHigh"),
            "week52_low": info.get("fiftyTwoWeekLow"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency"),
        }]


FetcherRegistry.register("yahoo_price", YahooPriceFetcher)


__all__ = ["YahooPriceFetcher"]
