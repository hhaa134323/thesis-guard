# Thesis 卡结构化 Schema（v0.1）

| 项 | 值 |
|----|----|
| 版本 | v0.1 草稿 |
| 基线 | `pre-market-briefing/src/fetchers/thesis.py` 的 Notion 台账 schema（待 clone 后对齐，B1） |
| 状态 | 待对齐 |

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
- `key_assumptions`：用户陈述中抽取的关键前提；`judgeable` 标记是否可被披露击中。
- `broken_conditions`：两层结构，详见 `docs/broken-condition-schema.md`。
  - `layer=mirror`：`source_assumption_id` 指向其镜像的假设。
  - `layer=redline`：`template`（large_fine/exec_change/restatement）+ `threshold`（用户可调）。
  - 共有：`text` / `judgeable` / `historical_example` / `status` / `evidence`。
- `manual_check_items`：价格图形型等不可自动核对项，按 `cadence` 提醒。
- `review_notes`：复盘标注沉淀（误报/确认），作为后续 eval 标注来源。

## 3. 与台账 schema 的对齐计划（待 B1 解除）

- clone 后读 `thesis.py`，逐字段映射：
  - 台账列 → card 字段。
  - 复盘备注 → `review_notes`（作为条件判定 eval 的基准）。
  - 台账不存在但本产品新增的字段（`broken_conditions` 两层、`manual_check_items`、`confirmation`）记录为刻意偏离。

## 4. 偏离台账的刻意设计

- 台账是「持有 thesis 陈列」；本产品卡新增「破局条件两层 + 状态机 + 证据」，因为产品核心是「条件核对」而非「thesis 陈列」。
- 保留 `holding_reason_raw` 与台账一致，保证对话抽取 eval 可复现。

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
