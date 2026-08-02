"""ticker → position_cap_tier 规则查表（确定性信息，不由 LLM 抽取）。

作者 2026-08-01 定：仓位上限档的规则在 Skill v4 里、按 ticker 定死，
transcript 里没有这个信息，让模型抽等于让它猜——glm-5.2 把 FDS 判成「中」，
实际是「硬thesis」）。改为规则查表：录入时按 ticker 查；查不到置 None，
进人工确认队列，不让模型猜。

归因（写进 docs/changelog.md + eval-report error analysis）：
「字段依据不在输入内，属 schema 设计错误，不是模型能力问题」——
确定性信息不该交给模型的典型案例。

档位来源：assets/notion/skill_thesis_review_v4.md「价值线」档位表的「现持仓」列。
"""
from __future__ import annotations

from .schema import PositionCapTier

# 源：Skill v4 档位表「现持仓」列。
TIER_MAP: dict[str, PositionCapTier] = {
    # 硬 thesis ~40%
    "FDS": PositionCapTier.HARD_THESIS,
    "BRK.B": PositionCapTier.HARD_THESIS,
    "MCO": PositionCapTier.HARD_THESIS,
    # 中 ~25%
    "VEEV": PositionCapTier.MID,
    "GOOGL": PositionCapTier.MID,
    "NOW": PositionCapTier.MID,
    "NFLX": PositionCapTier.MID,
    # 软 ~10%
    "FIS": PositionCapTier.SOFT,
    "HSBC": PositionCapTier.SOFT,
    # 宽基 ETF ~50%
    "QQQ": PositionCapTier.BROAD_ETF,
    # trinket 只减不加
    "CGNX": PositionCapTier.TRINKET,
    "NVDA": PositionCapTier.TRINKET,
    # 已清仓（DPZ/SPGI/GDXU）不建档位。
}


def lookup_tier(ticker: str) -> PositionCapTier | None:
    """按 ticker 查仓位上限档；查不到返回 None（→ 人工确认队列，不猜）。"""
    return TIER_MAP.get((ticker or "").strip().upper())
