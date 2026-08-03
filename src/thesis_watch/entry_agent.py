"""录入 Agent —— PydanticAI 单次结构化调用（v0.2）。

输入 thesis 文本 → 输出 EntryExtraction。模型无关（config.yaml task_model 驱动），
不依赖会话上下文。CLI / harness / gate 共用本模块。

作者 2026-08-01 定：
- 单次调用 + 结构化输出（不用多 agent / handoff）。
- 模型分工：qwen-turbo 日常迭代；glm-5.2-fast-preview 质量基线（--model 覆盖）。
- A/B 对照：A=直接抽（默认），B=带自澄清 reasoning prefix（批 eval 的澄清价值代理）。
- per-call 记指标：model / in_tok / out_tok / retries_429 / dur / status。
- 429 退避重试；429 与其它错误分开计数。
- OpenAI 兼容端点用 `LenientOpenAIChatModel` 容错非标 finish_reason（见 llm.py）。
"""
from __future__ import annotations

import os
import time
from typing import Any

from pydantic import ValidationError

from .config import get_llm_limits, get_task_model
from .schema import EntryExtraction

SYSTEM_PROMPT = """你是持仓条件录入助手。从用户给的 thesis 描述抽取结构化信息，输出 EntryExtraction 对象。

红线（不可违反）：
- 不给买卖/仓位建议、不预测涨跌、不出现「看涨/看跌/建议关注」。
- 每条事实须有源；文本里没有的不要编造，宁可留空或 None。
- 只整理条件，不下投资结论。

字段：
- ticker：用户持有的股票代码（如 MCO/HSBC/NVDA/NFLX）。从用户一句话里识别标的；说不清返 null。
- holding_reason_raw：用户原话买它的理由。**只放买入理由，不混策略表述**（如「策略：逆势、越跌越买」是操作策略不是买入理由，弃）。
- key_assumptions：关键假设——**只放 moat + 不被颠覆的理由**（结构性主题）：AI 替代 / 监管 / 利率与久期 / 竞争格局 / 客户集中度。**估值机械（EPS / FCF / DCF / SBC / 倍数口径 / reverse DCF）不进这里**——属于 entry_anchor.note，进不了 anchor 的弃置。
  **四条合格判定（每条候选假设逐条过，任一不过 → 不写 key_assumptions，改写进 open_questions 向用户追问，宁缺勿凑）**：
    1. 是关于**这门生意**的判断——不是估值口径、不是计算方法、不是价格形态
    2. **可能为假**——存在一个可想象的世界状态，使它不成立
    3. **比用户原话多出信息**——同义复述、拆分扩写、换词重写，一律不合格
    4. **能对应至少一条带可判定阈值的镜像**——对应不上说明它不可证伪，不合格
  正例（合格）：「切换成本锁定客户，竞品难蚕食份额」「监管收紧会压缩核心业务利润率」
  反例（不合格→open_question）：「估值用 P/E 25 倍」（估值口径，违反 1）/「看好服务收入持续高增」（同义复述原话，违反 3）
  **输入隔离**：抽 key_assumptions 时不得把「加仓价 / 安全边际」类内容当输入——该段只流向 entry_anchor。
- open_questions：四关拒掉的候选假设改写于此（field=key_assumptions，reason=哪条不过，text=原候选）；条件 3（同义复述）另由 harness 确定性兜底（is_paraphrase）。
- mirrors：每条假设对应的镜像破局条件。每条须含 assumption_text（关联对应假设原文）+ mirror_text（破局事件）+ **threshold（可判定数值/布尔事件，如 {"metric":"service_rev_yoy","operator":"<","value":0} 或 {"event":"ceo_departed","occurred":false}）+ source_type（sec_filing_field / news_headline / press_release_text / manual）**——P3 任一缺失则该镜像不可判定，harness make_mirror 不生成（转 open_questions），不要给残缺镜像。
- manual_items：价格图形型等不可自动核对项。
- filer_type：申报方类型（美国本土 10-K → domestic_10k；20-F/6-K 外国发行人 → foreign_issuer_20f_6k；ETF/ETN/基金/信托 → etf_fund）。
- ETF/基金类（etf_fund）：无公司层面 10-K/20-F，破条件依赖指数成分/基金公告/价格规模数据，v1 数据源不覆盖 → 所有破条件记为 manual_items（人工自查），不进自动核对。
- next_verdict：下一个能证伪 thesis 的事件+日期（财报日等）；不等于下次复盘日。
- entry_anchor：录入估值锚。从文本「加仓价 / 安全边际」相关段落中识别估值口径。
  - anchor_type 从以下闭集九项中选（选不出口径时返回 other，不要留 null；文本中确实没有加仓价/安全边际信息时才返回 null）：
    ttm_gaap_pe              TTM GAAP P/E（最近四季 GAAP 摄薄 EPS × 倍数）
    forward_non_gaap_pe      Forward non-GAAP P/E
    normalized_pe            归一化 P/E（如穿越周期归一化）
    normalized_operating_pe  归一化营业利润 P/E
    normalized_fwd_gaap_pe   归一化 Forward GAAP P/E
    p_fcf                    P/FCF（自由现金流倍数）
    p_tbv                    P/TBV（有形净资产倍数，银行股用）
    operating_multiple_2col  巴菲特两栏法（运营倍数）
    other                    其余（识别不出口径时用此值）
  - anchor_value 填倍数（如 25），不是价格（如 $394）；价格写进 note。
  - note 填补充说明 + 估值机械（如「25x ≈ $394」「16x ≈ $251」、EPS / FCF / DCF / SBC / 倍数口径——这些**不进 key_assumptions**）。
  - 文本中同时存在多个时点读数时，取日期最新的一条（如 MCO 取 7/24 重算的 $394 非 6/06 的 $349）。

注意：position_cap_tier 不在输出里——仓位档位由系统按 ticker 查表填（tier_map），你不用输出。
只输出 EntryExtraction 对应的 tool call，不要复述字段说明、不要展开解释。
"""

_VALID_FINISH = {"stop", "length", "tool_calls", "content_filter", "function_call"}


def _is_429(e: Exception) -> bool:
    s = (str(e) + " " + type(e).__name__).lower()
    return "429" in s or "rate" in s or "ratelimit" in s


def _classify(e: Exception | None) -> str:
    if e is None:
        return "pass"
    s = (str(e) + " " + type(e).__name__).lower()
    if "429" in s or "rate" in s:
        return "429"
    if "token limit" in s or "max_tokens" in s or "finish_reason" in s:
        return "length"
    if "validation" in s or isinstance(e, ValidationError):
        return "validation"
    return "other"


def build_agent(cfg: dict, *, model_override: str | None = None) -> tuple[Any, str, str]:
    """构造 PydanticAI Agent。读 config 的 task_model；model_override 覆盖模型名（run-config，不改 schema/prompt）。
    返回 (agent, model_name, provider)。
    """
    from pydantic_ai import Agent

    task = get_task_model(cfg)
    if model_override:
        task = {**task, "model": model_override}
    provider = task.get("provider")
    base_url = task.get("base_url")
    api_key = os.environ.get(task.get("api_key_env", ""), "")
    model_name = task.get("model", "")
    if not base_url or not api_key or not model_name:
        raise SystemExit(f"config llm.task_model 不全（provider/base_url/model/api_key_env）：{task}")

    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider
        model = AnthropicModel(model_name, provider=AnthropicProvider(api_key=api_key, base_url=base_url))
    elif provider == "openai":
        from pydantic_ai.providers.openai import OpenAIProvider
        from .llm import LenientOpenAIChatModel
        model = LenientOpenAIChatModel(
            model_name, provider=OpenAIProvider(api_key=api_key, base_url=base_url)
        )
    else:
        raise SystemExit(f"未知 provider: {provider}（仅支持 anthropic / openai）")
    return Agent(model, output_type=EntryExtraction, system_prompt=SYSTEM_PROMPT), model_name, provider


def extract(agent: Any, text: str, cfg: dict, *, mode: str = "A") -> dict:
    """单次结构化调用。mode A=直接抽（默认），B=带自澄清 reasoning prefix。
    返回 {ok, extraction, model_status, in_tok, out_tok, retries_429, dur_s, status, error}。
    """
    limits = get_llm_limits(cfg)
    if mode == "B":
        user_input = (
            "先在内心做一步澄清：列出这条 thesis 的关键 moat 与「什么具体事件出现 = thesis 破了」，"
        "再据此输出 EntryExtraction。\n\n" + text
        )
    else:
        user_input = text

    t0 = time.perf_counter()
    retries = 0
    while True:
        try:
            r = agent.run_sync(user_input, model_settings={"max_tokens": limits["max_tokens"]})
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
            ok = isinstance(ext, EntryExtraction)
            return {
                "ok": ok, "extraction": ext,
                "in_tok": it, "out_tok": ot,
                "retries_429": retries, "dur_s": round(dt, 2),
                "status": "pass" if ok else "validation", "error": None,
            }
        except ValidationError as e:
            return {
                "ok": False, "extraction": None, "in_tok": None, "out_tok": None,
                "retries_429": retries, "dur_s": round(time.perf_counter() - t0, 2),
                "status": "validation", "error": f"ValidationError: {str(e)[:300]}",
            }
        except Exception as e:  # noqa: BLE001
            if _is_429(e) and retries < limits["max_retries_429"]:
                retries += 1
                time.sleep(min(limits["backoff_base_sec"] * (2 ** (retries - 1)), limits["backoff_cap_sec"]))
                continue
            return {
                "ok": False, "extraction": None, "in_tok": None, "out_tok": None,
                "retries_429": retries, "dur_s": round(time.perf_counter() - t0, 2),
                "status": _classify(e), "error": f"{type(e).__name__}: {str(e)[:300]}",
            }


__all__ = ["SYSTEM_PROMPT", "build_agent", "extract"]
