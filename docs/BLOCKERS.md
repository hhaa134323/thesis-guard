# BLOCKERS

> 维护本文件直到所有阻塞项清零。每项含：现象、影响、缓解、状态。

## B1 — 外网直连被 reset（GitHub / SEC.gov；Notion 已恢复）

- **现象（2026-08-01 复测）**：本机 shell 无代理配置。直连测试：
  - `api.github.com` → 仍 reset（未复测，按前次结论）。
  - Notion MCP：**已恢复只读可达**——`notion-fetch`（含 `self` 探活）+ `notion-search` 的 `workspace_search` 模式正常工作；AI 语义搜索（默认 `ai_search`）首次报 socket closed，疑似 AI-search 后端不稳，**优先用 `content_search_mode: "workspace_search"`**。
  - `www.sec.gov` → 仍 reset（未复测）。
  - `www.baidu.com` → 200（国内网络正常）。
- **影响**：
  1. 无法 clone 私有库 `hhaa134323/pre-market-briefing` → 拿不到复用源码（sec_edgar / news / thesis / alerts / sinks）。**用前先告诉作者，不自重写。**
  2. ~~无法用 Notion MCP 只读拉台账/简报/Skill/spec 快照~~ → **已解除**：2026-08-01 已只读拉取全量快照到 `assets/`（见 B3）。
  3. 无法做竞品 web 调研（`docs/competitor-teardown.md`）——`web.search`/`web.loadPage` 走外网，仍受阻。
  4. 核对 Agent 的 SEC EDGAR 在线抓取仍受阻（产品核心数据源，W2 前需解除或走代理）。
- **缓解（待作者选一，仅 GitHub/SEC 部分）**：
  - (a) 启用系统级 VPN（TUN 模式，无需 env proxy 即可全局生效），完成后告知；
  - (b) 提供代理地址，我在 shell 设 `HTTPS_PROXY`/`git config http.proxy` 后重试；
  - (c) 作者自行 `git clone https://github.com/hhaa134323/pre-market-briefing D:/AgentProjects/pre-market-briefing`，我直接从本地复用。
- **状态**：部分解决。Notion 只读已通；GitHub/SEC 仍受阻，阻塞 pre-market-briefing 复用、竞品调研、SEC 在线抓取。

## B2 — 0 号用户使用记录缺失

- **现象**：PRD「需求证据」需要 0 号用户数月日常使用记录作为基线。**首条记录已入**（见下），但仍需纵向积累。
- **首条记录（2026-08-02，SK 海力士真实运行）**——驱动 v0.0.12 六项修复（P0–P5）：
  1. 输入「我持有SK海力士」→ 系统抽出 ticker = **SKHCF**（Sonic Healthcare，澳洲 OTC；正确是 **SKHY**，SK Hynix ADR，CIK 2120882）。根因：ticker 交给 LLM 猜，而它是确定性查询 → **P0** 改 SEC 官方表 `ticker_resolver` 解析。
  2. 确认阶段问「下次财报什么时候」+ 另一问，系统两次答非所问、原样返模板 → **P1** confirm 阶段 intent 分流（确认/修改/提问三路，提问类走 SEC fetch 附链接）。
  3. `key_assumptions` 填了一遍同义复述 → **P2** 四条合格定义 + 拒绝规则（`is_paraphrase` 确定性 backstop）。
  4. 估值锚候选给出 4 个，2 个系统执行不了（跨标的 capex / TrendForce 付费数据）→ **P4** 可执行性过滤 + 覆盖率显式呈现。
  5. `entry_anchor` 台账已填但卡片显示「未检出」→ **P3** 前端始终渲染（method+current+history 折叠）。
  6. 持仓周期台账有、card 无 → **P5** 补 `holding_horizon`（long/mid/trade，问用户不模型猜）。
- **影响**：首条记录已驱动 v0.0.12 修复；仍需数月纵向记录支撑 PRD 优先级定稿。
- **状态**：部分解决（首条已入，驱动 v0.0.12）；仍需纵向记录，不阻塞动工，但阻塞 PRD 定稿。

## B3 — assets/ 快照缺失 → ✅ 已解除（2026-08-01）

- **现象（历史）**：目标文本假设「eval 基准已快照定格」，但 `assets/` 实际为空，快照文件均不存在。
- **现状**：**已解除**。从 Notion 只读拉取并定格全量快照：
  - `assets/notion/thesis/` 台账 16 行（`00_schema_and_small_rows.md` + 12 ticker 单文件，复盘备注逐字照抄）；
  - `assets/notion/briefing_db_overview.md`（schema + 71 行元数据）；
  - `assets/notion/skill_thesis_review_v4.md`（复查 Skill v4 全文）；
  - `assets/notion/spec_public_v1_20260610.md` + `assets/onboarding_dryrun_0731.md`（此前已落地）。
- **状态**：已解除。两层 eval 基准已就位。

## 依赖 B1 的待办（按状态标注，2026-08-01）

1. ⛔ clone `pre-market-briefing` 到 `D:/AgentProjects/pre-market-briefing`（或作者指定位置）——GitHub 仍受阻（B1）。
2. ⛔ 核对复用模块清单是否与目标一致（sec_edgar / news / thesis / alerts / sinks / config / README）——待 clone。
3. ✅ Notion 只读拉取快照到 `assets/`，定格不再更新——2026-08-01 完成（台账 16 行 + briefing + skill v4）。
4. ✅ 用台账 schema 对齐 `docs/thesis-card-schema.md`——快照已含 schema，11 属性一致。
5. 🔵 基于 `skill_thesis_review_v4.md` 起草核对 Agent 提示词——W2 任务（skill 已落地）。
6. 🔵 基于 `onboarding_dryrun_0731.md` 起草 `docs/entry-agent-spec.md`——W1 进行中。
7. 🔵 跑双层 eval，出 `docs/eval-report.md`——W1 进行中（L1 抽取一致率）。
8. ⛔ 竞品 web 调研，出 `docs/competitor-teardown.md`——外网受阻（B1）。

## B4 — thinking 模式与 tool_choice=required 冲突（选模型硬约束）

- **现象**：deepseek-v4-flash（默认 thinking 模式）gate 5/5 返 400 `tool_choice does not support being set to required or object in thinking mode`。
- **根因**：PydanticAI 单次结构化输出强制 `tool_choice=required` 保证必出 tool call；部分模型（DeepSeek 系 thinking 版、可能其它 thinking 模型）在 thinking 模式下拒 `tool_choice=required/object`。
- **约束**：**以后换任务模型，先查这项**——候选模型不能默认 thinking。关 thinking 要走 provider 专有参数（`extra_body`），会塞 hack 进 LLM 层、破坏 model-agnostic，**不走**（作者 2026-08-01 否决 (a) 路线）。直接选非 thinking 的轻量模型。
- **已试**：deepseek-v4-flash（400）、deepseek-v4-flash-0731（403 access denied）。见 `docs/eval-report.md` §1。
- **状态**：硬约束，选模型必查。

## B5 — 部分模型被 provider 归类为 code model，tool-call arguments 间歇不合规（选模型硬约束）

- **现象**：qwen-flash gate 4/5 返 400 `InternalError.Algo.InvalidParameter: The "function.arguments" parameter of the code model must be in JSON format.`（1/5 过）。
- **根因**：DashScope 把 qwen-flash 归类为 "code model"，对 tool-call 的 `function.arguments` 格式有额外要求，间歇不合规。
- **约束**：**选模型时除 B4（thinking 冲突）外，还要查「是否被 provider 归为 code model」**——code model 的 tool-call arguments 格式间歇被拒，做结构化输出不稳。
- **已试**：qwen-flash（4/5 400，1/5 过 out_tok=438）。见 `docs/eval-report.md` §1。
- **状态**：硬约束，选模型必查（与 B4 并列两项）。

## B6 — Phase 5 清理旧代码 blocked（删 llm.py / entry_agent.py / menu.py / pydantic-ai）

- **现象（2026-08-04）**：Phase 5 任务含「删 llm.py / entry_agent.py / menu.py / pydantic-ai 依赖」，但执行时发现前提不成立——任务说「extract_card/generate_menu 已不依赖，orchestrator 内置」，实际 `orchestrator.py` 仍 `from .entry_agent import build_agent, extract` + `from .menu import build_menu_agent, generate_menu, filter_executable_mirrors`（行 43-47）。`extract_card` / `generate_menu` 工具内部仍委托 PydanticAI + glm-5.2-fast-preview（task_model），Phase 1 主动留的 delegation（"重构完成后再删"）。
- **根因（三项叠加）**：
  1. **前提不成立**：不能"直接删"——需先把 extract + generate_menu 移植到 OpenAI Agents SDK（nested agent 或直接 chat_completions + function-calling schema），再删。
  2. **产品决策（待 caca 定）**：移植时提取模型选 glm（W1 胜率 96% + W2 接受率 85.45%，eval 验过）还是切 deepseek（unify 栈，但需重跑 W1/W2 eval 确认质量不退）。这是模型/产品决策，不擅自定。
  3. **网络不通（2026-08-04）**：DeepSeek 百炼端点 APIConnectionError（上 session check_agent smoke 还通，本 session 不通，疑似 sandbox/网络波动）。移植后无法 live 验证——extract_card 是 core live-verified 流程（G3 双层），不验证就动不负责任。
- **影响**：Phase 5「清理旧代码」子项未完成。但 extract_card/generate_menu 当前 delegation **工作正常**（Phase 1 live-verified），删除是 cleanup 非 correctness fix，不阻塞产品功能。
- **缓解（待 caca 选 + 网络通）**：
  - (a) caca 定提取模型：glm 保留（保守，不退质量）vs 切 deepseek（unify，需重跑 eval）；
  - (b) 保守方案（不需模型决策）：保留 glm + 移植到直接 OpenAI chat_completions（function-calling tool schema 强制结构化输出），drop pydantic-ai + llm.py——但仍需网络通时 live 验 extract 质量不退；
  - (c) 网络通时移植 + 重跑 W1/W2 extract eval 确认 + 更新 5 个 consumer（`entry_cli.py` / `tests/test_menu_filter.py` / `scripts/day1_fds_validation.py` / `evals/run_l1.py` / `orchestrator.py`）。
- **状态**：✅ 已解除（2026-08-04）。caca 定切 deepseek；移植 extract+menu 到 OpenAI Agents SDK（`submit_extraction` / `submit_menu` tool call 提交结构化输出，不用 `output_type`——避 B4 thinking 冲突 + 短路空结构）；删 `entry_agent.py` / `menu.py` / `llm.py` + `pydantic-ai`/`pydantic-evals`/`anthropic` 依赖；prompts + `MenuMirror`/`MenuCandidates` + `filter_executable_mirrors` 移入 `orchestrator.py`；更新 5 个 consumer（`entry_cli` / `tests/test_menu_filter` / `scripts/day1_fds_validation` / `evals/run_l1` / `orchestrator`）；107 测试绿；live 验 deepseek extract + G3 双层 ok；W1 eval 重跑 deepseek vs glm 头对头（`evals/_l1_result.json`，`run_l1.py run --allow-stale-gt`，PYTHONUTF8=1 避 Windows gkb 崩 ⚠️ print）。
