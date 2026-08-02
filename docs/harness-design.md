# Harness 设计文档

| 项 | 值 |
|----|----|
| 版本 | v0.1 草稿 |
| 日期 | 2026-07-31 |
| 状态 | 选型待作者确认；阻塞中（B1） |

## 1. 选型与理由

### 1.1 Agent loop：Claude Agent SDK（原生）【提案，待确认】

- **方案 A（首选）**：用 Claude Agent SDK（Claude Code 的 SDK 形态）跑两个 agent（录入 / 核对），自定义工具集（包装复用 fetchers），系统提示词编码红线 + 拒判 + 证据自检。
  - **理由**：目标明确要求「用 Claude Code 原生能力实现 agent loop，不引入 Dify/LangChain，除非证明原生不够」。Agent SDK 即原生 tool-use loop，自带 tool 调度、权限、中断恢复，无需自造轮子，最贴近「原生」。
  - **风险**：作为服务端核对 agent 跑 5 用户（数据更新时触发，非日频轮询），成本与速率限制需评估；headless 调用稳定性需压测。
- **方案 B（备选）**：Anthropic Python SDK 手搓 tool-use loop。
  - **理由**：复用 fetchers 是 Python，同语言栈；完全可控，便于实现拒判/证据自检的自定义控制流。
  - **风险**：自造 loop 的重试/中断/并行调度需自实现，偏离「原生优先」倾向；仅当 A 证明不够才用。
- **决策点**：待作者拍。默认推进 A；B 作为 fallback 已在设计上对齐（工具签名一致，可平滑切换）。

### 1.2 后端：Python + FastAPI + SQLite

- **理由**：复用 fetchers 是 Python；「后端从简、单数据库」；SQLite 单文件便于 5 人 beta 托管与备份。
- **职责**：PWA 静态托管、预置账号、thesis 卡 CRUD、邮件调度、触发核对 Agent headless。

### 1.3 前端：~~PWA~~ → 桌面 localhost 单页（2026-08-02 形态定稿，见 PRD §11/§14）

> ⚠️ **本节 PWA 选型已作废**（2026-08-02 形态定稿为桌面 localhost 单页；**前端栈 2026-08-02 再修订为 React+Vite+shadcn/ui**，见 `docs/frontend-design-v1.md`）。录入交互用本地 Web 页面承载：FastAPI 托管前端构建产物 + .bat 启动，用户不碰 shell；形态 C——居中对话 + 右侧确认卡抽屉。部署中立（配置走 env，不写死 localhost）。以下历史方案留档。

- **方案 A（原倾向，已废）**：Vite + React + PWA 插件。对话式录入是核心交互，组件化对话 UI 体验更好；真 PWA（manifest + service worker）。
- **方案 B（已废）**：FastAPI + Jinja 服务端渲染 + manifest。最简，无构建步骤。
- **方案 C（已拍，2026-08-02；前端栈同日修订）**：桌面 localhost 单页——FastAPI 托管 React+Vite+shadcn 构建产物 + .bat 启动；部署中立（env 驱动）；形态 C（居中对话 + 右侧确认卡抽屉）。见 PRD §14 + `docs/frontend-design-v1.md`。
- **决策点**：~~待作者拍~~ → 已拍：桌面 localhost 单页（方案 C，见 PRD §14）。

### 1.4 触达：复用 `src/sinks/`（Gmail SMTP）

- 命中当天单独邮件；未命中合并进简报。

### 1.5 数据源：复用 `sec_edgar.py` + `news.py`

- 按申报方类型路由：外国发行人以 6-K 为主渠道，不沿用美国本土「6-K 降级」规则。
- v1 不接行情；价格图形型条件降级为人工自查项。

## 2. Agent loop 结构图

### 2.1 录入 Agent（entry agent）

```
用户输入 → [LLM 主循环]
  ├ 工具: read_card_draft / write_card_draft / lookup_filer_type(ticker) / lookup_historical_example(template)
  ├ 追问逻辑（可判定性引导）: 每条条件必须能映射到一个可被一手披露击中的事件；否则改造或降级人工自查
  ├ 镜像生成: 从关键假设自动生成候选镜像条件（Layer 1）
  ├ 红线默认包: 自动下发大额罚单/高管突变/财报重述（Layer 2，用户可调阈值/关停）
  └ 输出: thesis 确认卡（待用户复述确认）→ confirm 后入库
```

### 2.2 核对 Agent（check agent）— 数据更新时触发

```
触发（数据更新时：财报 / 公告 / 监管进展 / 新闻，每用户每 ticker）→ 加载 thesis 卡 → [LLM 主循环]
  ├ 工具: sec_edgar_fetch(ticker, form_type, since) / news_rss(ticker) / read_thesis_card / write_check_result
  ├ 对每条 broken_condition: 检索-深读 → 判定状态(untriggered|watch|triggered)
  ├ 证据自检: 每条命中必须附一手链接 + 原文摘录；evidence_self_check 回放校验
  ├ 拒判: 证据不足/歧义/无一手源 → 置 watch 或「无法判定」，不替用户结论
  └ 输出: 状态机卡片 + 触达决策（命中→单独邮件；未中→并入简报）
```

## 3. 工具清单（初版）

| 工具 | 用途 | 复用来源 |
|------|------|----------|
| `sec_edgar_fetch(ticker, form_type, since)` | SEC EDGAR 抓取（按申报方类型路由 6-K 为主） | `src/fetchers/sec_edgar.py` |
| `news_rss(ticker)` | Yahoo ticker 头条 RSS（去重、不过滤） | `src/fetchers/news.py` |
| `read_thesis_card(card_id)` | 读用户 thesis 卡 | 自建 |
| `write_check_result(card_id, cond_id, status, evidence)` | 写核对结果 | 自建 |
| `evidence_self_check(url, excerpt)` | 校验链接可达 + 摘录与原文一致 | 自建 |
| `lookup_filer_type(ticker)` | 查申报方类型（决定 6-K vs 10-K 路由） | 自建（基于 EDGAR） |
| `lookup_historical_example(cond_template)` | 查历史事件示例（录入时给候选） | 自建 |
| `render_briefing(user_id)` | 渲染简报 | 参考 `src/render/thesis_section.py` |
| `send_email(to, subject, body)` | Gmail SMTP | `src/sinks/` |

> 工具签名在 A/B 两方案下保持一致，便于切换。

## 4. 拒判策略（Refusal）

Agent 在以下情况**必须拒判**，不替用户下结论：

1. 找不到一手原文链接（只有二手转述 / 「据传」「市场预期」）。
2. 证据与条件映射存在歧义（事件部分相关但不确定是否击中）。
3. 数据源抓取失败或返回空（不臆测）。
4. 条件本身不可判定（无对应可被披露击中的事件）→ 录入阶段就应被追问改造或降级人工自查。

拒判输出：状态置 `watch` 或 `无法判定`，附「为什么无法判定 + 缺什么证据」，转交用户裁决。**拒判不算 eval 失败，单独统计拒判率与原因分布。**

## 5. 证据引用自检（Evidence self-check）

每条 `triggered` / `watch` 结论必须满足：

- 一手原文链接（SEC EDGAR filing URL 或新闻原文 URL，**非聚合页**）。
- 原文摘录（quote），且摘录必须能在 fetched 原文中定位到。
- 自检工具回放：`evidence_self_check(url, excerpt)` → fetch url → 断言 excerpt 子串存在 → 否则降级为 `watch` 并记录 error E3。

## 6. Error taxonomy v1

| code | 类别 | 触发 | 处置 |
|------|------|------|------|
| E1 | FETCH_FAIL | sec_edgar/news 抓取失败/超时 | 重试 N 次；仍失败 → 该条件 `无法判定` + 记录 |
| E2 | NO_PRIMARY_SOURCE | 只找到二手源 | 拒判 → `watch` |
| E3 | EVIDENCE_MISMATCH | 摘录与原文不一致 | 降级 `watch` + 记录；疑似幻觉 |
| E4 | AMBIGUOUS_MAPPING | 事件与条件映射歧义 | `watch` + 附歧义说明 |
| E5 | UNJUDGEABLE_COND | 条件无可击中事件 | 回流录入阶段改造/降级人工自查 |
| E6 | RATE_LIMIT | API 限流 | 退避重试 |
| E7 | SCHEMA_MISMATCH | thesis 卡字段缺失/类型错 | 拒收 + 提示修复 |
| E8 | RENDER_BLOCK | 文案命中红线黑名单 | 阻断发送 + 告警 |

所有 error 自动沉淀为 eval 标注与 error analysis 输入（→ `docs/eval-plan.md` §2.5）。

## 7. 红线落地（实现层）

- **R3 文案黑名单**：渲染/发送前 grep「看涨/看跌/建议关注/目标价/预期收益/据传」等 → 命中则 E8 阻断。
- **R5 一手链接**：`evidence_self_check` 强制；无一手源 → E2 拒判。
- **R6 不替结论**：核对输出只有状态机三态 + 证据，绝不输出「建议卖出/加仓」类。
- **R7 不写 Notion**：核对 Agent 工具集不含任何 Notion 写工具；Notion MCP 仅只读刷新 `assets/`，且不在 agent loop 内调用（MCP 只在构建期手动触发）。

## 8. 阻塞

B1 未解除前无法 clone 源码、无法对齐 `thesis.py` schema、无法在线跑 SEC 抓取。本文件为设计草案，待解除后进入实现。
