"""数据源抽象层（Stage 2 prep）。

Stage 2 要接行情 API、Yahoo RSS 等新数据源。统一接口 BaseFetcher + 注册表 FetcherRegistry：
新数据源只需写 subclass + FetcherRegistry.register("xxx", XxxFetcher)，调用方经
FetcherRegistry.get("xxx") 取实例，不直接 import subclass（解耦路由与实现）。

设计：
- BaseFetcher.fetch(ticker, **kwargs) -> list[dict]：统一返回 list[dict]（空 = 查不到，
  调用方须明说「查不到」，R5 不编造）。各数据源特有参数（form_type / lookback / range 等）走 **kwargs。
- FetcherRegistry 类级单例（classmethod + class-level dict）：register(name, cls) 注册
  subclass，get(name) 懒构造实例并缓存。重新 register 同名 → 失效旧实例（下次 get 重建）。
- 现有 sec_edgar（forms_for_filer / fetch_filings / fetch_latest_filing）包装成 SecFetcher，
  注册名 "sec"（见 sec_edgar.py 末）；orchestrator.check_filing 经 registry 取 "sec"，
  行为不变（与 form_type 过滤兼容）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseFetcher(ABC):
    """数据源统一接口。subclass 实现 fetch(ticker, **kwargs) -> list[dict]。

    返回 list[dict]（空列表 = 无数据/查不到，调用方须明说「查不到」，R5 不编造）。
    subclass 负责把私有 dataclass / 响应对象转成 plain dict 输出（跨数据源统一形状由
    subclass 自定，调用方按数据源约定读字段）。
    """

    name: str = ""  # 注册名（subclass 可覆写；register 以显式 name 参数为准）

    @abstractmethod
    def fetch(self, ticker: str, **kwargs) -> list[dict]:
        """取 ticker 相关数据。**kwargs 承载各数据源特有参数（form_type / lookback 等）。
        返回 list[dict]；空列表 = 查不到（不抛错，调用方判断）。"""
        raise NotImplementedError


class FetcherRegistry:
    """数据源注册表（类级单例）。register(name, cls) 注册 subclass；get(name) 懒构造并
    缓存实例。重新 register 同名 → 失效旧实例（下次 get 重建）。

    用法：
        FetcherRegistry.register("sec", SecFetcher)
        fetcher = FetcherRegistry.get("sec")          # -> SecFetcher 实例
        rows = fetcher.fetch("NVDA", form_type="10-K")
    """

    _classes: dict[str, type[BaseFetcher]] = {}
    _instances: dict[str, BaseFetcher] = {}

    @classmethod
    def register(cls, name: str, fetcher_cls: type[BaseFetcher]) -> None:
        """注册 fetcher subclass 到 name。重新注册同名 → 失效旧实例（下次 get 重建）。"""
        if not (isinstance(fetcher_cls, type) and issubclass(fetcher_cls, BaseFetcher)):
            raise TypeError(f"{fetcher_cls!r} 不是 BaseFetcher subclass")
        if not name:
            raise ValueError("fetcher 注册名不能为空")
        cls._classes[name] = fetcher_cls
        cls._instances.pop(name, None)  # 失效旧实例（重新注册时下次 get 重建）

    @classmethod
    def get(cls, name: str) -> BaseFetcher:
        """取 name 对应的 fetcher 实例（懒构造 + 缓存）。未注册 → KeyError。"""
        if name not in cls._classes:
            raise KeyError(
                f"未注册的数据源 fetcher：{name!r}（已注册：{list(cls._classes)}）"
            )
        if name not in cls._instances:
            cls._instances[name] = cls._classes[name]()
        return cls._instances[name]


__all__ = ["BaseFetcher", "FetcherRegistry"]
