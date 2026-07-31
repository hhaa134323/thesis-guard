"""红线 R1/R2/R3/R5 文案校验（v0.1）。

渲染或发送前对【系统输出】文本做黑名单校验，命中即阻断
（harness error E8，见 docs/harness-design.md §6）。

黑名单 = 目标里明确禁止的措辞（看涨/看跌/建议关注/目标价）+
投资建议动词（建议买入/卖出/加仓...）+ 无源表述（据传/市场预期）。

注意：
- 仅校验系统输出，不校验用户输入或对 SEC 原文的【引用】（引用需走 evidence 自检）。
- 黑名单偏保守以降低误杀；用户可经 config 扩展（见 config.example.yaml）。
"""
from __future__ import annotations

import os

# 默认黑名单（用户可经 config 扩展，不可缩水到低于红线要求）
DEFAULT_FORBIDDEN_PHRASES: list[str] = [
    # R3：不出现「看涨/看跌/建议关注」
    "看涨", "看跌", "建议关注",
    # R1：不给买卖/仓位建议（带「建议」前缀，降低误杀）
    "建议买入", "建议卖出", "建议加仓", "建议减仓", "建议清仓", "建议建仓",
    # R2：不预测涨跌、不输出目标价、不承诺收益
    "目标价", "预期涨幅", "预期跌幅", "预期收益", "承诺收益",
    # R5：禁止无源表述
    "据传", "市场预期", "市场传闻", "业内人士透露",
]


def get_forbidden_phrases(extra: list[str] | None = None) -> list[str]:
    """返回黑名单（去重，保序）。用户经 config 传入 extra 扩展。"""
    seen: list[str] = []
    for p in (DEFAULT_FORBIDDEN_PHRASES + (extra or [])):
        if p and p not in seen:
            seen.append(p)
    return seen


def find_violations(text: str, phrases: list[str] | None = None) -> list[str]:
    """返回命中的违禁短语（按出现顺序，去重）。"""
    pool = phrases if phrases is not None else DEFAULT_FORBIDDEN_PHRASES
    hits: list[str] = []
    for p in pool:
        if p in text and p not in hits:
            hits.append(p)
    return hits


class RedlineViolation(Exception):
    """渲染/发送文案命中红线黑名单（E8）。"""

    def __init__(self, violations: list[str], text: str):
        self.violations = violations
        self.text = text
        super().__init__(f"redline phrases hit: {violations}")


def guard(text: str, phrases: list[str] | None = None) -> str:
    """校验系统输出文本，命中则抛 RedlineViolation；否则原样返回。"""
    v = find_violations(text, phrases)
    if v:
        raise RedlineViolation(v, text)
    return text


def is_clean(text: str, phrases: list[str] | None = None) -> bool:
    """不抛异常的探测；返回是否有违禁。"""
    return not find_violations(text, phrases)
