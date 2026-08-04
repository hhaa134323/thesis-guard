"""通知包。导入即触发各 notifier subclass 注册到 NotifierRegistry（base.py 定义接口/注册表）。

- base.Notifier / NotifierRegistry：统一接口 + 注册表（Stage 2 通知抽象层）。
- email_notifier：SMTP 邮件渠道（EmailNotifier 注册名 "email"）。

调用方经 NotifierRegistry.get(name) 取实例，不直接 import subclass（解耦触达与实现）。
"""
from .base import Notifier, NotifierRegistry
from . import email_notifier  # noqa: F401  (import 触发 EmailNotifier 注册 "email")

__all__ = ["Notifier", "NotifierRegistry", "email_notifier"]
