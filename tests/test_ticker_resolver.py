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


def test_ticker_token_in_chinese_sentence(offline_db):
    # 句中独立 ticker 词（后接全角逗号 = 分隔符，非 CJK 表意）→ 命中
    matches = ticker_resolver.resolve("我持有AAPL，看好服务收入")
    assert len(matches) == 1
    assert matches[0].ticker == "AAPL"


def test_cjk_glue_guard_rejects_fragment(offline_db):
    """「SK海力士」清出 ASCII "SK"，但 SK 紧贴 CJK 表意字「海」→ 守卫弃；
    清洗后 "sk" 仅 2 字符 < 3 → 不模糊。结果 [] → 调用方问用户，不猜 SKHCF。"""
    matches = ticker_resolver.resolve("我持有SK海力士")
    assert matches == []


def test_resolve_skhy_when_user_types_code(offline_db):
    # 用户被追问后回 SKHY → 精确命中（验收：得到 SKHY）
    matches = ticker_resolver.resolve("SKHY")
    assert len(matches) == 1
    assert matches[0].ticker == "SKHY"
    assert matches[0].cik == "0002120882"  # 2120882 零填充 10 位


def test_ticker_token_eos(offline_db):
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
