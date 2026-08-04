"""watch 记忆（Stage 2 窗口 C / 任务 5）：跨日追踪「将破未破」条件。

核心设计（已定）：
- 确定性代码比对，不用 agent（agent 已做评估，比较只是数学）。
- 不自动过期：「将破未破」可能持续多季，自动过期会让用户错过真正的破。本模块**从不删除** state。
- SQLite watch_states 表（store.py 扩展，本模块只调 store 方法）。

三个公共函数（签名严格，scheduler 任务 3 依赖）：
- update_watch_states(check_results) → 读上次 states、比对当前、写新 states、返变化列表。
- get_active_watch_states() → 所有 active 项（digest 用）。
- check_quarterly_review() → 卡 next_verdict.date 到期 → 返需复查的 active 项。

**双模式输入**（scheduler 传 aggregate，eval/单测可传 per-condition）：
- per-condition dict（有 condition_id / cond_id）→ 直接比对（spec 契约，worsened 需 distance_to_threshold）。
- aggregate dict（有 card_id 无 condition_id，= check_agent.run_check 输出）→ 经 store.get_card +
  store.list_check_results 展开成 per-condition（CheckResult 无 value/distance → worsened 不可算，默认 unchanged）。

change ∈ new|worsened|unchanged|resolved|escalated（escalated = watch 项触发毕业线 / check_agent
判 triggered 且上次 active；current_status=escalated。**escalated 是 task 4 值之外的扩展**——task
列 4 值，但 acceptance 要求检测毕业线升级，故加 escalated 作 change + current_status 双信号）。
current_status ∈ active|resolved|escalated。

返回 dict 8 键：ticker / condition_id / change / current_status / **status**（current_status 别名，
notification._render_digest 读 status）/ condition_text / first_seen_date / last_checked_date。
（task spec 7 键 + status 别名，保 notification 渲染不空。）

check_results per-condition 字段（防御式 .get，与上游解耦）：ticker / condition_id（或 cond_id）/
status(triggered|watch|untriggered) / condition_text? / value? / distance_to_threshold?（越小越接近破，
<=0 = 已破触发毕业线）/ graduation_line? / checked_at?。

**集成现状（2026-08-04）**：scheduler.run_daily_check 已接本模块（try-import，watch_state 缺失则跳过），
传 aggregate check_results → 走展开路径。worsened 需 per-condition distance_to_threshold，check_agent
当前 CheckResult 不产出 → 集成态下 still-watch 项显示为 unchanged（new/resolved/escalated 正常）。

红线 R1-R9 不变；guardrail 层零改动；不碰 orchestrator/serve/entry_loop/notification/scheduler/
price_monitor/fetchers（只读调 store + price_monitor.load_all_cards 读 card）。store 加 watch_states 表。
"""
from __future__ import annotations

import datetime
import os
import re

from .price_monitor import load_all_cards
from .store import ThesisStore

_EPSILON = 1e-9  # 距离比较容差（浮点噪声）


def _now_iso(dt: datetime.datetime | None = None) -> str:
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _today() -> datetime.date:
    return datetime.date.today()


_STORE: ThesisStore | None = None


def _get_store() -> ThesisStore:
    """watch_state 自己的 store 单例（不依赖 orchestrator / price_monitor 的单例；
    production 走 THESIS_DB_PATH 文件，同库；:memory: 仅 demo）。"""
    global _STORE
    if _STORE is None:
        _STORE = ThesisStore(os.environ.get("THESIS_DB_PATH", ":memory:"))
        _STORE.seed_preset_users()
    return _STORE


def _normalize_status(s) -> str:
    s = (s or "").strip().lower()
    if "triggered" in s and "untriggered" not in s:
        return "triggered"
    if "watch" in s:
        return "watch"
    if "untriggered" in s:
        return "untriggered"
    return ""


def _as_float(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _process_one(store: ThesisStore, cr: dict) -> dict | None:
    """per-condition check_result → 比对 + 写 state + 返 change dict（无 transition → None）。

    transition 表：
    - triggered + 上次 active → escalated（triggered 从头即破无 watch 前史 → 不算 watch transition，跳过）。
    - watch + distance<=0（触发毕业线）→ escalated。
    - watch + 无 active 前史 → new。
    - watch + 上次 active + distance 变近 → worsened（需 distance，否则 unchanged）。
    - watch + 上次 active + distance 未近 → unchanged。
    - untriggered + 上次 active → resolved（无前史 → 跳过）。
    """
    ticker = str(cr.get("ticker", "") or "").upper()
    cid = str(cr.get("condition_id", "") or cr.get("cond_id", "") or "")
    if not ticker or not cid:
        return None
    status = _normalize_status(cr.get("status"))
    val = _as_float(cr.get("value"))
    dist = _as_float(cr.get("distance_to_threshold"))
    grad_line = str(cr.get("graduation_line", "") or "")
    checked_at = str(cr.get("checked_at", "") or _now_iso())
    cond_text = str(cr.get("condition_text", "") or "")

    prev = store.get_watch_state(ticker, cid)
    prev_status = prev.get("status") if prev else None
    prev_history = (prev.get("history") or []) if prev else []
    prev_dist = _as_float(prev_history[-1].get("distance_to_threshold")) if prev_history else None
    prev_cond_text = (prev.get("condition_text") or "") if prev else ""
    prev_grad = (prev.get("graduation_line") or "") if prev else ""
    prev_first_seen = (prev.get("first_seen_date") or "") if prev else ""

    if status == "triggered":
        if prev is not None and prev_status == "active":
            change, new_status = "escalated", "escalated"
        else:
            return None  # triggered 从头即破（无 active watch 前史）→ 非.watch transition
    elif status == "watch":
        if dist is not None and dist <= _EPSILON:
            change, new_status = "escalated", "escalated"  # 距离 <= 0 = 触发毕业线
        elif prev is None or prev_status != "active":
            change, new_status = "new", "active"
        else:
            if dist is not None and prev_dist is not None and dist < prev_dist - _EPSILON:
                change = "worsened"
            else:
                change = "unchanged"
            new_status = "active"
    elif status == "untriggered":
        if prev is not None and prev_status == "active":
            change, new_status = "resolved", "resolved"
        else:
            return None  # 无 active 前史 → 非 watch transition
    else:
        return None  # 未知 status → 跳过

    first_seen = prev_first_seen if (prev is not None and prev_status == "active") else checked_at
    cond_text = cond_text or prev_cond_text
    grad_line = grad_line or prev_grad

    history = list(prev_history)
    history.append({
        "date": checked_at,
        "value": val,
        "distance_to_threshold": dist,
        "status_change": change,
    })

    store.upsert_watch_state({
        "ticker": ticker, "condition_id": cid, "condition_text": cond_text,
        "graduation_line": grad_line, "first_seen_date": first_seen,
        "last_checked_date": checked_at, "status": new_status, "history": history,
    })

    return {
        "ticker": ticker, "condition_id": cid, "change": change,
        "current_status": new_status, "status": new_status,  # status 别名（notification 读 status）
        "condition_text": cond_text, "first_seen_date": first_seen,
        "last_checked_date": checked_at,
    }


def _expand_aggregate(store: ThesisStore, cr: dict) -> list[dict]:
    """aggregate check_result（per-card，scheduler 传入 = check_agent.run_check 输出）→ per-condition dicts。

    经 store.get_card（取 broken_conditions）+ store.list_check_results（取每 cond 最新 status）展开。
    CheckResult 无 value/distance_to_threshold → 展开后 worsened 不可算（_process_one 默认 unchanged）。
    无 card_id / card 不存在 → []。
    """
    card_id = str(cr.get("card_id", "") or "")
    ticker = str(cr.get("ticker", "") or "").upper()
    if not card_id:
        return []
    card = store.get_card(card_id)
    if card is None:
        return []
    latest: dict[str, object] = {}
    for r in store.list_check_results(card_id):
        cid = getattr(r, "cond_id", "")
        if cid and cid not in latest:
            latest[cid] = r
    out: list[dict] = []
    for cond in card.broken_conditions:
        r = latest.get(cond.id)
        if r is None:
            continue
        st = getattr(getattr(r, "status", None), "value", None) or str(getattr(r, "status", ""))
        out.append({
            "ticker": ticker or card.ticker.upper(),
            "condition_id": cond.id,
            "status": st,
            "condition_text": cond.text,
            "checked_at": getattr(r, "checked_at", "") or _now_iso(),
        })
    return out


def update_watch_states(check_results: list[dict]) -> list[dict]:
    """读上次 watch states，比对当前结果，写新 states，返变化列表。

    双模式：per-condition dict（有 condition_id）→ 直接比对；aggregate dict（有 card_id 无
    condition_id）→ 经 card + check_results 表展开。无 PK / 无 card → 跳过。

    Returns: [{ticker, condition_id, change, current_status, status, condition_text,
               first_seen_date, last_checked_date}]（有 transition 的项；无 transition 不产出）。
    """
    store = _get_store()
    out: list[dict] = []
    for cr in check_results or []:
        if cr.get("condition_id") or cr.get("cond_id"):
            items: list[dict] = [cr]
        else:
            items = _expand_aggregate(store, cr)
        for pc in items:
            r = _process_one(store, pc)
            if r is not None:
                out.append(r)
    return out


def get_active_watch_states() -> list[dict]:
    """所有 active watch states（digest 显示用）。"""
    return _get_store().list_active_watch_states()


# --- 季频复盘（卡 next_verdict.date 到期 → 返需复查的 active 项；不自动过期）---

def _parse_review_date(s: str) -> tuple[int, int, int]:
    """YYYY-MM-DD → (y,m,d)；YYYY-MM → (y,m,0)；YYYY-Qn → (y, mid-month, 0)；YYYY → (y,0,0)。"""
    s = (s or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"(\d{4})-(\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2)), 0
    m = re.match(r"(\d{4})-Q(\d)", s, re.I)
    if m:
        return int(m.group(1)), int(m.group(2)) * 3 - 1, 0  # Q1→Feb(2) Q2→May(5) Q3→Aug(8) Q4→Nov(11)
    m = re.match(r"(\d{4})", s)
    if m:
        return int(m.group(1)), 0, 0
    return 0, 0, 0


def _is_due(date_str: str, today: datetime.date) -> bool:
    """下次复盘日是否到期（<= today）。YYYY-MM-DD 比日；YYYY-MM / Qn 比月；YYYY 比年。无日期 → False。"""
    y, m, d = _parse_review_date(date_str)
    if y == 0:
        return False
    if d:
        try:
            return datetime.date(y, m, d) <= today
        except ValueError:
            return False
    if m:
        return (y, m) <= (today.year, today.month)
    return y <= today.year


def check_quarterly_review() -> list[dict]:
    """卡 next_verdict.date 到期 → 返需复查的 active watch 项（不自动过期：从不删除）。

    匹配：watch state 的 ticker ∈ 到期卡的 ticker 集合。
    quarters_on_watch = len(history)（scheduler 季频跑 → history 每季一条）。

    Returns: [{ticker, condition_id, condition_text, first_seen_date, quarters_on_watch}]。
    """
    store = _get_store()
    today = _today()
    active = store.list_active_watch_states()
    due_tickers: set[str] = set()
    for card in load_all_cards(store):
        nv = getattr(card, "next_verdict", None)
        date = getattr(nv, "date", None) if nv is not None else None
        if date and _is_due(date, today):
            due_tickers.add(card.ticker.upper())
    out: list[dict] = []
    for ws in active:
        if ws["ticker"].upper() in due_tickers:
            out.append({
                "ticker": ws["ticker"],
                "condition_id": ws["condition_id"],
                "condition_text": ws.get("condition_text", ""),
                "first_seen_date": ws.get("first_seen_date", ""),
                "quarters_on_watch": len(ws.get("history") or []),
            })
    return out


__all__ = ["update_watch_states", "get_active_watch_states", "check_quarterly_review"]
