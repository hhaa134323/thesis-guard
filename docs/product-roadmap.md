# 产品路线图：从录入工具到投研助手

> 创建时间：2026-08-04 | 更新：2026-08-05 | PM：caca + Notion AI
> 状态：Stage 2 已完成，Stage 3 待启动

## 背景

重构（Phase 0-5）完成后，录入 + 核对两个核心模块的 agent loop 架构已稳。本文件描述从当前状态到"投研助手"的演进路线，以及 Stage 2 启动前的技术准备。

## 演进路线

### Stage 1：录入 + SEC 核对（✅ 已完成）

**用户能做什么**：跟 agent 聊天录入 thesis（5 步讨论）→ 系统存卡 → 定时查 SEC filing 比对破局条件 → 三态输出（triggered/watch/untriggered）

**用户拿到什么**：把"我为什么买"从脑子里变成结构化记录 + SEC 自动核对

**缺口**：没有价格监控、没有通知推送、只有 SEC 一个数据源

---

### Stage 2：监控闭环（✅ 已完成，2026-08-05）

**上线什么（6 项）**：
1. YahooPriceFetcher — Yahoo Finance 免费行情 API，价格数据源
2. 安全边际监控 — 价格跌入安全边际 → alert（price_monitor.py）
3. 自动化调度 — APScheduler 每日定时跑检查（scheduler.py）
4. 通知编排 — Alert（命中单独发）+ Digest（每日汇总）+ S4 收尾（notification.py）
5. watch 记忆 — check_agent 读上次结果输出 change 六态（new/worsened/improved/unchanged/resolved/escalated）
6. SEC filing history tool — agent 可查历史 filing 列表，不只看最近一份

**用户拿到什么**：录入完 → 系统自动盯 → 到价/破局/红线 → 邮件推送。这就是"每天 1 分钟"的承诺——你不用主动查，系统告诉你什么时候该看。

**判断标准**：录完不用主动查，系统推送

**这是当前产品的最终形态**——录入 + 监控 + 通知，闭环了。

**实现**：commit `8c65773`，212 tests 全绿，端到端验收通过（B1+B2）。价格监控 env-blocked（已接受）。详见 Notion「Thesis Guard · Stage 2 业务流程设计」+ `docs/stage2-extension.md`。

---

### Stage 3：多源核对（扩展开始）

**上线什么**：
- Yahoo RSS 新闻源 → check agent 不只看 SEC filing，还看新闻标题
- 行业数据源 → mirror 能查的从"只有 SEC"扩展到"SEC + 新闻 + 行业"
- extract 带调研 → 录入时 agent 先拉新闻 + 查 filing → 带上下文抽假设（agent loop 开始兑现多步价值）

**用户拿到什么**：核对不只看财报了，还看新闻。假设质量更高（agent 带调研抽取，不是盲抽）。manual_items 开始变 mirror（有数据源的升级成自动）。

**判断标准**：核对不只看 SEC，假设带调研

---

### Stage 4：投研助手

**上线什么**：
- 跨 thesis 分析——agent 看你所有卡，发现矛盾和集中度
- thesis decay 追踪——假设随时间衰减，agent 主动提醒"你 6 个月前的假设现在还成立吗"
- 事件驱动提醒——"MCO 下周财报，你的假设 #2 关于营收增速，要不要提前关注"
- 组合视角——"你 5 只票 3 只押 AI 替代风险，集中度过高"

**用户拿到什么**：agent 不只是"记录 + 查"，而是主动帮你思考。从"你定的条件 X 今天被事件击中了"升级到"你的投资逻辑整体有没有问题"。

**这是质变**——从工具变成助手。工具等你问，助手主动说。

**判断标准**：agent 主动帮你思考组合

---

### Stage 5：主动投研（远期愿景）

**上线什么**：
- 机会发现——agent 知道你的投资风格，市场出现符合你风格的标的时主动提醒
- thesis 模板库——从你的历史 thesis 提炼模式，新录入时 agent 说"你上次关注类似公司时看重这 3 点，这次也看看？"
- 群体智慧——（如果做多用户）匿名聚合"同类投资者关注什么"，给你参考

**用户拿到什么**：agent 不只帮你管已有的，还帮你发现新的。从"管好你的票"到"帮你成为更好的投资者"。

**判断标准**：agent 帮你发现新机会

---

## Stage 2 技术准备（✅ 已完成）

以下 3 项在 Stage 2 启动前已完成：

### 1. 数据源抽象层（✅ 已完成）

`BaseFetcher` + `FetcherRegistry`（`fetchers/base.py`）— 新数据源 subclass + register 即可接入。Stage 2 已接入 YahooPriceFetcher。

### 2. 模型配置参数化（✅ 已完成）

`build_thesis_guard_agent(model_name=)` — 按会话选模型，runtime 可选。

### 3. 通知接口抽象（✅ 已完成）

`Notifier` + `NotifierRegistry` + `EmailNotifier`（`notifiers/base.py`）— 新通知渠道 subclass + register。邮件已实现。

---

## 有意识的取舍（不用改）

| 选择 | 理由 |
|---|---|
| SQLite 单库 | localhost 5 人 beta 够用，上线再换 |
| 不做注册系统 | 当前阶段不需要 |
| Python 不换语言 | AI 可维护性最佳，guardrail 代码不用重写 |
| React 前端 | SSE streaming 已验过，够用 |
| OpenAI Agents SDK | 对话 agent 的正确选择 |

---

## Agent Loop 架构的长期价值

当前 extract_card 在 agent loop 里的 37s 开销是纯成本（单次盲抽）。但随着数据源接入，agent loop 会兑现多步价值：

- **近期**：extract 前先拉新闻 → 带调研抽取 → 假设质量更高
- **中期**：check 前先查多源 → 核对不只看 SEC
- **远期**：跨 thesis 推理 → agent 主动发现矛盾和集中度

Agent loop 是一个赌注——赌未来功能需要 LLM 编排多个工具，而不是单次抽取。如果产品停在"录入 + 查 SEC"，agent loop 是过度设计。如果产品长成"AI 投研助手"，agent loop 是对的地基。
