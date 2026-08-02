"""核对 Agent（§2.3）：逐卡逐条件核对 SEC filings → 三态 + 证据 + self_check + redline + E1-E8。

Option A（R5 合规）：一次 LLM 调用判定卡上每条 broken_condition（基于 filings metadata）。
- evidence excerpt = SEC primaryDocDescription（原文片段），url = filings index；
- evidence_self_check 回放（default_fetcher 抓 index 页）验 excerpt 能定位 → 不过降 watch（E1/E3）；
- redline.guard 仅校验 LLM reasoning（系统输出），不校验 SEC 引用摘录；
- E1-E8 落日志供 error analysis；CheckResult 存 store。
深读 filing 正文延后（v1 用 metadata，够命中红线 item 5.02/4.02 等）。

不替用户结论（R6）：只输出状态机三态 + 证据，triggered 须用户收尾（§S4）。
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

from pydantic import BaseModel, Field

from . import redline
from .config import get_llm_limits, get_task_model
from .evidence import default_fetcher, self_check as evidence_self_check
from .fetchers import sec_edgar
from .llm import LenientOpenAIChatModel
from .models import CheckResult, CondStatus, Evidence, ThesisCard
from .store import ThesisStore

CHECK_PROMPT = """你是持仓条件核对 Agent。给定一张 thesis 卡的破局条件 + 该标的近期 SEC filings，逐条判定每条条件的状态。

判定三态：
- triggered：近期某 filing 明确击中该条件（如「CEO/CFO 离职」命中 8-K item 5.02；「财报重述」命中 8-K item 4.02 或 10-K/A/10-Q/A；外国发行人「重大事项」命中 6-K）。
- watch：部分相关但证据不足 / 映射歧义 / 无法确认（证据不足以判 triggered，但也不该忽略）。
- untriggered：近期无相关 filing。

每条 triggered/watch 必须附：
- evidence_url：命中的 SEC filing index URL（**只能从给定 recent_filings 里选**，不编造）；
- evidence_excerpt：该 filing 的 title 里的 primaryDocDescription 片段或 item 文本（须能在 filing index 页定位的原文片段）；
- reasoning：一句话说明为什么这条 filing 击中（或不击中）该条件。

红线（不可违反）：不给买卖 / 仓位建议、不预测涨跌、不出现「看涨 / 看跌 / 建议关注」；证据不足置 watch，**不替用户结论**；不编造 filing，只引用给定列表。
只输出 CheckVerdicts 的 tool call，不复述说明。"""


class CondVerdict(BaseModel):
    cond_id: str
    status: str  # triggered | watch | untriggered
    evidence_url: str = ""
    evidence_excerpt: str = ""
    reasoning: str = ""


class CheckVerdicts(BaseModel):
    verdicts: list[CondVerdict] = Field(default_factory=list)


def _is_429(e: Exception) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return "429" in s or "rate" in s or "ratelimit" in s


def build_check_agent(cfg: dict, *, model_override: str | None = None) -> tuple[Any, str, str]:
    """构造核对 Agent（output_type=CheckVerdicts）。复用 extract/menu 同款模型构建。"""
    from pydantic_ai import Agent

    task = get_task_model(cfg)
    if model_override:
        task = {**task, "model": model_override}
    provider = task.get("provider")
    base_url = task.get("base_url")
    api_key = os.environ.get(task.get("api_key_env", ""), "")
    model_name = task.get("model", "")
    if not (base_url and api_key and model_name):
        raise SystemExit(f"config llm.task_model 不全（provider/base_url/model/api_key_env）：{task}")

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key, base_url=base_url))
    elif provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider
        model = LenientOpenAIChatModel(model_name, provider=OpenAIProvider(api_key=api_key, base_url=base_url))
    else:
        raise SystemExit(f"未知 provider: {provider}（仅 anthropic / openai）")
    return Agent(model, output_type=CheckVerdicts, system_prompt=CHECK_PROMPT), model_name, provider


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


def _filings_for_llm(filings: list) -> list[dict]:
    return [{"form": f.form_type, "item": f.item, "title": f.title, "url": f.url,
             "filed_at": f.filed_at.isoformat(timespec="seconds")} for f in filings]


def _build_input(card: ThesisCard, filings: list) -> str:
    return json.dumps({
        "ticker": card.ticker,
        "filer_type": card.filer_type.value if hasattr(card.filer_type, "value") else str(card.filer_type),
        "broken_conditions": _conditions_for_llm(card),
        "recent_filings": _filings_for_llm(filings),
    }, ensure_ascii=False, indent=2)


def _map_status(s: str) -> CondStatus:
    s = (s or "").strip().lower()
    if s == "triggered" or "triggered" in s and "untriggered" not in s:
        return CondStatus.TRIGGERED
    if "watch" in s:
        return CondStatus.WATCH
    return CondStatus.UNTRIGGERED


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


def run_check(card: ThesisCard, cfg: dict, store: ThesisStore, *,
              lookback_hours: int = 72, fetcher: Callable | None = None,
              agent: Any = None, log: Callable = print) -> dict:
    """核对一张卡：拉 SEC filings → LLM 判定 → self_check → redline → 存 CheckResult。

    返回 {card_id, ticker, n_triggered, n_watch, n_untriggered, filings_count, errors}。
    fetcher=None 用 _sec_evidence_fetcher（30s+重试，SEC 慢链路容忍）；传 mock 可离线测。
    """
    fx = fetcher or _sec_evidence_fetcher
    forms = sec_edgar.forms_for_filer(card.filer_type)
    conds = card.broken_conditions

    # E1：SEC fetch
    filings: list = []
    if forms:
        try:
            filings = sec_edgar.fetch_filings([card.ticker], lookback_hours, form_types=list(forms))
        except Exception as e:  # noqa: BLE001
            log(f"[E1_FETCH_FAIL] {card.ticker} SEC fetch: {e}")
            for c in conds:
                _save(store, card, c.id, CondStatus.WATCH, [], "E1_FETCH_FAIL", log)
            return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": 0,
                    "n_watch": len(conds), "n_untriggered": 0, "filings_count": 0, "errors": ["E1"]}

    # 无 filings → 全 untriggered（已检查，0 触发 —— PRD「无事那行不许空」）
    if not filings:
        for c in conds:
            _save(store, card, c.id, CondStatus.UNTRIGGERED, [], None, log)
        return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": 0,
                "n_watch": 0, "n_untriggered": len(conds), "filings_count": 0, "errors": []}

    # LLM 判定（429 退避重试）
    own_agent = agent is None
    if own_agent:
        agent, _, _ = build_check_agent(cfg)
    limits = get_llm_limits(cfg)
    user_input = _build_input(card, filings)
    t0 = time.perf_counter()
    retries = 0
    out: CheckVerdicts | None = None
    while True:
        try:
            r = agent.run_sync(user_input, model_settings={"max_tokens": limits["max_tokens"]})
            out = getattr(r, "output", None) or getattr(r, "data", None)
            break
        except Exception as e:  # noqa: BLE001
            if _is_429(e) and retries < limits["max_retries_429"]:
                retries += 1
                time.sleep(min(limits["backoff_base_sec"] * (2 ** (retries - 1)), limits["backoff_cap_sec"]))
                continue
            log(f"[E6_RATE_LIMIT] {card.ticker} check agent 429: {e}" if _is_429(e)
                else f"[E7_SCHEMA] {card.ticker} check agent error: {e}")
            code = "E6_RATE_LIMIT" if _is_429(e) else "E7_SCHEMA"
            for c in conds:
                _save(store, card, c.id, CondStatus.WATCH, [], code, log)
            return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": 0,
                    "n_watch": len(conds), "n_untriggered": 0, "filings_count": len(filings),
                    "errors": [code]}

    if not isinstance(out, CheckVerdicts):
        log(f"[E7_SCHEMA] {card.ticker} check agent output 非 CheckVerdicts: {type(out)}")
        for c in conds:
            _save(store, card, c.id, CondStatus.WATCH, [], "E7_SCHEMA", log)
        return {"card_id": card.card_id, "ticker": card.ticker, "n_triggered": 0,
                "n_watch": len(conds), "n_untriggered": 0, "filings_count": len(filings),
                "errors": ["E7_SCHEMA"]}

    verdicts = {v.cond_id: v for v in out.verdicts}
    n_t = n_w = n_u = 0
    errors: list[str] = []
    triggered_details: list[dict] = []
    for c in conds:
        v = verdicts.get(c.id)
        if v is None:
            log(f"[E4_AMBIGUOUS] {card.ticker} cond {c.id} 未给判定")
            _save(store, card, c.id, CondStatus.WATCH, [], "E4_AMBIGUOUS", log)
            n_w += 1
            errors.append("E4_AMBIGUOUS")
            continue
        # R3 redline.guard：仅校验 LLM reasoning（系统输出），不校验 SEC 引用摘录
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
            "n_watch": n_w, "n_untriggered": n_u, "filings_count": len(filings),
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
