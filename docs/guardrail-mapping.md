# Guardrail Mapping: R1-R9 在新架构中的落地

> 对应 `docs/refactor-spec.md` §7
> 红线不变，执行方式从"状态机硬编码"改为"System Prompt + OpenAI Agents SDK Guardrails 双保险"

## 双保险架构

```
第一道防线：System Prompt（软约束）
  → LLM 看到红线规则，大多数情况会遵守
  → 但 LLM 可能偶尔违反（尤其用户诱导时）

第二道防线：OpenAI Agents SDK Guardrails（硬约束）
  → OutputGuardrail: 检查 LLM 最终输出是否违规
  → Tool-level Guardrail: 在 tool 函数内部检查
  → 违规时拦截，替换为安全文案或 raise 异常
  → 确定性代码，100% 可靠
```

## R1-R9 映射表

| 红线 | System Prompt | Guardrail | 实现方式 |
|---|---|---|---|
| R1 不给买卖建议 | 编码进 prompt | OutputGuardrail: `redline.guard()` | 现有 `redline.py` 不动 |
| R2 不预测涨跌 | 编码进 prompt | OutputGuardrail | 现有 `redline.py` 不动 |
| R3 不出现看涨看跌暗示 | 编码进 prompt | OutputGuardrail | 现有 `redline.py` 不动 |
| R4 不接 broker API | 编码进 prompt | 架构层面没有这个 tool | 不需要 guardrail |
| R5 每条事实有来源 | 编码进 prompt | Tool-level: extract_card 要求 source | 现有 `conditions.py` 不动 |
| R6 判断权归用户 | 编码进 prompt | prompt 约束 + OutputGuardrail | 不输出投资结论 |
| R7 不写 Notion | 编码进 prompt | 架构层面没有 Notion API tool | 不需要 guardrail |
| R8 eval GT 标注源 | 不影响用户交互 | eval spec 定义 | `docs/eval-refactor.md` |
| R9 脱敏 | 不影响 localhost | 上线前处理 | 不影响重构 |

## 新增 Guardrail（讨论式流程专用）

### G1: 必填字段检查（save_card 前置）

5 个必填字段缺一不可，不允许部分保存：
- ticker（已通过 resolve_ticker 验证）
- holding_reason_raw（thesis 原话）
- key_assumptions（用户已确认）
- mirrors（破局条件，含 redline 默认包）
- entry_anchor（安全边际/估值锚）
- holding_horizon（持仓周期）

```python
@function_tool
def save_card(...) -> dict:
    required = [ticker, holding_reason_raw, key_assumptions, mirrors, entry_anchor, holding_horizon]
    if any(v is None or v == "" or v == [] for v in required):
        raise ValueError("必填字段缺失，不允许部分保存")
    # ... save
```

**为什么不允许部分保存**：安全边际是"真正建仓"的触发线。如果允许存 3/4 字段（没填估值），系统不知道什么时候该提醒用户建仓，thesis card 失去核心功能。

### G2: 幻觉检查（save_card 前置）

save_card 只保存用户提供的数据，不允许 LLM 编造：
- entry_anchor 的数值必须来自用户（不是 LLM 查财报编的）
- key_assumptions 必须从用户原话抽取（不是 LLM 自己编的）
- 如果 LLM 在讨论中提到"当前 P/E 28倍"等数据，必须标注"我没有实时数据来源，你能确认吗？"

```python
@function_tool
def save_card(..., entry_anchor: dict, ...) -> dict:
    # entry_anchor 必须有 user_confirmed=True 标记
    if not entry_anchor.get("user_confirmed"):
        raise ValueError("安全边际未经用户确认")
    # ... save
```

### G3: key_assumptions 质量检查（extract_card 后置）

四条合格判定（详见 `docs/thesis-card-schema.md` §7）：
1. 是关于这门生意的判断（不是估值口径、计算方法、价格形态）
2. 可能为假
3. 比用户原话多出信息
4. 能对应至少一条带可判定阈值的镜像

**System Prompt 层**：四条定义 + 正反例 编码进 prompt（软约束，LLM 自判）

**Tool-level 层**（硬约束）：
```python
@function_tool
def extract_card(text: str, ticker: str) -> dict:
    result = _do_extract(text, ticker)
    
    # 条件3: 同义复述拒绝（确定性 backstop）
    for a in result.get("key_assumptions", []):
        if is_paraphrase(a["text"], text):
            raise ValueError("条件3: 同义复述拒绝")
    
    # 条件4: 不可证伪拒绝
    for a in result.get("key_assumptions", []):
        if not is_v1_auto(classify_condition(a["text"])):
            raise ValueError("条件4: 不可证伪拒绝")
    
    # P3: 缺 threshold/source_type
    for m in result.get("mirrors", []):
        if not m.get("threshold") or not m.get("source_type"):
            raise ValueError("P3: 缺 threshold/source_type")
    
    # 输入隔离：抽 key_assumptions 时不得把「加仓价/安全边际」类内容当输入
    # （在 _do_extract 内部实现，不把 entry_anchor 段传入 assumptions 抽取）
    
    # R1-R3 检查
    all_text = " ".join(
        [a["text"] for a in result.get("key_assumptions", [])] +
        [m["mirror_text"] for m in result.get("mirrors", [])]
    )
    violations = redline.guard(all_text)
    if violations:
        raise ValueError(f"R1-R3 违规: {violations}")
    
    return result
```

### G4: 用户确认检查（save_card 前置）

```python
@function_tool
def save_card(..., confirmed_by_user: bool, ...) -> dict:
    if not confirmed_by_user:
        raise ValueError("用户未确认，不允许保存")
    # ... save
```

## Guardrail 实现细节

### OutputGuardrail（最终输出检查）

检查 LLM 最终输出是否违反 R1-R3。这是确定性代码，100% 可靠。

```python
from agents import OutputGuardrail, GuardrailFunctionOutput

async def redline_guard(ctx, agent, output):
    violations = redline.guard(output.final_output)
    if violations:
        return GuardrailFunctionOutput(
            output_info={"violations": violations},
            tripwire_triggered=True
        )
    return GuardrailFunctionOutput(output_info={}, tripwire_triggered=False)
```

- 注册: `Agent(output_guardrails=[redline_guard])`
- 触发后: SDK 自动拦截，替换为安全文案
- 现有 `redline.py` 的 `guard()` 函数直接复用，不需要改

### InputGuardrail（用户输入检查）

新增，现有系统没有。防止用户诱导 LLM 违规。

```python
async def injection_guard(ctx, agent, input):
    dangerous = ["帮我分析能不能买", "你觉得会涨吗", "推荐一只股票"]
    for pattern in dangerous:
        if pattern in str(input):
            return GuardrailFunctionOutput(
                output_info={"reason": "用户在诱导投资建议"},
                tripwire_triggered=True
            )
    return GuardrailFunctionOutput(output_info={}, tripwire_triggered=False)
```

轻量级，只做关键词匹配，不做 LLM 判断。

## 现有 guardrail 代码复用

| 现有文件 | 新架构角色 | 改动 |
|---|---|---|
| `redline.py` | OutputGuardrail 核心 | 不动 |
| `conditions.py` | Tool-level guardrail (G3) | 不动 |
| `condition_classify.py` | Tool-level guardrail (G3) | 不动 |
| `schema.py` | 数据结构定义 | 不动 |
| `models.py` | ThesisCard 模型 | 不动 |

**guardrail 层零改动**——这是重构的核心原则：确定性校验代码保留，只改 orchestration 层。

## Guardrail 总览

| ID | 名称 | 类型 | 触发点 |
|---|---|---|---|
| R1-R3 | 红线文案检查 | OutputGuardrail | LLM 最终输出 |
| G1 | 必填字段检查 | Tool-level | save_card 调用前 |
| G2 | 幻觉检查 | Tool-level | save_card 调用前 |
| G3 | key_assumptions 质量 | Tool-level | extract_card 调用后 |
| G4 | 用户确认检查 | Tool-level | save_card 调用前 |
| InputGuardrail | 注入防护 | InputGuardrail | 用户输入 |