# 版本变更记录（Changelog）

> 规则：每次迭代写清楚——依据哪条用户反馈、砍了什么、为什么砍。KILL 判据体检结果也记这里。

## v0.0.16 — 2026-08-04 — Phase 4：check_agent agent loop 重构（pydantic_ai → OpenAI Agents SDK + DeepSeek）

**做了什么**
- **架构转换**：`check_agent.py` 从 `pydantic_ai.Agent(output_type=CheckVerdicts)` + run_check 预取 filings 灌进 prompt → OpenAI Agents SDK `Agent` + DeepSeek V4-Flash（百炼 chat_completions，与 orchestrator 同款 `OpenAIChatCompletionsModel` + `set_default_openai_api`）。agent 自己调工具取 filings 再提交判决，不再预取灌进 prompt。
- **2 个 @function_tool（context-injected via `RunContextWrapper[CheckCtx]`，确定性，不让 LLM 传参）**：
  - `fetch_recent_filings()` — 复用 `sec_edgar.forms_for_filer` + `fetch_filings`，按 filer_type 路由表单；写回 `ctx.fetched_filings` / `fetch_error` / `fetch_called`。
  - `submit_verdicts(verdicts)` — `strict_mode=False`（list[dict] 嵌套入参，与 `orchestrator.save_card` 同款），替代 `output_type` 做结构化输出通道；写回 `ctx.verdicts_submitted`。
- **为什么不用 `output_type=CheckVerdicts`**：实测 DeepSeek V4-Flash + chat_completions 用 output_type 会短路成空 `{"verdicts":[]}` 而不先调 fetch（trace 实测：ReasoningItem 说「该调 fetch」→ 直接产空 CheckVerdicts 结束 loop）。改 `submit_verdicts` tool call 后稳定（与 orchestrator `extract_card`/`save_card` 同款；prompt 收紧「先调 fetch_recent_filings，再调 submit_verdicts，不复述」）。
- **redline R1-R3 复用不变**：per-verdict `redline.guard(v.reasoning)`（粒度 E8，仅校验 LLM reasoning 系统输出，不校验 SEC 引用摘录）。
- **E1-E8 + fetch_called 诚实区分**：`fetch_error` → E1（fetch 失败）；`not fetch_called` → E7（agent 跳过 fetch 无据判定）；`not fetched_filings` → 全 untriggered（PRD「无事那行不许空」）；`not verdicts_submitted` → E7（未提交判决）；缺 cond → E4。
- **输出格式不变**：`CondVerdict(cond_id/status/evidence_url/evidence_excerpt/reasoning)`，status ∈ triggered|watch|untriggered（**三态**）。`run_all`/`run_check` 签名 + 返回 shape 不变（`notify.py` 依赖）。懒构建 `build_check_agent`（不在模块 import 时 SystemExit，避免阻断 orchestrator/tests 导入）。
- 不动 `orchestrator.py` / `serve.py` / 前端 / `entry_agent.py` / `menu.py`（仍走 pydantic_ai task_model=glm，Phase 5 再统一）。

**依据**
- refactor-spec §5 Phase 4 = 「check_agent agent loop」（纯架构转换）。任务原文写「判 HOLD/ADD/CUT/PASS、保持四判决格式不变」——核对后确认矛盾：HOLD/ADD/CUT/PASS 是**作者个人 Notion 复查 skill v4**（建仓后每日跑），不是本产品模块；产品 `check_agent` 一直是三态（`models.py` 明写「不存结论/建议」，旧 CHECK_PROMPT 明写「不给买卖/仓位建议、不替用户结论」），HOLD/ADD/CUT/PASS 本质是仓位/买卖建议，直接踩 R1/R2/R6 红线。经作者确认（AskUserQuestion）：**保持三态，纯架构转换，HOLD/ADD/CUT/PASS 不混入**。Notion 写入经作者确认 R7 仅限台账/简报，PM 看板可更新。
- 本地 `config.yaml` 加 `llm.agent_model` 段（gitignored，仅本机；`config.example.yaml` 已有）——否则 `orchestrator._build_model` import 时 SystemExit，75 测试全跑不起来。

**自测**
- 75 pytest 绿（无 regress；check_agent 无专属单测，公共 API 不变）。
- live MCO smoke（合成卡 + `:memory:` store + lookback 8760h=1y → 105 filings）：agent 先调 `fetch_recent_filings`（105 filings）再调 `submit_verdicts`（4 verdicts 全 untriggered）→ `run_check` 全链路（self_check/redline/save）→ `errors=[]` 无红线违反、4 CheckResults 落库、三态输出、`filings_count=105`。dur 84.6s（≤5min/case 内）。
- SEC fetch 直测：`fetch_filings(["MCO"], 8760)` → 105 filings（10-Q 2026-07-23 / 8-K 2026-07-22 / Form 4…），网络通。

**状态**：Phase 4 完成，待作者验收 + Phase 5（全量 10 case 验收 + 测试重整）。

## v0.0.15 — 2026-08-03 — F3 后端 view 字段（ticker_title / sources / menu.coverage）——给前端不猜字段名

**做了什么**
- **`view.ticker_title`**（F3 #6 公司全名）：`ticker_resolver` 命中时存 `TickerMatch.title` 到 session，`_view` 顶层返回；未命中/未 resolve → null。**注意：无 exchange 字段**——SEC `company_tickers.json` 无交易所信息，给不了。
- **`view.sources`**（F3 来源块 R5）：confirm 提问类 SEC `fetch_latest_filing` 命中时，结构化 `[{form,date,url,note}]` 存 session，`_view` 顶层返回；未命中/未问 → []。
- **`view.menu.coverage`**（F3 #5 已排除方向）：`_view` 在 S_MENU 态给 `menu.coverage = {total,excluded,reasons[],excluded_items[]}`（P4 的结构化版，原本只在 assistant 文本里）。`excluded_items` 每条 `{mirror_text,reasons[]}`。
- **已存在确认**（前端问的）：`card.broken_conditions[].source_type`（per-condition 数据来源，P3 加的，**在 view 里**）+ `threshold` + `layer`(mirror/redline) ；`view.open_questions[].text` = 被拒候选原文（P2）；`card.entry_anchor = {anchor_type,anchor_value,note}`（**单读数，无 history 数组**——§5 history 多时点是未来后端事）。

**依据**
- 前端窗口 F3 开工，按「后端先给 view 字段、前端不猜字段名」规矩对齐形状。

**自测**
- 83 测试绿（79 + 4 个 view 形状契约测试：ticker_title/sources 默认+设置、menu.coverage 形状、非 menu 态 menu=null）。

**状态**：F3 后端字段落地，等前端按形状渲染。本地提交（push 看 B1）。

## v0.0.14 — 2026-08-03 — 真跑 smoke 发现的 2 个 P0 bug 修（ticker token 扫描误命中 + filer_type LLM 兜底没去干净）

**做了什么**
- **Bug #1 ticker token 扫描误命中**：`ticker_resolver` 去掉句中 ticker 词扫描（论据里的 AI/HBM/capex 凑巧匹配真实 SEC ticker 会被误当候选）。只剩「整串精确 + 英文公司名模糊」。实测「我持有SK海力士，因为 AI 算力…HBM 需求…」原被误判成 AI(C3.ai)/HBM(Hudbay) 候选让用户选，现 → [] → 通用澄清「说代码或公司名」。删死代码 `_scan_ticker_tokens`/`_ticker_set`/`_TOKEN_RE`/`import re`。+ 回归测试（fixture 加 AI/HBM，验论据词不误命中）。
- **Bug #2 filer_type LLM 兜底没去干净**：`agent.build_card_from_extraction` 里 `filer_type=None` 时原回退 `ext.filer_type`（LLM 猜的），与 P0 审计「filer_type 不经 LLM」矛盾（卡上 filer=foreign_issuer_20f_6k + open_question 说「待确认」自相矛盾）。改 `filer_type=None → FilerType.OTHER`，卡显示 OTHER + open_question 一致。SKHY 的正确 foreign_issuer_20f_6k 要靠 `fetch_filer_type.py` 加进 `filer_type_lookup.yaml`（确定性），不靠 LLM。

**依据**
- v0.0.12+v0.0.13 后真跑一轮 SK海力士录入（curl 端到端）发现的 bug。Bug #1 是 P0 token 扫描太激进；Bug #2 是 P0 filer_type 改一半（`_resolve_filer` 去了 model_fallback 但 `build_card_from_extraction` 还回退 ext.filer_type）。

**自测**
- 79 测试绿（78 + 1 Bug #1 回归测试）。真跑验：start → 通用澄清（无 AI/HBM）；回 SKHY → card.filer_type=other + open_question「待确认」（一致）。

**状态**：2 bug 修好 + 端到端验过。本地提交（push 仍受 B1 GitHub 间歇 reset 阻塞）。

## v0.0.13 — 2026-08-03 — P2 条件4 确定性 backstop（condition_classify 接进抽取拒绝）

**做了什么**
- `entry_loop._apply_key_assumption_rejection` 加条件4（不可证伪）确定性 backstop：抽出的 key_assumption 过 `condition_classify`+`is_v1_auto`，**非 auto 的假设（其镜像必也非 auto、无可判定阈值）→ 转 open_question**。与菜单路径（P4 `filter_executable_mirrors`）同款 `condition_classify`，两路径对齐。
- 条件3（同义复述，`is_paraphrase`）先跑、条件4 后跑；条件 1/2 仍由 LLM 抽取时自判（进 `ext.open_questions`）。
- 测试 +4（含 SK海力士 4 假设复现：只留毛利率，ASP/份额/结构性 转 open_question 标条件4）。

**依据**
- v0.0.12 目检（SK海力士）发现 P2 半过：条件3（同义复述）`is_paraphrase` backstop 拦住了；但条件4（不可证伪）只靠 LLM 自判没拦住——ASP/份额/结构性 3 条无 auto 镜像的假设留在 `key_assumptions`、没转 `open_questions`。菜单路径（P4）用 `condition_classify` 排除了这 3 条，抽取路径没用 → 两套标准。本轮对齐。

**自测**
- 78 测试绿（v0.0.12 的 74 + 4 新条件4 测试）。

**状态**：P2 条件4 落地，serve 已加载新代码，等目检复跑（重跑 SK海力士 验 ASP/份额/结构性 进 open_question）。

## v0.0.12 — 2026-08-03 — SK 海力士真实运行驱动的六项修复（P0–P5）+ eval §7.1 逐字段

**做了什么**
- **P0 ticker 确定性解析 + schema 审计**：新增 `src/thesis_watch/fetchers/ticker_resolver.py`（SEC 官方 `company_tickers.json` + 本地缓存≤30d + User-Agent from env + `resolve(query)->list[TickerMatch]`，精确/模糊top3/空；CJK 紧贴守卫防「SK海力士」抽出 SK 误命中）。`entry_loop` 替换 LLM 出 ticker：1→用，>1→列候选问选，0→问，不猜（`ext.ticker` 弃用）。`filer_type` 去 LLM 兜底（查表无→pending）。`docs/thesis-card-schema.md` §6 全字段确定性审计表。验收：输入「我持有SK海力士」→ [] → 问用户 → SKHY，不出 SKHCF。
- **P1 confirm 阶段 intent 分流**：`dialogue.py` 加 `classify_confirm_intent`（confirm/modify/question 关键词分类）+ `is_factual_fetchable`。`entry_loop` S_CONFIRM 文本输入三路：确认→模板逐字保真；修改→引导右侧点改；提问→ LLM 应答 + SEC `fetch_latest_filing` 实取附一手链接（R5），取不到明说「查不到」+ 重新输出复述确认段拉回。验收：confirm 问「下次财报什么时候」→ 带 SEC 链接答案或查不到 + 重新显示确认卡。
- **P2 key_assumptions 定义 + 拒绝规则**：`thesis-card-schema.md` §7 + `prompts/entry-agent.md` + `entry_agent.py` SYSTEM_PROMPT 落地四条合格定义（关于这门生意/可能为假/比原话多信息/可对应带阈值镜像）+ 2 正例 2 反例（估值口径误当假设、同义复述）。`schema.py` 加 `OpenQuestion`；`entry_loop` 抽取阶段每条候选过四关（LLM 自判→ext.open_questions）+ 条件3 确定性 backstop `conditions.is_paraphrase`。输入隔离：加仓价/安全边际只流向 entry_anchor。验收：录 MCO/FDS，key_assumptions 不再换词重写，不确定转 open_question。
- **P3 mirror 强制可判定阈值 + entry_anchor 前端渲染**：`conditions.make_mirror` 强制产 `threshold`+`source_type` 二元组，任一缺→返 None 转 open_questions（禁 threshold:null；与 default_redline_pack 对齐，redline 加 source_type=sec_filing_field）。`schema.MirrorSpec`/`menu.MenuMirror` 加 threshold+source_type；`agent.build_card_from_extraction` 返 `(card, rejected_mirrors)`，entry_loop 转 open_questions。前端 `App.tsx` entry_anchor 始终渲染（method+current+history 折叠，无数据显示「未检出」），重建 static/。
- **P4 估值锚候选可执行性过滤 + 覆盖率显式**：`menu.py` 加 `filter_executable_mirrors`（condition_classify 驱动，跨主体/第三方/价格图形型 → 不呈现）。`entry_loop._do_menu` 过滤后 `_present_menu`/`_ctx_menu` 显式告知「原本 N 个方向，M 个无法自动核对，已排除（原因）」（PRD §4-A 不静默跳过）。
- **P5 字段对齐文档 + holding_horizon**：`thesis-card-schema.md` §4 完整对照表（11 台账字段 + 7 card 新增字段，逐行标刻意偏离/已对齐/本轮补，0 遗留）；§1 状态改「已对齐」；§3 改写为已执行结论。`models.ThesisCard` 加 `holding_horizon`（long≥3y/mid 3m-3y/trade≤3m，录入问用户不模型猜→open_question，应影响 mirror 阈值时间尺度）。前端 drawer 加持仓周期 select，重建 static/。
- **eval-report §7.1 逐字段**：接受率从单一总分改逐字段——mirrors 25/25(0%)、holding_reason_raw 4/5(20%)、key_assumptions 18/25(28%)，合计 47/55=85.45%；95% CI≈[76%,95%]，过线 0.45pp 小于一个字段(1.82pp)。
- **BLOCKERS B2**：记入 2026-08-02 SK海力士真实运行为首条记录（驱动本六项）。
- **红线 R9**：脱敏清单新增 `data/thesis.db`（SQLite store）、SK海力士真实运行 transcript/记录、新 transcript 样本。

**依据**
- 0 号用户首条真实运行记录（SK海力士，2026-08-02）暴露的六类问题，逐条对应 P0–P5。key_assumptions 失败率 28%（W2 盲评 8 条不合格中 7 条）+ 真实运行同义复述两次，根因是字段从未被定义（非 bug）。

**自测**
- 74 测试绿（基线 42 + 新增 32：ticker_resolver 10 + confirm_intent 9 + key_assumptions 6 + menu_filter 5 + holding_horizon 1 + make_mirror rejection 1）。前端 build → static/（entry_anchor + holding_horizon 渲染）。`make_mirror`/`build_card_from_extraction` 契约更新（返 `BrokenCondition|None` / `(card, rejected)`），test_conditions/test_agent 同步。

**状态**：六项全部落地，等作者目检真实运行（**先重启 serve 拾起新后端代码**：`PYTHONUTF8=1 PYTHONPATH=src python -m thesis_watch.serve`；前端 static/ 已重建）。**不自行重跑 eval**——key_assumptions 定义落地并经作者目检前，重跑无意义。

## v0.0.11 — 2026-08-02 — 话术生成层 + §2.5 前端 round-1（React+Vite+shadcn）+ W2 盲评模板/collect

**做了什么**
- 话术生成层 `src/thesis_watch/dialogue.py`：每轮对话文案 LLM 生成（追问/拒判说透为什么——锐利、有解释力，过 redline.guard）；**复述确认段保模板逐字保真**（确认卡文字与入库一致）。`entry_loop` 在 extracted/menu/confirm_card 三处接入 `generate_dialogue` + 模板兜底；抽取仍单次结构化调用（话术是独立呈现层调用）。
- §2.5 前端 round-1（`frontend/` React + Vite + shadcn/ui + Tailwind）：形态 C（居中对话 680px + 右抽屉 340px 滑入/滑出）；8 验收点（菜单 option 卡 / 三阶段进度行 / 抽屉软蓝高亮「刚填入」/ 拒判橙边卡三段式 / 行话 tooltip / 确认入库绿态 / 浅色蓝点缀 / 打字机逐字）；构建产物 → `static/` 由 FastAPI 托管。旧 vanilla 挪 `frontend/legacy/`。设计基线 `docs/frontend-design-v1.md`。
- W2 盲评流程（W1 同款模板+collect）：`evals/run_w2.py` 加 `template`/`collect` 子命令。`template` 读 `w2_converged_cards.yaml` + `load_input_text` → 铺 `evals/blind_verdicts_w2.yaml`（逐字段 model_output + `acceptable:null`/`reason:""`，含 reference_input 供对照，单模型 mode A 无 pick）。`collect` 算收敛后接受率 + 写 `eval-report.md` §7.1。

**依据**
- 作者 2026-08-02 补充：① 话术生成层（追问/拒判 LLM，复述确认模板逐字）；② 前端 8 验收点 + 打字机；③ 盲评不在对话口头，按 W1 模板+collect（填评人只看 blind_verdicts_w2.yaml 一个文件）。

**自测**
- 42 测试绿；前端 build 2.4s → `static/`；GET / React 页面（`id="root"`）；POST HSBC 话术 LLM 生成（解释价格图形型为什么核不了、能改成什么样）；`template` 生成 5 case / 33 字段盲评模板。

**状态**：前端 round-1 待作者目检（预期 2 轮以上迭代）；W2 盲评模板已生成（`acceptable:null`），作者填后跑 `collect`。

## v0.0.10 — 2026-08-02 — 前端栈修订：React+Vite+shadcn/ui（作废无构建链约束）+ 设计基线 v1

**做了什么**
- 前端栈修订：React + Vite + shadcn/ui（作者 2026-08-02 弹窗拍板）。**作废**此前「单 HTML + 原生 JS、不引入构建链」约束（v0.0.7）。构建产物为静态文件，由 FastAPI 托管，部署中立不变；接口契约不变。
- 落 `docs/frontend-design-v1.md` 设计基线：形态 C（居中对话 + 右侧确认卡抽屉）、浅色蓝点缀、7 施工验收点、分工铁律（组件库管皮肤，交互结构以基线为准）、交互分布铁律（对话承载语言/当次选择，抽屉承载累积卡/确认）、明确不做（不改 loop/prompt/schema、无深色/移动端/dashboard、无买卖建议 UI）。
- 同步 PRD §9 / harness-design §1.3 / README 技术约束（无构建链 → React+Vite+shadcn）。

**依据**
- 作者 2026-08-02 弹窗拍板：组件库管皮肤（提速+一致性），交互结构以基线为准不随库变；构建产物仍静态由 FastAPI 托管，部署中立不破。

**砍了什么 / 为什么**
- 砍「单 HTML+原生 JS 无构建链」：组件库一致性 + 开发效率 > 无构建链极简（原约束为防 CDN 白屏 + 部署中立，现构建产物静态托管仍满足）。

**状态**：施工中（按 frontend-design-v1.md §1 七验收点）。完成后停下等作者目检（预期两轮以上），通过后记 §2.5 前端打磨完成条目。

## v0.0.9 — 2026-08-02 — W2 §2.3+§2.4+§2.5：核对 agent + 输出层 + W2 eval harness

**做了什么**
- §2.3 核对 agent（`src/thesis_watch/check_agent.py`）：逐卡逐条件核对 SEC filings → 三态 + 证据；evidence_self_check 回放不过降 watch；redline.guard 仅校验 LLM reasoning（不校验 SEC 引用）；E1-E8 落日志；CheckResult 存 store。Option A（一次 LLM 调用判全卡，基于 filings metadata），R5 合规（excerpt=SEC primaryDocDescription，url=filings index，self_check 验 excerpt 在 index 页）。
- port `fetchers/sec_edgar.py`（从 pre-market-briefing 搬 + 适配）：按 filer_type 路由 form types（foreign→20-F/6-K 主渠道，不沿用本土 6-K 降级；etf→全 manual）。CIK 复用 filer_type_lookup.yaml（运行时不拉 5MB company_tickers.json，慢链路不超时）。evidence fetcher 30s+重试容忍 SEC 慢。
- §2.4 输出层（`src/thesis_watch/notify.py`）：render_briefing（命中单独邮件附原文链接 / 静默日一行存活「已检查 N/0 触发/最近裁判日」）+ smtplib SMTP_SSL（app password，env creds，无 creds dry-run）。render 用 run_check summary 的 triggered（当前轮，不读历史避免重复列）。
- §2.5 W2 eval harness（`evals/run_w2.py`）：跑录入 loop 收敛 → 测 平均澄清轮数/收敛失败率（auto）+ 导出 converged cards 供作者盲评 收敛后接受率（pending）。entry_loop 埋 metrics（turns/clarification_rounds/converged）。
- models.py `_coerce` 修 PEP 604 union（`X|None` origin 是 types.UnionType 非 typing.Union）——entry_anchor/next_verdict 读回来原本是 dict 没重建，现修好。

**依据**
- 作者 2026-08-02 W2 开工指令 §2.3/§2.4/§2.5 + 断点②。pre-market-briefing 仓库 clone 到 `D:\AgentProjects\pre-market-briefing`（作者提供路径）。
- mail_sender.py 在 pre-market-briefing 是 TODO stub → 本模块用 smtplib 实现（非 port）。thesis.py 是 Notion 读 → 不搬（R7）；notion_writer*.py 不搬（R7）。

**自测**
- 42 测试绿；sec_edgar 真连 SEC 拉 HSBC 7 条 6-K（CIK 走 lookup）；check_agent HSBC 端到端：1 watch（"HSBC TO SELL AUS HOME" 命中「亚洲剥离」镜像，判 watch 非触发——R6 不替结论）+ 2 untriggered，evidence_self_check 通过（excerpt 在 index 页验到，checked_ok=True），CheckResult 存 store。notify 静默日 + 命中邮件两 render 路径 + dry-run send 通。W2 harness 5 case（FDS/NVDA/MCO/GOOGL/VEEV，qwen-turbo，mode A）：平均澄清轮数 0.00、收敛失败率 0.00%、5 张 converged 卡导出待盲评。

**砍了什么 / 为什么**
- CIK 不拉 company_tickers.json（5MB 慢链路超时）→ 复用 filer_type_lookup.yaml 的 CIK。新 ticker 不在表 → 需先跑 fetch_filer_type 入表（runtime 不兜底）。
- redline.guard 不校验 SEC 引用摘录（仅校验 LLM reasoning）——R3 只管系统输出，引用是原文。

**断点②**：W2 §2.3+§2.4+§2.5 完成，等作者 review + 收敛后接受率盲评（5 张 converged 卡在 `evals/w2_converged_cards.yaml`）。

## v0.0.8 — 2026-08-02 — 断点①三处修：filer_type 录入侧查表 + 前端进度态 + 菜单候选≥3

**做了什么**
- filer_type 录入侧改确定性查表：`entry_loop._resolve_filer` 复用 `evals/filer_type_lookup.yaml`（SEC EDGAR 拉取）；ticker 在表 → 用查表值；不在表 → 模型 ext.filer_type 兜底 + open_question「模型兜底建议复核」；都缺 → OTHER + open_question「待确认」。`build_card_from_extraction` 加 `filer_type` 参数。HSBC 从 `other` → `foreign_issuer_20f_6k`（查表命中，无 open_question）；AAPL（不在表、模型给 other）→ pending + open_question。
- 前端进度态：`index.html` 加 `#status`；`app.js` `setStatus` 在 抽取/生成候选/渲染卡片/入库 各阶段给明确提示（5–45s 不空白沉默）；`applyView` 按 stage 显示完成态。
- 菜单候选偏少：`menu.py` MENU_PROMPT 调强（A/B 必须 3 条最多 4 条；A 从 ticker 基本面出发即使用户没明说也给；少于 3 不合格）。实测 qwen-turbo 给 A=3/B=3（修前 A=1/B=3）——**调 prompt 即生效，无需换模型**。

**依据**
- 作者 2026-08-02 断点①判决：① filer_type 判断决定 SEC 表单路由不该交给模型猜（同 position_cap_tier 的 tier_map 先例）；② 5–45s 等待不能空白沉默；③ 菜单每条假设至少 3 候选，glm 保守则换 qwen-plus 或调 prompt（实测调 prompt 即生效）。

**砍了什么 / 为什么**
- 砍 filer_type 的 LLM 主导：改查表为主、模型仅兜底。确定性信息不该交给模型猜。

**不变**
- 录入 8 屏 / 状态机 / 可用性验收（≤5min、阻断≤3）/ 一致性校验 / 确认卡字段 / confirmed_by_user→SQLite 不变；红线不变；工程纪律不变。

**自测**
- 42 测试绿；`_resolve_filer` 三路径单测（lookup 命中 / model_fallback / pending）全通；HSBC 端到端（in-process + HTTP urllib UTF-8）：filer=foreign_issuer_20f_6k、菜单 A=3/B=3、picks、confirm 全通；AAPL pending+open_question HTTP 验证；GET / 含 #status。

## v0.0.7 — 2026-08-02 — 形态修订：桌面 CLI → 桌面 localhost 单页（同日第二次形态决策）+ 部署中立约束

**做了什么**
- 形态修订：桌面 CLI → **桌面 localhost 单页（对话 + 确认卡）**。录入交互改为本地 Web 页面承载：FastAPI + 单 HTML，配 Windows 启动脚本（.bat：起服务 + 自动开浏览器），用户全程不碰 shell。页面布局：左侧对话流，右侧实时渲染的确认卡，卡片字段可直接点改。
- 补部署中立约束：代码随时能原样上公网——配置一律走环境变量（不写死 localhost/127.0.0.1、不留本机绝对路径），启动脚本与主程序解耦，目录按「一个命令可容器化」组织。本轮仍只跑本地、不加登录层（本地自用），不做云部署。
- 文档同步：README/PRD §9+§11 沿革+§14/changelog/entry-agent-spec/harness-design §1.3/demo-walkthrough 抬头，把「桌面 CLI」修订为「桌面 localhost 单页」；沿革记录同日两次形态决策（托管 PWA → 桌面 CLI → 桌面 localhost 单页）及各自理由。

**依据**
- 作者 2026-08-02 第二次拍板（同日修订 v0.0.6 的 CLI 形态）。CLI→localhost 页理由：① 目标用户是非技术投资者，shell 门槛与受众错配（与 R7「Notion 使用者不多」同一逻辑）；② 当前阶段形态服务于叙事与 demo，页面对面试官更直观；③ 界面传统、交互 AI——追问/复述/确认的录入引擎完全不变，只换承载层；④ 录入 8 屏原本就是图形化对话流程，本次回归原设计非新增。
- 部署中立：作者补充约束——代码随时能原样部署到公网，配置走 env，不写死本机；前端不引入构建链，第三方库须下载到本地 static/ 引用（作者踩过 CDN 无 fallback 白屏的坑）。

**砍了什么 / 为什么**
- 砍桌面 CLI 形态（同日 v0.0.6）：shell 门槛与目标受众（非技术投资者）错配。
- exe 打包暂缓：启动脚本（.bat）即可，本轮不做 exe。

**不变**
- R7 不绑 Notion；录入 loop 排第一；断点 ①② 不变（断点 ① 改页面演示）。
- 录入引擎（追问/复述/确认状态机、可用性验收、一致性校验、确认卡字段、confirmed_by_user→SQLite）不变，只换承载层（CLI→HTTP+HTML）。
- 技术栈沿用 PydanticAI 单次结构化调用 + 现有 models/redline/store；工程纪律不变。

**本轮明确不做**
- L2 eval、localhost 之外的页面、任何 Notion 写入、券商/行情接入、ETF 支持、exe 打包、云部署、登录层。

## v0.0.6 — 2026-08-02 — 形态 pivot：托管 PWA → 桌面 CLI + R7 维持 + 实施顺序（录入 loop 第一）

**做了什么**
- 形态 pivot：托管 PWA（移动端优先）→ **桌面 CLI**。录入交互用纯 CLI 多轮对话承载，不做 PWA 壳；localhost 单页暂缓（仅当端到端跑通且时间允许时再加，且只渲染确认卡展示+修正，不是操作台）。
- R7 维持原样：产品自包含，核对结果不写回作者 Notion 台账。
- 实施顺序定：**录入 loop 排第一** → 核对 agent loop → 输出层 → W2 eval 改造；带断点 ①（录入 loop 演示）②（W2 报告），到点停等作者指令。
- 文档同步：README 形态行 + 项目状态 + 技术分发约束 + 触达；PRD 版本/状态 + §9 + §11 沿革 + §14 决策状态 + §12 W2 重排脚注；harness-design §1.3 PWA 选型作废；demo-walkthrough 抬头改 CLI。

**依据**
- 作者 2026-08-02 拍板（W2 开工指令）。砍 PWA 三理由：① 交互本质是对话（说+拍板）+推送（有事叫我）+检查面（确认卡+eval 报告），GUI 只是皮肤，砍 PWA 是设计决策不是缺口；② 建设者侧核心交付是 harness + 双层 eval + error analysis 闭环，PWA 从来不是卖点；③ 每天 1 分钟体检哲学是「不要刷、等它叫你」，与 PWA 打开刷形态根本矛盾。
- R7 维持：目标用户 Notion 占比低，自包含便于日后转 public。
- 录入 loop 第一：依 eval-report §6.8——W2 三指标（收敛后接受率/平均澄清轮数/收敛失败率）测量对象是多轮澄清对话，loop 不做 W2 无测量对象。

**砍了什么 / 为什么**
- 砍 PWA 壳（含 Vite+React / Jinja 两选型）：GUI 只是皮肤，与「不要刷、等它叫」哲学矛盾。
- 不绑 Notion（R7 维持，非新增）：自包含。
- localhost 页面暂缓：端到端跑通且时间允许才加，且只渲染确认卡。

**不变**
- 红线 R1–R9 全部不变（R7 仅重申不绑 Notion）。
- 录入 8 屏内容（demo-walkthrough）作为 loop 映射基准不变。
- 工程纪律不变：eval 串行 + 429 退避不并发；gate 失败按 eval-plan §6 分类不私降门槛；里程碑结束写 changelog。

**本轮明确不做**
- L2 eval（GT 须作者手标 R8，单独开棒）、localhost 页面、任何 Notion 写入、券商/行情接入、ETF 支持。

## v0.0.5 — 2026-08-02 — PRD 定位修正（撤决策入口 + 价值形态 + W2 重排）

**做了什么**
- `docs/PRD.md` v0.1 → v0.2：
  - 新增 §2 产品价值形态「让『什么都不做』变得可信」+ 推论（**系统可信度 > 系统覆盖面**）——作为一切设计判据。
  - 新增 §3 核心需求（按优先级）：①模糊想法→可检验破条件（录入/澄清）②免去自行搜索+跨期记忆。非核心：交易决策辅助 / 行为纠偏 / 社交 / 组合优化。
  - 新增 §4 设计约束：A 覆盖率显式呈现不静默跳过（每条标注已核对/未核对+原因+下次自查日；manual_items 从「系统缺陷」改「明确交接清单」）；B 时长上限（日常≤3min、录入≤15min，上升=退化）；C 形态锚定简报不发明新交互。
  - 新增 §7 撤回「决策入口（我想买 X→给判决）」功能，理由留痕。
  - §11 沿革 + §12 W2 重排：覆盖率透明化→观察区分流→记忆/跨期追踪→补数据源（按覆盖率增量排序）。

**依据**
- 作者 2026-08-02 拍板：用户被动接收简报不主动询问；守纪律已是成果（作者原话「自从有了这个，基本都是 follow 上面动手，半年内无破纪律行为」）；新增标的咨询已被录入 Agent 覆盖。核心价值是可信的不作为，可信度取决于用户知道查了什么/没查什么。

**砍了什么 / 为什么**
- 砍「决策入口」功能：与真实被动使用行为不符、守纪律非痛点、新增标的已被录入覆盖。
- W2 砍「先铺数据源」：先做覆盖率透明化（可信度 > 覆盖面）。
- manual_items 从「系统缺陷」重定位为「明确交接清单」。

**不变**
- W1 范围不变（录入 Agent + eval 照常）；ground_truth 填写、盲评、A/B 照原计划。

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
