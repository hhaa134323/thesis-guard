"""check_agent impl 隔离单测（Phase 5：agent-loop 行为测试）。

测三态映射 + E1-E8 兜底分支：fetch 失败（E1）/ agent 跳过 fetch（E7）/ 无 filings
（全 untriggered）/ 未提交判决（E7）/ 正常逐条判决 / redline 命中（E8）/ evidence
回放不过（E3）/ 缺 cond 判决（E4）。Runner.run_sync monkeypatch 注入，不触网、不调 LLM。
"""
from __future__ import annotations

import datetime
import types

from thesis_watch import check_agent
from thesis_watch.check_agent import (
    CheckCtx,
    CondVerdict,
    _map_status,
    _verdict_from_dict,
    run_check,
)
from thesis_watch.fetchers.sec_edgar import FilingEvent
from thesis_watch.models import (
    BrokenCondition,
    CheckResult,
    CondStatus,
    ConditionLayer,
    Confirmation,
    FilerType,
    ThesisCard,
)
from thesis_watch.store import ThesisStore


# --------------------------------------------------------------------------- #
# 纯函数：_map_status / _verdict_from_dict
# --------------------------------------------------------------------------- #

def test_map_status_triggered():
    assert _map_status("triggered").value == "triggered"
    assert _map_status("TRIGGERED").value == "triggered"


def test_map_status_watch():
    assert _map_status("watch").value == "watch"
    assert _map_status("WATCH now").value == "watch"


def test_map_status_untriggered_and_unknown_defaults_untriggered():
    assert _map_status("untriggered").value == "untriggered"
    assert _map_status("").value == "untriggered"
    assert _map_status("nonsense").value == "untriggered"


def test_map_status_untriggered_not_confused_with_triggered():
    """untriggered 含 triggered 子串但不应判 triggered。"""
    assert _map_status("untriggered").value == "untriggered"


def test_verdict_from_dict_fields():
    v = _verdict_from_dict({"cond_id": "c1", "status": "triggered",
                            "evidence_url": "http://x", "evidence_excerpt": "ex",
                            "reasoning": "因为...", "change": "escalated"})
    assert isinstance(v, CondVerdict)
    assert v.cond_id == "c1"
    assert v.status == "triggered"
    assert v.evidence_url == "http://x"
    assert v.evidence_excerpt == "ex"
    assert v.change == "escalated"


def test_verdict_from_dict_missing_fields_safe():
    v = _verdict_from_dict({})
    assert v.cond_id == ""
    assert v.status == ""
    assert v.evidence_url == ""
    assert v.change == ""


# --------------------------------------------------------------------------- #
# run_check E1-E8 分支（mock Runner.run_sync 注入 ctx 状态）
# --------------------------------------------------------------------------- #

def _card(conds=("c1", "c2", "c3")):
    broken = [BrokenCondition(id=c, layer=ConditionLayer.MIRROR, text=f"cond {c}",
                              threshold={"metric": "x", "operator": "<", "value": 0},
                              source_type="sec_filing_field") for c in conds]
    return ThesisCard(user_id="beta1", ticker="MCO", filer_type=FilerType.DOMESTIC_10K,
                     holding_reason_raw="看好穆迪", key_assumptions=[],
                     broken_conditions=broken,
                     confirmation=Confirmation(paraphrased=True, confirmed_by_user=True))


def _filing():
    return FilingEvent(ticker="MCO", form_type="10-Q", item=None, title="10-Q 季报",
                       url="http://sec.gov/x", filed_at=datetime.datetime.now(datetime.timezone.utc))


class _FakeResult:
    final_output = None  # submit_verdicts 设计下 run_check 不读 final_output，只读 ctx


def _fake_runner(*, fetch_called=True, fetched_filings=None, fetch_error=None,
                 verdicts_submitted=None, raises=None):
    def run_sync(agent, user_input, *, context=None, max_turns=6):
        if raises is not None:
            raise raises
        context.fetch_called = fetch_called
        context.fetched_filings = list(fetched_filings or [])
        context.fetch_error = fetch_error
        context.verdicts_submitted = list(verdicts_submitted or [])
        return _FakeResult()
    return types.SimpleNamespace(run_sync=run_sync)


def _run(card, monkeypatch, *, fetcher=None, cfg=None, prev=None, **fake_kwargs):
    monkeypatch.setattr(check_agent, "Runner", _fake_runner(**fake_kwargs))
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    if prev:  # 预置上次 CheckResult（每 cond 一条），测「较上次」change + 无新 filing 短路
        for cid, st in prev.items():
            store.save_check_result(CheckResult(card_id=card.card_id, cond_id=cid,
                                                status=st, checked_at="2026-08-01T00:00:00Z"))
    # 传 dummy agent → run_check 不 build_check_agent（避 SystemExit / 不触网不调 LLM）
    return run_check(card, cfg or {}, store, lookback_hours=72, fetcher=fetcher,
                     agent=object(), log=lambda *_: None)


def test_e1_fetch_error_all_watch(monkeypatch):
    card = _card()
    r = _run(card, monkeypatch, fetch_error="E1_FETCH_FAIL: timeout")
    assert r["n_watch"] == 3 and r["n_triggered"] == 0 and r["n_untriggered"] == 0
    assert r["filings_count"] == 0
    assert r["errors"] == ["E1_FETCH_FAIL"]


def test_e7_agent_skipped_fetch_all_watch(monkeypatch):
    """agent 没调 fetch_recent_filings（DeepSeek 跳过工具）→ E7。"""
    card = _card()
    r = _run(card, monkeypatch, fetch_called=False, fetched_filings=[], verdicts_submitted=[])
    assert r["errors"] == ["E7_SCHEMA"]
    assert r["n_watch"] == 3


def test_no_filings_all_untriggered(monkeypatch):
    """首次（无上次结果）+ 窗口内无 filings → 全 untriggered（PRD「无事那行不许空」；
    有上次结果时改保持上次状态，见 test_no_filings_with_prev_keeps_status_unchanged）。"""
    card = _card()
    r = _run(card, monkeypatch, fetch_called=True, fetched_filings=[], verdicts_submitted=[])
    assert r["n_untriggered"] == 3 and r["n_watch"] == 0
    assert r["errors"] == []
    assert r["filings_count"] == 0
    assert r["changes"] == {}


def test_e7_no_verdicts_submitted(monkeypatch):
    """fetch 了 filings 但 agent 没调 submit_verdicts → E7。"""
    card = _card()
    r = _run(card, monkeypatch, fetch_called=True, fetched_filings=[_filing()],
             verdicts_submitted=[])
    assert r["errors"] == ["E7_SCHEMA"]
    assert r["n_watch"] == 3
    assert r["filings_count"] == 1


def test_normal_all_untriggered_verdicts(monkeypatch):
    card = _card()
    verdicts = [{"cond_id": "c1", "status": "untriggered", "evidence_url": "", "reasoning": "无相关"},
                {"cond_id": "c2", "status": "untriggered", "evidence_url": "", "reasoning": "无相关"},
                {"cond_id": "c3", "status": "untriggered", "evidence_url": "", "reasoning": "无相关"}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()], verdicts_submitted=verdicts)
    assert r["n_untriggered"] == 3 and r["n_triggered"] == 0 and r["n_watch"] == 0
    assert r["errors"] == []
    assert r["filings_count"] == 1


def test_e8_redline_in_reasoning_downgrades_cond(monkeypatch):
    """判决 reasoning 踩红线（建议买入）→ 该 cond 降 watch + E8_RENDER_BLOCK。"""
    card = _card()
    verdicts = [{"cond_id": "c1", "status": "triggered", "evidence_url": "",
                 "reasoning": "建议买入穆迪"},
                {"cond_id": "c2", "status": "untriggered", "reasoning": "无"},
                {"cond_id": "c3", "status": "untriggered", "reasoning": "无"}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()], verdicts_submitted=verdicts)
    assert r["n_watch"] == 1 and r["n_untriggered"] == 2
    assert "E8_RENDER_BLOCK" in r["errors"]


def test_e3_evidence_self_check_fail_downgrades_triggered(monkeypatch):
    """triggered + evidence_url，但 excerpt 不在 fetched body → 降 watch + E3。"""
    card = _card()
    verdicts = [{"cond_id": "c1", "status": "triggered",
                 "evidence_url": "http://sec.gov/x", "evidence_excerpt": "MISSING",
                 "reasoning": "命中"},
                {"cond_id": "c2", "status": "untriggered", "reasoning": "无"},
                {"cond_id": "c3", "status": "untriggered", "reasoning": "无"}]
    # fetcher 返不含 excerpt 的 body → self_check 不过
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body without the excerpt")
    assert r["n_watch"] == 1 and r["n_untriggered"] == 2
    assert any("E3" in e for e in r["errors"])


def test_triggered_evidence_self_check_pass_stays_triggered(monkeypatch):
    """triggered + evidence_url + excerpt 在 body → 保持 triggered。"""
    card = _card()
    verdicts = [{"cond_id": "c1", "status": "triggered",
                 "evidence_url": "http://sec.gov/x", "evidence_excerpt": "EXCERPT",
                 "reasoning": "命中"},
                {"cond_id": "c2", "status": "untriggered", "reasoning": "无"},
                {"cond_id": "c3", "status": "untriggered", "reasoning": "无"}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body with EXCERPT inside")
    assert r["n_triggered"] == 1
    assert r["errors"] == []


def test_e4_missing_cond_verdict_to_watch(monkeypatch):
    """submit_verdicts 缺某 cond 判决 → 该 cond watch + E4_AMBIGUOUS。"""
    card = _card(("c1", "c2", "c3"))
    verdicts = [{"cond_id": "c1", "status": "untriggered", "reasoning": "无"},
                {"cond_id": "c2", "status": "untriggered", "reasoning": "无"}]  # 缺 c3
    r = _run(card, monkeypatch, fetched_filings=[_filing()], verdicts_submitted=verdicts)
    assert r["n_untriggered"] == 2 and r["n_watch"] == 1
    assert "E4_AMBIGUOUS" in r["errors"]


def test_e6_429_no_retry_fast(monkeypatch):
    """Runner.run_sync 抛 429 + max_retries_429=0 → 立即 E6（不退避，快测）。"""
    card = _card()
    r = _run(card, monkeypatch, raises=Exception("HTTP 429 rate limit exceeded"),
             cfg={"llm": {"max_retries_429": 0}})
    assert r["errors"] == ["E6_RATE_LIMIT"]
    assert r["n_watch"] == 3


# --------------------------------------------------------------------------- #
# run_check 较上次 change（Stage 2 任务 5 agent 方案：agent 读 previous_verdicts
# 自判 change，code 原样收集；非 watch transition / 降级 → 不列）
# --------------------------------------------------------------------------- #

def test_change_new_first_watch(monkeypatch):
    """首次检查（无上次结果）+ watch + agent 标 new → change=new。"""
    card = _card(("c1",))
    verdicts = [{"cond_id": "c1", "status": "watch", "evidence_url": "http://sec.gov/x",
                 "evidence_excerpt": "EXCERPT", "reasoning": "命中", "change": "new"}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body with EXCERPT")
    assert r["changes"]["c1"]["change"] == "new"
    assert r["changes"]["c1"]["text"] == "cond c1"


def test_change_first_triggered_left_empty(monkeypatch):
    """从头就 triggered（无 watch 前史）→ change 留空 → 不列（非 watch transition）。"""
    card = _card(("c1",))
    verdicts = [{"cond_id": "c1", "status": "triggered",
                 "evidence_url": "http://sec.gov/x", "evidence_excerpt": "EXCERPT",
                 "reasoning": "命中", "change": ""}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body with EXCERPT")
    assert "c1" not in r["changes"]  # 空 change 不列


def test_change_with_prev_worsened(monkeypatch):
    """有上次结果（c1 watch）+ 这次仍 watch + agent 标 worsened → change=worsened。"""
    card = _card(("c1", "c2"))
    verdicts = [{"cond_id": "c1", "status": "watch", "evidence_url": "http://sec.gov/x",
                 "evidence_excerpt": "EXCERPT", "reasoning": "恶化", "change": "worsened"},
                {"cond_id": "c2", "status": "untriggered", "reasoning": "无", "change": ""}]
    r = _run(card, monkeypatch, prev={"c1": CondStatus.WATCH, "c2": CondStatus.UNTRIGGERED},
             fetched_filings=[_filing()], verdicts_submitted=verdicts,
             fetcher=lambda url: "body with EXCERPT")
    assert r["changes"]["c1"]["change"] == "worsened"
    assert "c2" not in r["changes"]  # c2 change="" 不列


def test_change_six_values_collected(monkeypatch):
    """change 的 6 种值（new/worsened/improved/unchanged/resolved/escalated）原样收集。
    纯 code 透传测试（prev 语义由 prompt 保证，code 不校验）——验证 code 把 agent 给的
    非空 change 原样写入 changes，不因值不同改写。"""
    card = _card(("c1", "c2", "c3", "c4", "c5", "c6"))
    mapping = {"c1": "new", "c2": "worsened", "c3": "improved",
               "c4": "unchanged", "c5": "resolved", "c6": "escalated"}
    verdicts = []
    for cid, ch in mapping.items():
        st = "triggered" if ch == "escalated" else ("untriggered" if ch == "resolved" else "watch")
        v = {"cond_id": cid, "status": st, "reasoning": "x", "change": ch}
        if st != "untriggered":
            v["evidence_url"] = "http://sec.gov/x"
            v["evidence_excerpt"] = "EXCERPT"
        verdicts.append(v)
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body with EXCERPT")
    for cid, ch in mapping.items():
        assert r["changes"][cid]["change"] == ch, f"{cid} expected {ch}"
        assert r["changes"][cid]["text"] == f"cond {cid}"


def test_change_empty_not_listed(monkeypatch):
    """agent 给空 change（非 transition）→ 不列；非空才列。"""
    card = _card(("c1", "c2"))
    verdicts = [{"cond_id": "c1", "status": "watch", "evidence_url": "http://sec.gov/x",
                 "evidence_excerpt": "EXCERPT", "reasoning": "命中", "change": "new"},
                {"cond_id": "c2", "status": "untriggered", "reasoning": "无", "change": ""}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body with EXCERPT")
    assert set(r["changes"].keys()) == {"c1"}


def test_change_skipped_on_e3_downgrade(monkeypatch):
    """triggered + change=escalated，但 evidence 回放不过（E3 降级 watch）→ change 不列
    （code 无法可靠判定降级后的 transition，留给下次 agent）。"""
    card = _card(("c1",))
    verdicts = [{"cond_id": "c1", "status": "triggered",
                 "evidence_url": "http://sec.gov/x", "evidence_excerpt": "MISSING",
                 "reasoning": "命中", "change": "escalated"}]
    r = _run(card, monkeypatch, fetched_filings=[_filing()],
             verdicts_submitted=verdicts, fetcher=lambda url: "body without the excerpt")
    assert r["n_watch"] == 1  # E3 降级
    assert r["changes"] == {}  # 降级 → change 不列


def test_no_filings_with_prev_keeps_status_unchanged(monkeypatch):
    """无新 filing + 上次 watch → 保持 watch + change=unchanged（不跑 agent 判决；
    「没有新 filing」≠「条件解除」）。上次 untriggered → 保持 untriggered，无 change。"""
    card = _card(("c1", "c2"))
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c1",
                                        status=CondStatus.WATCH, checked_at="2026-08-01T00:00:00Z"))
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c2",
                                        status=CondStatus.UNTRIGGERED, checked_at="2026-08-01T00:00:00Z"))
    monkeypatch.setattr(check_agent, "Runner", _fake_runner(fetch_called=True, fetched_filings=[]))
    r = run_check(card, {}, store, lookback_hours=72, agent=object(), log=lambda *_: None)
    assert r["changes"]["c1"]["change"] == "unchanged"
    assert r["n_watch"] == 1
    assert "c2" not in r["changes"]  # 上次 untriggered → 无 watch transition
    assert r["n_untriggered"] == 1
    # store 里 c1 仍 watch（保持上次状态，未被「无新 filing」降为 untriggered）
    latest = {cr.cond_id: cr for cr in store.list_check_results(card.card_id)}
    assert latest["c1"].status == CondStatus.WATCH
    assert latest["c2"].status == CondStatus.UNTRIGGERED


def test_no_filings_with_prev_triggered_kept(monkeypatch):
    """无新 filing + 上次 triggered → 保持 triggered（待用户 S4 收尾），无 change。"""
    card = _card(("c1",))
    store = ThesisStore(":memory:")
    store.seed_preset_users()
    store.save_check_result(CheckResult(card_id=card.card_id, cond_id="c1",
                                        status=CondStatus.TRIGGERED, checked_at="2026-08-01T00:00:00Z"))
    monkeypatch.setattr(check_agent, "Runner", _fake_runner(fetch_called=True, fetched_filings=[]))
    r = run_check(card, {}, store, lookback_hours=72, agent=object(), log=lambda *_: None)
    assert r["n_triggered"] == 1
    assert r["changes"] == {}  # triggered 保持，无 watch transition
    latest = {cr.cond_id: cr for cr in store.list_check_results(card.card_id)}
    assert latest["c1"].status == CondStatus.TRIGGERED
