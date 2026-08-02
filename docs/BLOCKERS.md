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

- **现象**：PRD「需求证据」需要 0 号用户数月日常使用记录作为基线，当前无数据。
- **影响**：PRD 需求证据章节为占位，无法支撑优先级排序的真实依据。
- **缓解**：作者提供记录（哪怕是原始便签/截图转述），我结构化进 PRD。
- **状态**：未解决，不阻塞动工，但阻塞 PRD 定稿。

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
