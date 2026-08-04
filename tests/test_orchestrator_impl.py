"""orchestrator impl 隔离单测（Phase 5：agent-loop 行为测试）。

测 _extract_card_impl（G3：is_paraphrase 条件3 + is_v1_auto 条件4 + make_mirror P3 + R1-R3）
与 _save_card_impl（G1 必填 + G4 用户确认 + G2 安全边际完整 + R1-R3）——两者是 orchestrator
extract_card / save_card 工具的纯逻辑实现，live demo 已验过，此处离线单测锁行为。
LLM 调用（_run_extract）monkeypatch 注入，不触网、不依赖模型。
"""
from __future__ import annotations

import pytest

from thesis_watch import orchestrator
from thesis_watch.orchestrator import _extract_card_impl, _save_card_impl
from thesis_watch.redline import RedlineViolation
from thesis_watch.schema import (
    Assumption,
    EntryExtraction,
    ManualCheckItem,
    MirrorSpec,
)
from thesis_watch.store import ThesisStore


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _ext(holding="看好穆迪评级业务牌照壁垒",
         assumptions=(),
         mirrors=(),
         manual=()):
    """构造 EntryExtraction（schema 契约，即 _run_extract 返回的 extraction）。"""
    return EntryExtraction(
        holding_reason_raw=holding,
        key_assumptions=[Assumption(text=t) for t in assumptions],
        mirrors=[MirrorSpec(assumption_text=a, mirror_text=m, threshold=t_, source_type=s)
                 for (a, m, t_, s) in mirrors],
        manual_items=[ManualCheckItem(text=x) for x in manual],
    )


def _patch_extract(monkeypatch, ext: EntryExtraction):
    """让 orchestrator._run_extract 不触网，返固定 extraction。"""
    monkeypatch.setattr(orchestrator, "_run_extract",
                        lambda agent, text, cfg: {"ok": True, "extraction": ext})


def _patch_store(monkeypatch) -> ThesisStore:
    """save_card 落 :memory: store，不污染真实 data/thesis.db（R9）。"""
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    monkeypatch.setattr(orchestrator, "_get_store", lambda: store)
    return store


_XBRL_ASSUMPTION = "季度毛利率维持在高位（≥40%）"      # is_v1_auto True
_MARKETSHARE_ASSUMPTION = "HBM 市场份额维持第一，高于三星和美光"  # is_v1_auto False
_PARAPHRASE_ASSUMPTION = "看好穆迪评级业务牌照壁垒"   # 与 holding 原话相同 → is_paraphrase True
_VALID_MIRROR = (_XBRL_ASSUMPTION, "毛利率跌破40%",
                 {"metric": "gross_margin", "operator": "<", "value": 40},
                 "sec_filing_field")


# --------------------------------------------------------------------------- #
# _extract_card_impl — G3 key_assumptions 质量（条件3 同义复述 / 条件4 不可证伪）
# --------------------------------------------------------------------------- #

def test_extract_keeps_xbrl_assumption_with_valid_mirror(monkeypatch):
    """合格假设（非复述 + v1-auto）+ 完整 mirror → 进 key_assumptions + mirrors。"""
    _patch_extract(monkeypatch, _ext(assumptions=(_XBRL_ASSUMPTION,), mirrors=(_VALID_MIRROR,)))
    out = _extract_card_impl("看好穆迪评级业务", "MCO")
    assert out["ok"] is True
    assert any(_XBRL_ASSUMPTION in a["text"] for a in out["key_assumptions"])
    assert len(out["mirrors"]) == 1
    assert out["mirrors"][0]["mirror_text"] == "毛利率跌破40%"
    # 合格的不进 open_questions
    assert not any(_XBRL_ASSUMPTION in o.get("text", "") for o in out["open_questions"])


def test_extract_rejects_paraphrase_assumption_to_open_questions(monkeypatch):
    """条件3：候选假设 = 原话同义复述 → 转 open_question（不进 key_assumptions）。"""
    _patch_extract(monkeypatch, _ext(assumptions=(_PARAPHRASE_ASSUMPTION,), mirrors=()))
    out = _extract_card_impl(_PARAPHRASE_ASSUMPTION, "MCO")
    assert out["ok"] is True
    assert out["key_assumptions"] == []
    oq = [o for o in out["open_questions"] if o["text"] == _PARAPHRASE_ASSUMPTION]
    assert oq and "条件3" in oq[0]["reason"]


def test_extract_rejects_non_auto_assumption_to_open_questions(monkeypatch):
    """条件4：市占率类假设（非 v1-auto / 不可证伪）→ 转 open_question。"""
    _patch_extract(monkeypatch, _ext(assumptions=(_MARKETSHARE_ASSUMPTION,), mirrors=()))
    out = _extract_card_impl("看好份额领先", "MCO")
    assert out["ok"] is True
    assert out["key_assumptions"] == []
    oq = [o for o in out["open_questions"] if o["text"] == _MARKETSHARE_ASSUMPTION]
    assert oq and "条件4" in oq[0]["reason"]


def test_extract_rejects_mirror_missing_threshold_to_open_questions(monkeypatch):
    """P3：mirror 缺 threshold → make_mirror None → 转 open_question（不进 mirrors）。"""
    mirror_no_thresh = ("切换成本锁定客户", "服务收入同比转负", None, "sec_filing_field")
    _patch_extract(monkeypatch, _ext(assumptions=(_XBRL_ASSUMPTION,), mirrors=(mirror_no_thresh,)))
    out = _extract_card_impl("看好穆迪", "MCO")
    assert out["ok"] is True
    assert out["mirrors"] == []
    oq = [o for o in out["open_questions"] if o["field"] == "mirrors"]
    assert oq and "P3" in oq[0]["reason"]


def test_extract_rejects_mirror_whose_assumption_was_rejected(monkeypatch):
    """对应假设被拒（条件3/4）→ 镜像无立足点 → 转 open_question。"""
    # paraphrase 假设会被拒；其 mirror 即使 threshold 齐全也不留
    mirror_of_rejected = (_PARAPHRASE_ASSUMPTION, "服务收入同比转负",
                          {"metric": "x", "operator": "<", "value": 0}, "sec_filing_field")
    _patch_extract(monkeypatch, _ext(assumptions=(_PARAPHRASE_ASSUMPTION,),
                                     mirrors=(mirror_of_rejected,)))
    out = _extract_card_impl(_PARAPHRASE_ASSUMPTION, "MCO")
    assert out["ok"] is True
    assert out["mirrors"] == []
    oq = [o for o in out["open_questions"] if o["field"] == "mirrors"]
    assert oq and "对应假设被拒" in oq[0]["reason"]


def test_extract_redline_in_mirror_text_raises(monkeypatch):
    """R1-R3：抽出的 mirror 文本踩红线（建议关注）→ 抛 RedlineViolation，由 SDK 传回 LLM。"""
    dirty_mirror = (_XBRL_ASSUMPTION, "建议关注收入转负",
                    {"metric": "x", "operator": "<", "value": 0}, "sec_filing_field")
    _patch_extract(monkeypatch, _ext(assumptions=(_XBRL_ASSUMPTION,), mirrors=(dirty_mirror,)))
    with pytest.raises(RedlineViolation):
        _extract_card_impl("看好穆迪", "MCO")


def test_extract_extraction_failed_returns_friendly_error(monkeypatch):
    """LLM 抽取失败（ok=False / extraction=None）→ 返友好错误，不把 ValidationError 甩用户。"""
    monkeypatch.setattr(orchestrator, "_run_extract",
                        lambda agent, text, cfg: {"ok": False, "extraction": None})
    out = _extract_card_impl("看好穆迪", "MCO")
    assert out["ok"] is False
    assert out["error"] == "extraction_failed"
    assert out["raw_text"] == "看好穆迪"


# --------------------------------------------------------------------------- #
# _save_card_impl — G1 必填 / G4 用户确认 / G2 安全边际完整 / R1-R3 / happy path
# --------------------------------------------------------------------------- #

def _save_args(**overrides):
    base = dict(
        ticker="MCO",
        holding_reason_raw="看好穆迪评级业务牌照壁垒",
        key_assumptions=[{"text": "切换成本锁定客户，竞品难蚕食份额", "judgeable": True}],
        mirrors=[{"assumption_text": "切换成本锁定客户", "mirror_text": "服务收入同比转负",
                  "threshold": {"metric": "rev_yoy", "operator": "<", "value": 0},
                  "source_type": "sec_filing_field"}],
        entry_anchor={"anchor_type": "ttm_gaap_pe", "anchor_value": 25, "note": "25x"},
        holding_horizon="long",
        confirmed_by_user=True,
    )
    base.update(overrides)
    return base


def test_save_happy_path_persists_card(monkeypatch):
    store = _patch_store(monkeypatch)
    out = _save_card_impl(**_save_args())
    assert out["saved"] is True
    assert out["ticker"] == "MCO"
    assert out["card_id"]
    card = store.get_card(out["card_id"])
    assert card is not None
    assert card.confirmation.confirmed_by_user is True
    assert card.holding_horizon == "long"


def test_save_g1_rejects_missing_required_field(monkeypatch):
    _patch_store(monkeypatch)
    # mirrors 为空 → 必填缺失
    with pytest.raises(ValueError, match="必填字段缺失"):
        _save_card_impl(**_save_args(mirrors=[]))


def test_save_g1_rejects_missing_entry_anchor(monkeypatch):
    _patch_store(monkeypatch)
    with pytest.raises(ValueError, match="必填字段缺失"):
        _save_card_impl(**_save_args(entry_anchor=None))


def test_save_g4_rejects_unconfirmed(monkeypatch):
    _patch_store(monkeypatch)
    with pytest.raises(ValueError, match="用户未明确确认"):
        _save_card_impl(**_save_args(confirmed_by_user=False))


def test_save_g2_rejects_incomplete_anchor_no_type(monkeypatch):
    _patch_store(monkeypatch)
    # 缺 anchor_type + 无 value/note → 安全边际不完整
    with pytest.raises(ValueError, match="安全边际不完整"):
        _save_card_impl(**_save_args(entry_anchor={"anchor_type": "", "note": ""}))


def test_save_g2_rejects_anchor_missing_value_and_note(monkeypatch):
    _patch_store(monkeypatch)
    # 有 anchor_type 但无 value 无 note → 不完整
    with pytest.raises(ValueError, match="安全边际不完整"):
        _save_card_impl(**_save_args(entry_anchor={"anchor_type": "ttm_gaap_pe",
                                                   "anchor_value": None, "note": ""}))


def test_save_rejects_invalid_horizon(monkeypatch):
    _patch_store(monkeypatch)
    with pytest.raises(ValueError, match="holding_horizon"):
        _save_card_impl(**_save_args(holding_horizon="forever"))


def test_save_redline_in_text_raises(monkeypatch):
    _patch_store(monkeypatch)
    with pytest.raises(RedlineViolation):
        _save_card_impl(**_save_args(holding_reason_raw="建议买入穆迪，评级壁垒强"))


def test_save_redline_in_assumption_raises(monkeypatch):
    _patch_store(monkeypatch)
    with pytest.raises(RedlineViolation):
        _save_card_impl(**_save_args(
            key_assumptions=[{"text": "看涨穆迪评级业务", "judgeable": True}]))
