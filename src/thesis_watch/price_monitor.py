"""安全边际监控（Stage 2 窗口 B / 任务 2）。

每日遍历所有 thesis card，对有「加仓价 / 安全边际」字段的 card 拉 Yahoo 行情，
比对价格阈值，到价产出 alert（给通知系统任务 4 的接口）。

v1 只做简单价格比较（current_price <= threshold）：
- 安全边际文本（entry_anchor.note 优先）里提取价格数（$380 / 加仓价 380 / ≤ 380 / 380）。
- 复杂算法估值（P/TBV、P/E、yield、DCF 等比率 / 方法名）→ skip（v1 不支持，不编造）。
- 多倍数类型（ttm_gaap_pe / p_tbv / ...）无货币标记价格 → skip（v1 只比价格不比倍数；
  倍数本身不是价格，比了会误报）。
- Yahoo fetch 返空 / yfinance 未装 → skip（R5 不编造价格）。

两档（2026-08-06 设计调整，PM 决策 08-05 18:28 看板）：
- 到价（hit）：current_price <= threshold → level="hit"、triggered=True；safety_margin 与
  stop_loss（trade 仓）都产。
- 接近（approaching）：threshold < current_price <= threshold * 1.1 → level="approaching"、
  triggered=False；**仅 safety_margin 方向**（非 trade 仓），stop_loss v1 不做接近档。

alert dict 9 键严格一致（notification 接口）：ticker / alert_type / current_price /
threshold / triggered / level / condition_text / position_type / timestamp。
skip dict：{ticker, skipped: True, reason}（内部记录，非 alert 接口）。

红线 R1-R9 不变；guardrail 层零改动；不碰 orchestrator / serve / entry_loop /
notification / fetchers（只读用 FetcherRegistry.get("yahoo_price")）。store 只读不写
（watch-memory 窗口可能扩展 store，避免冲突）。
"""
from __future__ import annotations

import datetime
import json
import os
import re

from .fetchers import FetcherRegistry
from .models import ThesisCard, from_dict
from .store import ThesisStore

# 复杂估值关键词（比率 / 方法名）→ v1 skip
_COMPLEX_RE = re.compile(
    r"P\s*/\s*TBV|P\s*/\s*E|P\s*/\s*FCF|P\s*/\s*B|yield|owner[-\s]?earnings|reverse\s+DCF|DCF",
    re.IGNORECASE,
)
# 货币 / 前缀标记的价格（$380 / ¥380 / ≈380 / =380 / 加仓价 380 / 止损价 380 / 价格 380）
# 末尾负向断言排除 multiple 后缀（25x / 25倍）——倍数不是价格。
_CURRENCY_PRICE_RE = re.compile(
    r"(?:[$¥]\s*|≈\s*|=\s*|加仓价\s*|止损价?\s*|价格\s*)(\d+(?:\.\d+)?)(?!\s*[x倍])",
)
# 裸价格数（≤ 380 / <= 380 / 380）——同样排除 multiple 后缀。
_BARE_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)(?!\s*[x倍])")

_HORIZON_LABELS = {"long": "长线", "mid": "中线", "trade": "交易"}


def _now_iso(dt: datetime.datetime | None = None) -> str:
    """UTC ISO 时间戳（Z 后缀，与 alert spec 一致：2026-08-04T16:00:00Z）。"""
    dt = dt or datetime.datetime.now(datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_all_cards(store: ThesisStore) -> list[ThesisCard]:
    """从 store 加载所有 thesis card（跨所有 user）。

    稳定只读查询（card_json → from_dict 还原）；不写 store.py（watch-memory 窗口可能扩展）。
    """
    rows = store.conn.execute("SELECT card_json FROM thesis_cards").fetchall()
    return [from_dict(ThesisCard, json.loads(r["card_json"])) for r in rows]


def _parse_safety_margin(anchor) -> tuple[str, float | None]:
    """从 EntryAnchorData 提取 (condition_text, price_threshold)。

    threshold=None → v1 不支持（复杂估值 / 多倍数无价格 / 无可提取数）→ 调用方 skip。
    condition_text="" → 无安全边际字段 → 调用方过滤（不产出 skip）。

    价格优先从 note 提取（entry_anchor.note 是自由文本，价格常在此，见
    docs/thesis-card-schema.md §6：anchor_value 是倍数不是价格，价格进 note）；
    note 空则 anchor_value 兜底（anchor_type=other 时可能是裸价格）。
    """
    note = (getattr(anchor, "note", "") or "").strip()
    anchor_value = getattr(anchor, "anchor_value", None)
    anchor_type = (getattr(anchor, "anchor_type", "") or "").strip()

    if note:
        text = note
    elif anchor_value is not None:
        text = str(anchor_value)
    elif anchor_type:
        text = anchor_type
    else:
        return ("", None)  # 完全空 → 无安全边际字段 → 过滤

    if _COMPLEX_RE.search(text):
        return (text, None)  # 复杂估值 → skip
    # 多倍数类型（P/E、P/TBV 等）且无货币标记价格 → v1 只比价格不比倍数 → skip
    if anchor_type and anchor_type != "other" and not _CURRENCY_PRICE_RE.search(text):
        return (text, None)
    m = _CURRENCY_PRICE_RE.search(text) or _BARE_PRICE_RE.search(text)
    if m:
        return (text, float(m.group(1)))
    return (text, None)  # 有文本但提不出价格 → skip


def _horizon_label(horizon: str | None) -> str:
    return _HORIZON_LABELS.get((horizon or "").strip().lower(), "未指定")


_STORE: ThesisStore | None = None


def _get_store() -> ThesisStore:
    """price_monitor 自己的 store 单例（不依赖 orchestrator；production 走 THESIS_DB_PATH
    文件，与 orchestrator 同库；:memory: 仅 demo 不跑监控）。"""
    global _STORE
    if _STORE is None:
        _STORE = ThesisStore(os.environ.get("THESIS_DB_PATH", ":memory:"))
        _STORE.seed_preset_users()
    return _STORE


def run_price_check(
    store: ThesisStore | None = None,
    *,
    now: datetime.datetime | None = None,
) -> list[dict]:
    """遍历所有 thesis card，检查安全边际，返回 alert + skip 列表。

    - 有安全边际 + 价格 <= 阈值 → 到价 alert（hit，9 键，notification 接口）
    - 有安全边际 + 非trade + 阈值 < 价格 <= 阈值*1.1 → 接近 alert（approaching，9 键）
    - 有安全边际 + 复杂估值 / 无可提取价格 → skip dict（reason=complex valuation not supported in v1）
    - 有安全边际 + Yahoo fetch 返空 → skip dict（reason=price unavailable，R5 不编造）
    - 有安全边际 + 价格 > 阈值*1.1 → 无产出（未触发且未接近）
    - 无安全边际字段 → 过滤（无产出）
    无 card / 全未触发 → []。
    """
    store = store or _get_store()
    timestamp = _now_iso(now)
    out: list[dict] = []
    for card in load_all_cards(store):
        anchor = getattr(card, "entry_anchor", None)
        if anchor is None:
            continue
        text, threshold = _parse_safety_margin(anchor)
        if not text:
            continue  # 无安全边际字段 → 过滤
        if threshold is None:
            out.append({"ticker": card.ticker, "skipped": True,
                        "reason": "complex valuation not supported in v1"})
            continue
        rows = FetcherRegistry.get("yahoo_price").fetch(card.ticker)
        if not rows or rows[0].get("current_price") is None:
            out.append({"ticker": card.ticker, "skipped": True,
                        "reason": "price unavailable"})
            continue
        current_price = float(rows[0]["current_price"])
        horizon = (card.holding_horizon or "").strip().lower()
        is_trade = horizon == "trade"
        alert_type = "stop_loss" if is_trade else "safety_margin"
        if current_price <= threshold:
            # 到价档（hit）：safety_margin 与 stop_loss 都产
            out.append({
                "ticker": card.ticker,
                "alert_type": alert_type,
                "current_price": current_price,
                "threshold": threshold,
                "triggered": True,
                "level": "hit",
                "condition_text": text,
                "position_type": _horizon_label(card.holding_horizon),
                "timestamp": timestamp,
            })
        elif not is_trade and threshold < current_price <= threshold * 1.1:
            # 接近档（approaching）：仅 safety_margin 方向（非 trade）；stop_loss v1 不做接近档
            out.append({
                "ticker": card.ticker,
                "alert_type": "safety_margin",
                "current_price": current_price,
                "threshold": threshold,
                "triggered": False,
                "level": "approaching",
                "condition_text": text,
                "position_type": _horizon_label(card.holding_horizon),
                "timestamp": timestamp,
            })
        # else: 未到价且未接近 → 无产出
    return out


__all__ = ["run_price_check", "load_all_cards", "_parse_safety_margin"]
