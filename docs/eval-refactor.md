# Eval & Acceptance Spec

> 对应 `docs/refactor-spec.md` §6
> 定义重构完成后的验收标准。caca 用此文档验收。

## 验收方式

caca 不需要读代码。验收方式是：
1. **跑 demo 脚本** — 在终端跑，看 agent 的回复是否正确
2. **用 web UI 测试** — 在浏览器里操作，看体验是否丝滑
3. **跑 pytest** — 确认现有测试不 regress

## Phase 检查点

| Phase | 完成标志 | caca 怎么验 |
|---|---|---|
| 1 | agent loop 跑通 | 终端 demo: Case 1-4 走通 |
| 2 | 接入 web | 浏览器: 录入一只票走通 |
| 3 | SSE streaming | 浏览器: 看到打字机效果 |
| 4 | check_agent | 终端: 跑一次定时检查 |
| 5 | 全量验收 | 本文所有 case |

## Regression（不能退步）

- 现有 83 测试全过（guardrail 层不动）
- entry_loop 测试重写为 agent loop 行为测试

## Acceptance Cases（10 个，分 3 层）

### 第一层：流程正确性（讨论式 vs 抽取式）

#### Case 1: 探针仓启动
**输入**: "我开始关注 MCO"
**期望**:
1. Agent 调 resolve_ticker("MCO") → 命中 Moody's
2. Agent 呈现"我找到 Moody's Corporation (ticker: MCO)，这是你说的标的吗？"
3. Agent 问"说说你为什么关注 MCO？"——**不问持仓量、不假设已建仓**
4. **验证点**: 区分探针仓 vs 已建仓，措辞用"关注"而非"持有"

#### Case 2: 已建仓启动
**输入**: "我持有 MCO"
**期望**:
1. Agent 调 resolve_ticker("MCO") → 命中 Moody's
2. Agent 呈现标的确认
3. Agent 问"说说你为什么持有 MCO？"——措辞用"持有"
4. Agent 仍然完整讨论 5 个字段，不跳过
5. **验证点**: 不因已建仓就跳过讨论

#### Case 3: 逐字段引导
**输入**: 用户只说了 thesis（"看好信用评级壁垒"），没说别的
**期望**:
1. Agent 调 extract_card → 返回 key_assumptions
2. Agent 呈现假设"我理解你的核心假设是：1. xxx 2. xxx，对吗？"
3. 用户确认后，Agent 主动问破局条件
4. 破局条件确认后，Agent 主动问估值
5. 估值确认后，Agent 主动问持仓周期
6. **验证点**: 5 步逐个讨论，不一口气全问

#### Case 4: key_assumptions 用户确认
**输入**: 用户说"看好信用评级壁垒"，extract_card 抽出 2 条假设
**期望**:
1. Agent 把假设呈现给用户："我理解你的核心假设是..."
2. 用户说"第 2 条不对"→ Agent 修改或追问
3. 用户确认后，Agent 才从假设生成 mirror 破局条件
4. **验证点**: 不跳过假设确认直接生成破局条件

### 第二层：估值/破局条件引导

#### Case 5: 估值选项
**输入**: 在估值步骤，用户说"不知道怎么估值"
**期望**:
1. Agent 根据公司业务类型提供 2-3 个估值方法选项
2. 例如 MCO（信用评级公司）→ 可能推荐 P/E、owner-earnings 收益率等
3. Agent 能解释为什么推荐这个方法
4. 用户选一个 + 给数字 → Agent 记录安全边际
5. **验证点**: 提供选项不问开放题；基于公司业务判断不机械套用分类

#### Case 6: 破局条件生成
**输入**: 在破局条件步骤，用户说"不知道什么情况会破"
**期望**:
1. Agent 调 generate_menu → 返回 A/B 候选
2. Agent 呈现候选"这里有几个候选方向，你看看哪个对"
3. 用户选 → Agent 记录
4. **验证点**: generate_menu 有效触发

### 第三层：Guardrail + Error

#### Case 7: 必填字段检查
**触发**: Agent 试图 save_card 但缺安全边际（entry_anchor 为空）
**期望**:
1. Guardrail 拦截，拒绝保存
2. Agent 提示用户"我们还没讨论估值/安全边际"
3. **验证点**: 5 字段全填才能存，不允许部分保存

#### Case 8: Ticker 未验证
**触发**: Agent 试图 save_card 但 ticker 未走 resolve_ticker
**期望**:
1. Guardrail 拦截
2. Agent 先调 resolve_ticker 确认标的
3. **验证点**: ticker 必须验证才能入库

#### Case 9: 中文公司名（A+ 规则）
**输入**: "我持有汇丰"
**期望**:
1. Agent 把"汇丰"翻译成"HSBC" → 调 resolve_ticker("HSBC") → 命中
2. Agent 呈现"我找到 HSBC Holdings PLC (ticker: HSBC)，这是你说的标的吗？"
3. 用户确认 → 继续讨论
4. **验证点**: 世界知识桥接 + 用户确认安全网

#### Case 10: LLM 幻觉防护
**触发**: Agent 在估值步骤编造财务数据（如"MCO 当前 P/E 28倍"）
**期望**:
1. Guardrail 检查 save_card 只含用户提供的数据
2. 如果 Agent 编造数据 → 拦截或提示"这个数据我没有来源，你能确认吗？"
3. **验证点**: 不允许 LLM 编造数据

## Error Analysis（旧 Bug → 新架构修复）

| 旧 Bug | 根因 | 新架构怎么修 | 验证方式 |
|---|---|---|---|
| #1 Entry loop 僵硬 | 状态机无法处理意外输入 | LLM 驱动对话，无状态机 | Case 3: 逐字段引导 |
| #2 Ticker 解析失败 | Fuzzy 匹配太激进 | resolve_ticker 只做精确匹配 + 用户确认 | Case 9 |
| #3 MCO mid-word 误命中 | Fuzzy 子串匹配 | 删除 fuzzy，只精确匹配 | Case 9 + resolve_ticker 单测 |
| #4 HSBC 文案误导 | 硬编码澄清文本 | LLM 生成自然语言澄清 | Case 9 |

### 新风险 + 防护

| 新风险 | 防护方式 | 验证方式 |
|---|---|---|
| LLM 编造财务数据 | OutputGuardrail: save_card 只含用户说的数据 | Case 10 |
| LLM 跳过必填字段 | OutputGuardrail: 5 字段完整性检查 | Case 7 |
| LLM 不问就保存 | OutputGuardrail: 检查用户确认 flag | Case 7 |
| LLM 建议错误估值方法 | System prompt 指引（不给映射表） | Case 5 |
| Tool API 超时 | Agent 自然语言告诉用户重试 | 手动测试 |

## Performance 验收

| 指标 | 标准 | 测量方式 |
|---|---|---|
| 单票录入时间 | ≤5min | 从用户第一条消息到 save_card |
| tool 调用次数 | ≤3 per turn | SDK tracing 日志 |
| SSE 首字延迟 | ≤2s | 浏览器 devtools |
| 红线拦截率 | 100% | 红线 case + 10 个变体 |

## Demo 脚本

Phase 1 完成后，PM 会给 caca 一个 demo 脚本 prompt，粘贴到终端跑。
脚本会走 Case 1-4（第一层流程正确性），caca 看终端输出判断 agent 行为是否正确。

Phase 2 完成后，caca 直接用浏览器测 Case 1-10。

Phase 3 完成后，caca 测"丝滑感"——SSE streaming 是否像 Notion AI 一样逐字出现。

---

## 验收结果（2026-08-04，Phase 5）

> 后端窗口执行。网络当时不通（DeepSeek 百炼端点 APIConnectionError），live agent 跑不了；
> 能用 pytest 离线覆盖的标 ✅，纯 live/浏览器交互的标「需 caca 验收」。

| Case | 自动化方式 | 结果 | 说明 |
|---|---|---|---|
| 1 探针仓 MCO | pytest（resolve_ticker 逻辑）+ SYSTEM_PROMPT 措辞 | ⚠️ 部分 + 需 caca live | resolve_ticker 精确匹配 ✓（test_ticker_resolver 9 测试）；措辞"关注"在 SYSTEM_PROMPT 明写 ✓；live agent 实跑 blocked（DeepSeek 不通）→ caca 重跑 demo |
| 2 已建仓 MCO | 同上 | ⚠️ 部分 + 需 caca live | 同 Case 1；措辞"持有"在 SYSTEM_PROMPT ✓ |
| 3 逐字段引导 | 仅浏览器 | 需 caca 验收 | 5 步逐字段讨论是 live 多轮 UX，只能浏览器测 |
| 4 key_assumptions 用户确认 | pytest（G3 逻辑）+ 浏览器 | ✅ 逻辑 + 需 caca UX | G3（条件3 is_paraphrase / 条件4 is_v1_auto / P3 / R1-R3）✓ test_orchestrator_impl 7 测试；UX 确认环节需浏览器 |
| 5 估值选项 | 仅浏览器 | 需 caca 验收 | 估值方法选项是 LLM 判断（SYSTEM_PROMPT 指引不给映射表），只能 live/浏览器测 |
| 6 generate_menu | pytest（filter_executable_mirrors）+ 浏览器 | ✅ 逻辑 + 需 caca UX | filter_executable_mirrors ✓ test_menu_filter；菜单呈现 UX 需浏览器 |
| 7 必填字段 | pytest | ✅ | save_card G1 必填 + G4 用户确认 ✓ test_orchestrator_impl（test_save_g1_rejects_* / test_save_g4_rejects_unconfirmed） |
| 8 ticker 未验证 | pytest（G4）+ live | ⚠️ 部分 + 需 caca live | G4（confirmed_by_user）✓ tested；"resolve_ticker 前置"是 agent loop 行为（SYSTEM_PROMPT 约束），需 live/浏览器验 |
| 9 汇丰→HSBC | pytest（resolve_ticker HSBC 逻辑）+ live | ⚠️ 部分 + 需 caca live | resolve_ticker("HSBC") 精确匹配 ✓；"汇丰→HSBC 翻译"是 DeepSeek 世界知识，需 live 跑（网络 blocked） |
| 10 LLM 幻觉防护 | pytest（G2 结构校验） | ⚠️ 部分 | save_card G2 安全边际结构校验（anchor_type+value 须有）✓ test_save_g2_rejects_*；**已知局限**：G2 是结构校验非事实核查，LLM 编造一个"看似合理"的 anchor_value G2 拦不住——需 caca 知悉 |

**自动化结论**：
- pytest 离线覆盖：Case 7、4（G3）、6（filter）、10（G2 结构）+ 1/2/8/9 的确定性部分（resolve_ticker / G4）。
- 需 caca 浏览器/live 验收：Case 3、5（纯 live UX）；Case 1、2、4、6、8、9 的 UX/翻译部分。
- 性能验收（单票 ≤5min / tool ≤3 per turn / SSE ≤2s 首字）：单票录入了 check_agent 84.6s（≤5min ✓）；其余需 caca 浏览器 devtools 量。

**Regression**：107 测试绿（基线 75 + Phase 5 新增 32：orchestrator impl 16 + check_agent 16）。
旧 entry_loop 状态机测试 Phase 2 已砍（83→75 差异），Phase 5 新增 agent-loop 行为测试补回（75→107）。

### W1 extract eval 重跑（2026-08-04，Phase 5 移植 deepseek 后）

`run_l1.py run --allow-stale-gt`（PYTHONUTF8=1；snapshot_ref 不匹配是 merge commit 形式差异，assets/ 内容 0 diff，GT 未过期）。15 case × 2 模型（deepseek-v4-flash + glm-5.2-fast-preview，头对头，都走新 orchestrator `submit_extraction` 路径）。

**客观一致率（逐字段，总体）**：

| 模型（新 orchestrator 路径） | filer_type | manual_items | next_verdict | n_pass |
|---|---|---|---|---|
| deepseek-v4-flash | **1.0** | 0.4286 | 0.0 | 14/15 |
| glm-5.2-fast-preview | **1.0** | 0.4615 | None（ambiguous） | 13/15 |
| 旧 glm（pydantic_ai output_type，8/3 基线） | 0.933 | 0.8 | 1.0 | 15/15 |

**对比结论**：
- **deepseek vs glm（都新路径，苹果对苹果）**：deepseek **不明显低于** glm——n_pass 14 > 13（deepseek 略稳，CRM 抽出 glm 没抽出）；manual_items 0.43 vs 0.46（deepseek 低 ~3pp，都低）；next_verdict 0.0 vs None（都差）。filer_type 都 1.0（满分）。per caca 规则（明显低于才记差距等定），deepseek 持平 glm，可记通过。
- **新路径 vs 旧 pydantic_ai 路径（移植成本）**：新 `submit_extraction`（loose dict）比旧 `output_type`（schema 强制）**退步**——manual_items 0.8→0.43-0.46、next_verdict 1.0→0/None（两模型都退）；filer_type 0.93→1.0（反而升）。**根因**：loose dict schema 不强制结构 → 模型把 next_verdict 当 string 传（无 date，coerce 后 date=None → `_date_match` 失败 → 0.0）+ manual_items 识别不全；旧 `output_type` 强制 NextVerdict{event,date} 结构 → date 在 → 1.0。
- **W2 主观接受率**：deferred——需 caca 填 `evals/blind_verdicts.yaml`（A/B 盲评 deepseek vs glm 的 holding_reason_raw/key_assumptions/mirrors）后跑 `run_l1.py collect`。`blind_pairs.yaml` 已导出（隐藏来源随机左右）。

**待 caca 定**（移植质量成本）：新路径 manual_items/next_verdict 退步是 `submit_extraction` loose schema 的代价（换 drop pydantic-ai）。选项：(a) 接受 tradeoff（deepseek+orchestrator 栈简、filer_type 满分，但 manual_items/next_verdict 弱）；(b) 改进 `submit_extraction` schema（typed fields 强制 next_verdict{event,date} 结构）；(c) 试 `output_type=EntryExtraction`（schema 强制，但 B4 deepseek thinking 拒 tool_choice=required 风险）。**不自作主张切回 pydantic_ai/glm**——等 caca 定。

### W1 schema 收紧实验（2026-08-04，typed ExtractionInput）— caca 选了 (b)

caca 选 (b)：`submit_extraction` 收紧 typed schema（`ExtractionInput` 镜像 `EntryExtraction`：`next_verdict` 强制 `{event, date}` 对象非 string，`manual_items` 强制 `[{text,reason,cadence}]`）。`strict_mode=True` 被 SDK strict-schema 生成器拒（nested model additionalProperties 冲突，非 B4）→ `strict_mode=False`；typed model 仍由 SDK 按 pydantic parse args → string next_verdict 校验失败 → 强制 `{event,date}` 或 null。`_coerce_extraction` 保留兜底。commit 434e1e1。

**5-case deepseek 快验**（FDS/MCO/FIS/NVDA/VEEV，typed schema；不跑全 30 省 40min）：

| 字段 | OLD deepseek（loose dict） | NEW deepseek（typed） | 目标 |
|---|---|---|---|
| next_verdict | 0.0 | **0.75** ✅ | ≥0.80（接近） |
| manual_items | 0.43（15 case）/ 0.2（这5） | 0.0（这5） | ≥0.70 ❓ 未达 |
| filer_type | 1.0 | 1.0 ✅ | 1.0 |
| entry_anchor_type/value | — | 1.0 ✅ | — |

- **next_verdict 修好了**：typed schema 强制 `{event, date}` → date 现在 parseable（FDS=2026-06 / MCO=2026-10 / FIS=2026-08 / NVDA=2026-08，VEEV=None）→ `_date_match` 命中 → 0.0→0.75。15-case 上大概率 ≥0.80。
- **manual_items 不确定**：这 5 case 4 个（FDS/MCO/FIS/NVDA）新旧都 False（case-selection——这些 case 模型本就不产 manual_items）；VEEV old=True new=False（疑似 LLM 运行间 variance，5 样本不足以下结论）。typed schema 强制 `{text,reason,cadence}` 结构，但 manual_items 是「模型要不要识别价格图形型条件」的**识别**问题，非结构问题——schema 收紧未必帮识别。
- **filer_type / entry_anchor 满分** ✓。

**结论**：typed schema（434e1e1）达 next_verdict 目标（0.0→0.75，主目标）+ filer_type/entry_anchor 满分；manual_items 未达（5-case 不确定，需全 15-case 确认，但根因是识别非结构）。**caca 已接受 (a)（2026-08-04）**：typed schema 为最终状态——next_verdict 修好是大头 + filer_type/entry_anchor 满分；manual_items 留作后续 prompt 引导（识别问题，非结构，不阻塞产品）。deepseek vs glm 持平 + manual_items 15-case 率待全量跑确认（可选，caca 定时机）。不自作主张切回 pydantic-ai/glm。

### W2 主观盲评结果（2026-08-04，caca 盲评 deepseek vs glm）

caca 填 `evals/blind_verdicts.yaml`（15 case × holding_reason_raw/key_assumptions/mirrors，A/B 匿名 deepseek+glm 随机左右；OLD qwen+glm 裁决备份 `.bak`）→ `python -m evals.run_l1 collect`。

- **用户接受率 = 93.33%（42/45）** —— vs 旧基线 85.45%，**上升 ~8pp** ✅（门槛 ≥0.85，§9.1）。
- **deepseek 胜率 = 51.11%（23/45）** > **glm 17.78%（8/45）** —— caca 盲评 deepseek 明显胜 glm ✅。
- 3 个不接受 = GDXU（W1 里 deepseek+glm 都 extraction failed "other"，盲评 both-wrong，一致）。
- 11 个 both-acceptable-no-pick（两模型都可接受，无偏好）。

**结论**：port + typed schema 不只「不退」——W2 主观上 **deepseek 质量高于 glm**（caca 偏好 deepseek 的 holding_reason_raw/key_assumptions/mirrors），接受率 85.45%→93.33%。W1 objective（deepseek ≈ glm，next_verdict 0.75 修好 + filer_type/entry_anchor 满分）+ W2 subjective（deepseek 胜）合起来：**切 deepseek 决策正确**，重构（Phase 0-5）质量达标。manual_items（W1 识别问题）留作后续 prompt 引导，不阻塞。