# 重构规格书：State Machine → Agent Loop

> 基线 tag: `pre-refactoring-arch` (ee7c5b2) | 重构分支: `refactor/agent-loop`
> 创建时间: 2026-08-03 | PM: caca + Notion AI

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
  Guardrails 在 tool 执行前后插入确定性校验（R1-R9 红线）
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
| tier_map.py | ~50 | ticker → 仓位档查表 |
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

| Phase | 天数 | 内容 | 依赖 |
|---|---|---|---|
| 0 | 0.5 | 验证 DeepSeek V4-Flash tool-use | 无 |
| 1 | 2-3 | orchestrator.py + 5 tools + guardrails + system prompt | Phase 0 通过 |
| 2 | 1-2 | 砍 entry_loop + 修 ticker_resolver + wire serve.py | Phase 1 |
| 3 | 1-2 | 前端 SSE streaming + inline 编辑 | Phase 2 |
| 4 | 1-2 | check_agent agent loop | Phase 2 |
| 5 | 1-2 | 测试 + eval 重跑 + docs | Phase 2-4 |

## 6. 验收标准

### Regression（不能退步）
- 现有 83 测试全过（guardrail 层不动）
- entry_loop 测试重写（状态机没了，改为 agent loop 行为测试）

### New acceptance cases
| 输入 | 期望行为 |
|---|---|
| "我持有MCO，看好信用评级壁垒" | resolve_ticker("MCO") → 命中 Moody's → extract_card → 呈现卡 |
| "我持有汇丰，因为股价稳健" | resolve_ticker("HSBC")（世界知识桥接）→ 命中 → extract_card → 呈现卡 |
| "我持有那个做GPU的" | resolve_ticker("NVDA")（世界知识桥接）→ 命中 → 问确认 |
| "无法确定" | generate_menu → 呈现候选 |
| "确认" | save_card → 落库 |
| 空输入（只有 ticker 没理由）| 问理由 |

### Performance
- 单票 ≤5min
- tool 调用次数 ≤3 per turn
- SSE streaming 首字延迟 ≤2s

## 7. 红线不变

R1-R9 红线在重构中完全不变。执行方式从"状态机里硬编码"改为"OpenAI Agents SDK guardrails + system prompt 双保险"。详见 `docs/guardrail-mapping.md`（待写）。