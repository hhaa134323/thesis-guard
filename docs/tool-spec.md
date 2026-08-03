# Agent Tool Spec

> 对应 `docs/refactor-spec.md` Phase 1
> Agent 有 5 个 tools。LLM 根据用户输入自主决定调哪个、什么时候调、怎么组合。
> 每个 tool 是一个 Python 函数，用 `@function_tool` 装饰器注册到 OpenAI Agents SDK。

## Tool 1: resolve_ticker

### 给 LLM 的描述
在 SEC 官方表中查找股票代码。输入英文 ticker（如 MCO/HSBC/NVDA）或英文公司名。返回匹配结果或 NOT FOUND。只认英文，不认中文公司名——如果用户说中文，你需要先翻译成英文 ticker 再调用。

### 输入
| 参数 | 类型 | 描述 |
|---|---|---|
| query | str | 英文 ticker 或英文公司名 |

### 输出
```json
{"ticker": "MCO", "title": "MOODYS CORP /DE/", "cik": "0001018724", "found": true}
```
或
```json
{"found": false, "query": "汇丰"}
```

### Guardrails
- 调用前：无（LLM 自由决定何时调）
- 调用后：无（纯查询，不涉及红线）

### 依赖
- 现有 `fetchers/ticker_resolver.py`（删 fuzzy 后的精确匹配版本）

---

## Tool 2: extract_card

### 给 LLM 的描述
从用户的 thesis 描述中抽取结构化信息，生成 thesis card draft。需要 ticker 已确认后才能调用。返回结构化的 EntryExtraction。

### 输入
| 参数 | 类型 | 描述 |
|---|---|---|
| text | str | 用户的 thesis 描述原文 |
| ticker | str | 已确认的英文 ticker |

### 输出
```json
{
  "holding_reason_raw": "看好信用评级行业壁垒",
  "key_assumptions": [{"text": "...", "judgeable": true}],
  "mirrors": [{"assumption_text": "...", "mirror_text": "...", "threshold": {...}, "source_type": "..."}],
  "open_questions": [{"field": "...", "reason": "...", "text": "..."}],
  "entry_anchor": {"anchor_type": "...", "anchor_value": 25, "note": "..."},
  "next_verdict": {"event": "...", "date": "..."},
  "manual_items": [{"text": "...", "reason": "..."}]
}
```

### Guardrails
- 调用前：ticker 必须已通过 resolve_ticker 确认
- 调用后：
  - `redline.guard()` 检查所有抽取的文本（R1-R3）
  - `is_paraphrase()` 检查 key_assumptions（条件3：同义复述拒绝）
  - `classify_condition()` + `is_v1_auto()` 检查可判定性（条件4：不可证伪拒绝）
  - `make_mirror()` 检查镜像完整性（P3：缺 threshold/source_type 拒绝）

### 依赖
- 现有 `entry_agent.py` 的 extract 逻辑（改为函数，不再用 PydanticAI Agent）
- 现有 `agent.py` 的 `build_card_from_extraction`
- 现有 `conditions.py` / `condition_classify.py` / `redline.py`

---

## Tool 3: generate_menu

### 给 LLM 的描述
当用户说"无法确定"或想不出破局条件时，生成候选菜单。返回 A（信什么假设）和 B（破什么条件）两组候选。

### 输入
| 参数 | 类型 | 描述 |
|---|---|---|
| ticker | str | 已确认的英文 ticker |
| reason | str | 用户的买入理由原文 |

### 输出
```json
{
  "candidate_assumptions": ["假设1", "假设2"],
  "candidate_mirrors": [
    {"assumption": "对应假设", "mirror_text": "破局事件", "threshold": {}, "source_type": "..."}
  ],
  "excluded_mirrors": [],
  "coverage": "已排除 N 个方向（共 M）：..."
}
```

### Guardrails
- 调用后：
  - `redline.guard()` 检查所有候选文本
  - `filter_executable_mirrors()` 过滤不可自动核对的 B 候选（P4）

### 依赖
- 现有 `menu.py` 的 `generate_menu` 逻辑
- 现有 `menu.py` 的 `filter_executable_mirrors`

---

## Tool 4: save_card

### 给 LLM 的描述
将 thesis card 保存到数据库。只有在用户明确确认后才能调用。

### 输入
| 参数 | 类型 | 描述 |
|---|---|---|
| ticker | str | 已确认的英文 ticker |
| holding_reason_raw | str | 买入理由原话 |
| key_assumptions | list | 关键假设列表 |
| mirrors | list | 镜像破条件列表 |
| entry_anchor | dict | 估值锚（可选）|
| next_verdict | dict | 下次裁判日（可选）|
| manual_items | list | 人工自查项（可选）|
| holding_horizon | str | 持仓周期 long/mid/trade（可选）|

### 输出
```json
{"saved": true, "card_id": "...", "ticker": "MCO"}
```

### Guardrails
- 调用前：用户必须已明确确认（"确认"、"对"、"入库"等）
- 调用后：
  - `redline.guard()` 最终检查
  - 确认 `confirmed_by_user = True`

### 依赖
- 现有 `store.py` 的 `upsert_card`
- 现有 `models.py` 的 `ThesisCard`

---

## Tool 5: check_filing

### 给 LLM 的描述
查询某 ticker 最近一份 SEC filing（10-K/10-Q/20-F/6-K）。用于回答用户在确认阶段的问题。

### 输入
| 参数 | 类型 | 描述 |
|---|---|---|
| ticker | str | 英文 ticker |

### 输出
```json
{"form_type": "10-K", "filed_at": "2026-07-15", "url": "https://..."}
```
或
```json
{"found": false}
```

### Guardrails
- 无（纯查询）

### 依赖
- 现有 `fetchers/sec_edgar.py` 的 `fetch_latest_filing`

---

## Tool 调用流程（LLM 自主决策，不硬编码）

```
用户："我持有MCO，看好信用评级壁垒"
  → LLM 调 resolve_ticker("MCO") → 命中 Moody's
  → LLM 调 extract_card("看好信用评级壁垒", "MCO") → 返回 card draft
  → LLM 呈现 card 给用户，问"对吗？"

用户："无法确定"
  → LLM 调 generate_menu("MCO", "看好信用评级壁垒") → 返回候选
  → LLM 呈现候选菜单

用户："确认"
  → LLM 调 save_card(...) → 落库
  → LLM 确认"已落库"

用户："最近财报什么时候？"
  → LLM 调 check_filing("MCO") → 返回 filing 信息
  → LLM 回答 + 拉回确认
```

**以上流程是 LLM 自主决策的典型路径，不是硬编码的 state machine。LLM 可以根据上下文自由组合 tools。**

---

## 文档依赖
- 本文定义 tool 接口 → `docs/agent-prompt.md`（待写）引用本文的 tool 描述
- `docs/guardrail-mapping.md`（待写）定义每个 tool 的 guardrail 细节
- `docs/eval-refactor.md`（待写）定义验收 case，引用本文的 tool 名