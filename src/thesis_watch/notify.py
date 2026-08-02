"""输出层（§2.4）：核对后渲染简报 + 邮件触达。

PRD §S3 / 屏 8：
- 命中条件的当天**单独发邮件**（附一手原文链接）。
- 静默日**只发一行存活**：「已检查 N 只 / 0 触发 / 最近一个裁判日：X 的 Y 月 Z 日」——
  让用户确认系统活着（不猜）。无事那行不许空（约束 A）。

邮件管道：smtplib SMTP_SSL 465 + app password（参考 pre-market-briefing src/sinks/mail_sender.py 的签名——
该处是 TODO stub，本模块实现之）。SMTP 配置走 env（不进代码/日志/提交，R7/secret 红线）。
无 SMTP creds → dry-run（打印简报到 stdout），便于本地 demo。
"""
from __future__ import annotations

import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable

from .models import CondStatus, ThesisCard
from .store import ThesisStore

SMTP_HOST = os.environ.get("THESIS_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("THESIS_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("THESIS_SMTP_USER", "")
SMTP_PASS = os.environ.get("THESIS_SMTP_PASS", "")
MAIL_FROM = os.environ.get("THESIS_SMTP_FROM", SMTP_USER)
MAIL_TO = os.environ.get("THESIS_NOTIFY_TO", "")


def _parse_ym(date_str: str) -> tuple[int, int] | None:
    """YYYY-MM → (y, m)；YYYY-Qn → (y, mid-month)；YYYY → (y, 0)。"""
    s = (date_str or "").strip()
    m = re.match(r"(\d{4})-(\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"(\d{4})-Q(\d)", s, re.I)
    if m:
        return int(m.group(1)), int(m.group(2)) * 3 - 1
    m = re.match(r"(\d{4})", s)
    if m:
        return int(m.group(1)), 0
    return None


def _nearest_verdict_day(cards: list[ThesisCard]) -> str:
    """最近一个裁判日（next_verdict.date 里最早的未来时点；无则「（无）」）。"""
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    candidates = []
    for c in cards:
        if not c.next_verdict:
            continue
        ym = _parse_ym(c.next_verdict.date or "")
        if ym is None:
            continue
        now_ym = (now.year, now.month)
        # 取 ≥ 当月的最早；若全在过去，取最大的（最近一个已过裁判日）
        candidates.append((ym, c.ticker, c.next_verdict.event or ""))
    if not candidates:
        return "（无）"
    future = [x for x in candidates if x[0] >= (now.year, now.month)]
    pool = future if future else candidates
    ym, ticker, event = min(pool, key=lambda x: x[0])
    y, m = ym
    return f"{ticker} 的 {y}{'-Q' + str((m + 2) // 3) if m and m in (2, 5, 8, 11) and not future else ('-' + str(m).zfill(2) if m else '')}（{event}）"


def render_briefing(summaries: list[dict], cards: list[ThesisCard]) -> dict:
    """渲染简报：命中 → 列每条触发条件 + 原文链接；无事 → 一行存活。

    summaries = check_agent.run_all 的返回（每卡 n_triggered/n_watch/n_untriggered + triggered 详情）。
    用 summary 的 triggered（当前轮），不读 store 历史 check_results（避免多次核对重复列同一条件）。
    cards 用于算最近裁判日。
    """
    n_checked = len(summaries)
    triggered_cards: list[dict] = []
    for s in summaries:
        trig = s.get("triggered") or []
        if trig:
            triggered_cards.append({"ticker": s["ticker"], "triggered": trig})

    nearest = _nearest_verdict_day(cards)
    has_triggered = bool(triggered_cards)

    if has_triggered:
        lines = [f"Thesis Watch · {len(triggered_cards)} 只标的命中破局条件"]
        for tc in triggered_cards:
            lines.append(f"\n■ {tc['ticker']}")
            for t in tc["triggered"]:
                lines.append(f"  · {t['cond']}")
                for u in t["urls"]:
                    lines.append(f"    原文：{u}")
        lines.append(f"\n判断权归你。确认破了 / 误报 / 忽略需你收尾。")
        subject = f"Thesis Watch · {len(triggered_cards)} 只命中"
        body_plain = "\n".join(lines)
        body_html = "<pre>" + body_plain.replace("<", "&lt;") + "</pre>"
    else:
        subject = "Thesis Watch · 今日无事"
        body_plain = (f"已检查 {n_checked} 只 / 0 触发 / 最近一个裁判日：{nearest}\n"
                      "判断权归你——坏的是价格，不是当初的理由。")
        body_html = "<pre>" + body_plain + "</pre>"

    return {"has_triggered": has_triggered, "n_checked": n_checked,
            "n_triggered_cards": len(triggered_cards), "nearest_verdict_day": nearest,
            "subject": subject, "body_plain": body_plain, "body_html": body_html,
            "triggered_cards": triggered_cards}


def send_email(subject: str, body_plain: str, body_html: str,
               to: str | None = None, log: Callable = print) -> bool:
    """SMTP_SSL 发邮件（app password）。无 SMTP_USER/PASS 或 MAIL_TO → dry-run 打印。"""
    to = to or MAIL_TO
    if not SMTP_USER or not SMTP_PASS or not to:
        log("[notify dry-run] 未配 SMTP creds/收件人，简报打印如下：")
        log(f"--- {subject} ---")
        log(body_plain)
        return False
    msg = MIMEMultipart("alternative")
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(MAIL_FROM, [to], msg.as_string())
    log(f"[notify] sent → {to} | {subject}")
    return True


def notify(user_id: str, summaries: list[dict], store: ThesisStore, *,
           log: Callable = print) -> dict:
    """核对汇总 → 渲染简报 → 发邮件（或 dry-run）。"""
    cards = store.list_cards(user_id)
    brief = render_briefing(summaries, cards)
    sent = send_email(brief["subject"], brief["body_plain"], brief["body_html"], log=log)
    brief["sent"] = sent
    return brief


def main() -> int:
    """CLI：python -m thesis_watch.notify --user beta1 [--lookback 72]
    跑核对（check_agent.run_all）→ 渲染简报 → 发邮件/dry-run。"""
    import argparse
    import sys

    from .check_agent import run_all
    from .config import load_config

    ap = argparse.ArgumentParser(description="输出层：核对 → 简报 → 邮件")
    ap.add_argument("--user", default="beta1")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--lookback", type=int, default=int(os.environ.get("THESIS_CHECK_LOOKBACK_HOURS", "72")))
    ap.add_argument("--db", default=os.environ.get("THESIS_DB", "data/thesis.db"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    store = ThesisStore(args.db)
    summaries = run_all(args.user, cfg, store, lookback_hours=args.lookback, log=print)
    brief = notify(args.user, summaries, store, log=print)
    print(f"\n=== 简报 === has_triggered={brief['has_triggered']} "
          f"n_checked={brief['n_checked']} n_triggered_cards={brief['n_triggered_cards']} "
          f"nearest_verdict_day={brief['nearest_verdict_day']} sent={brief['sent']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
