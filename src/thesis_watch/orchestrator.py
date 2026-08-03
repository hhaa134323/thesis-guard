"""Thesis Guard orchestrator —— OpenAI Agents SDK agent loop（Phase 1 重构）。

重构方向（docs/refactor-spec.md）：state machine（entry_loop.py）→ LLM 指挥 +
确定性校验。本模块是 orchestration 层，定义 ThesisGuard agent：

- 模型：DeepSeek V4-Flash，走百炼 OpenAI 兼容端点（chat_completions API）。
- 5 个 @function_tool：resolve_ticker / extract_card / generate_menu / save_card /
  check_filing。每个复用现有确定性逻辑（fetchers / entry_agent / menu / store /
  conditions / condition_classify / redline），不重写抽取/mirror/存储代码。
- 双保险：System Prompt（软，docs/agent-prompt.md 全文）+ SDK Guardrails（硬）。
  OutputGuardrail 调 redline.find_violations 查 R1-R3；InputGuardrail 关键词防用户诱导。
- guardrail 层零改动：redline / conditions / condition_classify / schema / models 不动。

Phase 1 不动 entry_loop / serve / dialogue（Phase 2 的事）；本模块只新增、可独立 import。
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

from agents import (
    Agent,
    GuardrailFunctionOutput,
    function_tool,
    input_guardrail,
    output_guardrail,
    set_default_openai_api,
)
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from . import redline
from .conditions import default_redline_pack, is_paraphrase, make_mirror
from .condition_classify import classify_condition, is_v1_auto, v1_gap_reasons
from .config import (
    get_agent_model,
    get_forbidden_extra,
    get_redline_thresholds,
    load_config,
)
from .entry_agent import build_agent as _build_extract_agent
from .entry_agent import extract as _run_extract
from .fetchers import sec_edgar, ticker_resolver
from .menu import build_menu_agent as _build_menu_agent
from .menu import filter_executable_mirrors, generate_menu as _run_generate_menu
from .models import (
    Assumption,
    Confirmation,
    EntryAnchorData,
    FilerType,
    ManualCheckItem,
    NextVerdictData,
    ThesisCard,
    to_dict,
)

# 百炼兼容端点用 chat_completions API（不支持 Responses API），SDK 须切默认。
set_default_openai_api("chat_completions")

# --- 配置（模块级加载；config.yaml 本地 gitignored，缺省走代码默认） ---
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = Path(os.environ.get("THESIS_CONFIG", str(_REPO_ROOT / "config.yaml")))
_CFG = load_config(str(_CONFIG_PATH))
_THRESHOLDS = get_redline_thresholds(_CFG)
_FORBID_EXTRA = get_forbidden_extra(_CFG)
_PHRASES = redline.get_forbidden_phrases(_FORBID_EXTRA)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --- 模型构建（agent loop 主模型；与 task_model=glm 分工，见 config.get_agent_model） ---
def _build_model(cfg: dict) -> OpenAIChatCompletionsModel:
    am = get_agent_model(cfg)
    base_url = am.get("base_url")
    model_name = am.get("model")
    api_key = os.environ.get(am.get("api_key_env", ""), "")
    if not (base_url and model_name and api_key):
        raise SystemExit(
            f"config llm.agent_model 不全（provider/base_url/model/api_key_env）：{am}"
        )
    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    return OpenAIChatCompletionsModel(model=model_name, openai_client=client)


_MODEL = _build_model(_CFG)

# extract / menu 仍走 PydanticAI + task_model=glm（复用现有抽取逻辑，重构完成后再删）。
_EXTRACT_AGENT, _EXTRACT_MODEL_NAME, _ = _build_extract_agent(_CFG)
_MENU_AGENT, _MENU_MODEL_NAME, _ = _build_menu_agent(_CFG)

# 持仓周期合法枚举（录入问用户，不模型猜；schema §4.2）。
_HORIZONS = {"long", "mid", "trade"}

# demo / Phase 1 默认 :memory:，不污染真实 data/thesis.db（R9 敏感）。Phase 2 接 serve 时改。
_STORE: Any = None


def _get_store() -> Any:
    global _STORE
    if _STORE is None:
        from .store import ThesisStore

        _STORE = ThesisStore(os.environ.get("THESIS_DB_PATH", ":memory:"))
        _STORE.seed_preset_users()
    return _STORE


# =========================================================================== #
# System Prompt（docs/agent-prompt.md 全文逐字照抄；改 prompt 请先改文档再同步此处）
# =========================================================================== #
SYSTEM_PROMPT = """你是 Thesis Guard 的 thesis 讨论伙伴。你的职责是跟用户逐字段讨论，
帮用户把投资逻辑结构化记录下来，形成 thesis card。

你不是填表的机器。你像一个懂投资的朋友，跟用户聊清楚每一个字段。

## 你有什么工具

你有 5 个工具：

1. resolve_ticker(query) — 在 SEC 官方表中查找股票代码。
   - 输入英文 ticker（如 MCO/HSBC/NVDA）或英文公司名
   - 只认英文。如果用户说中文公司名（如"汇丰"），你可以翻译成英文再调
   - 但调完后，你必须告诉用户你找到了什么，让用户确认：
     "我找到 [公司全名] (ticker: XXX)，这是你说的标的吗？"
   - 如果返回 NOT FOUND，问用户要英文 ticker 或公司名

2. extract_card(text, ticker) — 从用户的理由中抽取关键假设和镜像破局条件。
   - 只在 ticker 已确认后调用
   - **你必须调用此工具来抽取假设，不要自己在回复里拆解**
   - 返回 key_assumptions（关键假设）+ mirrors（镜像破局条件）
   - 你需要把工具返回的假设呈现给用户确认，再继续讨论破局条件

3. generate_menu(ticker, reason) — 当用户说"无法确定"或想不出破局条件时，
   生成候选菜单。
   - 返回 A（信什么假设）和 B（破什么条件）两组候选

4. save_card(...) — 保存 thesis card 到数据库。
   - 只在用户明确确认后调用（用户说"确认"、"对"、"入库"等）
   - 保存前确认所有必填字段都有值
   - 5 个必填字段缺一不可，不允许部分保存

5. check_filing(ticker) — 查询最近一份 SEC filing。
   - 用于回答用户在确认阶段的问题（如"最近财报什么时候？"）

## 你怎么跟用户讨论

### 开场

用户来了，先判断是哪种情况：
- "我开始关注 MCO" / "我持有 MCO" → 先 resolve_ticker 确认标的
- 标确认后，问"说说你为什么关注/持有这个标的？"

注意区分两种用户：
- 探针仓用户：刚开始关注，买了 1 股纳入追踪，还没真正建仓
- 已建仓用户：已经下注建仓，有实际持仓
两种用户都需要完整讨论 5 个字段，但措辞不同：
- 探针仓："说说你为什么开始关注这个标的？"
- 已建仓："说说你为什么持有这个标的？"

### 5 步讨论流程

确认标的后，逐字段跟用户讨论。不是一口气全问，是一个一个聊：

**第 1 步：Thesis（为什么买）**
- 用户说理由
- 你**必须调用 extract_card 工具**来抽取 key_assumptions，不要自己在回复里拆解假设
- 调用工具后，把工具返回的假设呈现给用户确认
- **如果用户说"不知道"或表达太模糊**：根据你对这家公司业务的理解，
  提供 2-3 个可能的方向供用户选择（如"壁垒可能来自：1. 牌照稀缺 2. 客户切换成本 3. 品牌信任度"）。
  用户选一个后，再调 extract_card 抽取。不要替用户下判断，只提供选项。

**第 2 步：Key Assumptions（关键假设）**
- 你把工具返回的假设呈现给用户："我理解你的核心假设是：1. xxx 2. xxx，对吗？"
- 用户确认或修改
- **合格判定**：每条假设必须同时满足四条，缺一不合格——
  1. 是关于这门生意的判断（不是估值口径、不是计算方法、不是价格形态）
  2. 可能为假（存在一个可想象的世界状态使它不成立）
  3. 比用户原话多出信息（同义复述、换词重写一律不合格）
  4. 能对应至少一条带可判定阈值的镜像（不可证伪的不合格）
- 不合格的假设不填，改写成 open_question 向用户追问。宁缺勿凑。
- **输入隔离**：抽 key_assumptions 时不得把"加仓价/安全边际"类内容当输入
  ——那属于估值，不是关键假设。估值口径混进关键假设会逼模型同义复述。
- **正例（合格）**：
  - "切换成本锁定客户，竞品难蚕食份额"——关乎这门生意、可能为假、
    比原话多、可镜像（份额跌破阈值 X%）
  - "监管收紧会压缩核心业务利润率"——关乎这门生意、可能为假、
    多出信息、可镜像（新规落地 + 利润率跌破 X%）
- **反例（不合格 → open_question）**：
  - "估值用 P/E 25 倍"——估值口径，不是这门生意的判断（违反条件 1）
  - "看好服务收入持续高增"——只是复述用户原话，没多出信息（违反条件 3）

**第 3 步：破局条件（mirror + redline）**
- 从每个确认的假设生成 mirror 破局条件
- 每条 mirror 必须有 threshold（可判定阈值）+ source_type（数据源类型）
- 附上红线默认包：大额罚单 / 高管突变 / 财报重述（阈值可调、可关停）
- 呈现给用户："这些情况出现就说明 thesis 破了，你看看对不对？"
- 用户说不清破什么 → 调 generate_menu 生成候选
- 原话含均线/形态/突破/支撑阻力等价格图形型 → 记为 manual_check_items，
  告诉用户"这一条系统不接行情，每月提醒你自查"

**第 4 步：安全边际（估值）**
- 问用户："你打算在什么价格加仓？还是我帮你想想估值方法？"
- 如果用户不知道怎么估值，根据你对这家公司业务的理解，
  提供 2-3 个适合的估值方法供用户选择。
- 你可以参考这些思路：
  - 稳定现金流的轻资产公司 → owner-earnings 收益率 / reverse DCF
  - 银行/金融 → P/TBV（市净率）
  - 控股/投资型 → 巴菲特两栏法
  - 指数 ETF → 盈利收益率 vs 长债收益率
- 但你的判断应该基于具体公司的业务特征，不要机械套用分类。
  要能向用户解释为什么推荐这个方法。
- 用户选了方法 + 给了数字 → 记录安全边际
- **安全边际是必填字段**——它是"真正建仓"的触发线，不能空着

**第 5 步：持仓周期**
- 问用户："你的持仓周期？长线（≥3年）/ 中线（3个月-3年）/ 交易（≤3个月）？"
- 用户选 → 记录
- 持仓周期影响复查 skill 用哪种视角解读异常

### 保存

5 个字段全部填完 → 呈现完整 thesis card 给用户复述 → 用户确认 → save_card 落库

**不允许部分保存。** 5 个字段（thesis / key_assumptions / 破局条件 / 安全边际 /
持仓周期）全部填完才能存。

### 灵活性

以上是典型流程，但你可以灵活组合。比如用户一口气说了
"我持有MCO，看好信用评级壁垒，打算25倍以下加仓"，你可以：
1. 先 resolve_ticker("MCO") 确认标的
2. 再调 extract_card 工具抽取假设 + 生成破局条件
3. 一次性呈现标的确认 + 假设 + 破局条件 + 估值
4. 只问持仓周期

关键是：不跳过用户确认环节，不省略必填字段。

## 红线（绝对不能违反）

R1: 不给买卖建议（不说"建议买入"、"值得持有"）
R2: 不预测涨跌（不说"会涨"、"会跌"、"看涨"、"看跌"）
R3: 不出现看涨看跌的暗示（不说"利好"、"利空"、"bullish"、"bearish"）
R4: 不接 broker API（你没有这个工具）
R5: 每条事实必须有来源（SEC filing、官方公告）
R6: 判断权归用户（你只整理条件，不下结论；不说"这个 thesis 成立/不成立"）
R7: 不写 Notion（你没有这个工具）

## 对话风格

- 简洁：不废话，直接做事
- 中性：不评价用户的理由好坏
- 确认导向：每个关键步骤都让用户确认
- 不猜：不知道就问，不编造信息
- 中文：用户用中文你就用中文回复
"""


# =========================================================================== #
# 5 个 @function_tool —— 复用现有逻辑，guardrail 在 tool 内部插入确定性校验
# =========================================================================== #


@function_tool
def resolve_ticker(query: str) -> dict:
    """在 SEC 官方表中查找股票代码。输入英文 ticker（如 MCO/HSBC/NVDA）或英文公司名。
    只认英文，不认中文公司名——用户说中文公司名（如「汇丰」），你需要先翻译成英文再调。
    返回 {found, ticker, title, cik}；找不到返回 {found:false, query}。调完务必让用户确认标的。"""
    matches = ticker_resolver.resolve(query)
    if not matches:
        return {"found": False, "query": query}
    m = matches[0]
    return {"found": True, "ticker": m.ticker, "title": m.title, "cik": m.cik}


def _extract_card_impl(text: str, ticker: str) -> dict:
    """extract_card 的纯逻辑实现（G3 质量校验；可独立单测，不经 SDK ctx）。
    从 thesis 抽 key_assumptions + mirrors；条件3（同义复述）/条件4（不可证伪）
    不过 → 转 open_questions（与 entry_loop v0.0.13 一致）；R1-R3 命中即抛 RedlineViolation。"""
    ext = _run_extract(_EXTRACT_AGENT, text, _CFG)
    if not ext.get("ok") or ext.get("extraction") is None:
        return {
            "ok": False,
            "status": ext.get("status"),
            "error": ext.get("error") or "抽取失败",
        }
    e = ext["extraction"]  # schema.EntryExtraction
    holding_reason_raw = e.holding_reason_raw or text

    # --- G3：key_assumptions 四条合格判定（确定性 backstop，复用现有原语） ---
    # 条件3（同义复述）+ 条件4（不可证伪）不过 → 转 open_questions（与 entry_loop
    # v0.0.13 现有行为一致；guardrail-mapping 的 raise 伪码是草图，以 schema §7 为准）。
    kept_assumptions: list[dict] = []
    open_questions: list[dict] = [
        {"field": o.field, "reason": o.reason, "text": o.text} for o in (e.open_questions or [])
    ]
    for a in e.key_assumptions or []:
        reasons: list[str] = []
        if is_paraphrase(a.text, holding_reason_raw):
            reasons.append("条件3: 同义复述，未比原话多出信息")
        labels = classify_condition(a.text)
        if not is_v1_auto(labels):
            reasons.append("条件4: 不可证伪/无可判定镜像（" + "；".join(v1_gap_reasons(labels)) + "")
        if reasons:
            open_questions.append(
                {"field": "key_assumptions", "reason": "；".join(reasons), "text": a.text}
            )
        else:
            kept_assumptions.append({"text": a.text, "judgeable": True})

    kept_texts = {a["text"] for a in kept_assumptions}

    # --- P3 + G3 mirror：make_mirror 强制 threshold/source_type；对应假设被拒的镜像一并转 open_questions ---
    mirrors_out: list[dict] = []
    for m in e.mirrors or []:
        # 复用 make_mirror 做完整性校验（缺 threshold/source_type → None）
        bc = make_mirror(
            Assumption(text=m.assumption_text), m.mirror_text,
            threshold=m.threshold, source_type=m.source_type,
        )
        if bc is None:
            open_questions.append({
                "field": "mirrors",
                "reason": "P3: 缺 threshold/source_type，镜像不可判定",
                "text": m.mirror_text,
            })
            continue
        if m.assumption_text not in kept_texts:
            open_questions.append({
                "field": "mirrors",
                "reason": "对应假设被拒（条件3/4），镜像无立足点",
                "text": m.mirror_text,
            })
            continue
        mirrors_out.append({
            "assumption_text": m.assumption_text,
            "mirror_text": m.mirror_text,
            "threshold": m.threshold,
            "source_type": m.source_type,
        })

    # --- R1-R3 硬校验：抽取出的文本不得踩红线（复用 redline.find_violations） ---
    all_text = " ".join(
        [holding_reason_raw]
        + [a["text"] for a in kept_assumptions]
        + [m["mirror_text"] for m in mirrors_out]
    )
    violations = redline.find_violations(all_text, _PHRASES)
    if violations:
        # 与 build_card_from_extraction 现有 redline.guard 行为一致：命中即抛，由 SDK 传回 LLM
        raise redline.RedlineViolation(violations, all_text)

    return {
        "ok": True,
        "holding_reason_raw": holding_reason_raw,
        "key_assumptions": kept_assumptions,
        "mirrors": mirrors_out,
        "open_questions": open_questions,
        "manual_items": [
            {"text": mi.text, "reason": mi.reason, "cadence": mi.cadence}
            for mi in (e.manual_items or [])
        ],
    }


@function_tool
def extract_card(text: str, ticker: str) -> dict:
    """从用户的 thesis 描述抽取关键假设 + 镜像破局条件。ticker 须已确认后才调。
    返回 {ok, holding_reason_raw, key_assumptions, mirrors, open_questions, manual_items}。
    假设须先呈现给用户确认再讨论破局条件。不合格的假设已转 open_questions，直接呈现给用户。"""
    return _extract_card_impl(text, ticker)


@function_tool
def generate_menu(ticker: str, reason: str) -> dict:
    """用户在破局条件步骤说「无法确定」/想不出破什么时调。返回候选 A（假设）+ B（镜像破条件）。
    已自动过滤 v1 不可自动核对的 B 候选并显式给出缺口原因（覆盖率须告知用户，不静默跳过）。"""
    out = _run_generate_menu(_MENU_AGENT, ticker, reason, _CFG)
    if not out.get("ok") or out.get("menu") is None:
        return {"ok": False, "status": out.get("status"), "error": out.get("error") or "菜单生成失败"}
    menu = out["menu"]  # menu.MenuCandidates
    cand_a = list(menu.candidate_assumptions or [])
    kept_b, excluded_b = filter_executable_mirrors(list(menu.candidate_mirrors or []))

    # R1-R3 校验候选文本
    all_text = " ".join(cand_a + [b.mirror_text for b in kept_b] + [ex.get("mirror_text", "") for ex in excluded_b])
    violations = redline.find_violations(all_text, _PHRASES)
    if violations:
        raise redline.RedlineViolation(violations, all_text)

    total = len(menu.candidate_mirrors or [])
    excluded_n = len(excluded_b)
    coverage = (
        f"原本 {total} 个方向，{excluded_n} 个当前无法自动核对，已排除（原因见 excluded_mirrors）"
        if total else "无候选"
    )
    return {
        "ok": True,
        "candidate_assumptions": cand_a,
        "candidate_mirrors": [
            {
                "assumption": b.assumption,
                "mirror_text": b.mirror_text,
                "threshold": b.threshold,
                "source_type": b.source_type,
            }
            for b in kept_b
        ],
        "excluded_mirrors": excluded_b,
        "coverage": coverage,
    }


def _save_card_impl(
    ticker: str,
    holding_reason_raw: str,
    key_assumptions: list,
    mirrors: list,
    entry_anchor: dict,
    holding_horizon: str,
    confirmed_by_user: bool,
    manual_items: list | None = None,
    next_verdict: dict | None = None,
) -> dict:
    """save_card 的纯逻辑实现（G1 必填 + G4 用户确认 + G2 安全边际 + R1-R3；可独立单测）。
    5 必填字段缺一不可；confirmed_by_user=True；entry_anchor 须有口径+数值（来自用户）。"""
    # --- G1：必填字段完整性（安全边际是建仓触发线，缺则不允许部分保存） ---
    required = {
        "ticker": ticker,
        "holding_reason_raw": holding_reason_raw,
        "key_assumptions": key_assumptions,
        "mirrors": mirrors,
        "entry_anchor": entry_anchor,
        "holding_horizon": holding_horizon,
    }
    missing = [k for k, v in required.items() if v is None or v == "" or v == []]
    if missing:
        raise ValueError(f"必填字段缺失，不允许部分保存：{missing}")

    # --- G4：用户必须已明确确认 ---
    if not confirmed_by_user:
        raise ValueError("用户未明确确认，不允许保存")

    # --- G2：entry_anchor 非空 + 有口径 + 有数值/说明（数值须来自用户，不许 LLM 编） ---
    ea = entry_anchor or {}
    anchor_type = ea.get("anchor_type") or ea.get("method") or ""
    anchor_value = ea.get("anchor_value") if ea.get("anchor_value") is not None else ea.get("value")
    note = ea.get("note", "") or ""
    if not anchor_type or (anchor_value is None and not note):
        raise ValueError("安全边际不完整：缺估值方法或数值（须来自用户，不编造）")

    horizon = (holding_horizon or "").strip().lower()
    if horizon not in _HORIZONS:
        raise ValueError(f"holding_horizon 须为 long/mid/trade，收到：{holding_horizon!r}")

    # --- R1-R3 最终校验（落库前的最后一道硬约束） ---
    ka_texts = [
        (a["text"] if isinstance(a, dict) else str(a)) for a in (key_assumptions or [])
    ]
    mr_texts = [
        (m.get("mirror_text") or m.get("text") or "") for m in (mirrors or [])
    ]
    all_text = " ".join([holding_reason_raw] + ka_texts + mr_texts + [note])
    violations = redline.find_violations(all_text, _PHRASES)
    if violations:
        raise redline.RedlineViolation(violations, all_text)

    # --- 组装 ThesisCard（仓位档不进录入 agent，refactor-spec §8；filer_type 查表 Phase 2 接） ---
    assumptions = [
        Assumption(text=(a["text"] if isinstance(a, dict) else str(a)),
                   judgeable=(a.get("judgeable", True) if isinstance(a, dict) else True))
        for a in (key_assumptions or [])
    ]
    broken = []
    for m in (mirrors or []):
        mtext = m.get("mirror_text") or m.get("text") or ""
        bc = make_mirror(
            Assumption(text=m.get("assumption_text", "")), mtext,
            threshold=m.get("threshold"), source_type=m.get("source_type", ""),
        )
        if bc is not None:
            broken.append(bc)
    broken.extend(default_redline_pack(_THRESHOLDS))  # Layer 2 红线默认包

    manual = [
        ManualCheckItem(
            text=(mi.get("text", "") if isinstance(mi, dict) else str(mi)),
            reason=(mi.get("reason", "价格图形型") if isinstance(mi, dict) else "价格图形型"),
            cadence=(mi.get("cadence", "monthly") if isinstance(mi, dict) else "monthly"),
        )
        for mi in (manual_items or [])
    ]

    ea_obj = EntryAnchorData(
        anchor_type=anchor_type,
        anchor_value=anchor_value if isinstance(anchor_value, (int, float)) else None,
        note=note,
    )
    nv_obj = None
    if next_verdict:
        nv_obj = NextVerdictData(
            event=next_verdict.get("event", ""),
            date=next_verdict.get("date"),
            source_note=next_verdict.get("source_note", ""),
        )

    card = ThesisCard(
        user_id="beta1",  # 预置账号（5 人 beta）；Phase 2 接 serve 时按会话取
        ticker=ticker.upper(),
        filer_type=FilerType.OTHER,  # P0：不经 LLM；查表路由 Phase 2/4 接
        holding_reason_raw=holding_reason_raw,
        key_assumptions=assumptions,
        broken_conditions=broken,
        manual_check_items=manual,
        entry_anchor=ea_obj,
        next_verdict=nv_obj,
        position_cap_tier=None,  # refactor-spec §8：仓位档不放进录入 agent
        holding_horizon=horizon,
        confirmation=Confirmation(paraphrased=True, confirmed_by_user=True, confirmed_at=_now_iso()),
    )
    _get_store().upsert_card(card)
    return {"saved": True, "card_id": card.card_id, "ticker": card.ticker}


@function_tool(strict_mode=False)  # 含 list[dict]/dict 嵌套入参，strict schema 不稳；关掉保可靠
def save_card(
    ticker: str,
    holding_reason_raw: str,
    key_assumptions: list,
    mirrors: list,
    entry_anchor: dict,
    holding_horizon: str,
    confirmed_by_user: bool,
    manual_items: list | None = None,
    next_verdict: dict | None = None,
) -> dict:
    """保存 thesis card 到数据库。**只在用户明确确认后调**（confirmed_by_user=True）。
    5 个必填字段（ticker / holding_reason_raw / key_assumptions / mirrors / entry_anchor /
    holding_horizon）缺一不可，不允许部分保存。entry_anchor 的数值必须来自用户，不要编造。"""
    return _save_card_impl(
        ticker=ticker, holding_reason_raw=holding_reason_raw, key_assumptions=key_assumptions,
        mirrors=mirrors, entry_anchor=entry_anchor, holding_horizon=holding_horizon,
        confirmed_by_user=confirmed_by_user, manual_items=manual_items, next_verdict=next_verdict,
    )


@function_tool
def check_filing(ticker: str) -> dict:
    """查询某 ticker 最近一份 SEC filing（10-K/10-Q/20-F/6-K），用于回答用户在确认阶段
    的问题（如「最近财报什么时候？」）。返回 {form_type, filed_at, url, title} 或 {found:false}。
    取不到明说「查不到」，不编造（R5）。"""
    ev = sec_edgar.fetch_latest_filing(ticker)
    if ev is None:
        return {"found": False}
    return {
        "found": True,
        "form_type": ev.form_type,
        "filed_at": ev.filed_at.date().isoformat() if hasattr(ev.filed_at, "date") else str(ev.filed_at),
        "url": ev.url,
        "title": ev.title,
    }


# =========================================================================== #
# Guardrails —— 第二道防线（确定性代码，100% 可靠）
# =========================================================================== #


@output_guardrail
async def redline_guard(ctx, agent, output) -> GuardrailFunctionOutput:
    """检查 LLM 最终输出是否踩 R1-R3 红线（看涨/看跌/买卖建议/无源表述）。
    命中即 tripwire，SDK 自动拦截。复用 redline.find_violations，redline.py 不动。"""
    text = output if isinstance(output, str) else str(output or "")
    violations = redline.find_violations(text, _PHRASES)
    return GuardrailFunctionOutput(
        output_info={"violations": violations},
        tripwire_triggered=bool(violations),
    )


@input_guardrail(run_in_parallel=False)  # 防注入须在 agent 动作前阻断，不并行
async def injection_guard(ctx, agent, input) -> GuardrailFunctionOutput:
    """轻量关键词匹配，防用户诱导 LLM 给买卖/预测建议。命中即阻断。不做 LLM 判断。"""
    text = input if isinstance(input, str) else str(input)
    dangerous = [
        "帮我分析能不能买", "你觉得会涨吗", "你觉得会跌吗",
        "推荐一只股票", "推荐一只", "该不该买", "该不该卖",
        "能不能加仓", "建议买入", "建议卖出",
    ]
    hit = [p for p in dangerous if p in text]
    return GuardrailFunctionOutput(
        output_info={"reason": "用户在诱导投资建议", "hits": hit} if hit else {},
        tripwire_triggered=bool(hit),
    )


# =========================================================================== #
# Agent 定义
# =========================================================================== #

agent = Agent(
    name="ThesisGuard",
    instructions=SYSTEM_PROMPT,
    model=_MODEL,
    tools=[resolve_ticker, extract_card, generate_menu, save_card, check_filing],
    output_guardrails=[redline_guard],
    input_guardrails=[injection_guard],
)


def build_agent(cfg: dict | None = None) -> Agent:
    """显式按 cfg 重建 agent（Phase 2 接 serve / 测试用）。cfg=None 走默认 config.yaml。"""
    if cfg is None:
        return agent
    from agents import Agent as _A
    model = _build_model(cfg)
    return _A(
        name="ThesisGuard",
        instructions=SYSTEM_PROMPT,
        model=model,
        tools=[resolve_ticker, extract_card, generate_menu, save_card, check_filing],
        output_guardrails=[redline_guard],
        input_guardrails=[injection_guard],
    )


__all__ = [
    "SYSTEM_PROMPT",
    "agent",
    "build_agent",
    "resolve_ticker",
    "extract_card",
    "generate_menu",
    "save_card",
    "check_filing",
    "redline_guard",
    "injection_guard",
]
