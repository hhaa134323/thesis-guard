# Eval 报告

| 项 | 值 |
|----|----|
| 日期 | 2026-08-02 |
| 调用方式 | PydanticAI 单次结构化调用（`output_type=EntryExtraction`），CLI `evals/run_l1.py`，config 驱动，不依赖会话上下文 |
| 模型 | qwen-turbo（日常迭代）/ glm-5.2-fast-preview（质量基线） |
| 基准 | assets/notion/thesis/ 15 ticker（12 当前持仓 + 3 已清仓边界），input_type=ai_polished |
| 状态 | L1 eval 完成（gate 5/5 + 双模型 30 case + 主观盲评 45 条） |

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
| qwen-turbo | openai `/compatible-mode` | **5/5 (100%)** | **4.96s** | **586** | 0/5（backup 试；**已定：仅用于 harness 冒烟/回归，不作质量迭代**——§3.2 裁决：有偏好时 glm 胜 96%） |
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

> 3 候选 + lenient 修复 + backup 试。**gate PASSED 5/5**（glm-5.2-fast-preview + lenient）。**已定**：glm-5.2-fast-preview 为质量基线与产品默认；qwen-turbo 仅用于 harness 冒烟与回归（管线连通性），不用于质量迭代。依据 §3.2 用户裁决——无差别率 41.7%，但有明确偏好的 25 条中 glm 胜 24 条（96%）。即质量出现差异时 qwen-turbo 几乎必输，用它调 prompt 得到的改进不能外推到 glm。

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

## 3. L1 对话抽取一致率 + 主观盲评（2026-08-02 完成）

模型：qwen-turbo（日常迭代，~5s/case）/ glm-5.2-fast-preview（质量基线，~46s/case）。
基准：assets/notion/thesis/ 15 ticker（12 当前持仓 + 3 已清仓边界样本），input_type=ai_polished。

### 3.1 客观字段结果

| 字段 | qwen-turbo (clean) | glm (clean) | 门槛 | 判定 |
|---|---|---|---|---|
| entry_anchor_type | 100% (9/9) | 100% (9/9) | ≥85% | ✅ |
| entry_anchor_value | 100% (8/8) | 100% (8/8) | ≥85% | ✅ |
| next_verdict | 75% (3/4) | 100% (1/1) | ≥85% | ⚠️ 样本不足（§6.3） |
| manual_items（覆盖标志） | 69% (9/13) | 77% (10/13) | ≥85% | ✗ 无法有效测量（见下） |

**entry_anchor 100%**：该字段接近查表任务（台账原文已含「25x ≈ $394」形式），100% 反映抽取管线正确，不反映模型推理强度。qwen-turbo 与 glm 无差异本身即证据。

**manual_items 69%/77%**：GT 由 classify_condition 推导，该分类器已知含 6 条误判 + CRM 5 条切分残渣，GT 自身带噪。本项不能判定为「模型未达标」，只能判定为「本轮无法有效测量」。GT 规则缺陷：台账破条件为空时 expected=False，但「台账没写破条件」恰恰意味着需要人工核，规则方向反了（W2 修）。

**next_verdict**：分母 4（qwen）与 1（glm），样本不足，不报率。

**filer_type**：不计入判据（§6.4，查 lookup）。模型能力观察：qwen-turbo 38% vs glm 92%，支持「有权威数据源的字段不交给模型」。

### 3.2 主观字段盲评结果

**主样本**（12 当前持仓 × 3 字段 = 36 条，对 85% 门槛）：

| 指标 | 值 |
|---|---|
| 用户接受率（acceptable=yes / 36） | **75% (27/36)** — 未达 85% |
| 模型无差别率（tie / 36） | **41.7% (15/36)** — ≥1/3 |
| pick=A/B + acceptable=no（两模型都不够） | 3 条（FDS × 3） |
| pick=tie + acceptable=no（模型一致但错） | 6 条（NOW × 3 + VEEV × 3） |

逐字段（主样本 12 each）：holding_reason_raw 75% / key_assumptions 75% / mirrors 75%——三字段齐平。

**3 个全败 case 根因（FDS/NOW/VEEV）**：prompt 缺结构性主题引导。三只票的真实买入逻辑均含 AI Agent 冲击维度（FDS 被冲击 / NOW 因 AI 买入 / VEEV 在 AI 恐慌中被误杀），两模型均未主动考虑该维度。该类判断（「这只票的关键风险是否包含 AI 替代」）可枚举为结构性主题清单，属确定性可注入的领域知识，不属于需要模型自发联想的推理能力。与 §2.1 position_cap_tier、§6.4 filer_type 同属一类：确定性的东西不该交给概率模型。
**fix_action**：prompt 增加结构性主题 checklist（AI 替代 / 监管 / 利率与久期 / 竞争格局 / 客户集中度），要求逐项 consider 后再产出 holding_reason。列入 W2。

**字段级联依赖**：9 条不接受源自 3 个独立根因，非 9 个独立错误。key_assumptions 与 mirrors 在单次结构化调用中以 holding_reason_raw 为条件生成，reason 偏则两者连带偏——字段间存在级联依赖。口径对比：字段级 75%（27/36）/ 标的级 75%（9/12）/ 独立根因数 3。单字段口径高估了错误的独立性、低估了单个错误的杀伤力。
**fix_action**：让 key_assumptions 与 mirrors 从原文独立抽取，不从模型生成的 reason 派生。列入 W2。

**边界样本**（3 已清仓 × 3 = 9 条，不算接受率，算拒答正确率）：

| Case | 结果 | 说明 |
|---|---|---|
| CGNX | 3/3 生成内容（非拒答） | 台账有 thesis，模型从薄输入抽出了内容，作者接受 |
| SPGI | 3/3 生成内容（非拒答） | 同上 |
| GDXU | 3/3 正确拒答 | 台账无破条件，两模型均未生成 → 正确 |

分组理由：产品只服务当前持仓，已清仓标的不构成产品价值；但它们是输入稀薄的边界样本，检验「输入为空时模型是否编造」（PRD §2「让『什么都不做』变得可信」）。两组 acceptable=yes 语义不同（主样本=内容可用；GDXU=正确拒答），合并会虚高接受率并掩盖拒答测试。

**模型胜率**（clear preference 分母=25，不含 tie）：glm 96% (24/25) / qwen-turbo 4% (1/25)。有明确偏好时几乎全选 glm。

**模型无差别率 41.7%**：≥1/3 → 支持「日常迭代用 qwen-turbo（~5s）、质量基线用 glm（~46s）」的分工，结论来自用户裁决而非成本推断。

### 3.3 W1 判据 #3 结论

**2 项达标 / 1 项样本不足 / 1 项无法有效测量 / 主观 75% 未达标。**

- ✅ entry_anchor_type 100%（两模型）
- ✅ entry_anchor_value 100%（两模型）
- ⚠️ next_verdict 样本不足（§6.3）
- ✗ manual_items GT 自身带噪，本轮无法有效测量
- ✗ 主观接受率 75%（单轮初稿口径）——3 case 全败（FDS/NOW/VEEV），根因是 prompt 缺结构性主题引导（§3.2）

**主观 75% 为单轮初稿口径，因 §6.8 效度限制，本轮不对该门槛作达标判定，W1 判据 #3 记为未完成测量而非未达标。**

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

### 6.3 next_verdict 本轮样本不足（2026-08-02 加）

GT 中 15 条仅 5 条 next_verdict 非 null（FDS / NVDA / VEEV / FIS / MCO），ambiguous 剔除后分母为 1（仅 NVDA glm 有 a_date）。该字段本轮**未获有效测量**，W2 补样本（更多 ticker 标注 next_verdict）。

### 6.4 filer_type 一致率不计入 W1 判据 #3（2026-08-02 加）

filer_type 在产品中已改为查 `filer_type_lookup.yaml`（SEC EDGAR API），**模型输出不参与产品逻辑**。本轮数据（qwen-turbo 38% vs glm-5.2-fast-preview 85%，前者大量输出 other）保留作为**模型能力观察**——支持「有权威数据源的字段不交给模型」这一设计决定。不计入 W1 判据 #3 的 ≥85% 门槛。

### 6.5 eval fixture 输入切片缺失（2026-08-02 修正）

本轮发现 eval fixture `load_input_text` 只截取「Thesis · 为什么买」段，未含「加仓价 / 安全边际」段 → entry_anchor 字段前两轮测量值为 0%（假阴性）。

修正：`load_input_text` 改为拼接「Thesis · 为什么买」+「加仓价 / 安全边际」两段（不含破条件段，那段由 `load_break_conditions` 单独读）。修正后 qwen-turbo entry_anchor_type 从 **0% → 100%**（11/11）。

**方法论教训**：eval 输入切片必须覆盖被测字段的来源段。这与前述「打分逻辑系统性高估」（§5）构成一对镜像错误——同一个 agent 既写被测物又写评分器时，两个方向的偏差都会出现（高估 + 低估）。

### 6.6 GT 样本构成含已清仓标的（2026-08-02 加）

GT 15 条含 3 只已清仓标的（CGNX/SPGI/GDXU），本轮通过分组处理（主样本 36 + 边界 9）。W2 重建 GT 时应按「当前持仓 / 边界样本」显式设计，而非照台账全量取。

### 6.7 边界样本仅 3 例，拒答正确率无统计显著性（2026-08-02 加）

边界样本 3 例（CGNX/SPGI/GDXU），拒答正确率仅作定性观察。GDXU 3/3 正确拒答（台账无破条件 → 两模型未生成）；CGNX/SPGI 台账有 thesis → 模型从薄输入生成了内容（非拒答测试）。样本量不足以对拒答行为下统计结论。

### 6.8 仅执行 mode A，A/B 澄清对照未测（本轮核心效度限制）

`run_l1.py` 中 `extract()` 写死 `mode='A'`（eval-plan §9.6 暂缓）。产品形态是多轮澄清对话——模型产出初稿，用户在对话中补充修正，最终 thesis 是收敛后的产物。本轮测量的是**零轮对话下的单轮初稿质量**，与产品实际输出不是同一个对象。

因此 §3.2 的 75% 不应直接对 85% 门槛判定达标与否：**尺子与被测物错配**。W2 应改测三个指标：收敛后接受率、平均澄清轮数、收敛失败率。其中平均澄清轮数对应 PRD §4-B 的时长约束，是真实用户成本度量。

## 7. W2 eval（收敛后质量，2026-08-02）

W1 §6.8 指出 mode A 单轮初稿与产品多轮收敛错配。W2 建 `evals/run_w2.py` harness，跑录入 loop 的收敛后质量，三指标：

| 指标 | 测法 | 本轮结果（model=qwen-turbo，mode=confirm，n=5：FDS/NVDA/MCO/GOOGL/VEEV） |
|---|---|---|
| 平均澄清轮数 | loop.metrics['clarification_rounds'] 均值（auto） | **0.00**（rich GT thesis text → 直接确认，0 阻断澄清；菜单路径 mode B 见下） |
| 收敛失败率 | 1 - converged/total（auto） | **0.00%**（5/5 收敛；extract 全 pass） |
| 收敛后接受率 | 作者盲评 converged cards（同 W1 blind_verdicts） | **pending**——5 张 converged 卡导出 `evals/w2_converged_cards.yaml`，待作者盲评 |

**mode A 说明**：rich GT thesis text 是当前持仓的自然输入（用户有完整 thesis），loop 1 轮确认收敛（0 澄清）——这本身是发现：对清晰 thesis 用户，loop 收敛快。菜单路径（mode B：稀疏输入 → 无法确定 → 候选菜单 → 勾选 → 收敛，1 澄清轮）已在 §2.1 HSBC 演练跑通，系统化测量列 W2.5 后续（需稀疏输入样本集）。

**收敛后接受率 pending**：与 W1 主观盲评同构——作者对 5 张 converged 卡逐字段 pick A/B/都不对 + acceptable yes/no。填 `evals/w2_blind_verdicts.yaml`（模板待建）后跑 `run_w2.py collect`（待实现）算接受率。本轮 n=5 + 作者盲评 pending，不作达标判定。

**W2.5 后续**：① mode B（菜单路径）系统化测量（稀疏输入样本 + clarification_rounds=1 的收敛后接受率）；② 全量 15 case 跑（本轮 n=5 demo）；③ 收敛后接受率盲评模板 + collect 子命令。

### 7.2 范围修正：放弃 qwen-turbo 版盲评，只评 glm 版（2026-08-02）

作者决定：`evals/blind_verdicts_w2.yaml`（qwen-turbo 版）不再继续填。

- **理由**：qwen-turbo 质量裁决 W1 已成立（盲评胜率 4% vs glm 96%，已定仅用于冒烟回归），B4 升级决策不依赖 W2 的 qwen 接受率。
- **处理**：case 1 (FDS) 保留作 error analysis 样本（model_output 供作者对照 reference_input 分析错误）；cases 2-5 (MCO/GOOGL/NVDA/VEEV) abandoned——不填 acceptable、不跑该版 collect。`blind_verdicts_w2.yaml` 已加头注释标记。
- **只 collect glm 版**：`evals/blind_verdicts_w2_glm.yaml`（5 case / 55 字段，作者填后跑 `run_w2.py collect --verdicts evals/blind_verdicts_w2_glm.yaml --result evals/_w2_result_glm.json --model-label "glm-5.2-fast-preview · mode A"`）。

**B4 决策依据（修订）**：W1 胜率裁决 + glm 版 W2 接受率。

- **glm ≥85%** → task_model 升级 glm-5.2-fast-preview（成本 58s vs qwen 5s/call）。
- **glm <85%** → 问题不在模型而在 prompt / 设计，转入 prompt 侧 error analysis（不改模型）。

**glm 版早期信号**：5 case / 55 字段（vs qwen-turbo 版 33）——checklist prompt 让 glm 抽出更多假设/镜像。但「更多」≠「更对」，接受率才能判。
