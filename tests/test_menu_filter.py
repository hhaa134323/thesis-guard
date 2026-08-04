"""P4 估值锚/破条件候选可执行性过滤测试（condition_classify 驱动，无网络）。"""
from __future__ import annotations

from thesis_watch.orchestrator import MenuMirror, filter_executable_mirrors


def _m(text: str) -> MenuMirror:
    return MenuMirror(assumption="a", mirror_text=text,
                      threshold={"x": 1}, source_type="sec_filing_field")


def test_filter_keeps_xbrl_structured():
    kept, excluded = filter_executable_mirrors([_m("服务收入同比转负")])
    assert len(kept) == 1 and len(excluded) == 0


def test_filter_excludes_cross_entity():
    """跨标的取数（GOOGL/META 的 capex）→ v1 不支持 → 不呈现（PRD §4-A 显式排除）。"""
    kept, excluded = filter_executable_mirrors([_m("英伟达客户 capex 指引下调（GOOGL/META 资本开支）")])
    assert len(kept) == 0 and len(excluded) == 1
    assert any("跨主体" in r for r in excluded[0]["reasons"])


def test_filter_excludes_third_party_paid_data():
    """TrendForce 付费/第三方行业数据 → 违反数据源约束 → 排除。"""
    kept, excluded = filter_executable_mirrors([_m("行业出货量下降（TrendForce 第三方数据）")])
    assert len(excluded) == 1 and len(kept) == 0
    assert any("第三方" in r for r in excluded[0]["reasons"])


def test_filter_excludes_price_pattern():
    """价格图形型 → v1 不接行情 → 排除。"""
    kept, excluded = filter_executable_mirrors([_m("跌破60日均线")])
    assert len(excluded) == 1 and len(kept) == 0


def test_filter_mixed_keeps_auto_only():
    mirrors = [_m("服务收入同比转负"), _m("跌破60日均线"), _m("GOOGL 的 capex 下滑")]
    kept, excluded = filter_executable_mirrors(mirrors)
    assert len(kept) == 1                      # 只留 xbrl 的
    assert len(excluded) == 2
    assert kept[0].mirror_text == "服务收入同比转负"
