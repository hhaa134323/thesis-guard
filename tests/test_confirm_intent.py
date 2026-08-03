"""Phase 2：dialogue.py 已删（agent loop 的 LLM 自然对话，不再需要单独话术层）。
本文件原测 classify_confirm_intent / is_factual_fetchable（dialogue，已删）+ fetch_latest_filing；
现只保留 sec_edgar.fetch_latest_filing 测试（orchestrator.check_filing 工具的依赖，guardrail 层不动）。
"""
from __future__ import annotations

import types

from thesis_watch.fetchers import sec_edgar


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
