"""通知编排（Stage 2 窗口 B / 任务 4）：Alert + Digest + S4 收尾。

三层通知（PRD §S3 触达 / §S4 收尾 / §S5 人工自查）：
- send_alert：triggered（check_agent 命中破局条件）或 safety_margin_hit（price_monitor 到价）
  → 当天**单独邮件**（附证据 + 一手链接 / 当前价 + 阈值）。经 NotifierRegistry.get("email").send。
- send_digest：每日汇总（所有持仓覆盖率 + watch 较上次变化 + manual_items + S3 无事行不空）。
  watch 变化读 check_results 每条的 changes（agent 自判 new/worsened/improved/unchanged/resolved/escalated）。
- request_s4_action：triggered 需用户收尾 → 邮件附三选项（确认破了 / 误报 / 忽略），
  误报数据沉淀 eval 标注（v1 记 JSONL 文件，THESIS_S4_LOG 配置，后续接 eval pipeline）。

邮件 plain text（不做 HTML 模板；EmailNotifier 默认 <pre> 包裹）。R1-R9 不变；每封邮件附
「判断权归你」（R6 不替用户结论）。不碰 orchestrator/serve/entry_loop/price_monitor/fetchers/notify
（notify.py 是旧单层简报，本模块是三层编排，并存；notify.py 不动）。

入参形状（防御式 .get，与上游解耦）：
- check_results（check_agent.run_check 输出）：
  {ticker, n_triggered, n_watch, n_untriggered, triggered:[{cond, urls}], ?changes:{cond_id:{change,text}}, ?next_verdict:{event,date}, ...}
- price_alerts（price_monitor.run_price_check 输出，8 键）：
  {ticker, alert_type, current_price, threshold, triggered, condition_text, position_type, timestamp}
- alert_data（send_alert 单条）：price_alert 8 键 / 或 {cond, urls, ?value, ?evidence_excerpt}
"""
from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path

from .notifiers import NotifierRegistry  # 导入即注册 EmailNotifier 到 "email"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _send_email(to: str, subject: str, body: str) -> bool:
    """经 email 渠道发 plain text 邮件（无 HTML 模板）。返 True=已发，False=dry-run/未发。"""
    return NotifierRegistry.get("email").send(to, subject, body)


# --- 最近裁判日（S3 无事行用；从 check_results 的 next_verdict 取，不依赖 ThesisCard）---
def _parse_ymd(date_str: str) -> tuple[int, int, int]:
    """YYYY-MM-DD → (y,m,d)；YYYY-MM → (y,m,0)；YYYY-Qn → (y, mid-month, 0)；YYYY → (y,0,0)。"""
    s = (date_str or "").strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"(\d{4})-(\d{2})", s)
    if m:
        return int(m.group(1)), int(m.group(2)), 0
    m = re.match(r"(\d{4})-Q(\d)", s, re.I)
    if m:
        return int(m.group(1)), int(m.group(2)) * 3 - 1, 0
    m = re.match(r"(\d{4})", s)
    if m:
        return int(m.group(1)), 0, 0
    return 0, 0, 0


def _nearest_verdict_day(check_results: list[dict]) -> str:
    """最近一个裁判日（check_results 里 next_verdict.date：≥当月最早的未来时点；全在过去取最近
    一个已过；全无 → 「（无）」）。格式「{ticker} 的 {m} 月 {d} 日（{event}）」（无日则 {m} 月）。"""
    today = datetime.date.today().isoformat()[:7]  # YYYY-MM
    cands: list[tuple[str, str, str]] = []
    for r in check_results:
        nv = r.get("next_verdict") or {}
        date = (nv.get("date") or "").strip()
        if date:
            cands.append((date, r.get("ticker", ""), nv.get("event") or ""))
    if not cands:
        return "（无）"
    future = [c for c in cands if c[0][:7] >= today]
    if future:
        date, ticker, event = min(future, key=lambda c: c[0])
    else:
        date, ticker, event = max(cands, key=lambda c: c[0])
    _y, m, d = _parse_ymd(date)
    if d:
        day_part = f"{m} 月 {d} 日"
    elif m:
        day_part = f"{m} 月"
    else:
        day_part = date[:4]
    return f"{ticker} 的 {day_part}（{event}）" if event else f"{ticker} 的 {day_part}"


# --- ① 即时 Alert ---
_ALERT_TYPE_LABELS = {"safety_margin": "安全边际到价", "stop_loss": "止损价到"}


def _render_alert(ticker: str, alert_data: dict) -> tuple[str, str]:
    """渲染 alert 邮件（plain text）。有 current_price → 价格 alert；否则 check_agent triggered。"""
    t = ticker or alert_data.get("ticker", "")
    cond = alert_data.get("cond") or alert_data.get("condition_text") or ""
    lines: list[str] = []
    if alert_data.get("current_price") is not None:
        atype = alert_data.get("alert_type", "safety_margin")
        label = _ALERT_TYPE_LABELS.get(atype, "价格到价")
        subject = f"Thesis Watch · {t} {label}"
        pos = alert_data.get("position_type", "")
        lines.append(f"■ {t} {label}（{pos}）" if pos else f"■ {t} {label}")
        if cond:
            lines.append(f"触发条件：{cond}")
        lines.append(f"当前价：{alert_data.get('current_price')} | 阈值：{alert_data.get('threshold')}")
        ts = alert_data.get("timestamp")
        if ts:
            lines.append(f"时间：{ts}")
        lines += ["", "判断权归你——价格到了，不是当初的理由变了。"]
    else:
        subject = f"Thesis Watch · {t} 破局条件命中"
        lines.append(f"■ {t} 破局条件命中")
        if cond:
            lines.append(f"条件：{cond}")
        val = alert_data.get("value") or alert_data.get("evidence_excerpt")
        if val:
            lines.append(f"值：{val}")
        urls = alert_data.get("urls") or ([alert_data["evidence_url"]] if alert_data.get("evidence_url") else [])
        if urls:
            lines.append("证据：")
            for u in urls:
                lines.append(f"  原文：{u}")
        lines += ["", "判断权归你。确认破了 / 误报 / 忽略需你收尾。"]
    return subject, "\n".join(lines)


def send_alert(ticker: str, alert_data: dict, to_email: str) -> bool:
    """即时 Alert：triggered（check_agent 命中）或 safety_margin_hit（price_monitor 到价）
    → 当天单独邮件（附证据 + 一手链接 / 当前价 + 阈值）。返 True=已发，False=dry-run。"""
    subject, body = _render_alert(ticker, alert_data)
    return _send_email(to_email, subject, body)


# --- ② 每日 Digest ---
def _status_label(r: dict) -> str:
    if r.get("n_triggered"):
        return "triggered"
    if r.get("n_watch"):
        return "watch"
    return "untriggered"


# watch 较上次变化的文案映射（unchanged 单独处理：label 含后缀「（无变化）」）
_CHANGE_LABELS = {
    "new": "新增 watch",
    "worsened": "恶化",
    "improved": "改善",
    "resolved": "已解除",
    "escalated": "升级 triggered",
}


def _render_digest(check_results: list[dict], price_alerts: list[dict],
                   manual_items: list[dict]) -> tuple[str, str]:
    real_alerts = [pa for pa in price_alerts if not pa.get("skipped")]
    n_tickers = len(check_results)
    n_triggered_cards = sum(1 for r in check_results if r.get("n_triggered"))
    total_triggers = n_triggered_cards + len(real_alerts)
    nearest = _nearest_verdict_day(check_results)

    lines = ["Thesis Watch · 每日简报", ""]
    for r in check_results:
        ticker = r.get("ticker", "")
        n_t = r.get("n_triggered", 0)
        n_w = r.get("n_watch", 0)
        n_u = r.get("n_untriggered", 0)
        total = r.get("total") or (n_t + n_w + n_u)
        checked = r.get("checked") or (n_t + n_w + n_u)
        lines.append(f"■ {ticker} [{_status_label(r)}]")
        lines.append(f"  已核对 {checked}/{total}（触发 {n_t} / 关注 {n_w} / 未触发 {n_u}）")
        for trig in r.get("triggered") or []:
            lines.append(f"  · 命中：{trig.get('cond', '')}")
            for u in trig.get("urls") or []:
                lines.append(f"    原文：{u}")
        for unch in r.get("unchecked") or []:
            lines.append(f"  · 未核对：{unch.get('cond', '')}（{unch.get('reason', '')}）")
        lines.append("")

    if real_alerts:
        lines.append("价格到价：")
        for pa in real_alerts:
            lines.append(f"  · {pa.get('ticker', '')} 当前 {pa.get('current_price')} ≤ 阈值 "
                         f"{pa.get('threshold')}（{pa.get('condition_text', '')}）")
        lines.append("")

    # 观察项：watch 较上次变化（读 check_results 每条的 changes；agent 自判，Task 5 已落地）
    watch_lines: list[str] = []
    for cr in check_results:
        ticker = cr.get("ticker", "")
        for cid, info in (cr.get("changes") or {}).items():
            if isinstance(info, dict):
                ch = info.get("change", "") or ""
                text = info.get("text", "") or ""
            else:
                ch, text = str(info), ""
            if not ch:
                continue  # 非 watch transition（空串）→ 不列
            if ch == "unchanged":
                watch_lines.append(f"  · {ticker} 仍在 watch：{text}（无变化）")
            else:
                label = _CHANGE_LABELS.get(ch, ch)
                watch_lines.append(f"  · {ticker} {label}：{text}")
    if watch_lines:
        lines.append("观察项：")
        lines.extend(watch_lines)
    else:
        lines.append("观察项：今日无 watch 变化")
    lines.append("")

    if manual_items:
        lines.append("需你自查：")
        for mi in manual_items:
            text = mi.get("text", "") if isinstance(mi, dict) else str(mi)
            if text:
                lines.append(f"  · {text}")
        lines.append("")

    # S3 无事行不空（约束 A）：让用户确认系统活着
    lines.append(f"已检查 {n_tickers} 只 / {total_triggers} 触发 / 最近裁判日：{nearest}")
    lines.append("判断权归你——坏的是价格，不是当初的理由。")

    subject = f"Thesis Watch · 每日简报（{n_tickers} 只，{total_triggers} 触发）"
    return subject, "\n".join(lines)


def send_digest(check_results: list[dict], price_alerts: list[dict],
                manual_items: list[dict], to_email: str) -> bool:
    """每日 Digest：所有持仓汇总（覆盖率 + watch 较上次变化 + manual_items + S3 无事行不空）。
    watch 变化读 check_results 每条的 changes（{cond_id:{change,text}}，agent 自判
    new/worsened/improved/unchanged/resolved/escalated；空串不列）。返 True=已发，False=dry-run。"""
    subject, body = _render_digest(check_results, price_alerts, manual_items)
    return _send_email(to_email, subject, body)


# --- ③ S4 收尾 ---
def _render_s4(ticker: str, triggered_data: dict) -> tuple[str, str]:
    t = ticker or triggered_data.get("ticker", "")
    cond = triggered_data.get("cond") or triggered_data.get("condition_text") or ""
    urls = triggered_data.get("urls") or []
    subject = f"Thesis Watch · {t} 待收尾（确认 / 误报 / 忽略）"
    lines = [f"■ {t} 破局条件命中，需你收尾", ""]
    if cond:
        lines.append(f"条件：{cond}")
    val = triggered_data.get("value") or triggered_data.get("evidence_excerpt")
    if val:
        lines.append(f"值：{val}")
    if urls:
        lines.append("证据：")
        for u in urls:
            lines.append(f"  原文：{u}")
    lines += ["", "请选择：",
              "  1) 确认破了",
              "  2) 误报",
              "  3) 忽略",
              "",
              "（误报数据将沉淀为 eval 标注，帮你和系统都校准。）"]
    return subject, "\n".join(lines)


def _log_s4_action(ticker: str, triggered_data: dict) -> None:
    """S4 收尾动作落 JSONL（误报→eval 标注的 v1 队列；THESIS_S4_LOG 未配 → 不落盘）。
    落盘失败不阻断邮件（v1 队列容错，不抛错）。"""
    path = os.environ.get("THESIS_S4_LOG", "")
    if not path:
        return  # 未配路径 → 不落盘（测试默认不写文件）
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ticker": ticker, "triggered_data": triggered_data,
               "requested_at": _now_iso(), "status": "pending"}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 落盘失败不阻断邮件（v1 队列容错）


def request_s4_action(ticker: str, triggered_data: dict, to_email: str) -> bool:
    """S4 收尾：triggered 需用户动作 → 邮件附三选项（确认破了 / 误报 / 忽略）。
    误报数据沉淀 eval 标注（v1 记 JSONL 文件，THESIS_S4_LOG 配置，后续接 eval pipeline）。
    返 True=已发，False=dry-run。"""
    subject, body = _render_s4(ticker, triggered_data)
    sent = _send_email(to_email, subject, body)
    _log_s4_action(ticker, triggered_data)  # 落盘（防御，失败不阻断邮件）
    return sent


__all__ = ["send_alert", "send_digest", "request_s4_action"]
