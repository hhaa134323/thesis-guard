"""自动化调度（Stage 2 窗口 C / 任务 3）：胶水层。

把 price_monitor + check_agent + watch_state + notification 粘成每日自动闭环。
run_daily_check() 流程：price alerts → check_agent（遍历预置用户）→ watch_state 更新 →
通知编排（alert / digest / S4）→ watch_state 季频复盘提醒。

调度：APScheduler AsyncIOScheduler，每日定时（默认美东 16:00 收盘后）。时间走 env
（THESIS_CHECK_TIME=HH:MM / THESIS_TZ，PRD §9 部署中立）。THESIS_SCHEDULER=1 时 serve.py
启动挂载；CLI：python -m thesis_watch.scheduler [--once|--serve]。

错误处理：price_monitor / check_agent 包 _retry（3 次递增退避 1/2/4s，无网络 / 限流容忍）；
任一步最终失败 → 记 errors，末尾 NotifierRegistry.get('email').send 发错误汇总邮件（不崩）。

R1-R9 不变；不替用户结论（R6：错误/复盘邮件也只述事实，不下结论）。不碰
price_monitor/notification/watch_state/orchestrator/fetchers（只读调用）。apscheduler + watch_state
为可选依赖（顶层 try-import，未装时模块仍加载、调度不启动但 run_daily_check 可跑/可测）。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Callable

from .config import load_config
from .notifiers import NotifierRegistry  # 导入即注册 EmailNotifier 到 "email"
from . import check_agent, notification, price_monitor
from .store import PRESET_USERS, ThesisStore

try:  # 可选重依赖：未装时模块仍加载，调度不启动（run_daily_check 不依赖它）
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
    _HAS_APSCHEDULER = True
except ImportError:
    AsyncIOScheduler = None  # type: ignore
    _HAS_APSCHEDULER = False

try:  # watch_state 窗口 C-2 并行开发，未交付时 None（run_daily_check 跳过 watch 步骤）
    from . import watch_state  # type: ignore
except ImportError:
    watch_state = None  # type: ignore


# --- 配置（env，部署中立；THESIS_CHECK_TIME/THESIS_TZ 在 _scheduler_config 里读）---
DB_PATH = os.environ.get("THESIS_DB", "data/thesis.db")
CONFIG_PATH = os.environ.get("THESIS_CONFIG", "config.yaml")
LOOKBACK_HOURS = int(os.environ.get("THESIS_CHECK_LOOKBACK_HOURS", "72"))
NOTIFY_TO = os.environ.get("THESIS_NOTIFY_TO", "")


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

    顺序：price_monitor → check_agent（遍历预置用户）→ watch_state.update →
    notification（alert / digest / S4）→ watch_state.check_quarterly_review。
    每步包 try/except（失败不崩，记 errors → 末尾发错误通知邮件）。watch_state 未装则跳过。
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

    # 2. check_agent（遍历预置用户，逐用户重试；空卡用户 run_all 短路返 []）
    check_results: list[dict] = []
    for u in PRESET_USERS:
        uid = u["user_id"]
        try:
            rs = _retry(lambda uid=uid: check_agent.run_all(
                uid, cfg, store, lookback_hours=LOOKBACK_HOURS, log=log))
            check_results.extend(rs)
        except Exception as e:  # noqa: BLE001
            errors.append(f"check_agent:{uid}: {type(e).__name__}: {e}")

    # 3. watch_state.update_watch_states（未装跳过）
    watch_changes: list[dict] = []
    if watch_state is not None:
        try:
            watch_changes = watch_state.update_watch_states(check_results)
        except Exception as e:  # noqa: BLE001
            errors.append(f"watch_state.update: {type(e).__name__}: {e}")

    # 4. notification
    # 4a. price alerts → send_alert
    for pa in price_alerts:
        try:
            notification.send_alert(pa.get("ticker", ""), pa, NOTIFY_TO)
        except Exception as e:  # noqa: BLE001
            errors.append(f"send_alert(price {pa.get('ticker', '')}): {type(e).__name__}: {e}")

    # 4b. triggered check results → send_alert + request_s4_action
    for cr in check_results:
        if cr.get("n_triggered"):
            for trig in cr.get("triggered") or []:
                try:
                    notification.send_alert(cr.get("ticker", ""), trig, NOTIFY_TO)
                    notification.request_s4_action(cr.get("ticker", ""), trig, NOTIFY_TO)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"send_alert/S4({cr.get('ticker', '')}): {type(e).__name__}: {e}")

    # 4c. digest（所有结果汇总；S3 无事行不空在 notification.send_digest 里）
    manual_items = _collect_manual_items(store)
    try:
        notification.send_digest(check_results, price_alerts, watch_changes,
                                  manual_items, NOTIFY_TO)
    except Exception as e:  # noqa: BLE001
        errors.append(f"send_digest: {type(e).__name__}: {e}")

    # 5. watch_state.check_quarterly_review → 复盘提醒（未装跳过）
    if watch_state is not None:
        try:
            review_items = watch_state.check_quarterly_review()
            if review_items:
                _send_quarterly_reminder(review_items)
        except Exception as e:  # noqa: BLE001
            errors.append(f"watch_state.review: {type(e).__name__}: {e}")

    # 错误通知邮件（任一步失败 → 发错误汇总；发不出去也不崩）
    if errors:
        try:
            body = "每日检查部分失败（已尽量继续）：\n" + "\n".join(f"- {e}" for e in errors)
            _send_email("Thesis Watch · 调度错误", body)
        except Exception:  # noqa: BLE001
            pass

    log(f"[scheduler] daily check done: {len(price_alerts)} price alerts, "
        f"{len(check_results)} check results, {len(watch_changes)} watch changes, "
        f"{len(errors)} errors")
    return {"price_alerts": len(price_alerts), "check_results": len(check_results),
            "watch_changes": len(watch_changes), "errors": errors}


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
