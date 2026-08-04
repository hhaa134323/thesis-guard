"""数据源抽象层单测（Stage 2 prep）：BaseFetcher / FetcherRegistry / SecFetcher。

锁 acceptance：
- from thesis_watch.fetchers.base import BaseFetcher, FetcherRegistry 能 import
- FetcherRegistry.get("sec") 返回 SEC fetcher 实例（SecFetcher，BaseFetcher subclass）
- SecFetcher.fetch 返回 list[dict]（空 = 查不到）；form_type 过滤生效；不传 = 任意表单最近一份
- register 拒绝非 BaseFetcher subclass；get 未注册名抛 KeyError
不触网：monkeypatch sec_edgar._ticker_to_cik_cache + requests（与 test_confirm_intent 同款）。
"""
from __future__ import annotations

import types

import pytest

from thesis_watch.fetchers import sec_edgar
from thesis_watch.fetchers.base import BaseFetcher, FetcherRegistry
from thesis_watch.fetchers.sec_edgar import SecFetcher


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


def _patch_sec(monkeypatch):
    """让 sec_edgar.fetch_latest_filing 不触网：CIK 走内存 map，requests 走 fake。"""
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"NVDA": "0001045810"})
    monkeypatch.setattr(sec_edgar, "requests",
                        types.SimpleNamespace(get=lambda url, headers, timeout: _FakeResp(_SUBMISSIONS)))


def test_base_fetcher_is_abstract():
    assert BaseFetcher.__abstractmethods__ == frozenset({"fetch"})
    with pytest.raises(TypeError):
        BaseFetcher()  # 抽象基类不可实例化


def test_registry_get_sec_returns_secfetcher_instance():
    fetcher = FetcherRegistry.get("sec")
    assert isinstance(fetcher, SecFetcher)
    assert isinstance(fetcher, BaseFetcher)
    assert fetcher.name == "sec"


def test_registry_get_unknown_name_raises_keyerror():
    with pytest.raises(KeyError):
        FetcherRegistry.get("nope-no-such-source")


def test_registry_register_rejects_non_subclass():
    with pytest.raises(TypeError):
        FetcherRegistry.register("bad", object)  # object 不是 BaseFetcher subclass


def test_secfetcher_fetch_no_form_type_returns_latest_any(monkeypatch):
    _patch_sec(monkeypatch)
    rows = FetcherRegistry.get("sec").fetch("NVDA")
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "NVDA"
    assert row["form_type"] == "10-K"            # 最近一份（2024-02-21）
    assert row["filed_at"] == "2024-02-21"
    assert "sec.gov/Archives/edgar/data" in row["url"]
    assert row["title"]


def test_secfetcher_fetch_form_type_filters(monkeypatch):
    _patch_sec(monkeypatch)
    rows = FetcherRegistry.get("sec").fetch("NVDA", form_type="10-Q")
    assert len(rows) == 1
    assert rows[0]["form_type"] == "10-Q"
    assert rows[0]["filed_at"] == "2023-11-08"


def test_secfetcher_fetch_form_type_no_match_returns_empty(monkeypatch):
    _patch_sec(monkeypatch)
    rows = FetcherRegistry.get("sec").fetch("NVDA", form_type="20-F")
    assert rows == []


def test_secfetcher_fetch_unknown_ticker_returns_empty(monkeypatch):
    # NOTICKER 不在 CIK map → 无 CIK → fetch_latest_filing 返 None → fetch 返 []
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"NVDA": "0001045810"})
    rows = FetcherRegistry.get("sec").fetch("NOTICKER")
    assert rows == []
