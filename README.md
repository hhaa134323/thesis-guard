# 个人持仓条件核对 Agent（Thesis Watch）

> 移动端优先的 PWA。用户用自然对话告诉 AI「我为什么持有这只票」，AI 追问并把破局条件整理成确认卡；之后每天由核对 Agent 用一手公开披露自动核对这些条件。命中当天单独发邮件，未命中合并进每日简报。**判断权永远归用户。**

## 项目状态

- 阶段：**第 1 周里程碑启动**（对话录入跑通）
- 当前版本：v0.0.1（仓库骨架 + 设计文档 v0.1）
- 日期：2026-07-31
- 状态详情见 `docs/changelog.md`，阻塞项见 `docs/BLOCKERS.md`

## 产品定位（一句话）

让自主决策的个人投资者，以每天 1 分钟的时间成本完成持仓逻辑体检；建设者侧作为从 0 到 1 的 Agent harness 项目，核心交付是 harness 本身、双层 eval 与 error analysis 闭环。

## 红线（任何实现都不得违反）

| # | 红线 | 说明 |
|---|------|------|
| R1 | 不给买卖建议、不推荐标的、不做仓位建议 | 只核对条件是否被事件击中，不下结论 |
| R2 | 不预测涨跌、不输出目标价、不承诺收益 | |
| R3 | 不出现「看涨/看跌/建议关注」措辞 | 渲染层加文案黑名单校验 |
| R4 | 不接入任何券商账户、不读取真实持仓、不代客操作 | 持仓全部用户手录 |
| R5 | 每条事实必须附一手原文链接 | 禁止「市场预期」「据传」等无源表述 |
| R6 | 判断权归用户 | 只呈现「你定的条件 X 今天出现了对应事件」，不替用户结论 |
| R7 | 禁止写入用户的 Notion 工作区任何页面/数据库 | Notion 资产以本 repo `assets/` 快照为准 |
| R8 | eval ground truth 必须由作者手工标注，不许模型生成/推断/兜底 | harness 读独立 `evals/ground_truth.yaml`；缺失或字段为空 → 报错退出，不用模型输出兜底 |

红线源自复用资产 `pre-market-briefing/README.md` 的「AI 边界（硬规则）」表（4 条可以 vs 5 条不可以），原样沿用并扩充。

## 技术与分发约束

- PWA，移动端优先；不上应用商店，不提交小程序审核
- 数据源仅限 SEC EDGAR 官方接口和公开新闻标题 RSS
- 按申报方类型路由披露表单：外国发行人（20-F/6-K 申报方）以 **6-K 为主渠道**，不得沿用美国本土公司的「6-K 降级」规则
- 不使用任何需要商业授权的行情数据；v1 不含价格类警报
- v1 锁美股，不做 A 股/港股
- 触达仅邮件：命中条件当天单独发；未命中合并进每日简报一行带过；PWA 推送留到 v2
- 后端从简：预置账号（5 人 beta 不做注册系统）、仅邮件触达、单数据库
- LLM 调用成本由作者自担，不做付费功能

## 复用资产（来自 `hhaa134323/pre-market-briefing` 私有库，直接复用不重写）

| 模块 | 用途 | 复用方式 |
|------|------|----------|
| `src/fetchers/sec_edgar.py` | SEC EDGAR 多表单抓取 | 直接复用，按申报方类型路由 |
| `src/fetchers/news.py` | Yahoo 按 ticker 头条 RSS（去重、不过滤） | 直接复用 |
| `src/fetchers/thesis.py` | 读 Notion Thesis 台账的只读实现 | 其 schema 即新产品 thesis 卡 schema 的基线 |
| `src/alerts/` | config 驱动的警报判定 | 阈值思路沿用，改为用户可配 |
| `src/render/thesis_section.py` | thesis 复查段输出样式 | 样式参考 |
| `src/sinks/` | Gmail SMTP 发送 | 邮件触达直接复用 |
| `config.example.yaml` | 阈值配置结构 | 参考 |
| `README.md` | 「AI 边界（硬规则）」表 | 红线基线 |

**明确不复用**：`tools/snapshot_pusher.py`、`src/fetchers/holdings.py`（OpenD 持仓链路，本产品改为用户手录，无对应物）。

## Notion 资产（eval 基准已快照定格，活库只读、禁止写入）

对话抽取 eval 与条件判定 eval 的基准集 = 本 repo `assets/` 下的快照文件（2026-08-01 定格）。**一律以文件为准，不要去读 Notion 活库**——台账每天被现有复查流程更新（复盘备注自动回写），基准不冻结，eval 就不可复现。

快照清单（2026-08-01 已从 Notion 只读拉取定格，复盘备注逐字照抄）：

- `assets/notion/thesis/` — 台账 **16 行全量** + 两个月复盘备注（**两层 eval 的核心基准**）。拆为 `00_schema_and_small_rows.md`（schema + QQQ/DPZ/SPGI/GDXU）+ 12 个 ticker 单文件（NVDA/VEEV/MCO/GOOGL/CGNX/NOW/NFLX/CRM/FIS/FDS/HSBC/BRK.B）。
- `assets/notion/briefing_db_overview.md` — 简报库 schema + 71 行元数据（单日正文留 Notion）。
- `assets/notion/skill_thesis_review_v4.md` — 复查 Skill v4 全文（核对 Agent 提示词起点）。
- `assets/notion/spec_public_v1_20260610.md` — 历史 spec（参考后归档）。
- `assets/onboarding_dryrun_0731.md` — 录入演练 transcript（录入 Agent 行为 spec 基线）。

> Notion MCP 只读可达（`workspace_search` 模式）；刷新快照走只读，**禁止写入**（R7）。台账与简报库是生产投资记录。

## 文档索引

| 文档 | 内容 | 状态 |
|------|------|------|
| `docs/PRD.md` | 核心场景、非目标、红线、需求证据、沿革 | v0.1 草稿 |
| `docs/harness-design.md` | loop 结构图、工具清单、拒判策略、error taxonomy | v0.1 草稿 |
| `docs/thesis-card-schema.md` | thesis 卡结构化 schema | v0.1 草稿 |
| `docs/broken-condition-schema.md` | 破条件两层结构 + 理由 | v0.1 草稿 |
| `docs/eval-plan.md` | 双层 eval 口径 + 埋点方案 + KILL 判据 | v0.1 草稿 |
| `docs/entry-agent-spec.md` | 录入 Agent 行为 spec | 🔵 进行中（transcript 已就位，W1） |
| `docs/eval-report.md` | 一致率报告（≥85% / ≥80%） | 🔵 进行中（基准已就位，待跑 L1） |
| `docs/competitor-teardown.md` | 竞品横测（项目六方法） | ⛔ 阻塞（缺网络） |
| `docs/changelog.md` | 版本变更记录 | 进行中 |
| `docs/BLOCKERS.md` | 阻塞项与缓解 runbook | 进行中 |

## 协作约定

- 需求优先级、砍什么留什么、指标怎么定，由作者决定；实现与指出技术风险由 Claude 负责。
- 每个里程碑结束前先跟作者确认再往下走。
- 每次迭代写清楚依据哪条用户反馈、砍了什么、为什么砍（见 `docs/changelog.md`）。
