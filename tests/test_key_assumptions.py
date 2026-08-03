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


# --------------------------------------------------------------------------- #
# P2 条件4（不可证伪）确定性 backstop —— entry_loop._apply_key_assumption_rejection
# 非自动核对的假设（其镜像必也非自动、无可判定阈值）→ 转 open_question，与菜单路径对齐。
# --------------------------------------------------------------------------- #
from thesis_watch.entry_loop import EntrySession
from thesis_watch.models import ThesisCard
from thesis_watch.models import Assumption as ModelAssumption


def _sess_with_assumptions(raw: str, assumptions: list[str]) -> EntrySession:
    """最小 session（不触 LLM/agent），card_draft 装给定假设，跑四关拒绝。"""
    sess = EntrySession(user_id="beta1", ticker="SKHY", cfg={})
    sess.ext = EntryExtraction(holding_reason_raw=raw)
    sess.card_draft = ThesisCard(
        user_id="beta1", ticker="SKHY", holding_reason_raw=raw,
        key_assumptions=[ModelAssumption(text=t) for t in assumptions])
    sess._apply_key_assumption_rejection()
    return sess


def test_condition4_rejects_market_share_assumption():
    """市占率类假设无 auto 镜像 → 条件4 不过 → 转 open_question。"""
    sess = _sess_with_assumptions("我持有SK海力士",
                                  ["HBM 市场份额维持第一，高于三星和美光"])
    assert sess.card_draft.key_assumptions == []
    reasons = " ".join(q["reason"] for q in sess.open_questions
                       if q["field"] == "key_assumptions")
    assert "条件4" in reasons
    assert "市占率" in reasons


def test_condition4_keeps_xbrl_assumption():
    """毛利率类假设有 auto 镜像（XBRL）→ 条件4 过 → 保留。"""
    sess = _sess_with_assumptions("我持有SK海力士",
                                  ["季度毛利率维持在高位（≥40%）"])
    assert len(sess.card_draft.key_assumptions) == 1
    assert sess.card_draft.key_assumptions[0].text == "季度毛利率维持在高位（≥40%）"


def test_condition3_still_rejects_paraphrase():
    """与原话高度相似 → 条件3 不过（先于条件4）→ 转 open_question。"""
    raw = "看好服务收入持续高增"
    sess = _sess_with_assumptions(raw, [raw])  # 完全相同
    assert sess.card_draft.key_assumptions == []
    reasons = " ".join(q["reason"] for q in sess.open_questions
                       if q["field"] == "key_assumptions")
    assert "条件3" in reasons


def test_sk_hynix_4_assumptions_only_gross_margin_kept():
    """目检复现：SK海力士 4 条假设，只有毛利率（XBRL）保留；ASP/份额/结构性 转 open_question（条件4）。"""
    raw = "我持有SK海力士，因为 HBM 存储周期"
    assumptions = [
        "AI算力持续扩张驱动HBM需求增长，使SK海力士HBM产品ASP（平均售价）不回落",
        "SK海力士在HBM技术上保持领先，HBM市场份额维持第一，高于三星和美光",
        "AI存储需求是结构性增长而非短期周期峰值，SK海力士不会重回2023式存储下行周期",
        "AI存储需求转化为实际财务业绩，SK海力士毛利率维持在高位（≥40%）",
    ]
    sess = _sess_with_assumptions(raw, assumptions)
    kept = [a.text for a in sess.card_draft.key_assumptions]
    assert len(kept) == 1
    assert "毛利率" in kept[0]
    c4 = [q for q in sess.open_questions
          if q["field"] == "key_assumptions" and "条件4" in q["reason"]]
    assert len(c4) == 3
