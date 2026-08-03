"""P2 key_assumptions 合格判定测试（is_paraphrase 确定性 backstop + schema open_questions）。"""
from __future__ import annotations

from thesis_watch.conditions import is_paraphrase
from thesis_watch.schema import Assumption, EntryExtraction, OpenQuestion


# --------------------------------------------------------------------------- #
# is_paraphrase（条件 3 确定性 backstop：同义复述 → 不合格）
# --------------------------------------------------------------------------- #

def test_paraphrase_identical():
    raw = "看好服务收入持续高增"
    assert is_paraphrase("看好服务收入持续高增", raw) is True


def test_paraphrase_substring():
    raw = "看好服务收入持续高增"
    # 候选是原话的子串 → 高度相似 → 同义复述
    assert is_paraphrase("服务收入持续高增", raw) is True
    # 原话是候选的子串
    assert is_paraphrase("我看好服务收入持续高增，所以持有", raw) is True


def test_paraphrase_low_similarity_kept():
    raw = "看好服务收入持续高增"
    # 真假设：与原话不相似 → 合格（条件 3 过）
    assert is_paraphrase("切换成本锁定客户，竞品难蚕食份额", raw) is False
    assert is_paraphrase("监管收紧会压缩核心业务利润率", raw) is False


def test_paraphrase_empty():
    assert is_paraphrase("", "原话") is False
    assert is_paraphrase("候选", "") is False


# --------------------------------------------------------------------------- #
# EntryExtraction.open_questions（LLM 自判四关的拒出候选落点）
# --------------------------------------------------------------------------- #

def test_open_questions_default_empty():
    e = EntryExtraction(holding_reason_raw="看好服务收入")
    assert e.open_questions == []


def test_open_questions_roundtrip():
    e = EntryExtraction(
        holding_reason_raw="看好服务收入持续高增",
        key_assumptions=[Assumption(text="切换成本锁定客户")],
        open_questions=[OpenQuestion(field="key_assumptions",
                                     reason="违反条件1（估值口径）",
                                     text="估值用 P/E 25 倍")],
    )
    d = e.model_dump()
    assert d["key_assumptions"][0]["text"] == "切换成本锁定客户"
    assert d["open_questions"][0]["field"] == "key_assumptions"
    assert "条件1" in d["open_questions"][0]["reason"]
