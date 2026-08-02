"""破局条件分类（v0.3，2026-08-02 修 negation + multi-label + _split_conditions）。

作者 2026-08-02 定（【十】）：
- _split_conditions 切错（按排版结构硬切 → 误切出非条件 → manual_items GT 退化为常量）。
  改：剥离结构行 + 保留 condition_tier(lagging|leading) + 续行合并。
- negation 误判 NVDA 2 条核心条件（「区别于单季」sentinel 误剥整条）。
  改：negation 仅识别排除性说明（注：...不算破），不作用于条件主句；删「区别于」sentinel。
- BRK.B combined ratio → 原判 press_release_text（v1-auto），但 BRK 不发 press release，
  需从 10-K 保险分部脚注推算 → 改 manual（删 combined ratio 出 _PRESS_METRICS）。
- multi-label：CGNX 一条件同时属 non_us_listed + market_share → classify_condition 返回 list[InfoType]。
  is_v1_auto = 全部标签可自动才算 True。

⚠️ 规则近似，输出进 GT 前必须经作者人工确认（docs/condition-classification.md）。
"""
from __future__ import annotations

import enum
import re


class InfoType(str, enum.Enum):
    MARKET_SHARE = "market_share"
    NON_US_LISTED = "non_us_listed"
    PRIVATE_COMPANY = "private_company"
    REGULATORY_PROCESS = "regulatory_process"
    THIRD_PARTY_DATA = "third_party_data"
    PRICE_PATTERN = "price_pattern"
    CROSS_ENTITY_FILING = "cross_entity_filing"
    QUALITATIVE = "qualitative"
    XBRL_STRUCTURED = "xbrl_structured"
    PRESS_RELEASE_TEXT = "press_release_text"


V1_AUTO = {InfoType.XBRL_STRUCTURED, InfoType.PRESS_RELEASE_TEXT}

# negation sentinels：仅排除性说明（注：...不算破），不含「区别于」（那是条件内澄清，非否定）
_NEGATION_SENTINELS = ["不算破", "不构成破局", "不构成破", "不算破局", "不算破的条件"]

# 结构行前缀（剥离，不作为条件）
_STRUCTURE_PREFIXES = re.compile(
    r"^(量化滞后线|领先代理|A\.|B\.|【|注[：:]|①|②|③|④|⑤|⑥|⑦|⑧|⑨|⑩)"
)
# 章节归属关键词
_TIER_KEYWORDS = {"量化滞后线": "lagging", "领先代理": "leading"}


def strip_negation(text: str) -> str:
    """排除否定/排除说明从句。删「注：…」整段 + 含「不算破/不构成破局」的从句。
    不删「区别于…」（条件内澄清，非否定）。"""
    if not text:
        return ""
    text = re.sub(r"注[：:][^；;\n]*", "", text)
    for sent in re.split(r"([；;\n])", text):
        if any(s in sent for s in _NEGATION_SENTINELS):
            text = text.replace(sent, "")
    return text.strip(" ；;，,")


def _split_conditions(text: str) -> list[tuple[str, str]]:
    """改进切分（v0.3）：按 ①②③④⑤+；+\n 切（不切 •——子项属条件内），
    剥离结构行（量化滞后线/A./B./【/注：），保留 condition_tier(lagging|leading)，续行合并。
    返回 [(condition_text, condition_tier), ...]。"""
    if not text:
        return []
    # 按 ①②③④⑤⑥⑦⑧⑨⑩ + ； + \n 切（条件级标记；不切 • 子项）
    raw_parts = re.split(r"([①②③④⑤⑥⑦⑧⑨⑩])", text)
    # 重组：序号开头的是新条件，其余是续行
    chunks: list[str] = []
    for p in raw_parts:
        p = p.strip()
        if not p:
            continue
        if re.match(r"^[①②③④⑤⑥⑦⑧⑨⑩]", p):
            chunks.append(p)
        elif chunks:
            chunks[-1] += p  # 续行合并到上一条
        else:
            chunks.append(p)  # 序号前的引导段（可能含 tier）
    conditions: list[tuple[str, str]] = []
    current_tier = ""
    for chunk in chunks:
        # 检测章节归属
        for kw, tier in _TIER_KEYWORDS.items():
            if kw in chunk:
                current_tier = tier
                break
        # 剥离纯结构行（量化滞后线标题/A./B./【/注：——不含条件内容）
        stripped = re.sub(r"^(量化滞后线|领先代理)[^：]*[：:].*", "", chunk)
        stripped = re.sub(r"^(A\.|B\.)\s*(硬滞后线|领先代理|量化)?[^：]*[：:]", "", stripped)
        stripped = re.sub(r"^【[^】]*】", "", stripped)
        stripped = re.sub(r"^注[：:][^；;\n]*", "", stripped)
        stripped = stripped.strip(" ；;，,。")
        if len(stripped) >= 5:
            conditions.append((stripped, current_tier))
    return conditions


# 公司自定义指标（press release 文本抽取）——删 combined ratio（BRK 不发 press release）
_PRESS_METRICS = re.compile(
    r"ASV|续约率|留存率|cRPO|NRR|Agentforce|dollar attrition|"
    r"MIS|MA ARR|订阅收入|churn|净留存|续订"
)
_XBRL = re.compile(
    r"营收|收入|EPS|每股收益|毛利率|净利|净利润|营业利润|revenue|income|"
    r"现金流|FCF|EBITDA|GAAP|non-GAAP|资产负债|每股|净利|利润率|capex|资本开支"
)
_MARKET_SHARE = re.compile(r"市占率|份额|market share|share|占有率")
_NON_US = re.compile(r"\d{4}\.[THKA]|日股|港股|非美|non-US|6861|Keyence|东京|东证")
_PRIVATE = re.compile(r"Bloomberg|AlphaSense|OpenAI|私人公司|未上市|private company|非上市")
_REGULATORY = re.compile(r"立法|监管|ESMA|反垄断|antitrust|regulation|裁定|罚单|监管机构|SEC.*罚|合规")
_CROSS_ENTITY = re.compile(r"MSFT|GOOGL|AMZN|META|别家|跨主体|的.*指引|的 capex|别家.*capex")
_THIRD_PARTY = re.compile(r"第三方|行业数据|industry data|行业报告|调研机构")
_QUALITATIVE = re.compile(r"战略|管理层|护城河|moat|文化|品牌|竞争优势|管理|战略清晰")


def classify_condition(text: str) -> list[InfoType]:
    """分类单条破局条件 → list[InfoType]（multi-label，【十】5）。
    空（否定-only）→ []。规则近似，需人工确认。"""
    t = strip_negation(text)
    if not t:
        return []
    labels: list[InfoType] = []
    if _NON_US.search(t):
        labels.append(InfoType.NON_US_LISTED)
    if _PRIVATE.search(t):
        labels.append(InfoType.PRIVATE_COMPANY)
    if _CROSS_ENTITY.search(t):
        labels.append(InfoType.CROSS_ENTITY_FILING)
    if _MARKET_SHARE.search(t):
        labels.append(InfoType.MARKET_SHARE)
    if _REGULATORY.search(t):
        labels.append(InfoType.REGULATORY_PROCESS)
    if _THIRD_PARTY.search(t):
        labels.append(InfoType.THIRD_PARTY_DATA)
    if _PRESS_METRICS.search(t):
        labels.append(InfoType.PRESS_RELEASE_TEXT)
    if _XBRL.search(t):
        labels.append(InfoType.XBRL_STRUCTURED)
    if _QUALITATIVE.search(t):
        labels.append(InfoType.QUALITATIVE)
    if not labels:
        labels.append(InfoType.QUALITATIVE)  # default
    return labels


def is_v1_auto(labels: list[InfoType] | InfoType | None) -> bool:
    """v1 可自动核对：全部标签可自动才算 True（【十】5 multi-label）。"""
    if labels is None:
        return False
    if isinstance(labels, InfoType):
        labels = [labels]
    return bool(labels) and all(l in V1_AUTO for l in labels)


def v1_gap_reasons(labels: list[InfoType]) -> list[str]:
    """v1 不可自动核对时的缺口理由列表。"""
    reasons = []
    for info in labels:
        if info not in V1_AUTO:
            reasons.append({
                InfoType.MARKET_SHARE: "v1 无市占率/份额数据源（data-sources ①）",
                InfoType.NON_US_LISTED: "非美上市主体不报 SEC（data-sources ②）",
                InfoType.PRIVATE_COMPANY: "私人公司竞品无公开财报（data-sources ③）",
                InfoType.REGULATORY_PROCESS: "监管立法进程 v1 不覆盖（data-sources ④）",
                InfoType.THIRD_PARTY_DATA: "第三方行业数据 v1 不覆盖",
                InfoType.PRICE_PATTERN: "价格/技术数据 v1 不接",
                InfoType.CROSS_ENTITY_FILING: "跨主体财报 v1 不覆盖（data-sources ⑤）",
                InfoType.QUALITATIVE: "主观定性，无可自动核对的数据",
            }.get(info, ""))
    return [r for r in reasons if r]
