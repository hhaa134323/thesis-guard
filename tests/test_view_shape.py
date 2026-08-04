"""F3 view 形状契约测试（Phase 2 重写：agent loop 委托后的 view shape）。

锁给前端的字段：stage / assistant / card / menu / open_questions / ticker /
ticker_title / sources / error / metrics / stored / card_id。
"""
from __future__ import annotations

from thesis_watch.entry_loop import EntrySession, S_MENU


def test_view_ticker_title_and_sources_when_set():
    sess = EntrySession(user_id="beta1", ticker="SKHY", cfg={})
    sess.ticker_title = "SK HYNIX LTD"
    sess.sources = [{"form": "6-K", "date": "2024-08-23",
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


def test_view_menu_shape_when_menu_stage():
    """S_MENU 态 + menu = generate_menu 输出 dict（含 coverage/excluded_mirrors）→ view.menu 透传。"""
    sess = EntrySession(user_id="beta1", ticker="SKHY", cfg={})
    sess.stage = S_MENU
    sess.menu = {
        "ok": True,
        "candidate_assumptions": ["毛利率维持高位"],
        "candidate_mirrors": [{"assumption": "毛利率维持高位", "mirror_text": "毛利率跌破40%",
                               "threshold": {"metric": "gm", "operator": "<", "value": 0.4},
                               "source_type": "sec_filing_field"}],
        "excluded_mirrors": [{"mirror_text": "HBM ASP 回落", "reasons": ["第三方行业数据 v1 不覆盖"]}],
        "coverage": "原本 2 个方向，1 个当前无法自动核对，已排除",
    }
    v = sess._view(assistant="x")
    assert v["menu"] is not None
    assert v["menu"]["candidate_assumptions"] == ["毛利率维持高位"]
    assert v["menu"]["excluded_mirrors"][0]["mirror_text"] == "HBM ASP 回落"


def test_view_no_menu_when_not_menu_stage():
    """非 S_MENU 态 → menu=null（不呈现）。"""
    sess = EntrySession(user_id="beta1", ticker="X", cfg={})
    sess.menu = {"ok": True, "candidate_assumptions": ["x"]}
    v = sess._view(assistant="x")
    assert v["menu"] is None


def test_view_stored_and_card_id_fields():
    """save_card 后 view 自带 stored + card_id（serve.py /confirm 不再 upsert）。"""
    sess = EntrySession(user_id="beta1", ticker="MCO", cfg={})
    sess.stored = True
    sess.card_id = "abc123"
    v = sess._view(assistant="已落库")
    assert v["stored"] is True
    assert v["card_id"] == "abc123"
