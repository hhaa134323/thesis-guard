"""Pydantic schema — 录入 Agent LLM 输出契约（v0.2，待 day-1 验证后并吞 models.py）。

作者 2026-08-01 定：数据契约与 LLM 输出契约**共用同一份 pydantic 定义**。
录入 Agent 的 PydanticAI 调用直接产出 EntryExtraction（结构化输出），
harness 再补红线默认包/id/时间戳/状态 + 规则查表项 → 完整 ThesisCard。

字段语义详解走系统提示词；本文件 description 故意精简（v0.2 调整），
避免冗长 description 被 LLM 在 tool-call 里复述、撑大 output token。
"""
from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class FilerType(str, enum.Enum):
    """SEC 申报方类型，决定核对时 SEC 表单路由（6-K 为主 vs 10-K）。

    ETF/ETN/基金/信托（etf_fund）无公司层面 10-K/20-F，破条件依赖指数成分/基金公告/价格规模，
    v1 数据源不覆盖 → 全 manual（见 docs/data-sources.md）。
    """
    FOREIGN_ISSUER_20F_6K = "foreign_issuer_20f_6k"
    DOMESTIC_10K = "domestic_10k"
    ETF_FUND = "etf_fund"
    OTHER = "other"


class ConditionLayer(str, enum.Enum):
    MIRROR = "mirror"
    REDLINE = "redline"


class PositionCapTier(str, enum.Enum):
    """仓位上限档（单一持仓上限 = thesis 脆弱度函数）。取值与 Skill v4 一致。
    **不由 LLM 抽取**——按 ticker 规则查表（见 tier_map.py）。"""
    HARD_THESIS = "硬thesis"
    MID = "中"
    SOFT = "软"
    BROAD_ETF = "宽基ETF"
    TRINKET = "trinket"


class Assumption(BaseModel):
    text: str
    judgeable: bool = True


class MirrorSpec(BaseModel):
    """LLM 为某条假设生成的镜像条件（Layer 1）。

    P3：mirror 生成侧强制可判定二元组——threshold + source_type。LLM 须为每条镜像给出：
    threshold（可判定数值/布尔事件，如 {"metric":"service_rev_yoy","operator":"<","value":0}）
    + source_type（sec_filing_field / news_headline / press_release_text / manual）。
    任一缺失 → harness make_mirror 返回 None，转 open_questions（不生成 threshold:null 镜像）。
    """
    assumption_text: str = Field(description="对应假设原文")
    mirror_text: str = Field(description="镜像破局条件")
    threshold: dict | None = Field(default=None, description="可判定阈值（数值/布尔事件）")
    source_type: str = Field(default="", description="阈值判定数据源类型")


class ManualCheckItem(BaseModel):
    """价格图形型等不可自动核对项。"""
    text: str
    reason: str = "价格图形型"
    cadence: str = "monthly"


class OpenQuestion(BaseModel):
    """抽取阶段被四关拒掉、转交用户追问的项（P2）。

    field：来源字段（默认 key_assumptions）；reason：哪条不过 + 为什么；text：原候选文本。
    合格的 key_assumption 须同时满足四条（见 docs/thesis-card-schema.md §7 + prompts/entry-agent.md），
    任一不过 → 不写 key_assumptions，改写为本对象向用户追问，宁缺勿凑。
    """
    field: str = "key_assumptions"
    reason: str = ""
    text: str = ""


class NextVerdict(BaseModel):
    """下一个能证伪 thesis 的事件+日期（不等于下次复盘日）。"""
    event: str
    date: str | None = None
    source_note: str = ""


class EntryAnchor(BaseModel):
    """录入估值锚（估值型破条件用；无数据时 value 留 None）。"""
    anchor_type: str
    anchor_value: float | None = None
    note: str = ""


class EntryExtraction(BaseModel):
    """录入 Agent LLM 调用的结构化输出契约（PydanticAI output_type）。

    position_cap_tier 不在此处——它是确定性信息（按 ticker 查 tier_map），
    不交给 LLM 猜（作者 2026-08-01 定，见 tier_map.py + changelog）。
    """
    ticker: str | None = None
    holding_reason_raw: str
    key_assumptions: list[Assumption] = Field(default_factory=list)
    open_questions: list[OpenQuestion] = Field(default_factory=list)  # P2：四关拒掉的候选 → 追问
    mirrors: list[MirrorSpec] = Field(default_factory=list)
    manual_items: list[ManualCheckItem] = Field(default_factory=list)
    filer_type: FilerType = FilerType.OTHER
    next_verdict: NextVerdict | None = None
    entry_anchor: EntryAnchor | None = None


__all__ = [
    "FilerType", "ConditionLayer", "PositionCapTier",
    "Assumption", "MirrorSpec", "ManualCheckItem", "OpenQuestion",
    "NextVerdict", "EntryAnchor", "EntryExtraction",
]
