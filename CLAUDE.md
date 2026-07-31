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

## Notion 用法（只读快照，禁止写入）

- 本地接了 Notion MCP。**只允许用于只读刷新 `assets/` 快照**。
- 禁止写入或修改「🧭 持仓 Thesis · 价值投资台账」「📊 Pre-Market Briefing · 开盘前简报」——它们是生产投资记录，现有复查 Skill 在同库读写。
- eval 一律以 `assets/` 下的快照文件为准，不要去读 Notion 活库（台账每天被回写，不冻结则不可复现）。
- 产品的 thesis 卡数据一律存产品自己的数据库，不以 Notion 为存储。

## 资产现状

- `assets/` 目前为空。目标里假设的 5 个快照文件尚未落地（见 `docs/BLOCKERS.md` B3）。在快照落地前，依赖基准的 eval / 行为 spec 无法完成。
- 复用源码来自私有库 `hhaa134323/pre-market-briefing`，尚未 clone（见 `docs/BLOCKERS.md` B1）。

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
