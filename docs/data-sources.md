# 可用数据源清单（W2 输入，2026-08-02 v0.2，**待作者审核一次后固定**）

> 用途：
> 1. 决定破局条件能否自动监测——所需信息在 v1 数据源内 → 自动；不在 → 进 `manual_items`（规则推导，见 `condition_classify.py`，不手标）。
> 2. `manual_items` ground truth 由本清单 + `classify_condition` 推导，不手标（R8 精神：确定性信息不交人/模型猜）。
> 与 `position_cap_tier` 同类问题（按 ticker 查 tier_map），都是规则推导。

## v1 数据源（可自动核对）

| 数据源 | 可获取内容 | 粒度 | 更新频率 | 备注 |
|--------|-----------|------|---------|------|
| **行 A：XBRL 结构化字段** | 标准财报数字（营收 / EPS / 毛利率 / 净利 / 现金流 / capex / 资产负债等，SEC filings XBRL 标签） | per-filing / per-line-item | 季频（10-K/10-Q/20-F）+ 事件驱动（8-K/6-K） | 可靠、可程序化取用；复用 `pre-market-briefing/src/fetchers/sec_edgar.py`（待 clone, B1） |
| **行 B：公司自定义指标（press release / 电话会文本）** | ASV、ASV 续约率、cRPO、NRR、Agentforce ARR、dollar attrition、combined ratio、MIS 收入拆分、MA ARR 等 | per-filing | 季频 + 事件驱动 | **需 LLM 从 EX-99.1 / 电话会 transcript 抽取**（半自动）；字段口径公司自定义，非 XBRL 标准 |
| 公开新闻 RSS | Yahoo 按 ticker 头条（去重、不过滤） | headline | 日频 | 复用 `news.py` |
| ~~行情 / 价格数据~~ | ~~价格、K 线、技术指标~~ | — | — | **v1 不接**（红线：不用需商业授权的行情；价格类警报留 v2）→ `price_pattern` 类条件进 `manual_items` |
| ~~ETF/基金数据~~ | ~~指数成分 / 基金 holdings / AUM / 规模~~ | — | — | **v1 不接**（W2+）→ ETF 类标的破条件全 `manual_items` |

**行 B 覆盖说明（重要）**：FDS / CRM / NOW 的核心判据 **100% 落在行 B**；MCO / BRK 各占一半。含义：**这几只票的可信度取决于文本抽取质量，不是取数可靠性**——LLM 抽错 = 判据错，即便取数链路无误。eval 时这几只的 press_release_text 字段须重点核。

## 缺失能力：字段消失检测

CRM 的破局条件之一「**公司停止披露该指标 = 红旗**」需要：比对本季 vs 上季披露的指标集合，发现**消失项**（某指标上季还报、本季不报）。v1 缺此能力（需持久化每季披露的指标集合 + 跨期 diff）。补上后归入行 B 的扩展。

## 六类缺口（v1 不支持 → `manual_items`，规则推导分类见 `condition_classify.py`）

| # | 缺口 | 需要它的票 | v1 是否支持 | 缺什么 |
|---|------|-----------|-----------|-------|
| ① | 市占率 / 份额 | NVDA · MCO · GOOGL · CGNX · FIS | ❌ | 第三方市占率数据（Gartner / IDC / Statista 等，商业授权或免费不全） |
| ② | 非美上市竞品 | CGNX 的 Keyence（6861.T，日股，不报 SEC） | ❌ | 非美交易所披露（东证 / 港交所等）；需按地区接不同源 |
| ③ | 私人公司竞品 | FDS 的 Bloomberg / AlphaSense；VEEV 相关方；OpenAI | ❌ | 私人公司无公开财报；靠新闻 / 融资公告 / 采访，不可靠 |
| ④ | 监管立法进程 | MCO（提案阶段即进观察项）；GOOGL 反垄断 | ❌ | 立法追踪（提案→一读→通过→生效），无标准源；新闻 RSS 太噪 |
| ⑤ | 跨主体取数 | NVDA 的条件要求读 MSFT / GOOGL / AMZN / META 的 capex 指引 | ❌ | 跨主体财报读取（读别家 filing 的特定字段），v1 只读本标的 |
| ⑥ | 历史状态存储 | 「连续 2 季」「连续 2 年」是跨时间比较 | ❌ | 持久化每季度的数值 + 跨期 diff（不是单次取数）；含上面的「字段消失检测」 |

## ETF/基金类标的（QQQ / GDXU 等）

- **v1 不支持 ETF 类自动核对**：ETF/ETN 无公司层面 10-K/20-F，破条件依赖指数成分 / 基金 holdings / AUM / 价格，均不在 v1 数据源内。
- **影响**：QQQ 是最大单一仓位（宽基档 ~50%）——v1 只能**人工自查**，不进自动核对。**不静默跳过**：GT 标 `filer_type=etf_fund`，harness 把 QQQ 的所有破条件记为 `manual_items`，单独统计。
- **W2+ 数据源**：指数成分 rebalancing 公告、基金 holdings / 份额变动、AUM / 规模、价格（价格仍 v2）。

## 规则

- 破局条件 `classify_condition` → InfoType：`xbrl_structured`（行 A）/ `press_release_text`（行 B）→ v1 可自动；其余 8 类（`market_share` / `non_us_listed` / `private_company` / `regulatory_process` / `third_party_data` / `price_pattern` / `cross_entity_filing` / `qualitative`）→ `manual_items`。
- `manual_items` ground truth = 本规则推导，**不手标**（不入 `evals/ground_truth.yaml`）。
- **预处理排除否定从句**：「注：xx 不算破」「xx 不构成破局」不参与分类。

## 待作者审核

- v1 数据源（行 A / 行 B / 新闻）是否齐全？行 B 的 LLM 抽取口径？
- 六类缺口 W2 接入顺序（按「能提高覆盖率多少」排，见 PRD §12 W2 重排）？
- `condition_classify.py` 的分类规则（`docs/condition-classification.md` 表）逐条确认后固化。
