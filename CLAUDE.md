# CLAUDE.md — 项目工作指南

本文件给在本仓库工作的 Claude Code 会话提供上下文。每个会话开始前先读这里。

## 这是什么项目

个人持仓条件核对 Agent（Thesis Watch），移动端优先 PWA。详见 `README.md` 与 `docs/PRD.md`。

## 不可违反的红线（硬规则）

实现任何东西之前，先确认不踩这 7 条（详见 README「红线」表）：

1. 不给买卖建议、不推荐标的、不做仓位建议
2. 不预测涨跌、不输出目标价、不承诺收益
3. 不出现「看涨/看跌/建议关注」措辞（渲染层加文案黑名单）
4. 不接入券商账户、不读真实持仓、不代客操作（持仓全部用户手录）
5. 每条事实必须附一手原文链接，禁止无源表述
6. 判断权归用户：只呈现「条件 X 今天出现了对应事件」，不替用户结论
7. **禁止写入用户的 Notion 工作区任何页面/数据库**
8. **eval ground truth 必须由作者手工标注**——Claude/任何模型不许生成、推断、或用模型产出去填；harness 读独立文件 `evals/ground_truth.yaml`（与代码和模型产物完全分离），文件缺失或字段为空 → 报错退出，**绝不允许用模型输出兜底**
9. **仓库转 public / 对外分享 / 作品集展示前，必须移除或脱敏**：`assets/`、`evals/ground_truth.yaml`、`evals/blind_verdicts.yaml`、`evals/blind_pairs.yaml`、及任何含真实持仓/真实 thesis/真实金额的文件；**新增此类文件时必须同步更新本清单**

## Notion 用法（只读快照，禁止写入）

- 本地接了 Notion MCP。**只允许用于只读刷新 `assets/` 快照**。
- 禁止写入或修改「🧭 持仓 Thesis · 价值投资台账」「📊 Pre-Market Briefing · 开盘前简报」——它们是生产投资记录，现有复查 Skill 在同库读写。
- eval 一律以 `assets/` 下的快照文件为准，不要去读 Notion 活库（台账每天被回写，不冻结则不可复现）。
- 产品的 thesis 卡数据一律存产品自己的数据库，不以 Notion 为存储。

## 资产现状

- `assets/` 已落地（2026-08-01，不再是空）：
  - `assets/notion/thesis/` — 台账 16 行全量：`00_schema_and_small_rows.md`（schema + QQQ/DPZ/SPGI/GDXU）+ 12 个 ticker 单文件（NVDA/VEEV/MCO/GOOGL/CGNX/NOW/NFLX/CRM/FIS/FDS/HSBC/BRK.B）。**复盘备注逐字照抄，未做任何摘要**（eval ground truth，摘要即废）。
  - `assets/notion/briefing_db_overview.md`（简报库 schema + 71 行元数据，单日正文留 Notion）、`assets/notion/skill_thesis_review_v4.md`（复查 Skill v4 全文，核对 Agent 提示词起点）、`assets/notion/spec_public_v1_20260610.md`（历史 spec）、`assets/onboarding_dryrun_0731.md`（录入演练 transcript）。
- Notion MCP **只读可达**（`notion-fetch` + `notion-search` 的 `workspace_search` 模式；AI 语义搜索不稳，优先 workspace_search）。只用于只读刷新 `assets/` 快照，禁止写入（R7）。
- 复用源码来自私有库 `hhaa134323/pre-market-briefing`，**仍未 clone 到本机**（GitHub 直连受阻，见 `docs/BLOCKERS.md` B1）。需要时先告诉作者，别自重写。

## 协作边界

- 需求优先级、砍什么留什么、指标怎么定，**由作者决定**，Claude 不替拍。
- Claude 负责：实现、指出技术风险、在里程碑结束前汇总并请作者确认。
- 涉及产品决策的地方，写 v1 提案 + 理由 + 待作者确认，不直接定死。

## 文档先于代码

新增功能前先更新 `docs/` 对应文档；每次迭代在 `docs/changelog.md` 记录依据、砍了什么、为什么。

## 技术选型倾向

- Agent loop 用 Claude Code 原生能力（Claude Agent SDK / 原生 tool-use loop），不引入 Dify/LangChain，除非证明原生不够。选型理由在 `docs/harness-design.md`。
- 后端从简：Python（FastAPI + 单库 SQLite）+ 复用 Python fetchers。
- 前端 PWA：待 `docs/harness-design.md` 选型确认。
