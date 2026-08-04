"""SEC filing history tool 单测（Stage 2 窗口 A-2）。

锁 acceptance：
- fetch_filing_history 取多条 SEC filing，按 filed_at 倒序，取前 N 条（不限 lookback）
- form_type 过滤（精确匹配，与 check_filing 一致）
- count 限制（传 count=3 只返回 3 条）
- 空 / 异常 / 无 CIK → []（R5 不编造）
- SecFetcher.fetch_history 包装为 list[dict]（字段同 check_filing）
- orchestrator._fetch_filing_history_impl：count 钳到 [0,50]；{found,filings} / {found:false}
- agent tools 列表 6 个（含 fetch_filing_history）

不触网：monkeypatch sec_edgar._ticker_to_cik_cache + requests（与 test_confirm_intent 同款）。
"""
from __future__ import annotations

import types

import pytest

from thesis_watch import orchestrator
from thesis_watch.fetchers import sec_edgar
from thesis_watch.fetchers.base import FetcherRegistry
from thesis_watch.fetchers.sec_edgar import SecFetcher, fetch_filing_history


# submissions recent 数组；filingDate 故意打乱（非倒序）以验证 fetch_filing_history
# 按 filed_at 重排倒序，而非盲信 submissions recent 数组顺序。
_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["10-Q", "10-K", "8-K", "10-K", "10-Q", "10-K"],
            "accessionNumber": [
                "0001045810-23-000001", "0001045810-25-000002", "0001045810-24-000003",
                "0001045810-24-000004", "0001045810-23-000005", "0001045810-25-000006",
            ],
            "filingDate": [
                "2023-01-09", "2025-02-15", "2024-01-05",
                "2024-02-20", "2023-02-18", "2025-01-10",
            ],
            "primaryDocDescription": [
                "Quarterly report", "Annual report", "Item 2.02",
                "Annual report", "Quarterly report", "Annual report",
            ],
        }
    }
}

# 全量 6 条 + 10-K 3 条，按 filed_at 倒序（用于断言）
_ALL_DESC = ["2025-02-15", "2025-01-10", "2024-02-20", "2024-01-05", "2023-02-18", "2023-01-09"]
_10K_DESC = ["2025-02-15", "2025-01-10", "2024-02-20"]


class _FakeResp:
    def __init__(self, data): self._d = data
    def raise_for_status(self): pass
    def json(self): return self._d


class _RaiseResp:
    def raise_for_status(self): raise RuntimeError("network down")
    def json(self): raise RuntimeError("unreachable")


def _patch_sec(monkeypatch, submissions=None):
    """让 sec_edgar.fetch_filing_history 不触网：CIK 走内存 map，requests 走 fake。"""
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"MCO": "0001018724"})
    payload = submissions if submissions is not None else _SUBMISSIONS
    monkeypatch.setattr(sec_edgar, "requests",
                        types.SimpleNamespace(get=lambda url, headers, timeout: _FakeResp(payload)))


# --------------------------------------------------------------------------- #
# fetch_filing_history（fetcher 函数层）
# --------------------------------------------------------------------------- #

def test_fetch_filing_history_returns_multiple_sorted_desc(monkeypatch):
    _patch_sec(monkeypatch)
    events = fetch_filing_history("MCO", count=10)
    assert len(events) == 6
    assert [e.filed_at.date().isoformat() for e in events] == _ALL_DESC
    e0 = events[0]
    assert e0.ticker == "MCO"
    assert e0.form_type == "10-K"            # 2025-02-15 是 10-K
    assert "sec.gov/Archives/edgar/data" in e0.url
    assert e0.title                          # _build_title 非空


def test_fetch_filing_history_form_type_filter(monkeypatch):
    _patch_sec(monkeypatch)
    events = fetch_filing_history("MCO", form_type="10-K", count=10)
    assert len(events) == 3
    assert all(e.form_type == "10-K" for e in events)
    assert [e.filed_at.date().isoformat() for e in events] == _10K_DESC


def test_fetch_filing_history_count_limit(monkeypatch):
    _patch_sec(monkeypatch)
    events = fetch_filing_history("MCO", count=3)
    assert len(events) == 3
    assert [e.filed_at.date().isoformat() for e in events] == _ALL_DESC[:3]


def test_fetch_filing_history_form_type_and_count_combined(monkeypatch):
    _patch_sec(monkeypatch)
    events = fetch_filing_history("MCO", form_type="10-K", count=2)
    assert len(events) == 2
    assert [e.filed_at.date().isoformat() for e in events] == _10K_DESC[:2]


def test_fetch_filing_history_unknown_ticker_returns_empty(monkeypatch):
    _patch_sec(monkeypatch)
    assert fetch_filing_history("NOPE") == []


def test_fetch_filing_history_empty_ticker_returns_empty(monkeypatch):
    _patch_sec(monkeypatch)
    assert fetch_filing_history("") == []


def test_fetch_filing_history_count_zero_returns_empty(monkeypatch):
    _patch_sec(monkeypatch)
    assert fetch_filing_history("MCO", count=0) == []


def test_fetch_filing_history_count_negative_returns_empty(monkeypatch):
    _patch_sec(monkeypatch)
    assert fetch_filing_history("MCO", count=-1) == []


def test_fetch_filing_history_network_error_returns_empty(monkeypatch):
    monkeypatch.setattr(sec_edgar, "_ticker_to_cik_cache", {"MCO": "0001018724"})
    monkeypatch.setattr(sec_edgar, "requests",
                        types.SimpleNamespace(get=lambda url, headers, timeout: _RaiseResp()))
    assert fetch_filing_history("MCO") == []


def test_fetch_filing_history_empty_submissions_returns_empty(monkeypatch):
    _patch_sec(monkeypatch, submissions={"filings": {"recent": {}}})
    assert fetch_filing_history("MCO") == []


# --------------------------------------------------------------------------- #
# SecFetcher.fetch_history（数据源抽象层 method）
# --------------------------------------------------------------------------- #

def test_secfetcher_fetch_history_returns_dicts(monkeypatch):
    _patch_sec(monkeypatch)
    rows = SecFetcher().fetch_history("MCO", form_type="10-K", count=3)
    assert len(rows) == 3
    r0 = rows[0]
    assert set(r0.keys()) == {"ticker", "form_type", "filed_at", "url", "title"}
    assert r0["ticker"] == "MCO"
    assert r0["form_type"] == "10-K"
    assert r0["filed_at"] == "2025-02-15"


def test_secfetcher_fetch_history_empty_returns_empty(monkeypatch):
    _patch_sec(monkeypatch)
    fetcher = FetcherRegistry.get("sec")
    assert fetcher.fetch_history("NOTICKER") == []


# --------------------------------------------------------------------------- #
# orchestrator._fetch_filing_history_impl（工具纯逻辑：count 钳制 + {found,filings} 包装）
# --------------------------------------------------------------------------- #

def _patch_fetch_history(monkeypatch, rows, captures=None):
    """patch SecFetcher 单例的 fetch_history，不触网、可捕获传入的 count。"""
    def _fake(ticker, form_type=None, count=10):
        if captures is not None:
            captures.append(count)
        return list(rows)
    fetcher = FetcherRegistry.get("sec")
    monkeypatch.setattr(fetcher, "fetch_history", _fake)


def test_impl_wraps_rows_to_filings(monkeypatch):
    rows = [
        {"ticker": "MCO", "form_type": "10-K", "filed_at": "2025-02-15",
         "url": "https://www.sec.gov/Archives/edgar/data/1045810/a/index.htm",
         "title": "10-K 年报 · Annual report"},
        {"ticker": "MCO", "form_type": "10-K", "filed_at": "2024-02-20",
         "url": "https://www.sec.gov/Archives/edgar/data/1045810/b/index.htm",
         "title": "10-K 年报 · Annual report"},
    ]
    _patch_fetch_history(monkeypatch, rows)
    out = orchestrator._fetch_filing_history_impl("MCO", form_type="10-K", count=10)
    assert out["found"] is True
    assert len(out["filings"]) == 2
    assert set(out["filings"][0].keys()) == {"form_type", "filed_at", "url", "title"}
    assert out["filings"][0]["filed_at"] == "2025-02-15"


def test_impl_empty_returns_not_found(monkeypatch):
    _patch_fetch_history(monkeypatch, [])
    out = orchestrator._fetch_filing_history_impl("MCO")
    assert out == {"found": False}


def test_impl_clamps_count_to_50(monkeypatch):
    captures = []
    _patch_fetch_history(monkeypatch, [], captures=captures)
    out = orchestrator._fetch_filing_history_impl("MCO", count=999)
    assert out == {"found": False}
    assert captures == [50]


def test_impl_count_zero_clamps_to_zero(monkeypatch):
    captures = []
    _patch_fetch_history(monkeypatch, [], captures=captures)
    orchestrator._fetch_filing_history_impl("MCO", count=0)
    assert captures == [0]


# --------------------------------------------------------------------------- #
# agent tools 列表（6 个，含 fetch_filing_history）
# --------------------------------------------------------------------------- #

def test_agent_has_six_tools():
    names = [getattr(t, "name", None) for t in orchestrator.agent.tools]
    assert len(orchestrator.agent.tools) == 6
    assert "fetch_filing_history" in names


def test_build_thesis_guard_agent_has_six_tools():
    # cfg=None 且 model_name=None → 返回模块级单例 agent（不重建模型，不触网）
    a = orchestrator.build_thesis_guard_agent()
    names = [getattr(t, "name", None) for t in a.tools]
    assert len(a.tools) == 6
    assert "fetch_filing_history" in names
