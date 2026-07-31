"""R3/R5 文案黑名单测试（无网络）。"""
from __future__ import annotations

import pytest

from thesis_watch.redline import (
    RedlineViolation,
    find_violations,
    get_forbidden_phrases,
    guard,
    is_clean,
)


def test_catches_explicit_forbidden():
    assert "看涨" in find_violations("该票看涨空间大")
    assert "建议关注" in find_violations("建议关注该标的")
    assert "目标价" in find_violations("目标价100美元")


def test_catches_advice_verbs():
    hits = find_violations("建议买入，建议加仓")
    assert "建议买入" in hits
    assert "建议加仓" in hits


def test_catches_sourceless_phrasing():
    assert "据传" in find_violations("据传即将重组")
    assert "市场预期" in find_violations("市场预期下季大增")


def test_clean_text_no_violation():
    text = "你定的条件「服务收入同比转负」今天出现了对应事件。"
    assert find_violations(text) == []
    assert is_clean(text) is True


def test_guard_raises():
    with pytest.raises(RedlineViolation) as ei:
        guard("建议卖出该票")
    assert "建议卖出" in ei.value.violations


def test_guard_passes_clean():
    assert guard("条件未触发。") == "条件未触发。"


def test_extra_phrases_extend():
    pool = get_forbidden_phrases(extra=["自定义禁词"])
    assert "自定义禁词" in pool
    assert "看涨" in pool  # 默认仍在


def test_multiple_hits_deduped():
    hits = find_violations("看涨！看涨！建议买入！")
    assert hits.count("看涨") == 1
    assert "建议买入" in hits
