"""P2 key_assumptions 合格判定测试。

Section 1：is_paraphrase（条件 3 确定性 backstop）+ EntryExtraction.open_questions。
Section 2：condition_classify.is_v1_auto（条件 4 确定性 backstop）—— G3 已迁到
orchestrator._extract_card_impl（live demo + impl 隔离单测验过），此处离线测原语
（guardrail 层 condition_classify，不动）。
"""
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


# --------------------------------------------------------------------------- #
# 条件4（不可证伪）确定性 backstop —— condition_classify.is_v1_auto
# G3 组合（is_paraphrase + is_v1_auto）在 orchestrator._extract_card_impl，live demo 验过；
# 此处离线测原语：classify_condition + is_v1_auto。
# --------------------------------------------------------------------------- #

from thesis_watch.condition_classify import classify_condition, is_v1_auto


def test_condition4_rejects_market_share_assumption():
    """市占率类假设 → MARKET_SHARE 标签 → 非 v1-auto → 条件4 不过（转 open_question）。"""
    labels = classify_condition("HBM 市场份额维持第一，高于三星和美光")
    assert "market_share" in [l.value for l in labels]
    assert is_v1_auto(labels) is False


def test_condition4_keeps_xbrl_assumption():
    """毛利率类假设 → XBRL 标签 → v1-auto → 条件4 过（保留）。"""
    labels = classify_condition("季度毛利率维持在高位（≥40%）")
    assert is_v1_auto(labels) is True


def test_condition3_still_rejects_paraphrase():
    """与原话完全相同 → 条件3 不过（is_paraphrase=True）→ 转 open_question。"""
    raw = "看好服务收入持续高增"
    assert is_paraphrase(raw, raw) is True


def test_sk_hynix_4_assumptions_only_gross_margin_is_auto():
    """目检复现：4 条假设，只有毛利率（XBRL）is_v1_auto True；ASP/份额/结构性 非 auto。"""
    assumptions = [
        "AI算力持续扩张驱动HBM需求增长，使SK海力士HBM产品ASP（平均售价）不回落",
        "SK海力士在HBM技术上保持领先，HBM市场份额维持第一，高于三星和美光",
        "AI存储需求是结构性增长而非短期周期峰值，SK海力士不会重回2023式存储下行周期",
        "AI存储需求转化为实际财务业绩，SK海力士毛利率维持在高位（≥40%）",
    ]
    auto_flags = [is_v1_auto(classify_condition(a)) for a in assumptions]
    assert sum(auto_flags) == 1
    assert auto_flags[3] is True  # 只有毛利率 auto
