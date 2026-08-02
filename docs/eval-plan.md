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

## 9. Eval 设计 v2（客观/主观拆分 + 盲评；2026-08-02 定，**supersede §1 的 L1 一致率设计**）

> 起因：台账 thesis 文本本身是 AI 润色过的（作者口述模糊 → AI 补全结构化字段），作者录入时想法就模糊，多数散户也如此。
> 由此：(1) 输入被污染（ai_polished 比真实 raw 口述干净，分数虚高）；(2) 主观字段无唯一答案，不能判一致率，改盲评。

### 9.1 L1 门槛预注册（写定不改，调整须 changelog 留理由）

- **客观字段**（有唯一可查证答案）：`filer_type` / `entry_anchor` / `next_verdict` / `manual_items` → 一致率 **≥85%**（原门槛不变）。
- **主观字段**（取决于作者怎么想，无唯一答案）：`holding_reason` / `key_assumptions` / `mirrors` → 用户接受率 **≥85%**（新指标，同门槛）。
- **两者分开报，不合并成一个总分。**

> 注：`manual_items` 作者未在拆分里点名，本设计判为客观（价格图形检测有可查证的分类答案：thesis 含/不含价格技术词）。作者可改判。

### 9.2 input_type 标记（输入污染）

- 每条 case 标 `input_type: ai_polished | raw`。现有 15 条台账输入全部 `ai_polished`（AI 已结构化）。
- **Limitation**（必进 eval-report）：当前一致率/接受率基于 AI 已结构化输入，面向真实用户原始口语输入时预期下降；W3 引入真实用户后须重测（`raw` 组）。

### 9.3 客观字段：GT 一致率（保持原做法）

- 作者手写标准答案（`filer_type` / `entry_anchor` / `next_verdict` / `manual_items`），harness 判 agent 输出 vs GT 一致率。客观可查证，与「想法模糊」无关。
- §8.1 exposure（seen/clean，报三数、clean 为准）+ §8.2 null/open_questions（剔除分母 + 统计模糊数）继续适用。
- 两模型（qwen-turbo / glm-5.2-fast-preview）各跑，一致率分开报。

### 9.4 主观字段：盲评（人类偏好评估）

- **不用 GT 一致率**（主观无唯一答案）。流程：
  1. qwen-turbo 与 glm-5.2-fast-preview 对同一条 case 各产一份（`holding_reason` / `key_assumptions` / `mirrors`）。
  2. 并排展示，**隐藏模型来源，左右顺序随机**。
  3. 作者对每条给三选一：**A 更贴近 / B 更贴近 / 都不对**。
  4. 选「都不对」必须由作者写一句为什么 → 该条计入**失败**。
  5. 指标：**用户接受率** = (A 或 B 被接受) / 总数；**两模型各自胜率** = 被接受数 / 总数。
- harness 支持：(a) 导出盲评对照文件（`evals/blind_pairs.yaml`，隐藏来源 + 随机左右）；(b) 回收作者裁决（`evals/blind_verdicts.yaml`）→ 算接受率 + 胜率。
- 门槛：用户接受率 ≥85%（§9.1）。

### 9.5 流程（harness 两阶段，作者卡点）

1. 作者填 `evals/ground_truth.yaml`（**仅客观字段**：filer_type / entry_anchor / next_verdict / manual_items + exposure + input_type + open_questions）。
2. harness `run`：两模型跑 15 case → 客观一致率（逐字段，exposure 三数）+ 导出盲评对照文件。
3. 作者做盲评（填 `evals/blind_verdicts.yaml`，A/B/都不对 + 都不对理由）。
4. harness `collect`：读裁决 → 算主观接受率 + 胜率 → 写 eval-report（客观一致率 + 主观接受率分开；under-fill + 台账模糊字段数 + per-call 指标同前）。

### 9.6 A/B 澄清对照（**已缩减，非取消**；作者 2026-08-02 定）

- A/B 在新设计下**更有落点**：A 组（不澄清，直接从台账抽）→ 用户接受率 X；B 组（走完整澄清流程）→ 用户接受率 Y。**Y − X = 澄清设计价值**（接受率 = 用户价值本身，比一致率差值更有说服力）。
- 真正阻碍是**成本**（B 要真走澄清对话，15 条 × 几分钟不现实），不是设计。故**缩减不取消**：
  - **W1 只做 3 条小样本 A/B**（作者走 3 次澄清对话，约 20 分钟）。
  - 选 case 规则：从 clean 组挑，覆盖不同 thesis 类型，**至少含一条图形型、一条纯财务型**。
  - 不追求统计显著，目的是**方向性信号 + 一份可展示对比**。
  - **全量 A/B 推到 W2**。
- W2 重启条件：B 组澄清流程产品化（多轮对话 agent 落地）+ 成本可控后，扩到全量 15 条。
- 范围调整已留痕（本节）。
