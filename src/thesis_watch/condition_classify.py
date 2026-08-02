"""破局条件分类（v0.2，替代 conditions.is_price_pattern）。

作者 2026-08-02 定：is_price_pattern 判断方向错（假阳/假阴都有）——真正决定一条件能否
自动核对的，不是它提没提价格，而是「核对它需要什么类型的信息」。

分类维度（InfoType，按所需信息类型）：
  market_share          市占率 / 份额
  non_us_listed         非美上市主体（如 6861.T / 0700.HK）
  private_company       私人公司竞品（Bloomberg / AlphaSense / OpenAI）
  regulatory_process    监管立法进程（ESMA / 反垄断 / 裁定）
  third_party_data      第三方行业数据
  price_pattern         价格技术形态（均线 / 头肩 / 突破…）
  cross_entity_filing   跨主体财报（读别家 capex 指引等）
  qualitative           主观定性判断（战略 / 管理层 / moat）
  xbrl_structured       XBRL 结构化字段（v1 可自动）
  press_release_text   公司自定义指标，需 LLM 从 press release/电话会抽（v1 半自动）

v1 可自动核对 = xbrl_structured + press_release_text；其余 → manual_items。
（详见 docs/data-sources.md 的六类缺口。）

⚠️ 本分类器是规则近似，输出进 GT 前必须经作者人工确认（docs/condition-classification.md）。
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


# 否定从句排除：形如「注：xx 不算破」「xx 不构成破局」的整句不参与分类。
_NEGATION_SENTINELS = [
    "不算破", "不构成破局", "不构成破", "不算破局", "不算破的条件",
    "区别于单季", "区别于短期",
]


def strip_negation(text: str) -> str:
    """排除否定/排除说明从句。删「注：…不算破…」整段、「…不算破…」从句。"""
    if not text:
        return ""
    # 删以「注：」「注:」开头到句末（；\n 或结尾）的整段
    text = re.sub(r"注[：:][^；;\n]*", "", text)
    # 删含否定 sentinel 的从句（以 ；/；/，/，/。 分隔）
    for sent in re.split(r"([；;\n])", text):
        if any(s in sent for s in _NEGATION_SENTINELS):
            text = text.replace(sent, "")
    return text.strip(" ；;，,")


# 价格图形词（原 is_price_pattern，但配 false-positive 排除）
_PRICE_WORDS = re.compile(
    r"均线|头肩|双顶|双底|颈线|支撑位|阻力位|回踩|"
    r"放量|缩量|金叉|死叉|MACD|KDJ|布林|趋势线|"
    r"突破|收盘价|开盘价|最高价|最低价|K线|金叉|死叉"
)
# 价格词的 false positive（"低价竞品"等不是图形）
_PRICE_FP = re.compile(r"低价竞品|低价.*竞品|低价.*策略|股价回撤不算|回撤.*不算")

# 公司自定义指标（press release 文本抽取）
_PRESS_METRICS = re.compile(
    r"ASV|续约率|留存率|cRPO|NRR|RR|Agentforce|dollar attrition|"
    r"combined ratio|综合率|MIS|MA ARR|订阅收入|churn|净留存|续订"
)
# XBRL 结构化字段（标准财报数字）
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


def classify_condition(text: str) -> InfoType | None:
    """分类单条破局条件 → InfoType。空（否定-only）→ None。规则近似，需人工确认。"""
    t = strip_negation(text)
    if not t:
        return None
    # 优先级：先排最具体的（非美/私人/跨主体），再市占/监管，再价格（带 FP 排除），再指标，再 XBRL，最后定性
    if _NON_US.search(t):
        return InfoType.NON_US_LISTED
    if _PRIVATE.search(t):
        return InfoType.PRIVATE_COMPANY
    if _CROSS_ENTITY.search(t):
        return InfoType.CROSS_ENTITY_FILING
    if _MARKET_SHARE.search(t):
        return InfoType.MARKET_SHARE
    if _REGULATORY.search(t):
        return InfoType.REGULATORY_PROCESS
    if _THIRD_PARTY.search(t):
        return InfoType.THIRD_PARTY_DATA
    if _PRICE_WORDS.search(t) and not _PRICE_FP.search(t):
        return InfoType.PRICE_PATTERN
    if _PRESS_METRICS.search(t):
        return InfoType.PRESS_RELEASE_TEXT
    if _XBRL.search(t):
        return InfoType.XBRL_STRUCTURED
    return InfoType.QUALITATIVE


def is_v1_auto(info: InfoType | None) -> bool:
    """v1 可自动核对：xbrl_structured（自动）+ press_release_text（半自动，LLM 抽）。"""
    return info in V1_AUTO


def v1_gap_reason(info: InfoType) -> str:
    """v1 不可自动核对时的缺口理由（对应 data-sources.md 六类）。"""
    return {
        InfoType.MARKET_SHARE: "v1 无市占率/份额数据源（data-sources ①）",
        InfoType.NON_US_LISTED: "非美上市主体不报 SEC（data-sources ②）",
        InfoType.PRIVATE_COMPANY: "私人公司竞品无公开财报（data-sources ③）",
        InfoType.REGULATORY_PROCESS: "监管立法进程 v1 不覆盖（data-sources ④）",
        InfoType.THIRD_PARTY_DATA: "第三方行业数据 v1 不覆盖（data-sources ⑤）",
        InfoType.PRICE_PATTERN: "价格/技术数据 v1 不接（不用商业授权行情）",
        InfoType.CROSS_ENTITY_FILING: "跨主体财报 v1 不覆盖（data-sources ⑤）",
        InfoType.QUALITATIVE: "主观定性，无可自动核对的数据",
    }.get(info, "")
