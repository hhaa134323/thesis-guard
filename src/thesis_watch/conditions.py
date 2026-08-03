"""破局条件两层逻辑（v0.1）。

对应 docs/broken-condition-schema.md。

- Layer 1 mirror：关键假设的镜像条件。真实「按假设自动生成候选」是录入
  Agent（LLM）的职责；本模块只提供结构构造与可判定性启发式。
- Layer 2 redline：通用红线默认包（大额罚单/高管突变/财报重述），阈值可配。

可判定性硬约束：任一条件必须能映射到「可被一手公开披露击中的事件」。
价格图形型（均线/形态/突破…）系统不接行情 → 降级人工自查。
"""
from __future__ import annotations

import re
import uuid

from .models import (
    Assumption,
    BrokenCondition,
    ConditionLayer,
    CondStatus,
    HistoricalExample,
    ManualCheckItem,
    RedlineTemplate,
)

# 价格图形型关键词 → 不接行情，降级人工自查（每月提醒）
_PRICE_PATTERN_RE = re.compile(
    r"均线|头肩|双顶|双底|颈线|支撑位|阻力位|回踩|"
    r"放量|缩量|金叉|死叉|MACD|KDJ|布林|趋势线|"
    r"突破|收盘价|开盘价|最高价|最低价"
)


def is_price_pattern(text: str) -> bool:
    """检测文本是否依赖价格图形（→ 人工自查项，不进自动核对）。"""
    return bool(_PRICE_PATTERN_RE.search(text or ""))


def judgeable(text: str) -> bool:
    """启发式可判定性：价格图形型视为不可自动判定。"""
    return not is_price_pattern(text)


def is_paraphrase(cand: str, raw: str, *, threshold: float = 0.8) -> bool:
    """key_assumption 合格条件 3 的确定性 backstop（P2）：
    「比用户原话多出信息」——同义复述/拆分扩写/换词重写一律不合格。

    启发式：候选与 holding_reason_raw 高度相似（子串包含或 difflib ratio ≥ threshold）
    → 疑未多出信息，判不合格。条件 1/2/4 是语义判断（LLM 抽取时自判 + 进 open_questions），
    条件 3 在此加确定性兜底，专治 W2 8 条不合格中 7 条的「同义复述」。
    """
    if not cand or not raw:
        return False
    c = cand.strip().lower()
    r = raw.strip().lower()
    if not c or not r:
        return False
    if c in r or r in c:
        return True  # 子串/包含 → 高度相似
    from difflib import SequenceMatcher
    return SequenceMatcher(None, c, r).ratio() >= threshold


def _new_id() -> str:
    return uuid.uuid4().hex


def make_mirror(assumption: Assumption, mirror_text: str,
                historical_example: HistoricalExample | None = None,
                *, threshold: dict | None = None,
                source_type: str = "") -> BrokenCondition | None:
    """把一条假设的镜像条件构造为 BrokenCondition（Layer 1）。

    P3：mirror 生成侧强制可判定二元组——threshold（可判定数值/布尔事件）+ source_type
    （sec_filing_field / news_headline / press_release_text / manual）。任一缺失 → 返回 None，
    调用方转 open_questions 向用户追问。**不允许生成 threshold:null 的镜像**
    （与 default_redline_pack 的硬编码阈值对齐，同一份代码不再两套标准）。
    mirror_text 由录入 Agent（LLM）生成；本函数负责结构与可判定性标注。
    """
    if not threshold or not source_type:
        return None
    return BrokenCondition(
        id=_new_id(),
        layer=ConditionLayer.MIRROR,
        source_assumption_id=assumption.id,
        text=mirror_text,
        judgeable=judgeable(mirror_text),
        threshold=dict(threshold),
        source_type=source_type,
        historical_example=historical_example or HistoricalExample(),
        status=CondStatus.UNTRIGGERED,
    )


def to_manual_check(text: str, reason: str = "价格图形型",
                    cadence: str = "monthly") -> ManualCheckItem:
    """价格图形型条件降级为人工自查项。"""
    return ManualCheckItem(id=_new_id(), text=text, reason=reason, cadence=cadence)


# Layer 2 默认包定义。historical_example 暂留未验证占位（verified=False），
# 待网络恢复后用一手链接补齐——不得编造来源（R5）。
_REDLINE_DEFAULTS: list[dict] = [
    {
        "template": RedlineTemplate.LARGE_FINE,
        "text": "大额罚单",
        "threshold": {"amount_usd": 100_000_000},
        "historical_example": HistoricalExample(
            event="某发行人因合规问题被监管处大额罚单（待补一手来源）",
            source_url="",
            source_type="sec_filing",
            verified=False,
        ),
    },
    {
        "template": RedlineTemplate.EXEC_CHANGE,
        "text": "高管突变（CEO/CFO 离任或被调查）",
        "threshold": {"roles": ["CEO", "CFO"], "lookback_days": 30},
        "historical_example": HistoricalExample(
            event="某发行人 CEO/CFO 突然离任并随之爆出会计/合规问题（待补一手来源）",
            source_url="",
            source_type="sec_filing",
            verified=False,
        ),
    },
    {
        "template": RedlineTemplate.RESTATEMENT,
        "text": "财报重述",
        "threshold": {"forms": ["20-F", "10-K", "10-Q", "6-K"]},
        "historical_example": HistoricalExample(
            event="某发行人对已披露财报进行重述更正（待补一手来源）",
            source_url="",
            source_type="sec_filing",
            verified=False,
        ),
    },
]


def default_redline_pack(thresholds: dict | None = None,
                        enabled_redlines: list[str] | None = None) -> list[BrokenCondition]:
    """下发通用红线默认包（Layer 2），用户阈值可覆盖、可关停。

    thresholds 形如 {"large_fine": {"amount_usd": 5e7}, ...}，
    与模板默认阈值合并（用户值优先）。
    enabled_redlines：可选，只保留这些 template（按 .value，如 "large_fine"）的红线；
    None=全部。用于去重——当某条 mirror 已覆盖某红线语义（如 CEO/CFO 离职既在
    mirror 又会触发 exec_change），关停该红线避免同一事件重复计入。
    """
    out: list[BrokenCondition] = []
    overrides = thresholds or {}
    enabled = set(enabled_redlines) if enabled_redlines is not None else None
    for d in _REDLINE_DEFAULTS:
        key = d["template"].value
        if enabled is not None and key not in enabled:
            continue
        merged = {**d["threshold"], **overrides.get(key, {})}
        out.append(BrokenCondition(
            id=_new_id(),
            layer=ConditionLayer.REDLINE,
            template=d["template"],
            text=d["text"],
            judgeable=True,
            threshold=merged,
            source_type="sec_filing_field",  # P3：红线阈值由 SEC filing 字段判定
            historical_example=d["historical_example"],
            status=CondStatus.UNTRIGGERED,
        ))
    return out


def build_card_conditions(assumptions: list[Assumption],
                          mirrors: list[BrokenCondition],
                          extra_redlines: list[BrokenCondition] | None = None,
                          user_thresholds: dict | None = None,
                          enabled_redlines: list[str] | None = None) -> tuple[list[BrokenCondition], list[ManualCheckItem]]:
    """组装一张卡的破局条件 + 人工自查项。

    - mirrors：录入 Agent 已为各假设生成的镜像候选（P3：缺 threshold/source_type 的已被
      make_mirror 返回 None，此处过滤；调用方应转 open_questions）
    - 额外追加默认红线包（用户阈值可调、可关停，见 default_redline_pack）
    - 返回 (broken_conditions, manual_check_items)
    """
    broken: list[BrokenCondition] = [m for m in list(mirrors) if m is not None]
    broken.extend(default_redline_pack(user_thresholds, enabled_redlines))
    if extra_redlines:
        broken.extend(extra_redlines)
    return broken, []
