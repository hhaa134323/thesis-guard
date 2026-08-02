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

## 6. Gate 门槛预注册（2026-08-01 定，写定不改）

> 之后任何调整都要在 `docs/changelog.md` 留记录和理由。

Gate 标准：5/5 结构化输出成功。

失败处理规则（按原因分类，不按通过率数字）：

- 403 / 400 provider 拒绝 → 可用性问题，换模型，门槛不动
- finish_reason=length → 配置问题，修配置重测，门槛不动
- SDK / 工具链校验失败 → 配置问题，修配置重测，门槛不动
- schema 不符 / 字段乱填 → 模型能力问题，先加重试，端到端仍到不了 5/5 才允许讨论降门槛，且必须记录理由

## 7. 排期依据：单轮 eval 耗时估算（2026-08-01）

任务模型 `glm-5.2-fast-preview` 实测 pass avg 58.6s/次（`docs/eval-report.md` §1）。
一轮 L1 eval = 15 case × A/B 对照（2 组）× 重试 ≈ **40 分钟以上**（58.6 × 15 × 2 ≈ 1758s ≈ 29 min 下限，含重试与 429 退避实际 ≥40 min）。

- 速度问题单独记，不阻塞主线：glm-5.2-fast-preview 58.6s vs qwen-flash 4.3s，差 13 倍。
- 等 gate 过后，再花 10 次调用试 `qwen-turbo` / `qwen-plus` 作备选任务模型；若任一能 5/5 且明显快于 58.6s，停下找作者拍板是否切换（不阻塞 W1）。
- 批量 eval 必须串行 + 429 退避，**不许并发**（本轮已实测 1 次 429，退避后通过——限流风险真实）。

## 8. Ground truth 红线（R8）+ harness 设计

🚨 **R8（与 R1–R7 同级）**：eval ground truth **必须由作者手工标注**——Claude/任何模型不许生成、推断、或用模型产出去填。

harness 设计：
1. ground truth 存成独立文件 `evals/ground_truth.yaml`，与代码和模型产物完全分离。
2. Claude 生成一份**空白标注模板**：15 个 ticker，每个列出所有待标字段，值全部留空，附简短填写说明。
3. 模板交给作者，作者填完再放回去。
4. harness 读本文件做比对；**文件缺失或字段为空 → 报错退出，绝不允许用模型输出兜底**。

under-fill 直接量（与一致率分开报，qwen-turbo vs glm-5.2-fast-preview 基线对比）：
- 字段填充率（各字段 non-null 占比）
- mirror 平均条数、holding_reason 平均字数

模型分工（作者 2026-08-01 定）：qwen-turbo = 日常迭代模型（3min/轮，跑多轮）；glm-5.2-fast-preview = 质量基线（只跑一次）。顺序：qwen-turbo 先跑通第一轮 L1 → 拿数字 → 补跑 glm 基线 → 两组并排放 eval-report.md。

### 8.1 exposure 标记（seen vs clean）

- FDS、HSBC = **seen**（演练 / gate 阶段曝光过，作者看过抽取结果，标注会被锚定，一致率天然偏高）；其余 13 条 = **clean**。
- 一致率报**三个数**：总体 / 仅 clean / 仅 seen。
- **85% 判定以 clean 组为准**；seen 组仅作参考（不进判定）。

### 8.2 「台账信息不足」字段（null + open_questions，不算模型错）

- 若某字段台账原文信息不足，作者填 `null` 并在 `open_questions` 写原因（{field, reason}）。
- **不算模型错**：该字段从一致率分母**剔除**（不计入 matched 也不计入 denominator）。
- 但**单独统计数量**「台账模糊字段数」，列进 eval-report——这个数字本身是**产品发现**（多少 thesis 模糊）。
- required 字段（holding_reason_raw / key_assumptions / mirrors / filer_type）若 `null` 但无 open_questions 说明 → harness 报错退出（R8，不兜底）。optional 字段（manual_items / next_verdict / entry_anchor）`null` 不强制 open_questions。
