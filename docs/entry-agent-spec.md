# 录入 Agent 行为 spec

| 项 | 值 |
|----|----|
| 版本 | v0.2（W1，gate 5/5 后定稿） |
| 日期 | 2026-08-01 |
| 基线 | `assets/onboarding_dryrun_0731.md`（6 轮 transcript + 8 条设计发现 + 彩蛋） |
| 实现 | `src/thesis_watch/entry_agent.py`（PydanticAI 单次结构化调用）+ `entry_cli.py`（CLI）+ `schema.py`（pydantic 契约）+ `tier_map.py`（仓位档规则查表）+ `llm.py`（LenientOpenAIChatModel 容错）+ `evals/run_l1.py`（pydantic-evals harness） |
| 状态 | ✅ gate 5/5（glm-5.2-fast-preview + lenient fix；qwen-turbo 5/5）；CLI 可运行；harness + 空白 GT 模板就绪，待 GT 填后跑 L1 |

## 0. 角色与边界

录入 Agent 只做：**对话抽取 → 可判定性追问 → 编译确认卡 → 复述确认**。入库后即止，不做投资判断。

- **R1/R6**：不输出买卖/仓位建议，不替用户结论；卡里只有「条件 + 证据 + 状态」，无结论字段。
- **R3**：对外输出经 `redline.guard`；R5 每条事实须一手链接；R7 不写 Notion；**R8 eval ground truth 由作者手工标注，模型不许填**（见 `docs/eval-plan.md` §8）。

## 1. 对话状态机（8 步）

```
1.开场 → 2.抽取 → 3.可判定性追问 → 4.镜像生成(L1) →
5.红线默认包(L2) → 6.无法确定菜单 → 7.价格图形识别 → 8.复述确认 → 入库
```

代码落点：`entry_agent.extract`（单次结构化调用产出 `EntryExtraction`）；`entry_cli.py`（CLI 封装）；`tier_map.lookup_tier`（position_cap_tier 规则查表）。

> **W2 录入 loop 承载层 = 桌面 localhost 单页**（FastAPI + 单 HTML + .bat 启动，见 PRD §14）；状态机/对话环节/可用性验收不变，只换承载层。`entry_cli.py` 仍是 W1 eval 的单次 CLI 程序（R8：eval 跑程序非内联，不动）。

## 2. 两层条件结构 【发现 1】

- **Layer 1 mirror**：关键假设的镜像条件，抓「我的逻辑错了」（个性化）。`schema.MirrorSpec`。
- **Layer 2 redline**：通用红线默认包（大额罚单 / 高管突变 / 财报重述），阈值可调可关停，抓「公司出大事」（兜底）。
- **去重**：镜像已覆盖某红线语义（如 CEO/CFO 离职既在 mirror 又会触发 exec_change）→ `enabled_redlines` 关停该红线（`conditions.default_redline_pack`）。

## 3. 「无法确定」候选菜单 【发现 2】

用户说不清破什么时（演练第 2 轮 caca 答「无法确定」），不逼从零想——给成对候选「假设 + 镜像」，选一次填两槽。每条附真实历史事件示例（`schema.HistoricalExample`，R5 未验证不展示具体事件）。

## 4. 菜单建议偏差风险 + W3 观察 【发现 3】

菜单降门槛但也带来建议偏差。W3 埋点 `entry_cond_user_spoken` vs `entry_cond_menu_picked`，比例 = `user_spoken / (user_spoken + menu_picked)`。彩蛋坐实（§12）：caca 本人演练 HSBC 时答「股价形状」+ 菜单挑 A4，与真实 thesis（亚洲银行特许）不符。

## 5. 历史事件示例 【发现 4】

每条破局条件附真实历史事件示例。`schema.HistoricalExample`（`source_url` / `source_type` / `verified`）。R5：`verified=False` 不展示具体事件，只占位「待补一手来源」——不编造。当前 Layer 2 三条红线示例均 `verified=False`，待网络恢复补一手源。

## 6. 价格图形型 → 人工自查项 【发现 5】

原话含均线/形态/突破等 → `manual_check_items`（cadence=monthly），不进自动核对。`conditions.is_price_pattern` 检测。HSBC 演练「稳健上升的形状」即触发。

## 7. 静默日推送策略 【发现 6】

命中当天单独发邮件（附原文链接）；未命中合并进简报一行。**无事那行不许空**——必须写明「已检查 N 只 / 0 触发 / 最近一个裁判日：X 的 Y 月 Z 日」，让用户确认系统活着（不猜）。触达层 W2 接入。

## 8. FPI 申报方路由 【发现 7】

外国发行人（20-F/6-K）主渠道 6-K，不沿用本土「6-K 降级」。`schema.FilerType.FOREIGN_ISSUER_20F_6K`。HSBC = FPI。

## 9. 耗时压缩目标 【发现 8】

演练 6 轮 ~6 分钟，目标 3 分钟。压缩点：A/B 两问合一屏。详见 §10 可用性验收。

## 10. 可用性验收标准（作者 2026-08-01 定）

- 单只票录入耗时 **≤5 分钟**。
- **阻断式澄清 ≤3 次**（超了是设计问题，不是用户问题）。
- 见 §11 澄清分级——阻断式只用于可判定性，其余记录式可跳过，故阻断次数天然受限。

## 11. 澄清分级（blocking vs recording）

| 级 | 用于 | 处理 | 落点 |
|----|------|------|------|
| **阻断式 blocking** | 可判定性（这条破条件到底怎么算破） | 不答不能落盘 | 录入流程阻塞，§10 限 ≤3 次 |
| **记录式 recording** | 其余全部（表述冲突 / 字段缺失 / 口径存疑） | 标记 `open_question` 存进卡，可跳过继续 | `open_question` 字段（与 eval GT 的 open_questions 同构） |

屏 5「信的与勾的不对应」属记录式 → 一致性校验（§11.1）标 open_question，不阻断。

### 11.1 一致性校验（屏 5 的正式名字）

用户信的假设与勾的破条件不对应时（演练：信 A4 管理层战略，勾 B6 监管罚单），系统不阻断，而是：
- 标 `open_question: {field, reason: "信的假设与勾的破条件不对应"}` 存进卡。
- 默认处理仍执行（A4 镜像 + B6 进红线默认包），但卡片带 open_question 提示用户复核。

## 12. 彩蛋（finding 3 坐实）

caca 台账真实 HSBC thesis =「以亚洲（香港）为核心的全球性大型银行，庞大的存款/财富管理特许」（`assets/notion/thesis/HSBC.md`）。演练中她答「股价形状」+ 菜单挑 A4——0 号用户本人演示了菜单偏差，发现 3 坐实。

## 13. 可运行 demo（CLI，非内联）

`entry_cli.py` 是 CLI 程序，**不依赖会话上下文**（作者 W1 硬要求）：

```
echo "thesis 文本" | python -m thesis_watch.entry_cli --ticker FDS
python -m thesis_watch.entry_cli --ticker FDS --input thesis.txt --mode A|B
```

- 读 `config.yaml` task_model（qwen-turbo 日常 / glm-5.2-fast-preview 基线，`--model` 覆盖）。
- PydanticAI 单次结构化调用 → `EntryExtraction`（pydantic 校验）+ `position_cap_tier`（`tier_map` 规则查表，非 LLM）。
- 输出 thesis-card JSON + per-call 指标（model / in_tok / out_tok / retries_429 / dur_s / status）。
- 已验证可运行（qwen-turbo 3s 出合法 JSON）。

> 生产用 API responder 即本 CLI；不内联手抽（R8：eval 必须跑这个程序，不能由 Claude 内联抽取）。

## 14. Eval（pydantic-evals + 逐字段 + A/B + under-fill + exposure + R8）

- **harness**：`evals/run_l1.py`，pydantic-evals `Dataset`/`Case` 承载；评分自实现。
- **ground truth**：`evals/ground_truth.yaml`，**作者手工标注**（R8）；`evals/ground_truth.template.yaml` 是空白模板。缺失或 required 字段 null 无 open_questions → 报错退出，不兜底。
- **逐字段一致率**（非总分）：holding_reason / key_assumption / 破条件 / filer_type 各自一个；**≥85% 逐字段判**。
- **A/B 对照**：A=直接抽（默认），B=自澄清 prefix（批 eval 的澄清价值代理）。两组一致率对比 = 澄清设计价值。
- **under-fill 指标**（与一致率分开）：字段填充率 / mirror 平均条数 / holding_reason 平均字数。qwen-turbo vs glm 基线对比，直接回答 terse 是否丢信息。
- **exposure 分组**（§eval-plan 8.1）：FDS/HSBC=seen（仅参考），余 clean。报三数（总体/clean/seen），**85% 看 clean**。
- **null + open_questions**（§eval-plan 8.2）：台账信息不足的字段填 null + 原因 → 从分母剔除 + 单独统计「台账模糊字段数」（产品发现）。
- **case 明细**：每 case 出 per-field ✓/✗ + mirror_coverage + under-fill + **root_cause_hypothesis + fix_action**（作者填，非模型）。
- 模型分工：qwen-turbo 日常迭代（3min/轮）；glm-5.2-fast-preview 质量基线（只跑一次）。两组并排进 `docs/eval-report.md`。

## 15. 红线落地（实现层）

| 红线 | 落地 |
|------|------|
| R3 | `redline.guard` 在 `render_summary` 输出前校验，命中 E8 阻断 |
| R5 | `HistoricalExample.source_url` + `verified`；`evidence_self_check` W2 |
| R6 | 卡 schema 无结论字段；`render_summary` 只呈现条件 |
| R7 | 录入工具集不含 Notion 写工具 |
| R8 | GT 独立文件 `evals/ground_truth.yaml`，作者手工标，缺失/空报错退出，不兜底 |

## 16. 8 条设计发现 → spec 落节映射表

| # | 发现 | 落在 spec | 代码/数据落点 |
|---|---|---|---|
| 1 | 两层条件结构 | §2 | `conditions.make_mirror`/`default_redline_pack`；`schema.ConditionLayer` |
| 2 | 「无法确定」→ 候选菜单 | §3 | 行为层 `prompts/entry-agent.md` |
| 3 | 菜单偏差 → W3 观察 | §4 | `docs/eval-plan.md` §2.1 埋点 |
| 4 | 历史事件示例 | §5 | `schema.HistoricalExample` |
| 5 | 图形型 → 人工自查 | §6 | `conditions.is_price_pattern`/`to_manual_check` |
| 6 | 静默日推送 | §7 | `docs/harness-design.md` §1.4（W2） |
| 7 | FPI 6-K 路由 | §8 | `schema.FilerType.FOREIGN_ISSUER_20F_6K` |
| 8 | 耗时 6min→3min，A/B 合一屏 | §9 + §10 可用性 | UX 目标，W3 优化 |

## 17. schema 变更说明（作者问：破条件 schema 有没有被改动）

- **`docs/broken-condition-schema.md` + `models.BrokenCondition` 未改**（v0.1 schema 已覆盖 8 条发现）。
- 新增（logic/API 增量，非 schema 变更）：
  - `conditions.default_redline_pack` + `agent.build_card` 加 `enabled_redlines` 可选参——实现 schema 已承诺的「红线可关停/去重」。
  - `schema.py`（pydantic，LLM 输出契约 `EntryExtraction`）：新增 `next_verdict`、`entry_anchor` 两个 LLM 抽取字段；`position_cap_tier` **不进 LLM 契约**（按 ticker 规则查表 `tier_map.py`，因台账无档位信息、属确定性信息不该交给模型猜——glm-5.2 把 FDS 判成「中」、实际「硬thesis」坐实）。
  - `llm.py` `LenientOpenAIChatModel`：覆写 pydantic-ai `_validate_completion` 容错非标 `finish_reason`（SDK 层，不动 schema/tool_choice/gate）。
- 理由均记 `docs/changelog.md` v0.0.4。

## 18. 取值规则（entry_anchor 多时点读数 → 全抽进 history）

台账 thesis 文本可能含**多个时点读数**（MCO 加仓价 6/06 线 $349 与 7/24 重算 $394 并列；GOOGL 正文后附「（历史）当前读数 2026-06-06」整段）。这些**不是污染**，是用户刻意保留的重估轨迹（审计轨迹，不清除）。

- **不再「取最新、丢弃旧值」**——把文本中**所有时点读数全部抽进 `history` 数组**（含明确标注「（历史）」的段落，不跳过）。
- 日期无法判定的条目 → open_questions，不猜。
- **方法层变更**（method 变，如 NVDA forward P/E → 穿越周期归一化）记 `method_change_log`，不混进 history。
- entry_anchor 两层结构（method / history / current + method_change_log）见 `docs/thesis-card-schema.md` §5。
- 防止 **X5「history 抽取不全」**（eval-plan §9.3）：文本有 N 个时点只抽到 M<N，或把方法层变更误记为数值层滚动。
