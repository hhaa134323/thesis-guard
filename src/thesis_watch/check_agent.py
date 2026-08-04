"""核对 Agent（§2.3）：逐卡逐条件核对 SEC filings → 三态 + 证据 + self_check + redline + E1-E8。

Phase 4 重构（agent loop）：旧架构 pydantic_ai 单次 output_type=CheckVerdicts + run_check
预取 filings 灌进 prompt → 新架构 OpenAI Agents SDK Agent loop：agent 自己调
fetch_recent_filings 工具取最近 SEC filings（复用现有 sec_edgar fetcher 作为 @function_tool），
再调 submit_verdicts 工具提交逐条三态判决（结构化输出走 tool call，与 orchestrator 的
save_card 同款——实测 DeepSeek V4-Flash + chat_completions 用 output_type 会短路成空 CheckVerdicts
而不先调 fetch，改走 submit_verdicts tool 才稳定）。模型走 DeepSeek V4-Flash（百炼
chat_completions，与 orchestrator 同款 OpenAIChatCompletionsModel + set_default_openai_api）。

输出格式不变：判决数据形 CondVerdict(cond_id/status/evidence_url/evidence_excerpt/reasoning)，
status ∈ triggered|watch|untriggered（**三态**，非仓位建议——R1/R2/R6 红线；HOLD/ADD/CUT/PASS
是作者个人 Notion 复查 skill v4，不是本产品模块，不混入）。run_all/run_check 公共签名 +
返回 shape 不变（notify.py 依赖）。不动 orchestrator.py / serve.py / 前端。

- evidence excerpt = SEC primaryDocDescription（原文片段），url = filings index；
- evidence_self_check 回放（default_fetcher 抓 index 页）验 excerpt 能定位 → 不过降 watch（E1/E3）；
- redline.guard 仅校验 LLM reasoning（系统输出），不校验 SEC 引用摘录（R1-R3 复用，per-verdict 粒度 E8）；
- E1-E8 落日志供 error analysis；CheckResult 存 store。
深读 filing 正文延后（v1 用 metadata，够命中红线 item 5.02/4.02 等）。

不替用户结论（R6）：只输出状态机三态 + 证据，triggered 须用户收尾（§S4）。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from agents import (
    Agent,
    Runner,
    RunContextWrapper,
    function_tool,
    set_default_openai_api,
)
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from . import redline
from .config import get_agent_model, get_llm_limits
from .evidence import default_fetcher, self_check as evidence_self_check
from .fetchers import sec_edgar
from .models import CheckResult, CondStatus, Evidence, ThesisCard
from .store import ThesisStore

# 百炼兼容端点用 chat_completions API（不支持 Responses API），SDK 须切默认（与 orchestrator 同）。
set_default_openai_api("chat_completions")

# agent loop 上限：fetch_recent_filings（1）+ submit_verdicts（1）+ DeepSeek 偶发多轮余量。
_MAX_TURNS = 6

CHECK_PROMPT = """你是持仓条件核对 Agent。给定一张 thesis 卡的破局条件，逐条判定每条条件的状态。

## 你有什么工具（必须按顺序调用）

1. fetch_recent_filings() — 拉本卡标的最近 SEC filings（按 filer_type 自动路由表单：外国发行人主渠道 6-K，本土 10-K/10-Q/8-K，ETF/基金 v1 不自动核对）。返回 {filings:[{form,item,title,url,filed_at}], count, error?}。
2. submit_verdicts(verdicts) — 提交逐条判决。verdicts 是数组，每条 {cond_id, status, evidence_url, evidence_excerpt, reasoning}。

**流程（必须）**：先调 fetch_recent_filings 取 filings → 再根据 filings 调 submit_verdicts 提交逐条判决 → 然后简短收尾。
- 不调 fetch_recent_filings 直接判 = 无据判定，禁止（R5）。
- 不要在回复文本里复述判决，必须用 submit_verdicts 工具提交。
- submit_verdicts 的 verdicts 必须覆盖输入里的**每一条** broken_condition（cond_id 一一对应）。

## 判定三态

- triggered：近期某 filing 明确击中该条件（如「CEO/CFO 离职」命中 8-K item 5.02；「财报重述」命中 8-K item 4.02 或 10-K/A/10-Q/A；外国发行人「重大事项」命中 6-K）。
- watch：部分相关但证据不足 / 映射歧义 / 无法确认（证据不足以判 triggered，但也不该忽略）。
- untriggered：近期无相关 filing。

每条 triggered/watch 必须附：
- evidence_url：命中的 SEC filing index URL（**只能从 fetch_recent_filings 返回的 filings 里选**，不编造）；
- evidence_excerpt：该 filing 的 title 里 primaryDocDescription 片段或 item 文本（须能在 filing index 页定位的原文片段）；
- reasoning：一句话说明为什么这条 filing 击中（或不击中）该条件。
untriggered 可留空 evidence_url/excerpt。

## 红线（不可违反）

R1: 不给买卖 / 仓位建议（不说「建议买入 / 卖出 / 加仓 / 减仓」）
R2: 不预测涨跌、不输出目标价（不说「会涨 / 会跌 / 目标价」）
R3: 不出现看涨看跌暗示（不说「看涨 / 看跌 / 利好 / 利空」）
R5: 每条事实必须有来源，只引用 fetch_recent_filings 返回的 filing，不编造
R6: 判断权归用户——只标「条件 X 今天出现了对应事件」，不替用户结论（不说该不该买/卖/加/减）

证据不足置 watch，**不替用户结论**。先调 fetch_recent_filings，再调 submit_verdicts，不复述。"""


class CondVerdict(BaseModel):
    cond_id: str
    status: str  # triggered | watch | untriggered
    evidence_url: str = ""
    evidence_excerpt: str = ""
    reasoning: str = ""


class CheckVerdicts(BaseModel):
    """判决集合（输出格式契约；run_check 从 submit_verdicts 工具的入参构造，保持形状不变）。"""
    verdicts: list[CondVerdict] = Field(default_factory=list)


@dataclass
class CheckCtx:
    """run_check → 工具的共享上下文（context-injected tool，确定性，不让 LLM 传参）。
    fetch_recent_filings 写回 fetched_filings / fetch_error / fetch_called；
    submit_verdicts 写回 verdicts_submitted。run_check 读这些状态做 E1-E8 判定，避免重复抓取。"""
    card: ThesisCard
    filer_type: Any = None  # models.FilerType
    lookback_hours: int = 72
    fetched_filings: list = field(default_factory=list)
    fetch_error: str | None = None
    fetch_called: bool = False
    verdicts_submitted: list = field(default_factory=list)


def _is_429(e: Exception) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return "429" in s or "rate" in s or "ratelimit" in s


def _build_model(agent_model: dict) -> OpenAIChatCompletionsModel:
    """百炼 OpenAI 兼容端点 → OpenAIChatCompletionsModel（与 orchestrator._build_model 同款）。
    入参为已解析的 agent_model dict（get_agent_model + model_override 合并后）。"""
    base_url = agent_model.get("base_url")
    model_name = agent_model.get("model", "")
    api_key = os.environ.get(agent_model.get("api_key_env", ""), "")
    if not (base_url and model_name and api_key):
        raise SystemExit(
            f"config llm.agent_model 不全（provider/base_url/model/api_key_env）：{agent_model}"
        )
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


def build_check_agent(cfg: dict, *, model_override: str | None = None) -> tuple[Any, str, str]:
    """构造核对 Agent（OpenAI Agents SDK + DeepSeek V4-Flash）。
    走 submit_verdicts tool 提交结构化判决（不用 output_type——DeepSeek + chat_completions
    用 output_type 会短路成空 CheckVerdicts 不先调 fetch；改 tool call 与 orchestrator 同款稳定）。
    懒构建（不在模块 import 时 SystemExit，避免阻断 orchestrator/tests 导入）。
    返回 (agent, model_name, provider)；model_override 覆盖模型名（eval --model 用）。"""
    am = get_agent_model(cfg)
    if model_override:
        am = {**am, "model": model_override}
    provider = am.get("provider", "openai")
    model_name = am.get("model", "")
    model = _build_model(am)
    agent = Agent(
        name="ThesisCheck",
        instructions=CHECK_PROMPT,
        model=model,
        tools=[fetch_recent_filings, submit_verdicts],
    )
    return agent, model_name, provider


def _conditions_for_llm(card: ThesisCard) -> list[dict]:
    out = []
    for c in card.broken_conditions:
        d: dict = {"cond_id": c.id, "layer": c.layer.value, "text": c.text}
        if c.template:
            d["template"] = c.template.value
        if c.threshold:
            d["threshold"] = c.threshold
        out.append(d)
    return out


def _filing_to_dict(f) -> dict:
    return {"form": f.form_type, "item": f.item, "title": f.title, "url": f.url,
            "filed_at": f.filed_at.isoformat(timespec="seconds")}


def _build_input(card: ThesisCard) -> str:
    """给 agent 的用户消息：只给卡的破局条件（filings 由 agent 调 fetch_recent_filings 自取）。"""
    return json.dumps({
        "ticker": card.ticker,
        "filer_type": card.filer_type.value if hasattr(card.filer_type, "value") else str(card.filer_type),
        "broken_conditions": _conditions_for_llm(card),
    }, ensure_ascii=False, indent=2)


@function_tool
def fetch_recent_filings(ctx: RunContextWrapper[CheckCtx]) -> dict:
    """拉本卡标的最近 SEC filings（按 filer_type 自动路由表单：外国发行人主渠道 6-K，本土 10-K/10-Q/8-K；
    ETF/基金 v1 不自动核对）。返回 {filings:[{form,item,title,url,filed_at}], count, error?}。
    判定每条条件前必须先调它取 filings，不调直接判 = 无据判定（R5 禁止）。"""
    c = ctx.context
    c.fetch_called = True
    forms = sec_edgar.forms_for_filer(c.filer_type)
    if not forms:
        c.fetched_filings = []
        return {"filings": [], "count": 0, "note": "该申报方类型 v1 不自动核对（ETF/基金）"}
    try:
        fs = sec_edgar.fetch_filings([c.card.ticker], c.lookback_hours, form_types=list(forms))
    except Exception as e:  # noqa: BLE001 — SEC 慢链路 / ticker 无 CIK 等，记 E1 不崩 agent loop
        c.fetch_error = f"E1_FETCH_FAIL: {e}"
        c.fetched_filings = []
        return {"filings": [], "count": 0, "error": f"E1_FETCH_FAIL: {e}"}
    c.fetched_filings = fs
    return {"filings": [_filing_to_dict(f) for f in fs], "count": len(fs)}


@function_tool(strict_mode=False)  # verdicts: list[dict] 嵌套入参，strict schema 不稳；关掉保可靠（与 orchestrator.save_card 同款）
def submit_verdicts(ctx: RunContextWrapper[CheckCtx], verdicts: list) -> dict:
    """提交逐条判决（结构化输出通道，替代 output_type）。verdicts 是数组，每条
    {cond_id, status(triggered|watch|untriggered), evidence_url, evidence_excerpt, reasoning}。
    必须覆盖输入里每条 broken_condition。triggered/watch 的 evidence_url 只能来自
    fetch_recent_filings 返回的 filings，不编造（R5）。"""
    ctx.context.verdicts_submitted = list(verdicts or [])
    return {"ok": True, "count": len(verdicts or [])}


def _map_status(s: str) -> CondStatus:
    s = (s or "").strip().lower()
    if s == "triggered" or "triggered" in s and "untriggered" not in s:
        return CondStatus.TRIGGERED
    if "watch" in s:
        return CondStatus.WATCH
    return CondStatus.UNTRIGGERED


def _verdict_from_dict(d: dict) -> CondVerdict:
    """submit_verdicts 入参（dict）→ CondVerdict（容错：缺字段补空）。"""
    return CondVerdict(
        cond_id=str(d.get("cond_id", "")),
        status=str(d.get("status", "") or ""),
        evidence_url=str(d.get("evidence_url", "") or ""),
        evidence_excerpt=str(d.get("evidence_excerpt", "") or ""),
        reasoning=str(d.get("reasoning", "") or ""),
    )


def _save(store: ThesisStore, card: ThesisCard, cond_id: str, status: CondStatus,
          evidence: list[Evidence], refusal: str | None, log: Callable) -> None:
    cr = CheckResult(card_id=card.card_id, cond_id=cond_id, status=status,
                     evidence=evidence, refusal_code=refusal)
    try:
        store.save_check_result(cr)
    except Exception as e:  # noqa: BLE001
        log(f"[save] {card.card_id}/{cond_id} fail: {e}")


def _sec_evidence_fetcher(url: str, timeout: float = 30.0, retries: int = 1):
    """SEC 证据回放 fetcher：30s 超时 + 1 次重试（SEC.gov 在慢链路上易超时）。"""
    last = None
    for _ in range(retries + 1):
        try:
            return default_fetcher(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0)
    raise last


def _all_watch(store: ThesisStore, card: ThesisCard, conds, code: str, log: Callable,
               filings_count: int, errors: list[str] | None = None) -> dict:
    """E1/E6/E7 兜底：全部降 watch + 拒判码落日志 + 存 CheckResult。"""
    for c in conds:
        _save(store, card, c.id, CondStatus.WATCH, [], code, log)
    return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": 0,
            "n_watch": len(conds), "n_untriggered": 0, "filings_count": filings_count,
            "errors": errors if errors is not None else [code]}


def run_check(card: ThesisCard, cfg: dict, store: ThesisStore, *,
              lookback_hours: int = 72, fetcher: Callable | None = None,
              agent: Any = None, log: Callable = print) -> dict:
    """核对一张卡：agent loop（fetch_recent_filings → submit_verdicts）→ self_check → redline → 存 CheckResult。

    返回 {card_id, ticker, n_triggered, n_watch, n_untriggered, filings_count, errors}。
    fetcher=None 用 _sec_evidence_fetcher（30s+重试，SEC 慢链路容忍；仅用于 evidence_self_check 回放，
    非 filings 抓取——filings 由 agent 调 fetch_recent_filings 工具自取）；传 mock 可离线测 evidence 回放。
    agent=None 懒构建（run_check 内 build_check_agent）；传预构建 agent 可复用 / eval 注入。
    """
    fx = fetcher or _sec_evidence_fetcher
    conds = card.broken_conditions
    ctx = CheckCtx(card=card, filer_type=card.filer_type, lookback_hours=lookback_hours)

    own_agent = agent is None
    if own_agent:
        agent, _, _ = build_check_agent(cfg)
    limits = get_llm_limits(cfg)
    user_input = _build_input(card)
    t0 = time.perf_counter()
    retries = 0
    while True:
        try:
            result = Runner.run_sync(agent, user_input, context=ctx, max_turns=_MAX_TURNS)
            break
        except Exception as e:  # noqa: BLE001 — 429 / MaxTurns / 网络都兜底
            if _is_429(e) and retries < limits["max_retries_429"]:
                retries += 1
                time.sleep(min(limits["backoff_base_sec"] * (2 ** (retries - 1)), limits["backoff_cap_sec"]))
                continue
            code = "E6_RATE_LIMIT" if _is_429(e) else "E7_SCHEMA"
            log(f"[{code}] {card.ticker} check agent error: {e}")
            return _all_watch(store, card, conds, code, log, len(ctx.fetched_filings))

    # E1：fetch 在工具内失败（agent loop 仍跑了）→ 全 watch + E1（覆盖 agent 判决）
    if ctx.fetch_error:
        log(f"[E1_FETCH_FAIL] {card.ticker} SEC fetch: {ctx.fetch_error}")
        return _all_watch(store, card, conds, "E1_FETCH_FAIL", log, 0)

    # agent 没调 fetch_recent_filings（DeepSeek 跳过工具直接 submit 空/无据判决）→ E7
    if not ctx.fetch_called:
        log(f"[E7_SCHEMA] {card.ticker} agent 未调 fetch_recent_filings（无据判定）")
        return _all_watch(store, card, conds, "E7_SCHEMA", log, 0)

    # 无 filings → 全 untriggered（已检查，0 触发 —— PRD「无事那行不许空」）
    if not ctx.fetched_filings:
        for c in conds:
            _save(store, card, c.id, CondStatus.UNTRIGGERED, [], None, log)
        return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": 0,
                "n_watch": 0, "n_untriggered": len(conds), "filings_count": 0, "errors": []}

    # fetch 了但 agent 没调 submit_verdicts（结构化输出缺失）→ E7
    if not ctx.verdicts_submitted:
        log(f"[E7_SCHEMA] {card.ticker} agent 未调 submit_verdicts（无判决）")
        return _all_watch(store, card, conds, "E7_SCHEMA", log, len(ctx.fetched_filings))

    verdicts = {_verdict_from_dict(d).cond_id: _verdict_from_dict(d) for d in ctx.verdicts_submitted}
    n_t = n_w = n_u = 0
    errors: list[str] = []
    triggered_details: list[dict] = []
    for c in conds:
        v = verdicts.get(c.id)
        if v is None or not v.cond_id:
            log(f"[E4_AMBIGUOUS] {card.ticker} cond {c.id} 未给判定")
            _save(store, card, c.id, CondStatus.WATCH, [], "E4_AMBIGUOUS", log)
            n_w += 1
            errors.append("E4_AMBIGUOUS")
            continue
        # R1-R3 redline.guard：仅校验 LLM reasoning（系统输出），不校验 SEC 引用摘录
        try:
            redline.guard(v.reasoning)
        except redline.RedlineViolation as e:
            log(f"[E8_RENDER_BLOCK] {card.ticker} cond {c.id} reasoning 命中红线: {e.violations}")
            _save(store, card, c.id, CondStatus.WATCH, [], "E8_RENDER_BLOCK", log)
            n_w += 1
            errors.append("E8_RENDER_BLOCK")
            continue
        status = _map_status(v.status)
        evidence: list[Evidence] = []
        if status != CondStatus.UNTRIGGERED and v.evidence_url:
            ev = Evidence(url=v.evidence_url, excerpt=v.evidence_excerpt, source_type="sec_filing")
            # R5 evidence_self_check 回放
            chk = evidence_self_check(v.evidence_url, v.evidence_excerpt, fx)
            ev.checked_ok = chk.ok
            ev.checked_at = _now_iso()
            if not chk.ok:
                log(f"[{chk.reason}] {card.ticker} cond {c.id} evidence 回放不过: {chk.detail}")
                errors.append(chk.reason or "E3_EVIDENCE_MISMATCH")
                status = CondStatus.WATCH  # 降级
            evidence.append(ev)
        refusal = None
        if status == CondStatus.WATCH and not v.evidence_url:
            refusal = "E2_NO_PRIMARY_SOURCE"
            errors.append("E2_NO_PRIMARY_SOURCE")
        _save(store, card, c.id, status, evidence, refusal, log)
        if status == CondStatus.TRIGGERED:
            triggered_details.append({"cond": c.text, "urls": [e.url for e in evidence if e.url]})
            n_t += 1
        elif status == CondStatus.WATCH:
            n_w += 1
        else:
            n_u += 1
    return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": n_t,
            "n_watch": n_w, "n_untriggered": n_u, "filings_count": len(ctx.fetched_filings),
            "errors": errors, "dur_s": round(time.perf_counter() - t0, 2),
            "triggered": triggered_details}


def run_all(user_id: str, cfg: dict, store: ThesisStore, *,
            lookback_hours: int = 72, fetcher: Callable | None = None,
            log: Callable = print) -> list[dict]:
    """核对一个用户的所有 confirmed 卡（日常核对入口）。eval 串行 + 429 退避（不并发）。"""
    cards = [c for c in store.list_cards(user_id) if c.confirmation.confirmed_by_user]
    results = []
    for card in cards:
        log(f"--- 核对 {card.ticker} ({card.filer_type.value}) ---")
        r = run_check(card, cfg, store, lookback_hours=lookback_hours, fetcher=fetcher, log=log)
        results.append(r)
    return results


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def main() -> int:
    """CLI：python -m thesis_watch.check_agent --user beta1 [--lookback 72]"""
    import argparse
    import sys

    from .config import load_config

    ap = argparse.ArgumentParser(description="核对 Agent：逐卡核对 SEC filings → 三态")
    ap.add_argument("--user", default="beta1")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--lookback", type=int, default=int(os.environ.get("THESIS_CHECK_LOOKBACK_HOURS", "72")))
    ap.add_argument("--db", default=os.environ.get("THESIS_DB", "data/thesis.db"))
    args = ap.parse_args()

    cfg = load_config(args.config)
    store = ThesisStore(args.db)
    results = run_all(args.user, cfg, store, lookback_hours=args.lookback, log=print)
    print("\n=== 核对汇总 ===")
    for r in results:
        print(f"  {r['ticker']:8s} triggered={r['n_triggered']} watch={r['n_watch']} "
              f"untriggered={r['n_untriggered']} filings={r['filings_count']} errors={r.get('errors')}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
