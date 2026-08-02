# 版本变更记录（Changelog）

> 规则：每次迭代写清楚——依据哪条用户反馈、砍了什么、为什么砍。KILL 判据体检结果也记这里。

## v0.0.3 — 2026-08-01 — Notion 快照全量落地 + 过时状态修正 + W1 推进

**做了什么**
- 从 Notion 只读拉取并定格 `assets/` 全量快照（**复盘备注逐字照抄，未做任何摘要**——eval ground truth，摘要即废）：
  - `assets/notion/thesis/` 台账 16 行全量：`00_schema_and_small_rows.md`（schema + QQQ/DPZ/SPGI/GDXU）+ 12 个 ticker 单文件（NVDA/VEEV/MCO/GOOGL/CGNX/NOW/NFLX/CRM/FIS/FDS/HSBC/BRK.B）。
  - `assets/notion/briefing_db_overview.md`（简报库 schema + 71 行元数据，单日正文留 Notion）。
  - `assets/notion/skill_thesis_review_v4.md`（复查 Skill v4 全文，核对 Agent 提示词起点）。
- 实测 Notion MCP 可达：`notion-fetch`（含 `self` 探活）+ `notion-search` 的 `workspace_search` 模式正常；AI 语义搜索（`ai_search`）首次报 socket closed，疑似后端不稳，优先用 `workspace_search`。GitHub / SEC.gov 直连仍受阻（pre-market-briefing 仍未 clone）。
- 修正过时状态文档：CLAUDE.md「资产现状」、README「Notion 资产」快照清单与文档索引状态、`docs/BLOCKERS.md` B1（部分解决）/B3（已解除）/依赖待办，均改为当前真实状态。
- 建立项目记忆（`memory/`）：红线 R1–R7 + R7 只读自守（本机 `--dangerously-skip-permissions` 无写确认门）、资产清单、W1 阶段与停止点、KILL 判据、本机环境事实、运行模型 glm-5.2（eval 须记模型名版本）。

**依据**
- 作者指令：补齐 10 个 ticker 快照（复盘备注逐字不得摘要）+ briefing + skill v4；修正过时状态；推进 W1。实测台账实际 16 行（含 VEEV，作者清单未列），顺手补齐 VEEV 以保证 eval 基准完整——已在汇报中标注，作者可决定是否保留。

**砍了什么 / 为什么**
- 不重写 `pre-market-briefing` 源码（fetchers 等）——作者规则：未 clone 时用前先问，不自重写；GitHub 受阻时也不臆造。
- changelog 历史 entry（v0.0.2 的「B3 assets/ 空」）原样保留——那是 v0.0.2 时的事实，改写即篡改历史；当前状态由本 v0.0.3 entry 承载。
- 复盘备注用脚本逐字拷贝（JSON 字段直写文件，不经 LLM），从机制上杜绝摘要/改写风险。

**阻塞（详见 BLOCKERS.md）**
- B1 部分：GitHub/SEC 仍受阻 → pre-market-briefing 未 clone、SEC 在线抓取、竞品 web 调研仍受阻。
- B2 未变：0 号用户日常使用记录仍缺。
- B3 已解除。

## v0.0.4 — 2026-08-01 — W1 录入 Agent：PydanticAI 接入 + 多模型 gate + 配置分离 + finish_reason 修复

**做了什么**
- 技术选型确认（作者定）：生产 responder 用 **PydanticAI 单次结构化调用**（非 Claude Agent SDK——百炼兼容端点非 Anthropic 原生、Agent SDK 能力错位、loop 抖动污染指标、CLI 运行时依赖锁死第三方）。schema 直接定义成 pydantic 模型（数据契约 + LLM 输出契约共用一份），eval 用 pydantic-evals。`src/thesis_watch/schema.py` + `llm.py`。
- 配置分离（`config.yaml` / `config.example.yaml`）：`session_model`（glm-5.2 / Anthropic 端点，产 spec/schema/prompt）与 `task_model`（录入抽取 + eval）两个独立项，不复用同一字段。key 走 env（`api_key_env`）。
- day-1 gate（`scripts/day1_fds_validation.py`，FDS 连跑 5 次，5/5 才过）+ **Gate 门槛预注册**（`docs/eval-plan.md` §6，写定不改）：失败按原因分类（provider 拒绝/length/SDK 校验→修配置换模型门槛不动；schema 不符→先重试再议降门槛）。
- 多模型 gate 横向（见 `docs/eval-report.md` §1）：glm-5.2 2/5（length）、deepseek-v4-flash-0731 0/5（403）、deepseek-v4-flash 0/5（thinking 冲突）、qwen-flash 1/5（code model）、qwen3.6-flash 0/5（thinking）、glm-5.2-fast-preview 4/5（finish_reason 非标）。
- **finish_reason 修复**（SDK 层容错，不动 schema/tool_choice/gate）：pydantic-ai `_ChatCompletion` 只放宽 service_tier、漏 finish_reason；子类化 `OpenAIChatModel` 覆写 `_validate_completion`（pydantic-ai 设计的 hook）用 `_LenientChatCompletion` 放宽 finish_reason（`src/thesis_watch/llm.py`）。修完原样重跑 5 次（进行中）。
- `position_cap_tier` 从 LLM 输出契约移除 → 规则查表（`src/thesis_watch/tier_map.py`，按 Skill v4 档位）。归因：字段依据不在输入内，**schema 设计错误不是模型能力问题**——确定性信息不该交给模型。
- 限流防护：LLM 层加请求间隔 + 429 指数退避重试（上限从 config 读）；429 与其它错误分开计数进 per-call 指标表。eval 批跑串行（max_concurrency=1），不并发。本轮实测 1 次 429，退避后通过。
- 选模型硬约束两条记 BLOCKERS：B4（thinking + tool_choice=required 冲突）、B5（code model 归类，tool-call arguments 间歇不合规）。

**依据**
- 作者：PydanticAI 单次结构化 + pydantic-evals；模型/端点 config 驱动；key 走 env；会话/任务模型分离（避免争抢额度 / 消除 eval 自评污染 / 批量成本）；gate 5/5 门槛写定；failure 按原因分类。
- 作者：DeepSeek 系优先作废（无实质依据）；关 thinking 否决（破坏 model-agnostic）；放宽 tool_choice 否决（迁就模型）。

**砍了什么 / 为什么**
- 【3】「精简 description 降 out_tok」**假设证伪**：同一 schema 下 qwen-flash out_tok=438 vs glm 系 4364，证明 out_tok 大是 glm 系 verbose 不是 description 冗长。该待办关闭（见 eval-report §2.3）。
- 不关 thinking（保 model-agnostic）、不放宽 tool_choice（保结构化输出保证）、不降 gate 门槛（5/5 不变）。

**阻塞**
- gate 5/5 待 lenient 修复后重跑确认（进行中）。
- B4/B5 为选模型硬约束（已记 BLOCKERS）。
- 任务模型未最终定（glm-5.2-fast-preview 待 5/5 确认；qwen-turbo/qwen-plus 备选待 gate 后试，不阻塞 W1）。

## v0.0.2 — 2026-07-31 — 代码骨架（数据/逻辑层）+ 双 Agent 提示词 v0.1

**做了什么**
- 写 `src/thesis_watch/` 包（纯 stdlib + pyyaml）：
  - `models.py`：ThesisCard/Assumption/BrokenCondition/Evidence/CheckResult 等，含通用 serde（dataclass↔JSON），强制一手链接字段（R5）、历史示例带 `verified`（R5）。
  - `conditions.py`：两层逻辑——镜像构造 `make_mirror`、默认红线包 `default_redline_pack`（阈值可调）、价格图形型检测 `is_price_pattern`（→ 人工自查）。
  - `redline.py`：R3/R5 文案黑名单 + `guard`（命中即 E8）。
  - `config.py` / `evidence.py` / `store.py`：用户可配阈值、证据自检契约（fetcher 可注入）、SQLite 单库 + 5 人预置账号。
- 写双 Agent 系统提示词 v0.1（`src/thesis_watch/prompts/{entry,check}-agent.md`）：编码红线、拒判、证据自检、状态机、6-K 路由规则；栈无关（方案 A/B 皆可加载）。
- 写 `src/thesis_watch/agent.py`：harness 骨架——工具注册分发 `ToolRegistry`、可插拔 `Extractor`（mock/真实）、`build_card`（对话→两层卡）、`render_summary`（复述，经 redline.guard）、`demo()`。mock extractor 跑通端到端，真实 responder（A/B）替换即可。
- 写测试套件 `tests/`（42 例，全绿）：models serde round-trip、redline 命中、两层逻辑、evidence 自检、store 持久化、agent 骨架（含脏镜像触发 guard）。
- 装 pytest 9.1.1（走清华镜像，国内 PyPI 可达）。

**依据**
- 目标功能要求 + 红线逐条落到代码与提示词；设计文档（v0.0.1）为基线。
- 0 号用户反馈：尚无。

**砍了什么 / 为什么**
- 不写 agent loop 本体（A/B 待作者拍板）、不接 fetchers（待 B1 clone）、不写前端（栈待确认）——避免在未确认选型上做重投入，降低返工。
- 历史事件示例一律 `verified=False` + 占位，不编造来源（R5）；待网络恢复用一手链接补齐。

**验证**
- `python -m pytest tests/ -q` → 42 passed。
- `PYTHONPATH=src python -m thesis_watch.agent` → 端到端跑通，产出合法 card_json（控制台中文乱码为 Windows GBK 码页问题，数据为正确 UTF-8）。

**阻塞（详见 BLOCKERS.md）**
- B1 外网 reset：clone 源库、Notion 快照、竞品调研、SEC 在线抓取、真实 fetcher 集成仍受阻。
- B2 0 号用户记录缺失。
- B3 assets/ 空。

## v0.0.1 — 2026-07-31 — 仓库骨架 + 设计文档 v0.1

**做了什么**
- 建仓库骨架：`docs/` `assets/notion/` `src/` `.claude/agents` `.claude/tools`。
- 写定基线文档：`README.md`（红线表、复用资产表、Notion 用法）、`CLAUDE.md`。
- 写设计文档 v0.1：`docs/PRD.md`、`docs/harness-design.md`、`docs/thesis-card-schema.md`、`docs/broken-condition-schema.md`、`docs/eval-plan.md`。
- 写阻塞 runbook：`docs/BLOCKERS.md`。

**依据**
- 目标文本（/goal）给定的全部约束与资产清单，逐条转写为文档基线。
- 0 号用户反馈：尚无（见 B2）。

**砍了什么 / 为什么**
- 本轮无砍切，仅奠基。技术选型（Claude Agent SDK vs 手搓 SDK loop、前端 PWA 栈）以「提案 + 理由」形式写进 `docs/harness-design.md`，待作者拍板后再固化。

**阻塞（详见 BLOCKERS.md）**
- B1 外网 reset：clone 源库、Notion 快照、竞品调研、SEC 在线抓取全部受阻。
- B2 0 号用户记录缺失：PRD 需求证据待补。
- B3 assets/ 空：与目标「已快照定格」描述不符，已记录。

**下一里程碑目标（第 1 周）**
- 对话录入跑通：聊 3 分钟生成一张 thesis 确认卡（含可判定性追问 + 复述确认）。
- 用台账做对话抽取一致率 eval，目标 ≥ 85%。
- 阻塞解除后启动；启动前与作者确认选型。
