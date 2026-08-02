"""Day-1 结构化输出 gate（作者 2026-08-01 定；v0.2 provider-aware + 配置分离 + 限流防护）。

用 FDS（台账字段最全的一行）连跑 5 次 PydanticAI 结构化输出，确认任务模型能稳定
返回符合 schema 的 EntryExtraction 对象。

通过条件：5 次全部 pydantic 校验通过。任一失败 → 退出码 1，停下告诉作者；
不自换方案、不改 schema 迁就模型。

每调用记录：模型名、in/out token、429 重试次数、耗时、错误分类（pass/length/429/validation/other）。
模型/端点从 config.yaml 的 task_model 读（不硬编码）；key 走 env。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# 让 src 可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pydantic import ValidationError  # noqa: E402

from thesis_watch.config import get_llm_limits, get_task_model, load_config  # noqa: E402
from thesis_watch.schema import EntryExtraction  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FDS_PATH = ROOT / "assets" / "notion" / "thesis" / "FDS.md"
CONFIG_PATH = ROOT / "config.yaml"
RESULT_JSON = ROOT / "scripts" / "_last_gate_result.json"
RUNS = 5

# 系统提示词；position_cap_tier 不再由 LLM 抽（改为 tier_map 规则查表）。
SYSTEM_PROMPT = """你是持仓条件录入助手。从用户给的 thesis 描述抽取结构化信息，输出 EntryExtraction 对象。

红线（不可违反）：
- 不给买卖/仓位建议、不预测涨跌、不出现「看涨/看跌/建议关注」。
- 每条事实须有源；文本里没有的不要编造，宁可留空或 None。
- 只整理条件，不下投资结论。

字段：
- holding_reason_raw：用户原话买它的理由。
- key_assumptions：关键假设（moat + 不被颠覆的理由）。
- mirrors：每条假设对应的镜像破局条件（assumption_text 关联对应假设原文，mirror_text 写破局事件）。
- manual_items：价格图形型等不可自动核对项。
- filer_type：申报方类型（FDS 是美国本土 10-K 申报方 → domestic_10k）。
- next_verdict：下一个能证伪 thesis 的事件+日期（财报日等）；不等于下次复盘日。
- entry_anchor：录入估值锚（FDS 用 TTM GAAP P/E）；无数据时 value 留 None。

注意：position_cap_tier 不在输出里——仓位档位由系统按 ticker 查表填，你不用输出。
只输出 EntryExtraction 对应的 tool call，不要复述字段说明、不要展开解释。
"""


def load_fds_input() -> str:
    text = FDS_PATH.read_text(encoding="utf-8")

    def section(header: str) -> str:
        i = text.find(header)
        if i < 0:
            return ""
        start = i + len(header)
        j = text.find("\n## ", start)
        return text[start: j if j > 0 else len(text)].strip()

    return (
        "持仓：FDS\n\n"
        f"【Thesis · 为什么买】\n{section('## Thesis · 为什么买')}\n\n"
        f"【Thesis 破的条件】\n{section('## Thesis 破的条件')}\n\n"
        f"【加仓价 / 安全边际】\n{section('## 加仓价 / 安全边际')}\n"
    )


def build_agent(task: dict):
    from pydantic_ai import Agent

    provider = task.get("provider")
    base_url = task.get("base_url")
    api_key = os.environ.get(task.get("api_key_env", ""), "")
    model_name = task.get("model", "")
    if not base_url or not api_key or not model_name:
        raise SystemExit(
            f"config.yaml llm.task_model 不全（provider/base_url/model/api_key_env）：{task}"
        )

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key, base_url=base_url))
    elif provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider
        from thesis_watch.llm import LenientOpenAIChatModel
        model = LenientOpenAIChatModel(
            model_name, provider=OpenAIProvider(api_key=api_key, base_url=base_url)
        )
    else:
        raise SystemExit(f"未知 provider: {provider}（仅支持 anthropic / openai）")
    return Agent(model, output_type=EntryExtraction, system_prompt=SYSTEM_PROMPT), model_name


def _classify(e: Exception | None) -> str:
    if e is None:
        return "pass"
    s = (str(e) + " " + type(e).__name__).lower()
    if "429" in s or "rate" in s or "ratelimit" in s:
        return "429"
    if "token limit" in s or "max_tokens" in s or "finish_reason" in s:
        return "length"
    if "validation" in s or isinstance(e, ValidationError):
        return "validation"
    return "other"


def call_once(agent, user_input: str, max_tokens: int):
    """单次逻辑调用；429 退避重试（上限从 config），其它异常不重试。
    返回 (status, retries_429, dur, ext, in_tok, out_tok, err)。
    """
    t0 = time.perf_counter()
    retries = 0
    limits = None  # filled from outer
    while True:
        try:
            r = agent.run_sync(user_input, model_settings={"max_tokens": max_tokens})
            dt = time.perf_counter() - t0
            ext = getattr(r, "output", None)
            if ext is None:
                ext = getattr(r, "data", None)
            it = ot = None
            try:
                usage = r.usage
                it = getattr(usage, "request_tokens", None) or getattr(usage, "input_tokens", None)
                ot = getattr(usage, "response_tokens", None) or getattr(usage, "output_tokens", None)
            except Exception:
                pass
            return "pass" if isinstance(ext, EntryExtraction) else "validation", retries, dt, ext, it, ot, None
        except ValidationError as e:
            return "validation", retries, time.perf_counter() - t0, None, None, None, f"ValidationError: {str(e)[:300]}"
        except Exception as e:  # noqa: BLE001
            if _classify(e) == "429" and retries < _MAX_RETRIES_429:
                retries += 1
                backoff = min(_BACKOFF_BASE * (2 ** (retries - 1)), _BACKOFF_CAP)
                time.sleep(backoff)
                continue
            return _classify(e), retries, time.perf_counter() - t0, None, None, None, f"{type(e).__name__}: {str(e)[:300]}"


# 限流参数（main 里从 config 覆盖）
_MAX_RETRIES_429 = 5
_BACKOFF_BASE = 2.0
_BACKOFF_CAP = 60.0


def main() -> int:
    global _MAX_RETRIES_429, _BACKOFF_BASE, _BACKOFF_CAP
    # --model <name>：覆盖 config 的 task_model.model（仅 run-config；schema/prompt 不变）
    model_override = None
    args = sys.argv[1:]
    if "--model" in args:
        i = args.index("--model")
        model_override = args[i + 1] if i + 1 < len(args) else None
    cfg = load_config(str(CONFIG_PATH))
    limits = get_llm_limits(cfg)
    _MAX_RETRIES_429 = limits["max_retries_429"]
    _BACKOFF_BASE = limits["backoff_base_sec"]
    _BACKOFF_CAP = limits["backoff_cap_sec"]
    max_tokens = limits["max_tokens"]
    interval = limits["request_interval_sec"]

    task = get_task_model(cfg)
    if model_override:
        task = {**task, "model": model_override}
    agent, model_name = build_agent(task)
    user_input = load_fds_input()
    provider = task.get("provider")
    print(f"=== FDS day-1 gate · {RUNS} runs · task_model={model_name} ({provider}) max_tokens={max_tokens} ===")
    print(f"input length: {len(user_input)} chars\n")

    rows: list[dict] = []
    for i in range(1, RUNS + 1):
        status, retries, dur, ext, it, ot, err = call_once(agent, user_input, max_tokens)
        rows.append({
            "run": i, "model": model_name, "status": status,
            "ok": status == "pass",
            "in_tok": it, "out_tok": ot, "dur_s": round(dur, 2),
            "retries_429": retries,
            "holding": (ext.holding_reason_raw[:30] if (ext and ext.holding_reason_raw) else None),
            "nmirrors": (len(ext.mirrors) if ext else None),
            "anchor": (ext.entry_anchor.anchor_type if (ext and ext.entry_anchor) else None),
            "verdict": (ext.next_verdict.event if (ext and ext.next_verdict) else None),
            "error": err,
        })
        r = rows[-1]
        print(f"run {i}: {r['status']} dur={r['dur_s']}s in={r['in_tok']} out={r['out_tok']} "
              f"retries429={r['retries_429']} nmirrors={r['nmirrors']} anchor={r['anchor']} verdict={r['verdict']}"
              + (f"  err={err[:120]}" if err else ""))
        if i < RUNS:
            time.sleep(interval)

    passed = sum(1 for r in rows if r["ok"])
    durs = [r["dur_s"] for r in rows if r["ok"]]
    outs = [r["out_tok"] for r in rows if r["ok"] and r["out_tok"]]
    fail_breakdown = {}
    for r in rows:
        if not r["ok"]:
            fail_breakdown[r["status"]] = fail_breakdown.get(r["status"], 0) + 1
    summary = {
        "model": model_name, "provider": provider, "max_tokens": max_tokens,
        "passed": passed, "total": RUNS,
        "pass_rate": round(passed / RUNS, 4),
        "avg_dur_pass_s": round(sum(durs) / len(durs), 2) if durs else None,
        "avg_out_tok_pass": round(sum(outs) / len(outs)) if outs else None,
        "fail_breakdown": fail_breakdown or None,
        "rows": rows,
    }
    print(f"\n=== RESULT: {passed}/{RUNS} passed ===")
    if durs:
        print(f"  pass dur: min={min(durs)}s max={max(durs)}s avg={summary['avg_dur_pass_s']}s")
    if outs:
        print(f"  pass out_tok: min={min(outs)} max={max(outs)} avg={summary['avg_out_tok_pass']}")
    if fail_breakdown:
        print(f"  fail breakdown: {fail_breakdown}")

    RESULT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  result json: {RESULT_JSON}")

    if passed == RUNS:
        print("GATE PASSED — 可往下写实现 + pydantic-evals")
        return 0
    print("GATE FAILED — 停下告诉作者；不自换方案、不改 schema 迁就模型")
    return 1


if __name__ == "__main__":
    sys.exit(main())
