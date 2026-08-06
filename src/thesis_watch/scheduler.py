"""自动化调度（Stage 2 窗口 C / 任务 3）：胶水层。

把 price_monitor + check_agent + notification 粘成每日自动闭环。watch 记忆由 check_agent
自身输出（较上次 change，读 previous_verdicts），不再走独立 watch_state 模块/SQLite 表
（旧 C-2 代码方案两个死结：无新 filing 假解除 / 无数值无法判恶化——改 agent 自判）。
run_daily_check() 流程：price alerts → check_agent（遍历预置用户，结果含 changes）→
通知编排（破局 triggered 单独 alert + S4；价格提醒并入 digest；digest 读 check_results
的 changes）→ 季频复盘（查 check_results 最近 N 次 watch → 提醒，stateless，无 watch_states 表）。

调度：APScheduler AsyncIOScheduler，每日定时（默认美东 16:00 收盘后）。时间走 env
（THESIS_CHECK_TIME=HH:MM / THESIS_TZ，PRD §9 部署中立）。THESIS_SCHEDULER=1 时 serve.py
启动挂载；CLI：python -m thesis_watch.scheduler [--once|--serve]。

错误处理：price_monitor / check_agent 包 _retry（3 次递增退避 1/2/4s，无网络 / 限流容忍）；
任一步最终失败 → 记 errors，末尾 NotifierRegistry.get('email').send 发错误汇总邮件（不崩）。

R1-R9 不变；不替用户结论（R6：错误/复盘邮件也只述事实，不下结论）。不碰
price_monitor/notification/orchestrator/fetchers（只读调用）。apscheduler 为可选依赖
（顶层 try-import，未装时模块仍加载、调度不启动但 run_daily_check 可跑/可测）。
"""
from __future__ import annotations

import asyncio
import datetime
import os
import re
import time
from typing import Callable

from .config import load_config
from .models import CondStatus
from .notifiers import NotifierRegistry  # 导入即注册 EmailNotifier 到 "email"
from . import check_agent, notification, price_monitor
from .store import PRESET_USERS, ThesisStore

try:  # 可选重依赖：未装时模块仍加载，调度不启动（run_daily_check 不依赖它）
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
    _HAS_APSCHEDULER = True
except ImportError:
    AsyncIOScheduler = None  # type: ignore
    _HAS_APSCHEDULER = False


# --- 配置（env，部署中立；THESIS_CHECK_TIME/THESIS_TZ 在 _scheduler_config 里读）---
DB_PATH = os.environ.get("THESIS_DB", "data/thesis.db")
CONFIG_PATH = os.environ.get("THESIS_CONFIG", "config.yaml")
LOOKBACK_HOURS = int(os.environ.get("THESIS_CHECK_LOOKBACK_HOURS", "72"))
NOTIFY_TO = os.environ.get("THESIS_NOTIFY_TO", "")
# 季频复盘：某 cond 最近 N 次核对全 watch 才提醒（默认 3 ≈ 持续 watch 已确立；env 可调）
_QUARTERLY_WATCH_N = int(os.environ.get("THESIS_QUARTERLY_WATCH_N", "3"))


def _get_store() -> ThesisStore:
    store = ThesisStore(DB_PATH)
    store.seed_preset_users()
    return store


def _get_cfg() -> dict:
    return load_config(CONFIG_PATH)


def _send_email(subject: str, body: str) -> bool:
    """经 email 渠道发 plain text 邮件（错误通知 / 复盘提醒用）。返 True=已发。"""
    return NotifierRegistry.get("email").send(NOTIFY_TO, subject, body)


def _retry(fn: Callable, *, attempts: int = 3, label: str = ""):
    """3 次重试，间隔递增（1/2/4 秒）。无网络 / 限流容忍。最终失败抛 last error。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts - 1:
                time.sleep(2 ** i)
    assert last is not None
    raise last


def _collect_manual_items(store: ThesisStore) -> list[dict]:
    """从所有 thesis card 收集 manual_check_items（S5 自查清单，给 digest）。"""
    out: list[dict] = []
    for card in price_monitor.load_all_cards(store):
        for mi in (getattr(card, "manual_check_items", None) or []):
            out.append({"text": getattr(mi, "text", str(mi)),
                        "reason": getattr(mi, "reason", ""),
                        "cadence": getattr(mi, "cadence", "")})
    return out


def _scheduler_config() -> dict:
    """调度时间 / 时区从 env 读（THESIS_CHECK_TIME=HH:MM / THESIS_TZ）。默认 16:00 America/New_York。"""
    check_time = os.environ.get("THESIS_CHECK_TIME", "16:00")
    tz = os.environ.get("THESIS_TZ", "America/New_York")
    hour, minute = (int(x) for x in check_time.split(":"))
    return {"check_time": check_time, "tz": tz, "hour": hour, "minute": minute}


async def run_daily_check(*, store: ThesisStore | None = None,
                          cfg: dict | None = None,
                          log: Callable = print) -> dict:
    """每日检查流程（调度器自动调用 / CLI 手动）。返 daily 摘要 dict。

    顺序：price_monitor → check_agent（遍历预置用户，结果含 changes）→
    notification（alert / digest / S4；digest 读 check_results 的 changes）→
    季频复盘（check_results 最近 N 次 watch → 提醒，stateless）。
    每步包 try/except（失败不崩，记 errors → 末尾发错误通知邮件）。
    """
    store = store or _get_store()
    cfg = cfg or _get_cfg()
    errors: list[str] = []

    # 1. price_monitor → price alerts（重试）
    try:
        price_alerts = _retry(lambda: price_monitor.run_price_check(store=store),
                              label="price_monitor")
    except Exception as e:  # noqa: BLE001
        errors.append(f"price_monitor: {type(e).__name__}: {e}")
        price_alerts = []

    # Bug 2 fix: 过滤 skip（price_monitor 返 alert + skip 混合列表）
    price_alerts = [pa for pa in price_alerts if not pa.get("skipped")]

    # 2. check_agent（遍历预置用户，逐用户重试；空卡用户 run_all 短路返 []；
    #    结果含 changes = {cond_id:{change,text}}，watch 较上次变化由 agent 自判）
    check_results: list[dict] = []
    for u in PRESET_USERS:
        uid = u["user_id"]
        try:
            rs = await asyncio.to_thread(
                _retry,
                lambda uid=uid: check_agent.run_all(
                    uid, cfg, store, lookback_hours=LOOKBACK_HOURS, log=log),
                label="check_agent",
            )
            check_results.extend(rs)
        except Exception as e:  # noqa: BLE001
            errors.append(f"check_agent:{uid}: {type(e).__name__}: {e}")

    # 3. notification
    # 价格提醒不再单独发邮件（2026-08-06 设计调整，PM 决策 08-05 18:28 看板）：
    # price alerts 并入 3c send_digest 的「价格提醒」段渲染（到价 hit + 接近 approaching）。
    # 破局条件 triggered 的 alert 逻辑不变：下面 3b 仍单独发 send_alert + request_s4_action。
    # 3b. triggered check results → send_alert + request_s4_action
    for cr in check_results:
        if cr.get("n_triggered"):
            for trig in cr.get("triggered") or []:
                try:
                    notification.send_alert(cr.get("ticker", ""), trig, NOTIFY_TO)
                    notification.request_s4_action(cr.get("ticker", ""), trig, NOTIFY_TO)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"send_alert/S4({cr.get('ticker', '')}): {type(e).__name__}: {e}")

    # 3c. digest（所有结果汇总；watch 变化读 check_results 的 changes；S3 无事行不空在 send_digest 里）
    manual_items = _collect_manual_items(store)
    try:
        notification.send_digest(check_results, price_alerts, manual_items, NOTIFY_TO)
    except Exception as e:  # noqa: BLE001
        errors.append(f"send_digest: {type(e).__name__}: {e}")

    # 4. 季频复盘：查 check_results 最近 N 次 watch → 提醒（stateless，无 watch_states 表）
    n_review = 0
    try:
        review_items = _quarterly_review_items(store)
        n_review = len(review_items)
        if review_items:
            _send_quarterly_reminder(review_items)
    except Exception as e:  # noqa: BLE001
        errors.append(f"quarterly_review: {type(e).__name__}: {e}")

    # 错误通知邮件（任一步失败 → 发错误汇总；发不出去也不崩）
    if errors:
        try:
            body = "每日检查部分失败（已尽量继续）：\n" + "\n".join(f"- {e}" for e in errors)
            _send_email("Thesis Watch · 调度错误", body)
        except Exception:  # noqa: BLE001
            pass

    log(f"[scheduler] daily check done: {len(price_alerts)} price alerts, "
        f"{len(check_results)} check results, {n_review} quarterly reviews, "
        f"{len(errors)} errors")
    return {"price_alerts": len(price_alerts), "check_results": len(check_results),
            "quarterly_reviews": n_review, "errors": errors}


def _is_review_due(date_str: str, today: datetime.date) -> bool:
    """下次复盘日是否到期（<= today）。支持 YYYY-MM-DD / YYYY-MM / YYYY-Qn / YYYY；
    无日期 / 非法 → False（不催）。与旧 watch_state._is_due 同款——季频 cadence 仍由
    card.next_verdict.date 驱动，避免无门控每日刷屏。"""
    s = (date_str or "").strip()
    if not s:
        return False
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) <= today
        except ValueError:
            return False
    m = re.match(r"(\d{4})-Q(\d)", s, re.I)
    if m:
        q = int(m.group(2))
        if not 1 <= q <= 4:
            return False
        month = q * 3 - 1  # Q1→Feb(2) Q2→May(5) Q3→Aug(8) Q4→Nov(11)，与 notification._parse_ymd 同款
        return (int(m.group(1)), month) <= (today.year, today.month)
    m = re.match(r"(\d{4})-(\d{2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2))) <= (today.year, today.month)
    m = re.match(r"(\d{4})", s)
    if m:
        return int(m.group(1)) <= today.year
    return False


def _quarterly_review_items(store: ThesisStore, *, n_recent: int = _QUARTERLY_WATCH_N) -> list[dict]:
    """季频复盘（stateless，无 watch_states 表）：卡 next_verdict.date 到期 + 该卡某 cond
    最近 n_recent 次核对全 watch → 返需复查项。替代旧 watch_state.check_quarterly_review
    （旧用 active watch state 单点判定，新用 check_results 最近 N 次持续 watch，更稳）。
    不自动过期（从不删 check_results）。Returns: [{ticker, condition_text, n_watch}]。"""
    today = datetime.date.today()
    out: list[dict] = []
    for card in price_monitor.load_all_cards(store):
        if not getattr(card.confirmation, "confirmed_by_user", False):
            continue
        nv = getattr(card, "next_verdict", None)
        date = getattr(nv, "date", None) if nv is not None else None
        if not date or not _is_review_due(date, today):
            continue
        # 按 cond 收集最近 n_recent 次（list_check_results 已按 checked_at DESC，[0] 最新）
        by_cond: dict[str, list] = {}
        for r in store.list_check_results(card.card_id):
            cid = getattr(r, "cond_id", "")
            if cid:
                by_cond.setdefault(cid, []).append(r)
        for cond in card.broken_conditions:
            recent = by_cond.get(cond.id, [])[:n_recent]
            if len(recent) >= n_recent and all(
                getattr(r, "status", None) == CondStatus.WATCH for r in recent
            ):
                out.append({"ticker": card.ticker, "condition_text": cond.text,
                            "n_watch": len(recent)})
    return out


def _send_quarterly_reminder(review_items: list[dict]) -> None:
    """季频复盘提醒邮件（watch 项到复盘日，需用户复查）。R6：只述事实不结论。"""
    lines = ["以下 watch 项到复盘日，需你复查（确认仍 watch / 升级 triggered / 降级 untriggered）：", ""]
    for it in review_items:
        lines.append(f"· {it.get('ticker', '')} — {it.get('condition_text', '')}")
    _send_email("Thesis Watch · 季频复盘提醒", "\n".join(lines))


# --- 调度器（APScheduler）---
def build_scheduler():
    """构造 AsyncIOScheduler：每日 CHECK_TIME（TZ）跑 run_daily_check。
    apscheduler 未装 → None（调用方判断，如 serve.py 打印提示）。"""
    if not _HAS_APSCHEDULER or AsyncIOScheduler is None:
        return None
    cfg = _scheduler_config()
    sched = AsyncIOScheduler()
    sched.add_job(run_daily_check, "cron",
                  hour=cfg["hour"], minute=cfg["minute"], timezone=cfg["tz"],
                  id="thesis_daily_check", misfire_grace_time=3600)
    return sched


def start_scheduler():
    """构造 + 启动调度器（serve.py THESIS_SCHEDULER=1 时调）。apscheduler 未装 → None。"""
    sched = build_scheduler()
    if sched is not None:
        sched.start()
    return sched


def main() -> int:
    """CLI：python -m thesis_watch.scheduler [--once|--serve]
    默认 --once：跑一次 run_daily_check（asyncio.run）。
    --serve：挂 APScheduler 调度（阻塞；apscheduler 未装则报错退出）。"""
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="自动化调度：每日 check + 通知")
    ap.add_argument("--once", action="store_true", help="跑一次 run_daily_check（默认）")
    ap.add_argument("--serve", action="store_true", help="挂 APScheduler 调度（阻塞）")
    args = ap.parse_args()

    if args.serve:
        if not _HAS_APSCHEDULER:
            print("apscheduler 未装（pip install apscheduler）；无法挂调度。", file=sys.stderr)
            return 1
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        sched = start_scheduler()
        cfg = _scheduler_config()
        print(f"Thesis Watch 调度器已启动：每日 {cfg['check_time']} ({cfg['tz']}) 跑 run_daily_check。Ctrl+C 退出。")
        try:
            loop.run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass
        return 0

    # --once（默认）
    asyncio.run(run_daily_check())
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
