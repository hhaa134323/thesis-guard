# MEMORY — 跨 AI 交接（2026-08-03）

> 本文件给协作 AI 拉取进度。Claude（本会话）维护，提交到 GitHub。
> 详细变更见 `docs/changelog.md`（v0.0.12 P0–P5 + v0.0.13 P2 条件4）；本文是 digest + 当前状态 + 开口项 + 硬规则。
> 读这一个文件就能接上。

## 当前状态
- 分支 `main`。已 push 到 `bf19d0f`（v0.0.12）。本地新增 `e651a4b`（本文件）+ v0.0.13（P2 条件4）——这两次 push 受 B1 GitHub 间歇 reset 阻塞，待网络恢复再推。
- v0.0.12（P0–P5）+ v0.0.13（P2 条件4 backstop）已落地；目检 5 过 + P2 已修（v0.0.13，待复跑确认）。
- serve 在跑（PID 28688，http://127.0.0.1:8000/，v0.0.12+v0.0.13 后端 + 前端窗口最新 build `index-CnCgShHx.js`）。前端窗口自检服在 :8001（http.server）。
- **不重跑 eval**（等 key_assumptions 定义经作者目检后再说）。
- **两窗口并行**：本窗口 = `src/` `docs/`（除 `docs/frontend-design-v1.md` 归前端窗口）`tests/` + 仓库根（含本文件、CLAUDE.md）；前端窗口 = `frontend/` + `static/` + `docs/frontend-design-v1.md`（构建产物，谁改 frontend/src 谁 build 谁提交）。本窗口不读不改不 git add 前端域。

## v0.0.13 做了什么（P2 条件4 backstop，2026-08-03）
- `entry_loop._apply_key_assumption_rejection` 加条件4（不可证伪）确定性 backstop：抽出的 key_assumption 过 `condition_classify`+`is_v1_auto`，**非 auto 的假设（其镜像必也非 auto、无可判定阈值）→ 转 open_question**。与菜单路径（P4 `filter_executable_mirrors`）同款，两路径对齐。条件3（`is_paraphrase`）先跑、条件4 后跑。
- 修 v0.0.12 目检发现：ASP/份额/结构性 3 条无 auto 镜像的假设原留在 key_assumptions，现转 open_question（标条件4）。
- 测试 +4（含 SK海力士 4 假设复现：只留毛利率）。78 绿。

## v0.0.12 做了什么（P0–P5，逐条一行）
- **P0 ticker 确定性**：`src/thesis_watch/fetchers/ticker_resolver.py`（SEC `company_tickers.json` + 本地缓存≤30d + `resolve()`，CJK 紧贴守卫防「SK海力士」误命中 SK）；`entry_loop` 替换 LLM 出 ticker（1→用 / >1→问选 / 0→问，不猜）；`filer_type` 去 LLM 兜底。
- **P1 confirm intent 分流**：`dialogue.classify_confirm_intent`（confirm/modify/question 关键词）+ `is_factual_fetchable`；提问类走 `sec_edgar.fetch_latest_filing` 附 SEC 链接（R5），取不到明说「查不到」+ 重新输出复述确认段拉回。
- **P2 key_assumptions 四条 + 拒绝规则**：`thesis-card-schema.md` §7 + `prompts/entry-agent.md` + `entry_agent.py` SYSTEM_PROMPT；`schema.OpenQuestion`；`conditions.is_paraphrase`（条件3「同义复述」确定性 backstop）；输入隔离（加仓价/安全边际只流向 entry_anchor）。
- **P3 mirror 强制可判定**：`conditions.make_mirror` 强制 `threshold`+`source_type`，缺→返 None→open_questions（禁 `threshold:null`，与 redline 对齐）；`schema.MirrorSpec`/`menu.MenuMirror` 加两字段；`agent.build_card_from_extraction` 返 `(card, rejected_mirrors)`。前端 `App.tsx` entry_anchor **始终渲染**（method+current+history 折叠，无数据显示「未检出」）。
- **P4 候选可执行性过滤**：`menu.filter_executable_mirrors`（`condition_classify` 驱动，跨主体/第三方/价格图形型→不呈现）；`_present_menu`/`_ctx_menu` 显式告知「原本 N 个方向，M 个无法自动核对，已排除（原因）」（PRD §4-A 不静默跳过）。
- **P5 字段对齐 + holding_horizon**：`thesis-card-schema.md` §4 完整对照表（11 台账字段 + 7 card 新增，0 遗留）+ §1 状态改「已对齐」+ §3 改写已执行；`models.ThesisCard` 加 `holding_horizon`（long≥3y/mid/trade≤3m，录入问用户不模型猜→open_question）；前端 drawer 加持仓周期 select。
- **收尾**：`changelog.md` v0.0.12；`BLOCKERS.md` B2 记 SK海力士真实运行为首条；`eval-report.md` §7.1 逐字段（mirrors 25/25·0% / holding_reason_raw 4/5·20% / key_assumptions 18/25·28%，合计 47/55=85.45%，95% CI≈[76%,95%]，过线 0.45pp < 一个字段 1.82pp）；R9 脱敏清单 + `.gitignore` 机械对齐（`data/*.db`、`data/company_tickers.json`、`shots/`、`screenshots/`）。

## 目检结果（SK海力士真实运行，2026-08-03）
| 项 | 结果 | 证据 |
|---|---|---|
| P0 | ✅ | 澄清后命中 SKHY，全程无 SKHCF |
| P1 | ✅（有缺口，见开口1） | 「查不到 SKHY 的 SEC 财报 filing」——明确查不到，没套模板 |
| P2 | ✅（v0.0.13 修） | v0.0.12 半过（条件3 过、条件4 漏）；v0.0.13 加条件4 backstop，ASP/份额/结构性 转 open_question，待复跑确认 |
| P3-B | ✅（半验证） | entry_anchor「未检出」正确显示（输入无加仓价）；有数据分支未测 |
| P4 | ✅ | 「4 条假设，3 条无法自动核对，已排除」+ 逐条原因 + 25% 覆盖率 |
| P5 | ✅ | holding_horizon 下拉 + open_question 都在 |

## 开口项（等作者定夺，**未动**）
1. **P1 CIK 复用缺口**：`fetch_latest_filing` 走 `filer_type_lookup.yaml`（16 预置 ticker，无 SKHY）→ 「查不到」；但 `ticker_resolver` 已从 `company_tickers.json` 拿到 SKHY 的 CIK（2120882）。fetcher 回退用 resolver 的缓存就能给新 ticker 拉 filing + 链接，而不是「查不到」。验收算过（「明确查不到」达标），质量能更好。
2. **未测分支**：P1 的「带 SEC 链接」分支（用 MCO/FDS 等在 lookup 里的票问「下次财报什么时候」）；P3-B 的「有数据显示」分支（输入带加仓价，如「我持有 MCO，加仓价 $394，安全边际 16x」）。
3. **P2 条件4 复跑确认**：v0.0.13 已加条件4 backstop（`condition_classify`+`is_v1_auto` 接进 `_apply_key_assumption_rejection`，非 auto 假设转 open_question），单测过；等真实复跑 SK海力士 确认 ASP/份额/结构性 进 open_question。注意近似：condition_classify 关键词规则，定性假设可能过拒（但符合工单 condition4「不可证伪」语义）。

## 硬规则（必须遵守）
- **测试改动**：让测试**更难过**→直接做 + 说一声；**更容易过**→停下问。（本轮 P3 改 `make_mirror` 签名，`test_conditions.py` 3 处调用跟着改 + 加 `assert m.threshold/source_type` + 新增 `test_make_mirror_rejects_missing_threshold_or_source`，是更难过，已做已说、作者已放行。）
- **红线**（CLAUDE.md）：R1–R3 不建议/不预测/黑名单措辞；R4 不接券商/不读真实持仓；**R5 每条事实附一手链接**；R6 判断权归用户；**R7 不写 Notion**（只读刷新 assets/ 快照）；**R8 eval GT 每字段标来源、不模型兜底**（harness 读独立 `evals/ground_truth.yaml`）；**R9 转 public 前脱敏**（清单见 CLAUDE.md 第9条）+ `.gitignore` 机械对齐。
- **前端边界**：`frontend/` + `static/` 归另一窗口，本窗口不读不改不 git add。要动前端先停下问。
- **仓库根文件**（CLAUDE.md、本文件等）归本窗口，改了直接 `git add`，不等清单。
- **config/key**：`config.yaml`（gitignored，本地有）task_model=`glm-5.2-fast-preview`；API key 走 env `ANTHROPIC_AUTH_TOKEN`（这个会话的 shell 已有，serve 子进程继承；`.env` 不被 app 自动加载）。

## 关键文件指针
- `docs/changelog.md` — v0.0.12 详细。
- `docs/thesis-card-schema.md` — §4 对齐表 / §6 字段确定性审计 / §7 key_assumptions 四条定义。
- `docs/BLOCKERS.md` — B2 SK海力士首条记录；B1 GitHub/SEC 网络状态。
- `docs/eval-report.md` — §7.1 逐字段接受率 + §6.5 key_assumptions 根因。
- `docs/PRD.md` — §4-A 覆盖率显式约束 / §9 数据源约束。
- `CLAUDE.md` — 红线 R1–R9 + Notion 只读用法 + 资产现状。
- `src/thesis_watch/entry_loop.py` — 录入 state machine（P0/P1/P2/P4/P5 集成处）。
- `src/thesis_watch/fetchers/ticker_resolver.py` — P0；`fetchers/sec_edgar.py` — P1 `fetch_latest_filing`。
- `src/thesis_watch/conditions.py` — `make_mirror` / `is_paraphrase` / `default_redline_pack`。
- `src/thesis_watch/condition_classify.py` — InfoType + `is_v1_auto`（P2 条件4 修复 + P4 过滤共用）。

## serve / 运行
- 起 serve：`PYTHONUTF8=1 PYTHONPATH=src python -m thesis_watch.serve`（bash；UA env `THESIS_SEC_USER_AGENT`；host/port `THESIS_HOST`/`THESIS_PORT` 默认 127.0.0.1:8000）。
- pytest：`PYTHONUTF8=1 python -m pytest -q`（78 绿：基线 42 + 新增 36；v0.0.12 +32 / v0.0.13 +4 条件4）。**注意**：Windows 下 pip 读 requirements.txt 需 `PYTHONUTF8=1`（否则 GBK 解码报错）。
- 装依赖：`PYTHONUTF8=1 python -m pip install -r requirements.txt`。
