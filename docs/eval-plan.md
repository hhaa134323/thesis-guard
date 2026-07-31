# Eval 计划 + 埋点方案 + 评估口径（v0.1）

| 项 | 值 |
|----|----|
| 版本 | v0.1 草稿 |
| 基准 | `assets/notion/thesis_db_part1-4.md` 快照（2026-07-31 定格，待 B1/B3 解除） |

## 1. 双层 eval

### Layer 1 — 对话抽取一致率（W1，目标 ≥ 85%）

- **任务**：录入 Agent 从一段自然对话抽取 thesis 卡，与人工标注台账比对。
- **基准**：台账 15 行（`holding_reason` + 关键假设 + 复盘条件）。
- **口径**：字段级一致率 = 一致字段数 / 总字段数；逐卡平均。
- **error analysis**：错抽 / 漏抽 / 多抽 / 可判定性误判，分类计数，对应 `docs/harness-design.md` error taxonomy。

### Layer 2 — 事件×条件判定一致率（W2，目标 ≥ 80%）

- **任务**：核对 Agent 对「某事件是否击中某条件」做判定，与人工复查记录比对。
- **基准**：台账两个月复盘备注（人工判定结果）。
- **口径**：判定一致率 = 与人工一致的 (条件,事件) 数 / 总 (条件,事件) 数。
- **附**：误报率（agent `triggered` 且人工否）/ 漏报率（人工 `triggered` 但 agent 漏）。

## 2. 埋点方案（tracking）

### 2.1 录入漏斗
- `entry_start` / `entry_assumption_added` / `entry_cond_menu_shown` / `entry_cond_user_spoken`（用户自发）/ `entry_cond_menu_picked`（菜单选）/ `entry_confirm` / `entry_abandon`
- **专项观察（W3）**：破条件「用户自发说出」vs「菜单挑选」比例 = `user_spoken / (user_spoken + menu_picked)`。

### 2.2 核对结果
- `check_run` / `check_cond_status`（untriggered|watch|triggered）/ `check_refusal`（原因码 E1–E8）

### 2.3 用户收尾
- `user_resolve`（confirmed_broken | false_alarm | ignored）

### 2.4 留存与决策影响（KILL 判据输入）
- `app_open_daily`（每日打开，7 天窗口）
- `decision_influence`（用户自报「这次核对影响了我对这只票的判断」——埋点按钮）

### 2.5 eval 自动沉淀
- 误报 / 确认 → 自动写入 eval 标注集（`review_notes`），扩充后续 eval 基准。

## 3. KILL 判据（W4 体检）

- 7 天内打开少于 5 天 → 停。
- 没有一次 `decision_influence` → 停。
- 命中其一即停掉不养老，结果记 `docs/changelog.md`。

## 4. 评估口径定义

- **一致率**：严格字段/判定匹配，不含「方向对但措辞不同」。
- **误报**：agent `triggered` 且人工 `not_triggered`。
- **漏报**：agent 漏掉人工 `triggered`。
- **拒判**：不计入分母错误，单独报「拒判率 + 拒判原因分布」（拒判是设计行为，不是失败）。

## 5. 阻塞

- B1/B3 未解除前，eval 无法跑（无基准快照）。本文件为计划，待基准落地后执行并产出 `docs/eval-report.md`。
