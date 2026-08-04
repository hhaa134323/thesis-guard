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
                            "reasoning": "因为..."})
    assert isinstance(v, CondVerdict)
    assert v.cond_id == "c1"
    assert v.status == "triggered"
    assert v.evidence_url == "http://x"
    assert v.evidence_excerpt == "ex"


def test_verdict_from_dict_missing_fields_safe():
    v = _verdict_from_dict({})
    assert v.cond_id == ""
    assert v.status == ""
    assert v.evidence_url == ""


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


def _run(card, monkeypatch, *, fetcher=None, cfg=None, **fake_kwargs):
    monkeypatch.setattr(check_agent, "Runner", _fake_runner(**fake_kwargs))
    store = ThesisStore(":memory:")
    store.seed_preset_users()
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
    """fetch 调了但窗口内无 filings → 全 untriggered（PRD「无事那行不许空」）。"""
    card = _card()
    r = _run(card, monkeypatch, fetch_called=True, fetched_filings=[], verdicts_submitted=[])
    assert r["n_untriggered"] == 3 and r["n_watch"] == 0
    assert r["errors"] == []
    assert r["filings_count"] == 0


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
