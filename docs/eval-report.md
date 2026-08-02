# Eval 报告

| 项 | 值 |
|----|----|
| 日期 | 2026-08-01 |
| 调用方式 | PydanticAI 单次结构化调用（`output_type=EntryExtraction`），CLI 程序 `scripts/day1_fds_validation.py`，配置驱动（`config.yaml` task_model），不依赖会话上下文 |
| 基准 | `assets/notion/thesis/FDS.md`（台账字段最全的一行，1137 字符输入） |
| 状态 | day-1 gate 未通过（任务模型待定）；L1 一致率 eval 待 gate 过后跑 |

## 1. 结构化输出稳定性（多模型对比 · gate 连跑 5 次）

> 这张表是交付物，不是过程垃圾。glm-5.2 数据保留；新模型追加进同一张表。

| model | provider / 端点 | 成功率 | 平均耗时(pass) | 平均 out_tok(pass) | 失败原因 |
|-------|-----------------|--------|----------------|---------------------|----------|
| glm-5.2 | anthropic `/apps/anthropic` | 2/5 (40%) | 85.4s | 4789 | 3/5 `Model token limit (8192) exceeded`（finish_reason=length；成功 run out_tok 4327–5250，verbose） |
| deepseek-v4-flash-0731 | openai `/compatible-mode` | 0/5 (0%) | <1s | — | 5/5 `403 Model access denied`（key 无该 dated 版权限） |
| deepseek-v4-flash | openai `/compatible-mode` | 0/5 (0%) | <1s | — | 5/5 `400 tool_choice=required 与 thinking 模式冲突`（pydantic-ai 强制 tool_choice=required；deepseek thinking 模式拒） |
| qwen-flash | openai `/compatible-mode` | 1/5 (20%) | 4.3s | 438 | 4/5 `400 function.arguments 必须 JSON 格式`（qwen-flash 被当 code model，tool-call 参数格式被拒，间歇；1/5 过） |
| qwen3.6-flash | openai `/compatible-mode` | 0/5 (0%) | — | — | 5/5 `400 tool_choice=required 与 thinking 模式冲突`（同 B4，亦为 thinking 模型） |
| glm-5.2-fast-preview | openai `/compatible-mode` | 4/5 (80%) | 58.6s | 4364 | 1/5 `finish_reason 非标准`（pydantic-ai openai validator 拒非标 finish_reason；1 次 429 退避后过——限流防护生效） |
| **glm-5.2-fast-preview + lenient fix** | openai `/compatible-mode` | **5/5 (100%) ✅** | **45.7s** | **5135** | 0/5（`LenientOpenAIChatModel` 容错非标 finish_reason 后全过；**gate 通过，任务模型定**） |
| qwen-turbo | openai `/compatible-mode` | **5/5 (100%)** | **4.96s** | **586** | 0/5（backup 试；比 glm-5.2-fast-preview 快 ~9x（45.7s→4.96s）、out_tok 5135→586——**命中 §7 切换门槛，待作者拍板**） |
| qwen-plus | openai `/compatible-mode` | 3/5 (60%) | 10.31s | 501 | 2/5 `function.arguments JSON 格式`（code model 间歇拒，同 qwen-flash，B5） |

**per-call 指标**：

| model | run | status | dur_s | in_tok | out_tok | retries_429 | 备注 |
|-------|-----|--------|-------|--------|---------|------------|------|
| glm-5.2 | 1 | pass | 93.94 | 2456 | 5250 | 0 | cap=中(误) nmirrors=4 anchor=TTM GAAP P/E verdict=FY26 Q3 |
| glm-5.2 | 2 | pass | 76.94 | 2456 | 4327 | 0 | cap=中(误) nmirrors=5 |
| glm-5.2 | 3 | length | 145.77 | — | — | 0 | token limit (8192) |
| glm-5.2 | 4 | length | 152.83 | — | — | 0 | token limit (8192) |
| glm-5.2 | 5 | length | 154.53 | — | — | 0 | token limit (8192) |
| deepseek-v4-flash | 1–5 | other(400) | 0.36–1.42 | — | — | 0 | tool_choice/thinking 冲突，未触达生成 |
| qwen-flash | 1 | other(400) | 8.22 | — | — | 0 | function.arguments JSON 格式 |
| qwen-flash | 2 | other(400) | 8.72 | — | — | 0 | function.arguments JSON 格式 |
| qwen-flash | 3 | other(400) | 5.93 | — | — | 0 | function.arguments JSON 格式 |
| qwen-flash | 4 | pass | 4.34 | 1997 | 438 | 0 | nmirrors=3 anchor=TTM GAAP P/E verdict=FDS 2026 Q2 |
| qwen-flash | 5 | other(400) | 9.00 | — | — | 0 | function.arguments JSON 格式 |
| qwen3.6-flash | 1–5 | other(400) | 0.13–0.86 | — | — | 0 | tool_choice/thinking（B4），全即时拒 |
| glm-5.2-fast-preview | 1 | pass | 106.49 | 1895 | 2947 | 1 | 429 退避后过；nmirrors=4 anchor=TTM_GAAP_PE verdict=Q3 FY26 |
| glm-5.2-fast-preview | 2 | other | 15.28 | — | — | 0 | finish_reason 非标准（openai validator 拒） |
| glm-5.2-fast-preview | 3 | pass | 44.44 | 1895 | 5075 | 0 | nmirrors=4 |
| glm-5.2-fast-preview | 4 | pass | 28.94 | 1895 | 3131 | 0 | nmirrors=5 anchor=TTM GAAP P/E (ADD 16x) |
| glm-5.2-fast-preview | 5 | pass | 54.49 | 1895 | 6303 | 0 | nmirrors=4 |
| glm-5.2-fast-preview+lenient | 1 | pass | 39.11 | 1895 | 4088 | 0 | nmirrors=4 anchor=TTM GAAP P/E verdict=Q3 FY26 |
| glm-5.2-fast-preview+lenient | 2 | pass | 53.91 | 1895 | 5958 | 0 | nmirrors=5 |
| glm-5.2-fast-preview+lenient | 3 | pass | 47.57 | 1895 | 5767 | 0 | nmirrors=5 |
| glm-5.2-fast-preview+lenient | 4 | pass | 44.93 | 1895 | 5083 | 0 | nmirrors=5 |
| glm-5.2-fast-preview+lenient | 5 | pass | 43.00 | 1895 | 4779 | 0 | nmirrors=5 |
| qwen-turbo | 1 | pass | 5.41 | 2001 | 571 | 0 | |
| qwen-turbo | 2 | pass | 4.42 | 2001 | 562 | 0 | |
| qwen-turbo | 3 | pass | 5.21 | 2001 | 643 | 0 | |
| qwen-turbo | 4 | pass | 5.59 | 2001 | 587 | 0 | |
| qwen-turbo | 5 | pass | 4.18 | 2001 | 569 | 0 | |
| qwen-plus | 1 | other(400) | 8.75 | — | — | 0 | function.arguments JSON（code model） |
| qwen-plus | 2 | pass | 7.70 | 1997 | 485 | 0 | |
| qwen-plus | 3 | pass | 11.56 | 1997 | 509 | 0 | |
| qwen-plus | 4 | pass | 11.68 | 1997 | 508 | 0 | |
| qwen-plus | 5 | other(400) | 9.00 | — | — | 0 | function.arguments JSON（code model） |

> 3 候选 + lenient 修复 + backup 试。**gate PASSED 5/5**（glm-5.2-fast-preview + lenient）。**backup 试命中切换门槛：qwen-turbo 5/5 + 4.96s/call（glm-5.2-fast-preview 45.7s 的 1/9）+ out_tok 586（5135 的 1/9）**——按 eval-plan §7 stop-condition，**待作者拍板是否切换任务模型**（切换后一轮 L1 eval 从 ≥40min 降到 ~3min）。qwen-plus 3/5（code model 间歇，B5）。

## 2. Error analysis（根因/修复，非现象统计）

### 2.1 position_cap_tier —— schema 设计错误，非模型能力

- **现象**：glm-5.2 2/5 把 FDS 判成 `中` 档，实际 Skill v4 是 `硬thesis`。
- **root_cause_hypothesis**：仓位档位规则在 Skill v4 里、按 ticker 定死；FDS transcript 里**没有档位信息**，模型没有依据只能猜。
- **归因**：**字段依据不在输入内，属 schema 设计错误，不是模型能力问题**——确定性信息不该交给模型的典型案例。
- **fix_action**：`position_cap_tier` 已从 LLM 输出契约（`EntryExtraction`）移除，改为 `tier_map.py` 按 ticker 规则查表；查不到置 `None` 进人工确认队列。**schema 不迁就模型，是迁回确定性规则。**

### 2.2 结构化输出失败分类（gate）

| 类别 | 计数 | 根因 | 修复方向 |
|------|------|------|----------|
| length（max_tokens 截断） | glm-5.2 3/5；glm-5.2-fast-preview 1/5 | glm 系 verbose，输出 4-5k token，偶超 8192。**out_tok 横向证明 bloat 是 glm 系 verbose，非 description 写太长**：qwen-flash 同 schema 只产 438 token | 换非 verbose 模型；或接受 glm 系偶发 length |
| 403 access | deepseek-0731 5/5 | key 无该 dated 版权限 | 用稳定别名 |
| 400 tool_choice/thinking | deepseek-v4-flash 5/5、qwen3.6-flash 5/5 | pydantic-ai 强制 `tool_choice=required`；thinking 模式拒 required/object（B4 硬约束） | 换非 thinking 模型（不走关 thinking，保 model-agnostic） |
| 400 function.arguments JSON | qwen-flash 4/5 | qwen-flash 被当 code model，tool-call arguments 格式被拒（间歇，1/5 过） | 模型选型问题，非 schema；换模型 |
| finish_reason 非标准 | glm-5.2-fast-preview 1/5 | pydantic-ai openai validator 拒非标 finish_reason（model 返回 stop/length/tool_calls 之外的值） | pydantic-ai openai SDK 严格性，或模型偶发；非 schema，待排查 |

### 2.3 Finding：out_tok 大是模型 verbose，非 description 冗长（【3】假设证伪 · 单独记，不混进稳定性表）

- **对照**（同一 post-trim schema）：qwen-flash out_tok=438 / glm-5.2-fast-preview out_tok=4364 / glm-5.2(pre-trim) out_tok=4789。
- **结论**：out_tok 大是 **glm 系模型自身 verbose**，**不是 schema description 写太长**——qwen-flash 在同一 schema 下只产 438 token，与 glm 系差一个量级。description 精简（v0.2）未改变 glm 系 verbose（glm-5.2-fast-preview post-trim 仍 4364）。
- **【3】「精简 description 降 out_tok」假设证伪**——该待办关闭，不再追 description 精简方向。out_tok 问题随模型选型解决（选非 verbose 模型，如 qwen 系），不靠改 schema。
- 严格隔离 description 效果需 glm-5.2-regular 跑 post-trim，未做（结论已清楚，不必要）。

## 3. L1 对话抽取一致率（待跑）

gate 过后跑：16 台账 case + HSBC transcript，A/B 对照（A 不澄清直接抽 / B 走完整澄清），逐字段一致率（`holding_reason` / `key_assumption` / 破条件 / `filer_type` 各自 ≥85%，非总分），per case 出 `root_cause_hypothesis` + `fix_action`。

## 4. 局限

- 每个数字标注 model + version（见 §1 表）。
- gate 用 `config.yaml` 的 `task_model`；会话模型（glm-5.2）与任务模型分离（见 `docs/changelog.md` v0.0.4）。
- 429 与其它错误分开计数（§1 per-call `retries_429` + status 列）。**本轮实测 1 次 429**（glm-5.2-fast-preview run 1，退避后通过，retries_429=1）——限流风险真实，**批量 eval 必须串行 + 退避，不许并发**（见 `docs/eval-plan.md` §7）。
- **评估者能力圈分层**（主观盲评接受率解读，2026-08-02 加）：
  - **口径 / 会计逻辑类判断**（如「该用 P/TBV 还是 P/E」「调整后 vs GAAP」）→ 评估者具备专业背景（CPA 会计科目已通过），盲评接受率**有效**（反映正确性）。
  - **具体倍数 / 目标价类判断**（如「$130 是否合理」「P/E 16x 对不对」）→ 评估者自述能力不足，接受率反映**「合理性感知」而非正确性**，须单独标注 + 打折解读。
  - harness 按此分层标注每个主观字段（holding_reason / key_assumptions / mirrors 的各条）属于哪一类。

## 5. 方法论迭代记录（2026-08-02 修正，跑 eval 前发现）

初版打分有**三处会让 headline 数字虚高**，均在跑 eval 前发现并修正：

1. **entry_anchor 用 bigram 模糊匹配**：ttm_gaap_pe 与 forward_non_gaap_pe 共享 6 个 bigram → 误判命中；15 只票 8 只属 P/E 家族 → 一致率虚高接近 100% 但不测出任何东西。**修正**：改 `AnchorType` 闭集枚举（`models.py`）精确相等 + `anchor_value` 相对误差 ≤5% 单独报（不合并 type）。
2. **next_verdict 比中文 event 文本**：GT「Q3 2026 财报」与输出「Q2 FY27 财报」仅靠「财报」二字即判命中，季度错了也算对。**修正**：改比 `date`（归一到 YYYY-Qn 精确；GT 月精度 → ±1 月命中）；event 文本仅 case 明细打印，不参与判定。
3. **盲评将「二选一偏好」等同于「接受」**：二选一场景用户挑较好的一方，不代表其达标；两个都不合格时勉强择一也计为接受。「用户接受率」实际测的是「是否存在明显更差的一方」而非「是否达标」。**修正**：拆成两问——`pick`（偏好：哪个更好）+ `acceptable`（接受：选中的是否可直接用）；用户接受率 = acceptable=yes/total（对应 ≥85% 门槛）；模型胜率 = pick/total（仅选型，不设门槛）。both_wrong → acceptable=no。

**manual_items 表述降级**：manual_items 评分 = (len > 0) == expected，只判「有没有」不判「对不对」（FDS 7 条破条件，识别 1 条 vs 7 条得分相同）。报告中**不称「准确率」**，改称「**是否识别出存在人工项（覆盖标志，非逐条准确率）**」。若成本允许，额外报逐条 set-level precision/recall 作参考，不设门槛、不进 85% 判定。

## 6. Limitations（eval 前已知问题，2026-08-02 记，不改代码）

> eval 代码与分类规则已冻结。以下问题在跑 eval 前已识别，选择不修而记录，避免在评估基线上持续移动。修复列入 W2。

### 6.1 v1 覆盖率 36%（20/55）为上界，含 6 条误判，实际约 25%

**跨主体取数误判**（分类器识别指标类型，但不识别数据归属主体）：
- NVDA「AI capex 周期结构性见顶」：需读 MSFT/GOOGL/AMZN/META capex → 跨主体，非 NVDA 自身披露
- NVDA「某季 hyperscaler capex 指引环比转负」：同上
- MCO「一级市场发行量连续多月放缓」：需外部市场数据（SIFMA/Dealogic）
- 以上三条均属 data-sources ⑤ 已列缺口，分类器未接上该规则

**多判据条件误判**（条件含多个判据，任一可自动即整条判 True）：
- NVDA「数据中心 GPU 毛利率持续下移」：公司只披露整体毛利率，不拆分部 → 需推算
- NOW「NRR…或平台被 AI 原生工作流替代」：NRR 非常规披露 + 后半句定性
- NFLX「…提价导致 churn 明显抬升」：Netflix 已停止披露 churn

### 6.2 CRM 条件切分 5 条结构残渣未剥离干净

以下均分类为 qualitative，不影响 manual_items 判定方向，但使条件计数偏高：
- 「【量化版 · 基线按 2026-06-21 一手（FY27 Q1，press release 5/」
- 「每季复盘用最新一手刷新基线】」
- 「硬滞后线（季报数字踩中 → 🔴 CUT；均需「连续 2 季」确认窗口）」
- 「触发：同时出现」
- 「net new ARR / 大客户订阅净新增连续 2 季负增长 且」（续行未合并）
- 「领先代理（→ 🔭 观察项，不直接 CUT）」
