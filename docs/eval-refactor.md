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