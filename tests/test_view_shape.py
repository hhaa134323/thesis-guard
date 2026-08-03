"""F3 view 形状契约测试（menu.coverage / ticker_title / sources）——锁给前端的字段。"""
from __future__ import annotations

from thesis_watch.entry_loop import EntrySession, S_MENU
from thesis_watch.menu import MenuCandidates, MenuMirror


def test_view_ticker_title_and_sources_when_set():
    sess = EntrySession(user_id="beta1", ticker="SKHY", cfg={})
    sess._ticker_title = "SK HYNIX LTD"
    sess._sources = [{"form": "6-K", "date": "2024-08-23",
                      "url": "https://www.sec.gov/x", "note": "下次不预披露"}]
    v = sess._view(assistant="x")
    assert v["ticker_title"] == "SK HYNIX LTD"
    assert v["sources"] == [{"form": "6-K", "date": "2024-08-23",
                              "url": "https://www.sec.gov/x", "note": "下次不预披露"}]


def test_view_ticker_title_and_sources_default():
    """未 resolve / 未 SEC fetch → ticker_title=null, sources=[]。"""
    sess = EntrySession(user_id="beta1", ticker="X", cfg={})
    v = sess._view(assistant="x")
    assert v["ticker_title"] is None
    assert v["sources"] == []


def test_view_menu_coverage_shape():
    """F3：menu.coverage = {total, excluded, reasons, excluded_items}（仅 S_MENU）。"""
    sess = EntrySession(user_id="beta1", ticker="SKHY", cfg={})
    sess.stage = S_MENU
    sess.menu = MenuCandidates(
        candidate_assumptions=["毛利率维持高位"],
        candidate_mirrors=[MenuMirror(
            assumption="毛利率维持高位", mirror_text="毛利率跌破40%",
            threshold={"metric": "gm", "operator": "<", "value": 0.4},
            source_type="sec_filing_field")])
    sess._excluded_mirrors = [
        {"mirror_text": "HBM ASP 回落", "reasons": ["第三方行业数据 v1 不覆盖"]},
        {"mirror_text": "HBM 份额失去第一", "reasons": ["v1 无市占率数据源（data-sources ①）"]},
    ]
    v = sess._view(assistant="x")
    assert v["menu"] is not None
    cov = v["menu"]["coverage"]
    assert cov["total"] == 3          # 1 kept + 2 excluded
    assert cov["excluded"] == 2
    assert "第三方" in " ".join(cov["reasons"])
    assert len(cov["excluded_items"]) == 2
    assert cov["excluded_items"][0]["mirror_text"] == "HBM ASP 回落"
    assert cov["excluded_items"][0]["reasons"] == ["第三方行业数据 v1 不覆盖"]


def test_view_no_menu_when_not_menu_stage():
    """非 menu 态 → menu=null（coverage 不出现）。"""
    sess = EntrySession(user_id="beta1", ticker="X", cfg={})
    sess._excluded_mirrors = [{"mirror_text": "x", "reasons": ["y"]}]
    v = sess._view(assistant="x")
    assert v["menu"] is None
