# 可用数据源清单（W2 输入，2026-08-02 v0.1，**待作者审核一次后固定**）

> 用途：
> 1. 决定破局条件能否自动监测——所需信息在清单内 → 自动；不在 → 进 `manual_items`。
> 2. `manual_items` 的 ground truth 由本清单 + 规则**推导**，不手标（R8 精神：确定性信息不交人/模型猜）。
> 与 `position_cap_tier` 同类问题（按 ticker 查 tier_map），都是规则推导，不是标注题。

## 清单（W2 能接到的数据类型）

| 数据源 | 可获取内容 | 粒度 | 更新频率 | 备注 |
|--------|-----------|------|---------|------|
| SEC EDGAR filings | 10-K / 10-Q / 20-F / 6-K / 8-K 正文 + EX-99.1 press release；财报数字（营收 / EPS / 毛利率 / 指引）、MD&A、风险因子、高管变动、财报重述 | per-filing / per-line-item | 季频（10-K/10-Q/20-F）+ 事件驱动（8-K/6-K） | 复用 `pre-market-briefing/src/fetchers/sec_edgar.py`（待 clone, B1）；外国发行人以 6-K 为主渠道 |
| 公开新闻 RSS | Yahoo 按 ticker 头条（去重、不过滤） | headline | 日频 | 复用 `news.py` |
| ~~行情 / 价格数据~~ | ~~价格、K 线、技术指标（均线/形态/突破/支撑阻力）~~ | — | — | **v1 不接**（红线：不用需商业授权的行情；价格类警报留 v2）→ 价格图形型条件进 `manual_items` |
| ~~ETF/基金数据（指数成分/基金 holdings/公告/AUM/规模）~~ | ~~指数 rebalancing、基金持仓变动、份额/规模~~ | per-rebalance / per-filing | 季频+事件 | **v1 不接**（W2+ 考虑）→ ETF 类标的破条件全 `manual_items`（见下） |

## ETF/基金类标的（QQQ / GDXU 等）

- **v1 不支持 ETF 类自动核对**：ETF/ETN 无公司层面 10-K/20-F，破条件依赖指数成分 rebalancing / 基金 holdings+公告 / AUM+规模 / 价格数据，均不在 v1 数据源（SEC filings + 新闻 RSS）内。
- **影响**：QQQ 是最大单一仓位（宽基档 ~50%）——v1 只能**人工自查**，不进自动核对。**不能悄悄跳过**：GT 标 `filer_type=etf_fund`，harness 把 QQQ 的所有破条件记为 `manual_items`，单独统计。
- **W2+ 数据源**（接入后可支持）：指数成分 rebalancing 公告、基金 holdings/份额变动、AUM/规模、价格（价格仍 v2）。

## 规则

- 破局条件所需信息在清单内（SEC filings 字段 / 财报数字 / 新闻标题）→ **可自动监测**。
- 不在清单内（价格 / 技术指标、需商业授权数据）→ **进 `manual_items`**（每月人工自查）。
- `manual_items` ground truth = 本规则推导，**不手标**（不入 `evals/ground_truth.yaml`）。

## W1 简化

W1 用 `conditions.is_price_pattern(thesis_text)` 作 `manual_items` GT 的近似规则（thesis 含价格图形词 → manual；否则期望空）。完整的「逐条破局条件 vs 清单」规则是 W2（需 mirrors 已定 + 复用 fetchers 落地后）。

## 待作者审核

- 清单是否齐全？粒度 / 频率对不对？
- W2 还计划接什么数据源（如交易所公告、监管站点、行业数据库）？
- 审核后固定，W2 接入 fetcher 时按此实现。
