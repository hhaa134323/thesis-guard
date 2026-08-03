"""P1 confirm 阶段 intent 分流测试（无网络；fetch_latest_filing 走 monkeypatch）。"""
from __future__ import annotations

import types

from thesis_watch.fetchers import sec_edgar
from thesis_watch.dialogue import classify_confirm_intent, is_factual_fetchable


# --------------------------------------------------------------------------- #
# classify_confirm_intent
# --------------------------------------------------------------------------- #

def test_intent_confirm():
    assert classify_confirm_intent("对") == "confirm"
    assert classify_confirm_intent("没问题，入库") == "confirm"
    assert classify_confirm_intent("好的") == "confirm"
    assert classify_confirm_intent("") == "confirm"


def test_intent_modify():
    assert classify_confirm_intent("把 holding_reason 改成 看好 AI 算力") == "modify"
    assert classify_confirm_intent("改一下 ticker") == "modify"
    assert classify_confirm_intent("换成 SKHY") == "modify"


def test_intent_question():
    assert classify_confirm_intent("下次财报什么时候？") == "question"
    assert classify_confirm_intent("它是什么意思") == "question"
    assert classify_confirm_intent("这条假设对吗") == "question"


def test_intent_default_question_not_template():
    """无任何标记的文本默认 question（宁可应答也不套模板——修 P1「答非所问」核心）。"""
    assert classify_confirm_intent("随便一句话没有标记") == "question"


# --------------------------------------------------------------------------- #
# is_factual_fetchable
# --------------------------------------------------------------------------- #

def test_factual_fetchable_true():
    assert is_factual_fetchable("下次财报什么时候") is True
    assert is_factual_fetchable("最近一份 filing 是什么") is True
    assert is_factual_fetchable("它的 10-K 哪天交的") is True


def test_factual_fetchable_false():
    assert is_factual_fetchable("这条假设什么意思") is False
    assert is_factual_fetchable("我改一下") is False
    assert is_factual_fetchable("") is False


# --------------------------------------------------------------------------- #
# fetch_latest_filing（monkeypatch：CIK map + SEC submissions JSON）
# --------------------------------------------------------------------------- #

_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["10-K", "8-K", "10-Q"],
            "accessionNumber": ["0001045810-24-000001", "0001045810-24-000002", "0001045810-24-000003"],
            "filingDate": ["2024-02-21", "2024-01-15", "2023-11-08"],
            "primaryDocDescription": ["Annual report", "Item 2.02", "Quarterly report"],
        }
    }
}


class _FakeResp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


def test_fetch_latest_filing_ticker_not_in_map(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"NVDA": "0001045810"})
    # NOTICKER 不在 map → 无 CIK → None（不触网，不猜）
    assert sec_edgar.fetch_latest_filing("NOTICKER") is None


def test_fetch_latest_filing_picks_latest_financial(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"NVDA": "0001045810"})
    monkeypatch.setattr(sec_edgar, "requests",
                        types.SimpleNamespace(get=lambda url, headers, timeout: _FakeResp(_SUBMISSIONS)))
    f = sec_edgar.fetch_latest_filing("NVDA", form_types=["10-K", "10-Q"])
    assert f is not None
    assert f.ticker == "NVDA"
    assert f.form_type == "10-K"            # 10-K(2024-02-21) 比 10-Q(2023-11-08) 新
    assert f.filed_at.year == 2024
    assert "sec.gov/Archives/edgar/data" in f.url


def test_fetch_latest_filing_no_matching_form(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"NVDA": "0001045810"})
    monkeypatch.setattr(sec_edgar, "requests",
                        types.SimpleNamespace(get=lambda url, headers, timeout: _FakeResp(_SUBMISSIONS)))
    # 只要 20-F（NVDA 没有）→ None
    assert sec_edgar.fetch_latest_filing("NVDA", form_types=["20-F"]) is None
