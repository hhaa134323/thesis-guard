"""ticker_resolver 确定性解析测试（离线，fixture 驱动，无网络）。

P0 验收：输入「我持有SK海力士」→ 不出 SKHCF（无 LLM），得到 [] → 问用户；
用户回 SKHY → 精确命中 SKHY。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from thesis_watch.fetchers import ticker_resolver


# SEC company_tickers.json 结构：{"0": {"cik_str","ticker","title"}, ...}
_FIXTURE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1067983, "ticker": "BRK.B", "title": "Berkshire Hathaway Inc"},
    "2": {"cik_str": 2120882, "ticker": "SKHY", "title": "SK HYNIX LTD"},
    "3": {"cik_str": 99999, "ticker": "SK", "title": "SK Test Corp"},
    "4": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
    "5": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    # Bug #1 回归：AI / HBM 是真实 SEC ticker，论据里出现不该被误当标的
    "6": {"cik_str": 1577526, "ticker": "AI", "title": "C3.ai, Inc."},
    "7": {"cik_str": 1322422, "ticker": "HBM", "title": "Hudbay Minerals Inc"},
}


@pytest.fixture()
def offline_db(tmp_path, monkeypatch):
    """把 resolver 指向本地 fixture 缓存，隔绝网络。"""
    cache = tmp_path / "company_tickers.json"
    cache.write_text(json.dumps(_FIXTURE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("THESIS_TICKER_CACHE", str(cache))
    ticker_resolver.reset()
    yield
    ticker_resolver.reset()


def test_exact_whole_ticker(offline_db):
    matches = ticker_resolver.resolve("AAPL")
    assert len(matches) == 1
    assert matches[0].ticker == "AAPL"
    assert matches[0].title == "Apple Inc."
    assert matches[0].cik == "0000320193"  # 320193 零填充 10 位


def test_exact_whole_ticker_with_dot(offline_db):
    matches = ticker_resolver.resolve("BRK.B")
    assert len(matches) == 1
    assert matches[0].ticker == "BRK.B"
    assert matches[0].cik == "0001067983"


def test_in_sentence_ticker_not_auto_resolved(offline_db):
    """Bug #1 修复后：不做句中 ticker 词扫描（论据英文词凑巧匹配真 ticker 会误命中）。
    「我持有AAPL，看好」→ [] → 调用方问用户要代码；用户回 AAPL → 整串精确命中。"""
    matches = ticker_resolver.resolve("我持有AAPL，看好服务收入")
    assert matches == []


def test_thesis_text_english_words_not_mistaken_as_tickers(offline_db):
    """Bug #1 回归：论据里的 AI / HBM 凑巧是真实 SEC ticker，但句中词扫描已去 → 不误命中。
    「我持有SK海力士，因为 AI 算力扩张驱动 HBM 需求增长」→ []（不出 AI/HBM）。"""
    matches = ticker_resolver.resolve("我持有SK海力士，因为 AI 算力扩张驱动 HBM 需求增长")
    assert matches == []


def test_chinese_company_in_sentence_returns_empty(offline_db):
    """中文公司名「SK海力士」查不到 SEC 英文 title → [] → 调用方问用户要代码，不猜 SKHCF。"""
    matches = ticker_resolver.resolve("我持有SK海力士")
    assert matches == []


def test_resolve_skhy_when_user_types_code(offline_db):
    # 用户被追问后回 SKHY → 精确命中（验收：得到 SKHY）
    matches = ticker_resolver.resolve("SKHY")
    assert len(matches) == 1
    assert matches[0].ticker == "SKHY"
    assert matches[0].cik == "0002120882"  # 2120882 零填充 10 位


def test_ticker_in_sentence_resolved_via_fuzzy(offline_db):
    """「我持有SKHY」整串非精确、不做句中扫描，但 fuzzy「skhy」命中「SK HYNIX LTD」（ratio≥0.5）→ [SKHY]。
    句中打了 ticker、fuzzy 解析出来——正确（区别于 Bug #1 论据词 AI/HBM 误命中，那俩 fuzzy 不命中）。"""
    matches = ticker_resolver.resolve("我持有SKHY")
    assert len(matches) == 1
    assert matches[0].ticker == "SKHY"


def test_fuzzy_company_name_english(offline_db):
    matches = ticker_resolver.resolve("Apple")
    assert len(matches) >= 1
    assert matches[0].ticker == "AAPL"


def test_fuzzy_company_name_in_sentence(offline_db):
    # 「我持有Apple，看好」清出 "apple" → 子串命中 Apple Inc.
    matches = ticker_resolver.resolve("我持有Apple，看好")
    assert len(matches) >= 1
    assert matches[0].ticker == "AAPL"


def test_no_match_returns_empty(offline_db):
    assert ticker_resolver.resolve("不存在的XYZQQ公司") == []


def test_empty_query_returns_empty(offline_db):
    assert ticker_resolver.resolve("") == []
    assert ticker_resolver.resolve("   ") == []
