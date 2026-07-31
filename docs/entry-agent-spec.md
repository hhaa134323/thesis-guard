# 录入 Agent 行为 spec

| 项 | 值 |
|----|----|
| 版本 | 未启动 |
| 状态 | ⛔ BLOCKED — 缺 `assets/onboarding_dryrun_0731.md` 演练 transcript（B1/B3） |

## 阻塞说明

本 spec 须**以演练 transcript 为基线**撰写（目标要求）。transcript 尚未落地（Notion 快照未拉取），故本文件仅列大纲，待 B1 解除后基于 transcript 回填并附首批 eval 用例。

## 大纲（待 transcript 回填）

1. 角色与边界：录入 Agent 只做「对话抽取 + 可判定性追问 + 编译确认卡」，不下任何投资结论（红线 R1/R6）。
2. 对话流：
   - 开场：请用户用一句话说持有理由。
   - 抽取：从原话抽 `holding_reason_raw` + `key_assumptions`。
   - 可判定性追问：每条假设追问「破它会是什么样的事件 + 能不能从一手披露看到」；不可判定 → 改造或降级人工自查。
   - 镜像生成：从假设自动给候选镜像条件（Layer 1），用户可改可加。
   - 红线默认包：下发大额罚单/高管突变/财报重述（Layer 2），用户可调阈值/关停。
   - 「无法确定」菜单：假设与其镜像成对给出，选一次填两槽；每条附真实历史事件示例。
   - 复述确认：用结构化卡片回述，用户确认后入库。
3. 价格图形型识别：原话含均线/形态/突破等 → 记 `manual_check_items`（cadence=monthly），不进自动核对。
4. 首批 eval 用例（待 transcript 抽取）：
   - 每条 transcript 段 → 期望 thesis 卡 → 字段级一致率（W1 ≥ 85%）。
   - 覆盖：正常抽取、漏抽、可判定性误判、价格图形降级、菜单挑选 vs 自发。

## 依赖

- `assets/onboarding_dryrun_0731.md`（演练 transcript）
- `docs/thesis-card-schema.md` v1（字段对齐）
- `docs/broken-condition-schema.md`（两层逻辑）
