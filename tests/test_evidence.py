"""证据引用自检契约测试（无网络，fetcher 注入）。"""
from __future__ import annotations

from thesis_watch.evidence import EvidenceCheckResult, self_check


def test_empty_url_is_E2():
    r = self_check("", "摘录")
    assert r.ok is False
    assert r.reason == "E2_NO_PRIMARY_SOURCE"


def test_empty_excerpt_is_E3():
    r = self_check("https://sec.gov/x", "")
    assert r.ok is False
    assert r.reason == "E3_EVIDENCE_MISMATCH"


def test_no_fetcher_skips_network_ok():
    r = self_check("https://sec.gov/x", "摘录")
    assert r.ok is True
    assert "skipped" in r.detail


def test_fake_fetcher_match_ok():
    body = "公司因合规问题被处以 1 亿美元罚款。"
    r = self_check("https://sec.gov/x", "1 亿美元罚款",
                  fetcher=lambda url: body)
    assert r.ok is True
    assert r.reason is None


def test_fake_fetcher_mismatch_E3():
    r = self_check("https://sec.gov/x", "不存在的摘录",
                  fetcher=lambda url: "完全不同的正文")
    assert r.ok is False
    assert r.reason == "E3_EVIDENCE_MISMATCH"


def test_fake_fetcher_raises_E1():
    def boom(url):
        raise RuntimeError("connection reset")
    r = self_check("https://sec.gov/x", "摘录", fetcher=boom)
    assert r.ok is False
    assert r.reason == "E1_FETCH_FAIL"


def test_fake_fetcher_none_E1():
    r = self_check("https://sec.gov/x", "摘录", fetcher=lambda url: None)
    assert r.ok is False
    assert r.reason == "E1_FETCH_FAIL"
