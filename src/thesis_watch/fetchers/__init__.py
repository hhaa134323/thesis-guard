"""数据源包。导入即触发各 fetcher subclass 注册到 FetcherRegistry（base.py 定义接口/注册表）。

- base.BaseFetcher / FetcherRegistry：统一接口 + 注册表（Stage 2 数据源抽象层）。
- sec_edgar：SEC EDGAR fetcher（SecFetcher 注册名 "sec"）。
- ticker_resolver：ticker → CIK / 公司名解析。

调用方经 FetcherRegistry.get(name) 取实例，不直接 import subclass（解耦路由与实现）。
"""
from .base import BaseFetcher, FetcherRegistry
from . import sec_edgar, ticker_resolver  # noqa: F401  (import 触发 SecFetcher 注册 "sec")

__all__ = ["BaseFetcher", "FetcherRegistry", "sec_edgar", "ticker_resolver"]
