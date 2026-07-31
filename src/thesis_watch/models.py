"""Thesis 卡数据模型（v0.1）。

对应 docs/thesis-card-schema.md。纯 stdlib（dataclasses + enum + typing），
不引入 ORM，保持「后端从简」。序列化为 JSON 存 SQLite（见 store.py）。

设计要点：
- 判断权归用户（R6）：卡只存「条件 + 证据 + 状态」，不存「结论/建议」。
- 每条证据必须有一手链接（R5）：Evidence.url 必填，EvidenceSelfCheck 回放校验。
- 历史事件示例也是事实，必须有源（R5）：HistoricalExample 带 source_url + verified。
- triggered 后必须用户收尾：CheckResult.resolve（沉淀为 eval 标注）。
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import typing


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _uuid() -> str:
    import uuid
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #

class FilerType(str, enum.Enum):
    """SEC 申报方类型，决定核对时的表单路由。

    外国发行人（20-F/6-K 申报方）以 6-K 为主渠道，不得沿用美国本土「6-K 降级」规则。
    """
    FOREIGN_ISSUER_20F_6K = "foreign_issuer_20f_6k"
    DOMESTIC_10K = "domestic_10k"
    OTHER = "other"


class ConditionLayer(str, enum.Enum):
    MIRROR = "mirror"      # Layer 1：关键假设的镜像条件
    REDLINE = "redline"    # Layer 2：通用红线默认包


class CondStatus(str, enum.Enum):
    UNTRIGGERED = "untriggered"
    WATCH = "watch"            # 需关注 / 拒判 / 无法判定
    TRIGGERED = "triggered"    # 已触发，待用户收尾


class RedlineTemplate(str, enum.Enum):
    LARGE_FINE = "large_fine"        # 大额罚单
    EXEC_CHANGE = "exec_change"      # 高管突变
    RESTATEMENT = "restatement"      # 财报重述


class ResolveAction(str, enum.Enum):
    """triggered 后用户收尾动作（自动沉淀为 eval 标注）。"""
    CONFIRMED_BROKEN = "confirmed_broken"
    FALSE_ALARM = "false_alarm"
    IGNORED = "ignored"


# --------------------------------------------------------------------------- #
# 数据类
# --------------------------------------------------------------------------- #

@dataclasses.dataclass
class HistoricalExample:
    """破局条件的真实历史事件示例。

    R5：示例也是事实，必须有源；verified=False 时不得展示给用户。
    待网络恢复后用一手链接补齐并置 verified=True。
    """
    event: str = ""
    source_url: str = ""          # 一手原文链接（SEC filing / 新闻原文，非聚合页）
    source_type: str = "news"     # sec_filing | news
    verified: bool = False


@dataclasses.dataclass
class Assumption:
    id: str = dataclasses.field(default_factory=_uuid)
    text: str = ""
    judgeable: bool = True


@dataclasses.dataclass
class Evidence:
    url: str = ""                       # 一手原文链接
    excerpt: str = ""                   # 原文摘录，须能在 fetched 原文中定位
    source_type: str = "news"           # sec_filing | news
    checked_ok: bool | None = None      # evidence_self_check 回放结果
    checked_at: str | None = None


@dataclasses.dataclass
class BrokenCondition:
    id: str = dataclasses.field(default_factory=_uuid)
    layer: ConditionLayer = ConditionLayer.MIRROR
    text: str = ""
    judgeable: bool = True
    historical_example: HistoricalExample = dataclasses.field(default_factory=HistoricalExample)
    status: CondStatus = CondStatus.UNTRIGGERED
    evidence: list[Evidence] = dataclasses.field(default_factory=list)
    # Layer 1 (mirror)
    source_assumption_id: str | None = None
    # Layer 2 (redline)
    template: RedlineTemplate | None = None
    threshold: dict[str, typing.Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ManualCheckItem:
    """人工自查项：价格图形型等系统不接行情的条件，按 cadence 提醒。"""
    id: str = dataclasses.field(default_factory=_uuid)
    text: str = ""
    reason: str = "价格图形型"
    cadence: str = "monthly"


@dataclasses.dataclass
class Confirmation:
    paraphrased: bool = False
    confirmed_at: str | None = None
    confirmed_by_user: bool = False


@dataclasses.dataclass
class CheckResult:
    """单次核对结果（核对 Agent 写入）。"""
    card_id: str = ""
    cond_id: str = ""
    status: CondStatus = CondStatus.UNTRIGGERED
    evidence: list[Evidence] = dataclasses.field(default_factory=list)
    refusal_code: str | None = None     # E1..E8（拒判原因，见 harness-design §6）
    checked_at: str = dataclasses.field(default_factory=_now_iso)
    resolve: ResolveAction | None = None  # 用户收尾（仅 triggered）


@dataclasses.dataclass
class ThesisCard:
    card_id: str = dataclasses.field(default_factory=_uuid)
    user_id: str = ""
    ticker: str = ""
    filer_type: FilerType = FilerType.OTHER
    holding_reason_raw: str = ""
    key_assumptions: list[Assumption] = dataclasses.field(default_factory=list)
    broken_conditions: list[BrokenCondition] = dataclasses.field(default_factory=list)
    manual_check_items: list[ManualCheckItem] = dataclasses.field(default_factory=list)
    confirmation: Confirmation = dataclasses.field(default_factory=Confirmation)
    created_at: str = dataclasses.field(default_factory=_now_iso)
    updated_at: str = dataclasses.field(default_factory=_now_iso)
    review_notes: list[dict[str, typing.Any]] = dataclasses.field(default_factory=list)


# --------------------------------------------------------------------------- #
# 通用 serde（dataclass ↔ JSON-native dict）
# --------------------------------------------------------------------------- #

def _is_dataclass_type(t: typing.Any) -> bool:
    return isinstance(t, type) and dataclasses.is_dataclass(t)


def _jsonable(o: typing.Any) -> typing.Any:
    if isinstance(o, enum.Enum):
        return o.value
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_jsonable(x) for x in o]
    return o


def _coerce(tp: typing.Any, val: typing.Any) -> typing.Any:
    if val is None:
        return None
    origin = typing.get_origin(tp)
    if origin is list:
        (inner,) = typing.get_args(tp)
        return [_coerce(inner, x) for x in val]
    if origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _coerce(args[0], val)
        return val
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return tp(val)
    if _is_dataclass_type(tp):
        return from_dict(tp, val)
    return val


def to_dict(obj: typing.Any) -> dict:
    """dataclass → JSON-native dict（枚举转 .value）。"""
    return _jsonable(dataclasses.asdict(obj))


def from_dict(cls: type, d: dict) -> typing.Any:
    """JSON-native dict → dataclass（枚举/嵌套/列表自动还原）。"""
    if not isinstance(d, dict):
        return d
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, typing.Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in d:
            kwargs[f.name] = _coerce(hints.get(f.name, str), d[f.name])
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[attr-defined]
            kwargs[f.name] = f.default_factory()  # type: ignore[misc]
        elif f.default is not dataclasses.MISSING:
            kwargs[f.name] = f.default
    return cls(**kwargs)


def to_json(obj: typing.Any) -> str:
    import json
    return json.dumps(to_dict(obj), ensure_ascii=False)


__all__ = [
    "FilerType", "ConditionLayer", "CondStatus", "RedlineTemplate", "ResolveAction",
    "HistoricalExample", "Assumption", "Evidence", "BrokenCondition",
    "ManualCheckItem", "Confirmation", "CheckResult", "ThesisCard",
    "to_dict", "from_dict", "to_json",
]
