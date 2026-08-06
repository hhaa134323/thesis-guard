# PRD Stage 2 扩展（2026-08-05）

> 本文件是 PRD v0.4 的 Stage 2 扩展附录。PRD §1-§14 的核心原则不变，本文件记录 Stage 2 的 scope 变化。

## 解除的 v1 约束

| PRD 原文 | Stage 2 状态 | 说明 |
|---------|-------------|------|
| §6: v1 不含价格类警报 | ✅ 已解除 | YahooPriceFetcher + price_monitor + 安全边际提醒已实现 |
| §9: 数据源仅限 SEC EDGAR | ✅ 已扩展 | 加 Yahoo Finance 价格数据；RSS 新闻留 Stage 3 |
| §9: v1 不含价格类警报 | ✅ 已解除 | 同上 |
| 无自动化调度 | ✅ 已解除 | APScheduler 每日自动检查（scheduler.py） |
| 无通知推送 | ✅ 已解除 | Alert + Digest + S4 收尾邮件通知（notification.py） |

## Stage 2 新增功能（6 项）

1. **YahooPriceFetcher**（`fetchers/yahoo_price.py`）— Yahoo Finance 免费行情 API，价格数据源
2. **安全边际监控**（`price_monitor.py`）— 价格跌入安全边际 → alert（到价 hit + 接近 approaching 两档）
3. **自动化调度**（`scheduler.py`）— APScheduler 每日定时跑检查
4. **通知编排**（`notification.py`）— Alert（破局条件 triggered 命中单独发 + S4 收尾）+ Digest（每日汇总，含价格提醒段）
5. **watch 记忆** — check_agent 读上次结果输出 change 六态（new/worsened/improved/unchanged/resolved/escalated）
6. **SEC filing history tool** — agent 可查历史 filing 列表，不只看最近一份

## 不变的约束

- §4-A 覆盖率显式呈现
- §4-B 日常查看 ≤ 3 分钟
- §4-C 形态锚定简报
- §6 不给买卖建议（红线）
- §8 R1-R9 红线
- 判断权归用户

## 不变量

**用户根本需求：告诉我该关注什么**

一切功能围绕它生长。详见 Notion「Thesis Guard · Stage 2 业务流程设计」。

## 实现状态

- 代码：`refactor/agent-loop` 分支，origin 顶 `741ceb1`
- 测试：202 pytest 全绿
- 业务流程设计文档：Notion「Thesis Guard · Stage 2 业务流程设计」
- 项目看板：Notion「Thesis Guard · Stage 2 监控闭环项目看板」

## 价格提醒设计调整（2026-08-06，PM 决策 08-05 18:28 看板）

价格类提醒不再单独发邮件，并入 digest；新增「接近」档。

- **价格提醒不单发**：`scheduler.run_daily_check` 中 price alert 不再调 `send_alert`（删 3a 循环）；改由 `notification._render_digest` 的「价格提醒」段统一渲染（到价 + 接近）。**破局条件 triggered 的 alert 逻辑不变**（仍 3b 单独发 `send_alert` + `request_s4_action`）。
- **到价档（hit）**：`current_price <= threshold` → `level="hit"`、`triggered=True`；safety_margin 与 stop_loss（trade 仓）都产。
- **接近档（approaching）**：`threshold < current_price <= threshold * 1.1` → `level="approaching"`、`triggered=False`；**仅 safety_margin 方向**（非 trade 仓），stop_loss（trade）v1 不做接近档。
- **alert 结构加 `level` 字段**（hit / approaching）承载区分；`skip` 过滤逻辑（`8c65773`：`[pa for pa in pas if not pa.get("skipped")]`）不得回归。
- **digest 汇总行 `M 触发`**：只计破局 triggered 卡 + 到价（hit）price alert；接近档不计入「触发」（未真正到价），仅在「价格提醒」段呈现。
