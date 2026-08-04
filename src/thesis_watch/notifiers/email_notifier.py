"""邮件通知渠道（SMTP_SSL + app password）。

包装原 notify.send_email 的 SMTP 发送逻辑为 EmailNotifier(Notifier)，注册名 "email"。
SMTP 配置走 env（不进代码/日志/提交，R7/secret 红线）。无 SMTP creds/收件人 → dry-run
（打印简报到 stdout），便于本地 demo（行为与原 notify.send_email 一致）。
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable

from .base import Notifier, NotifierRegistry

SMTP_HOST = os.environ.get("THESIS_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("THESIS_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("THESIS_SMTP_USER", "")
SMTP_PASS = os.environ.get("THESIS_SMTP_PASS", "")
MAIL_FROM = os.environ.get("THESIS_SMTP_FROM", SMTP_USER)
MAIL_TO = os.environ.get("THESIS_NOTIFY_TO", "")


class EmailNotifier(Notifier):
    """SMTP_SSL 邮件渠道（app password）。无 SMTP_USER/PASS 或收件人 → dry-run 打印。"""

    name = "email"

    def send(self, to: str, subject: str, body: str, *,
             body_html: str | None = None, log: Callable = print) -> bool:
        """SMTP_SSL 发邮件（app password）。无 SMTP_USER/PASS 或收件人 → dry-run 打印。

        body=纯文本正文；body_html 可选 HTML 正文（无则用 body 包 <pre>）。
        to 为空时回退 MAIL_TO（env 收件人，与原 send_email 默认一致）。"""
        to = to or MAIL_TO
        if not SMTP_USER or not SMTP_PASS or not to:
            log("[notify dry-run] 未配 SMTP creds/收件人，简报打印如下：")
            log(f"--- {subject} ---")
            log(body)
            return False
        html = body_html if body_html is not None else ("<pre>" + body + "</pre>")
        msg = MIMEMultipart("alternative")
        msg["From"] = MAIL_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(MAIL_FROM, [to], msg.as_string())
        log(f"[notify] sent → {to} | {subject}")
        return True


NotifierRegistry.register("email", EmailNotifier)


__all__ = ["EmailNotifier", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "MAIL_FROM", "MAIL_TO"]
