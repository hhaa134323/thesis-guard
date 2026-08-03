# Thesis 卡结构化 Schema（v0.1）

| 项 | 值 |
|----|----|
| 版本 | v0.1 草稿 |
| 基线 | Notion 台账「🧭 持仓 Thesis · 价值投资台账」schema（已对齐，见 §4） |
| 状态 | 已对齐（P5 持仓周期补齐，0 遗留） |

## 1. 设计原则

- 一张卡 = 一个 ticker 的一次持有逻辑。
- 卡内含：持有理由原始陈述、关键假设、破局条件（两层）、人工自查项、确认状态、复盘标注。
- 判断权归用户：卡只存「条件 + 证据 + 状态」，不存「结论/建议」。
- 与台账对齐 `holding_reason_raw` 等字段，确保对话抽取 eval 可用台账做基准。

## 2. 字段（v1 提案，待对齐 thesis.py）

```json
{
  "card_id": "uuid",
  "user_id": "preset_user_id",
  "ticker": "AAPL",
  "filer_type": "foreign_issuer_20f_6k | domestic_10k | ...",
  "holding_horizon": "long | mid | trade",
  "holding_reason_raw": "用户原话",
  "key_assumptions": [
    { "id": "a1", "text": "服务收入持续高增", "judgeable": true }
  ],
  "broken_conditions": [
    {
      "id": "c1",
      "layer": "mirror",
      "source_assumption_id": "a1",
      "text": "服务收入同比转负",
      "judgeable": true,
      "threshold": null,
      "historical_example": "...",
      "status": "untriggered | watch | triggered",
      "evidence": []
    },
    {
      "id": "c2",
      "layer": "redline",
      "template": "large_fine",
      "text": "大额罚单",
      "threshold": { "amount_usd": ">=1e8" },
      "historical_example": "...",
      "status": "...",
      "evidence": []
    }
  ],
  "manual_check_items": [
    { "id": "m1", "text": "跌破60日均线", "reason": "价格图形型", "cadence": "monthly" }
  ],
  "confirmation": { "paraphrased": true, "confirmed_at": "2026-07-31", "confirmed_by_user": true },
  "created_at": "...",
  "updated_at": "...",
  "review_notes": []
}
```

字段说明：

- `filer_type`：决定核对时 SEC 表单路由（6-K 为主 vs 10-K 等）。
- `holding_horizon`：持仓周期（P5 新增），枚举 `long`（≥3y，noise 阈值最高）/ `mid`（3m-3y，看 thesis + 季报，不止损）/ `trade`（≤3m，可用 trailing stop）。**录入时必须问用户，不允许模型猜**；应影响 mirror 阈值的时间尺度选择（long→季频阈值，trade→日频/trailing stop）。
- `key_assumptions`：用户陈述中抽取的关键前提；`judgeable` 标记是否可被披露击中。**合格判定见 §7（四条，缺一不合格；不合格转 `open_questions`，宁缺勿凑）**。
- `broken_conditions`：两层结构，详见 `docs/broken-condition-schema.md`。
  - `layer=mirror`：`source_assumption_id` 指向其镜像的假设。
  - `layer=redline`：`template`（large_fine/exec_change/restatement）+ `threshold`（用户可调）。
  - 共有：`text` / `judgeable` / `historical_example` / `status` / `evidence`。
- `manual_check_items`：价格图形型等不可自动核对项，按 `cadence` 提醒。
- `review_notes`：复盘标注沉淀（误报/确认），作为后续 eval 标注来源。

## 3. 与台账 schema 的对齐结论（已执行，2026-08-03 P5）

台账对齐**已完成**（不再「待 B1 解除」——台账 schema 来自 Notion 活库只读快照 `assets/notion/thesis/`，不依赖 pre-market-briefing 源码 clone）：

- 逐字段映射见 §4 对照表：11 个台账字段 + 7 个 card 新增字段，逐行标 刻意偏离 / 已对齐 / 本轮补。
- 复盘备注 → `review_notes`（条件判定 eval 基准）。
- 持仓周期 → `holding_horizon`（P5 补，枚举 long/mid/trade，录入问用户不模型猜）。
- 0 个「尚未对齐」字段；`pre-market-briefing` 源码 clone（B1）与台账对齐解耦——B1 仅影响复用 fetcher，不影响 schema 对齐。

## 4. 偏离台账的刻意设计

台账是「持有 thesis 陈列」；本产品卡新增「破局条件两层 + 状态机 + 证据」，因为产品核心是「条件核对」而非「thesis 陈列」。保留 `holding_reason_raw` 与台账一致，保证对话抽取 eval 可复现。

### 4.1 台账字段 → card 字段对照（逐行标 刻意偏离 / 已对齐 / 本轮补）

台账 schema（Notion「🧭 持仓 Thesis · 价值投资台账」）字段：Ticker / Market / Status / 持仓周期 / Thesis·为什么买 / Thesis破的条件 / 加仓价·安全边际 / 下次复盘日 / 关注词 / 复盘备注 / 搜索名。

| 台账字段 | card 字段 | 判定 | 理由 |
|---|---|---|---|
| Ticker | `ticker` | 已对齐 | 语义一致；P0 改 SEC 确定性解析（不经 LLM） |
| Market | — | 刻意偏离 | 台账运营字段（市场分类），非录入 agent 职责 |
| Status | — | 刻意偏离 | 复查 agent 的输出，非录入输入（不循环） |
| 持仓周期 | `holding_horizon` | **本轮补（P5）** | 枚举 long/mid/trade，录入问用户不模型猜；影响 mirror 阈值时间尺度 |
| Thesis·为什么买 | `holding_reason_raw` | 已对齐 | 逐字保真，eval 可复现 |
| Thesis破的条件 | `broken_conditions` | 刻意偏离 | 升级为两层（mirror + redline），产品核心是条件核对 |
| 加仓价·安全边际 | `entry_anchor` | 已对齐 | P3 前端已渲染（method + current + history 折叠） |
| 下次复盘日 | — | 刻意偏离 | 台账运营字段（复盘日历），非录入职责 |
| 关注词 | — | 刻意偏离 | 台账运营字段 |
| 复盘备注 | `review_notes` | 已对齐 | 作为条件判定 eval 基准 |
| 搜索名 | — | 刻意偏离 | 台账运营字段 |

### 4.2 card 新增字段（台账不存在，刻意新增）

| card 字段 | 判定 | 理由 |
|---|---|---|
| `filer_type` | 刻意新增（事实） | SEC 申报方类型，决定核对表单路由（P0 查表不经 LLM） |
| `key_assumptions` | 刻意新增（判断） | 条件核对的锚；P2 四条合格判定 |
| `broken_conditions` 两层 | 刻意新增 | mirror（Layer 1）+ redline（Layer 2 通用红线包） |
| `manual_check_items` | 刻意新增 | 价格图形型等降级，显式人工交接（非系统缺陷，PRD §4-A） |
| `confirmation` | 刻意新增（系统状态） | 用户复述确认后才入库 |
| `position_cap_tier` | 刻意新增（事实） | 仓位上限档按 ticker 查表（tier_map，不经 LLM） |
| `holding_horizon` | 本轮补（P5，事实） | 用户自报，影响 mirror 阈值时间尺度 |

> **刻意偏离** = 台账有但 card 不做（运营字段 / 职责错配）；**已对齐** = 语义一致；**本轮补** = 之前缺、P5 补上。
> 0 个「尚未对齐」（P5 后持仓周期已补，无遗留）。

## 5. entry_anchor 结构（两层：方法 + 历史；2026-08-02 改）

> 背景：MCO / GOOGL 字段中的多时点读数**不是数据污染**，是用户刻意保留的**重估轨迹**——估值方法固定，数值随新财报滚动重算，历史读数是**审计轨迹**，不应清除。

```yaml
entry_anchor:
  method:      估值方法（如 ttm_gaap_pe / p_fcf / p_tbv / normalized_operating_pe / operating_multiple_2col）
  method_note: 为什么选这个口径（口径选择理由，方法层变更需留痕）
  history:     [{ date, multiple, basis, value }]   # 按日期升序；文本所有时点读数全抽，含「（历史）」段
  current:     history 中日期最新的一条              # 派生字段，不手填
method_change_log: [{ date, from, to, reason }]      # 方法层变更（如 NVDA forward P/E → 穿越周期归一化），与数值层滚动区分
```

- **方法层变更**（method 变）须单独记 `method_change_log`，**不混进 history**（history 是同方法下的数值滚动）。
- **CGNX 双线**（起步加仓线 / 安全边际线）：疑为两种方法——定义前 GT 置 null + open_questions，不猜。
- **抽取规则**：文本中所有时点读数全部抽进 history（含明确标注「（历史）」的段落，不跳过）；日期无法判定 → open_questions。见 `docs/entry-agent-spec.md` §18。
- **副产品**：history 落地后，「当前价距破线的距离」及其季度间变化可直接计算（不需新增数据源）——是 PRD §12 W2「记忆/跨期追踪」+「观察区按逼近程度排序」的底层数据，优先级上调。

## 6. 字段确定性审计（P0，2026-08-03）

逐字段判定：**事实**（有唯一正确答案，须查表/API/规则，不经 LLM）vs **判断**（需语义理解，LLM 抽取/生成）。
**红线**：事实字段一经判定为事实，禁止交给 LLM 猜——glm 把「SK海力士」猜成 SKHCF（Sonic Healthcare）即此问题的真实案例。

| 字段 | 类型判定 | 当前来源 | 改后来源 |
|---|---|---|---|
| card_id | 系统（uuid） | 代码 uuid | 不变 |
| user_id | 事实（预置账号） | 输入 beta1–5 | 不变 |
| **ticker** | **事实（唯一正确代码）** | LLM（ext.ticker） | **`fetchers/ticker_resolver.py` SEC 官方表；ext.ticker 弃用，0/多→问用户，不猜** |
| **filer_type** | **事实（SEC 申报方类型）** | `filer_type_lookup.yaml` 查表 + **LLM 兜底** | **查表 only，去 LLM 兜底；查表无→pending/open_question** |
| holding_reason_raw | 判断（语义：用户原话复述） | LLM 抽取 | 不变（语义判断） |
| key_assumptions | 判断（语义：关键前提） | LLM 抽取 | 不变（P2 加四条定义 + 拒绝规则约束抽取质量） |
| broken_conditions[].text（mirror） | 判断（语义：破局事件） | LLM 生成 | 不变 |
| broken_conditions[].threshold（mirror） | **事实（可判定阈值）** | 空（make_mirror 不产） | **P3：make_mirror 强制产 threshold + source_type，缺→open_question，禁 `threshold:null`** |
| broken_conditions[].source_type（mirror） | **事实（数据源类型）** | 无字段 | **P3 新增** |
| broken_conditions[] redline template | 事实（规则） | `default_redline_pack` 规则 | 不变（已确定性） |
| broken_conditions[] redline threshold | 事实（规则阈值） | `default_redline_pack` 规则 | 不变（已确定性） |
| manual_check_items | 事实+判断（`is_price_pattern` 规则判定降级；text 来自用户/LLM） | 规则 + LLM | 不变（`is_price_pattern` 已确定性规则） |
| entry_anchor.method | 事实（闭集枚举 AnchorType） | LLM 抽 + 闭集校验 | 不变（闭集已约束非猜；P3 前端渲染） |
| entry_anchor.value | 事实（用户文本中的数值） | LLM 抽取 | 不变（数值非猜测） |
| next_verdict.event | 判断（语义：证伪事件） | LLM 抽取 | 不变（语义判断） |
| next_verdict.date | **事实（SEC 财报/filing 日历）** | LLM 抽取 | **抽取阶段不采信 LLM 日期（R5：LLM 给不出一手链接）；confirm 阶段用户问→`fetchers/sec_edgar.py` 实取附链接（P1）** |
| position_cap_tier | **事实（按 ticker 查表）** | `tier_map.py` 查表 | 不变（已确定性） |
| holding_horizon | **事实（用户自报，枚举）** | 无 | **P5 新增：录入时问用户，不模型猜** |
| confirmation | 系统状态 | 代码 | 不变 |
| review_notes | 系统/eval 标注 | 代码 | 不变 |
| created_at / updated_at | 系统 | 代码 | 不变 |

**本轮（P0）已落地**：`ticker`（resolver）、`filer_type`（去 LLM 兜底）。
**后续轮次承接**：mirror threshold/source_type → P3；next_verdict.date 的 SEC 实取 → P1 confirm 阶段 fetcher；holding_horizon → P5。

> 设计说明：`ticker`/`filer_type` 在 `EntryExtraction`（LLM 输出契约）里**字段保留**（不动 eval GT 契约），但录入 loop **不再采信 LLM 输出值**——`ticker` 走 resolver（`ext.ticker` 弃用），`filer_type` 走查表（`ext.filer_type` 弃用）。判定为事实的字段，决策权不在 LLM，即满足「不经 LLM」。后续若 eval GT 解耦，可彻底从 LLM 契约移除这两个字段。

## 7. key_assumptions 合格判定（P2，2026-08-03）

一条 key_assumption 必须同时满足以下四条，缺一不合格：

1. 是关于**这门生意**的判断——不是估值口径、不是计算方法、不是价格形态
2. **可能为假**——存在一个可想象的世界状态，使它不成立
3. **比用户原话多出信息**——同义复述、拆分扩写、换词重写，一律不合格
4. **能对应至少一条带可判定阈值的镜像**——对应不上说明它不可证伪，不合格

不合格的处理：不填。改写成 open_question 向用户追问。宁缺勿凑。

> **背景（eval-report §6.5 根因）**：该字段 W2 盲评 55 条中 8 条不合格、7 条来自它（字段失败率 28%）；真实运行又填了一遍同义复述。两次都不是 bug——是这个字段从来没被定义过。补 §6.5 的输入污染（「加仓价/安全边际」段被拼进 GT 输入，对应 entry_anchor 而非 key_assumptions）后，本节落地四条定义 + 拒绝规则。

**实现**：
- **拒绝规则**：抽取阶段对每条候选假设逐条过四关，任一不过 → 不写入 `key_assumptions`，改写为 `open_questions`（LLM 自判，schema 已加 `OpenQuestion` 字段）。
- **条件 3 确定性 backstop**：`conditions.is_paraphrase`——候选与 `holding_reason_raw` 高度相似（子串/包含或 difflib ratio ≥ 0.8）即判同义复述，harness 兜底剔出转 `open_questions`（专治 W2 7/8 的同义复述）。
- **输入隔离**：抽 `key_assumptions` 时不得把「加仓价 / 安全边际」类内容作输入，该段只流向 `entry_anchor`（估值口径混进关键假设输入 = 模型同义复述的根因）。
- 正反例见 `src/thesis_watch/prompts/entry-agent.md`「key_assumptions 合格判定」段。
