# 重构规格书：State Machine → Agent Loop

> 基线 tag: `pre-refactoring-arch` (ee7c5b2) | 重构分支: `refactor/agent-loop`
> 创建时间: 2026-08-03 | PM: caca + Notion AI
> 更新时间: 2026-08-03 (讨论式流程确认后)

## 1. 问题陈述

当前 `entry_loop.py` 是 31KB 的状态机（6 个 stage 硬编码转移）。用户的输入如果不匹配状态机预期，系统无法正确处理。

具体表现：
- Bug #3: "我持有MCO" → fuzzy 子串误命中 EMCOR/Amcor/Kimco → 给错候选
- Bug #4: "我持有汇丰" → SEC 无中文公司名 → dialogue LLM 生成误导文案
- 无限 edge case: "我持有苹果"、"我持有做GPU的"、"我持有巴菲特的公司"

根因：确定性代码做"从自然语言推断 ticker"，有无限 edge case。LLM 有世界知识能直接桥接，但被排除在决策层之外。

## 2. 架构决策

### 从：状态机驱动
```
用户输入 → entry_loop.py state machine → 到某阶段调 LLM 做特定任务
LLM 只在指定节点被调用，做指定的事（抽 ticker、抽 card、生成追问）
状态机决定流程，LLM 没有决策权
```

### 到：LLM 指挥 + 确定性校验
```
用户输入 → OpenAI Agents SDK Agent Loop（DeepSeek V4-Flash）
  LLM 决定调什么 tool、什么时候调、怎么组合
  Tools 提供事实锚定（SEC 查询、结构化抽取、存储）
  Guardrails 在 tool 执行前后插入确定性校验（R1-R9 红线 + G1-G4 流程检查）
```

### 为什么不是"全 LLM"或"全确定性"
- 全 LLM：LLM 会猜 ticker、会编事实 → 需要工具校验
- 全确定性：无限 edge case → 需要 LLM 世界知识
- 正确架构：LLM 带来世界知识（汇丰=HSBC、MCO=Moody's），工具带来事实锚定（SEC 确认 ticker 真实存在）

## 3. 技术选型

| 组件 | 选择 | 理由 |
|---|---|---|
| 语言 | Python（保留） | AI 可维护性最佳；现有 guardrail 代码复杂且测试过 |
| 框架 | OpenAI Agents SDK 0.19.2 | 内置 agent loop + guardrails + streaming + tracing；支持 OpenAI 兼容端点 |
| 模型 | DeepSeek V4-Flash（百炼） | 9 项 agent benchmark 超越 V4-Pro-Preview；$0.14/1M input；Function Calling 支持 |
| 备选模型 | Qwen3.7-plus（百炼） | 支持 FC + 结构化输出双能力；如 DeepSeek tool-use 不稳则切换 |
| 前端 | React（保留） | Phase 3 加 SSE streaming |

### 百炼兼容配置
- base_url: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- API: Chat Completions（百炼不支持 Responses API）
- SDK 配置: `set_default_openai_api("chat_completions")` + `OpenAIChatCompletionsModel`
- 模型名: `deepseek-v4-flash`

## 4. 文件迁移计划

### 保留（guardrail 层，不动）
| 文件 | 行数 | 角色 |
|---|---|---|
| redline.py | ~70 | R1-R3 文案黑名单 |
| conditions.py | ~200 | make_mirror / is_paraphrase / is_price_pattern |
| condition_classify.py | ~250 | InfoType 分类 + is_v1_auto |
| schema.py | ~120 | EntryExtraction / MirrorSpec / OpenQuestion |
| models.py | ~260 | ThesisCard 等模型 |
| tier_map.py | ~50 | ticker → 仓位档查表（保留但不用于录入 agent） |
| store.py | ~150 | SQLite 存储 |
| notify.py | ~200 | 邮件发送 |
| fetchers/sec_edgar.py | — | SEC filing 抓取 |
| fetchers/news.py | — | RSS |
| config.py | ~70 | 配置加载（小改：加 model config） |

### 改（orchestration 层）
| 文件 | 现状 | 改成 | 工作量 |
|---|---|---|---|
| entry_agent.py | PydanticAI 单次抽取 | `@function_tool` 函数，保留 extract 逻辑 | 重写 |
| entry_loop.py | 800 行状态机 | ~200 行 session 管理 + view 序列化 | 大砍 |
| menu.py | LLM 在指定节点生成菜单 | `@function_tool` 函数 | 小改 |
| serve.py | 3 个 JSON endpoint | wire 到 agent loop + SSE streaming | 改 |
| agent.py | harness 骨架 + build_card_from_extraction | build_card_from_extraction 保留为 tool | 小改 |
| check_agent.py | 定时检查 agent | 可改 agent loop（Phase 4） | 后改 |

### 删
| 文件 | 原因 |
|---|---|
| dialogue.py | agent loop 里 LLM 自然对话，不需要单独生成 |
| llm.py | 不再需要 LenientOpenAIChatModel hack |

### 砍
| 文件 | 改动 |
|---|---|
| ticker_resolver.py | 删 fuzzy 子串 + token 扫描，只留精确匹配 + SEC 查询 |

### 新建
| 文件 | 用途 |
|---|---|
| orchestrator.py | OpenAI Agents SDK agent 定义 + tool 注册 + guardrail 注册 |

### 依赖变化
- 删：pydantic-ai（重构完成后）
- 加：openai-agents 0.19.2（已装）
- 保留：openai, pydantic

## 5. Phase 计划

| Phase | 天数 | 内容 | 依赖 | 状态（2026-08-04） |
|---|---|---|---|---|
| 0 | 0.5 | 验证 DeepSeek V4-Flash tool-use | 无 | ✅ |
| 1 | 2-3 | orchestrator.py + 5 tools + guardrails + system prompt | Phase 0 通过 | ✅ |
| 2 | 1-2 | 砍 entry_loop + 修 ticker_resolver + wire serve.py | Phase 1 | ✅ |
| 3 | 1-2 | 前端 SSE streaming + inline 编辑 | Phase 2 | ✅ |
| 4 | 1-2 | check_agent agent loop | Phase 2 | ✅（commit de3e545） |
| 5 | 1-2 | 测试 + eval 重跑 + docs | Phase 2-4 | 🔄 进行中（见下） |

**Phase 5 进度（2026-08-04）**：
- ✅ 测试重做：新增 32 个 agent-loop 行为测试（`tests/test_orchestrator_impl.py` 16 + `tests/test_check_agent.py` 16），覆盖 extract_card G3 / save_card G1·G4·G2 / check_agent 三态 + E1-E8。75 → 107 全绿。
- ✅ 10 case 验收：pytest 离线覆盖 Case 4/6/7/10 + 1/2/8/9 的确定性部分（resolve_ticker / G4）；纯 live/浏览器 UX（Case 3/5 + 各 case 的 UX/翻译）列给 caca 验收。结果见 `docs/eval-refactor.md` 末尾「验收结果」。
- ✅ 清理旧代码（删 llm.py / entry_agent.py / menu.py / pydantic-ai）：**已做**。caca 定切 deepseek；移植 extract+menu 到 OpenAI Agents SDK（`submit_extraction` / `submit_menu` tool call，不用 output_type——避 B4 thinking 冲突 + 短路空结构）；prompts + `MenuMirror`/`MenuCandidates` + `filter_executable_mirrors` 移入 `orchestrator.py`；删 `pydantic-ai`/`pydantic-evals`/`anthropic` 依赖；更新 5 consumer（`entry_cli` / `tests/test_menu_filter` / `scripts/day1_fds_validation` / `evals/run_l1` / `orchestrator`）；107 测试绿；live 验 deepseek extract + G3 双层 ok；W1 eval 重跑 deepseek vs glm 头对头确认不退（见 BLOCKERS B6 已解除）。

## 6. 验收标准

### Regression（不能退步）
- 107 测试全过（guardrail 层不动 + Phase 5 补回 agent-loop 行为测试：旧 entry_loop 状态机测试 Phase 2 砍掉造成 83→75，Phase 5 新增 32 → 107）

### New acceptance cases（5 步讨论式流程）

详见 `docs/eval-refactor.md`（10 个 case，分 3 层）。核心验收：

| 输入 | 期望行为 | 验证点 |
|---|---|---|
| "我开始关注 MCO" | resolve_ticker → 确认 → 问"为什么关注" | 探针仓措辞 |
| "我持有 MCO" | resolve_ticker → 确认 → 问"为什么持有" | 已建仓仍完整讨论 |
| 用户只说 thesis | Agent 逐字段引导 5 步讨论 | 不一口气全问 |
| "不知道怎么估值" | Agent 根据公司业务推荐 2-3 个方法 | 提供选项不问开放题 |
| "无法确定"破局条件 | generate_menu → 呈现候选 | 菜单有效 |
| 缺安全边际就保存 | Guardrail 拦截 | 5 字段全填才能存 |
| "我持有汇丰" | 翻译 → resolve_ticker → 用户确认 | 世界知识桥 + 确认 |
| Agent 编造估值数据 | Guardrail 拦截 | 不允许 LLM 编数据 |

### Performance
- 单票 ≤5min
- tool 调用次数 ≤3 per turn
- SSE streaming 首字延迟 ≤2s

## 7. 红线不变

R1-R9 红线在重构中完全不变。执行方式从"状态机里硬编码"改为"OpenAI Agents SDK guardrails + system prompt 双保险"。新增 G1-G4 流程检查 guardrail（必填字段、幻觉检查、key_assumptions 质量、用户确认）。详见 `docs/guardrail-mapping.md`。

## 8. 讨论式流程设计决策（2026-08-03 确认）

### 角色定位
- 从"录入助手"改为"thesis 讨论伙伴"
- 从"一口气抽取"改为"逐字段讨论"

### 5 步讨论流程
1. Thesis（为什么买）→ 用户说理由
2. Key Assumptions（关键假设）→ Agent 拆解呈现 → **用户确认**
3. 破局条件（mirror + redline）→ Agent 从假设生成 → 用户确认
4. 安全边际（估值）→ Agent 提供选项 → 用户选
5. 持仓周期 → 用户选

### 关键决策
- **不允许部分保存**：5 字段全填才能存（安全边际是建仓触发线）
- **估值方法不硬编码映射表**：Agent 根据公司业务用判断力推荐，不机械套用分类
- **仓位档不放进录入 agent**：是 caca 个人系统，依赖 OpenD，不是通用产品功能
- **key_assumptions 用户确认**：不跳过假设确认直接生成破局条件
- **探针仓 vs 已建仓**：两种用户都完整讨论 5 字段，措辞不同