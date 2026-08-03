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
  → 违规时拦截，替换为安全文案
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

### Tool-level Guardrail（工具调用后检查）

在 tool 函数内部实现，不需要 SDK 的 guardrail 机制。
违规时 raise 异常 → SDK 捕获 → LLM 看到错误 → 自动修正。

```python
@function_tool
def extract_card(text: str, ticker: str) -> dict:
    result = _do_extract(text, ticker)
    
    # 条件3: 同义复述拒绝
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
| `conditions.py` | Tool-level guardrail | 不动 |
| `condition_classify.py` | Tool-level guardrail | 不动 |
| `schema.py` | 数据结构定义 | 不动 |
| `models.py` | ThesisCard 模型 | 不动 |

**guardrail 层零改动**——这是重构的核心原则：确定性校验代码保留，只改 orchestration 层。