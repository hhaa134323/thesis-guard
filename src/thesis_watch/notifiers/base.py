"""通知抽象层（Stage 2 prep）。

Stage 2 要加价格到价提醒、mirror 触发通知、红线触发通知；渠道会扩展（站内、webhook）。
统一接口 Notifier + 注册表 NotifierRegistry：新渠道只需写 subclass +
NotifierRegistry.register("xxx", XxxNotifier)，调用方经 NotifierRegistry.get("xxx")
取实例，不直接 import subclass（解耦触达与实现）。

设计（镜像 fetchers/base.py 的 BaseFetcher + FetcherRegistry）：
- Notifier.send(to, subject, body, *, body_html=None, log=print) -> bool：统一发送接口。
  body=纯文本正文；body_html 可选 HTML 正文（邮件用；新渠道可忽略）。返回 True=已发，
  False=dry-run/未发（无 creds 时不抛错，调用方判断）。
- NotifierRegistry 类级单例（classmethod + class-level dict）：register(name, cls) 注册
  subclass，get(name) 懒构造实例并缓存。重新 register 同名 → 失效旧实例（下次 get 重建）。
- 现有邮件发送（notify.send_email 的 SMTP_SSL 逻辑）包装成 EmailNotifier，注册名 "email"
  （见 email_notifier.py 末）；notify.notify 经 registry 取 "email"，行为不变。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class Notifier(ABC):
    """通知渠道统一接口。subclass 实现 send(to, subject, body, *, body_html, log) -> bool。

    返回 True=已发送；False=dry-run/未发（无 creds 时不抛错，调用方判断）。
    body=纯文本正文；body_html 可选 HTML 正文（邮件用，新渠道可忽略）。
    """

    name: str = ""  # 注册名（subclass 可覆写；register 以显式 name 参数为准）

    @abstractmethod
    def send(self, to: str, subject: str, body: str, *,
             body_html: str | None = None, log: Callable = print) -> bool:
        """发一条通知。返回 True=已发；False=dry-run/未发。"""
        raise NotImplementedError


class NotifierRegistry:
    """通知注册表（类级单例）。register(name, cls) 注册 subclass；get(name) 懒构造并
    缓存实例。重新 register 同名 → 失效旧实例（下次 get 重建）。

    用法：
        NotifierRegistry.register("email", EmailNotifier)
        notifier = NotifierRegistry.get("email")     # -> EmailNotifier 实例
        notifier.send(to="a@b.com", subject="...", body="...", body_html="...")
    """

    _classes: dict[str, type[Notifier]] = {}
    _instances: dict[str, Notifier] = {}

    @classmethod
    def register(cls, name: str, notifier_cls: type[Notifier]) -> None:
        """注册 notifier subclass 到 name。重新注册同名 → 失效旧实例（下次 get 重建）。"""
        if not (isinstance(notifier_cls, type) and issubclass(notifier_cls, Notifier)):
            raise TypeError(f"{notifier_cls!r} 不是 Notifier subclass")
        if not name:
            raise ValueError("notifier 注册名不能为空")
        cls._classes[name] = notifier_cls
        cls._instances.pop(name, None)  # 失效旧实例（重新注册时下次 get 重建）

    @classmethod
    def get(cls, name: str) -> Notifier:
        """取 name 对应的 notifier 实例（懒构造 + 缓存）。未注册 → KeyError。"""
        if name not in cls._classes:
            raise KeyError(
                f"未注册的通知渠道 notifier：{name!r}（已注册：{list(cls._classes)}）"
            )
        if name not in cls._instances:
            cls._instances[name] = cls._classes[name]()
        return cls._instances[name]


__all__ = ["Notifier", "NotifierRegistry"]
