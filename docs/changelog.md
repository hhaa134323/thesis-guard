# 版本变更记录（Changelog）

> 规则：每次迭代写清楚——依据哪条用户反馈、砍了什么、为什么砍。KILL 判据体检结果也记这里。

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
