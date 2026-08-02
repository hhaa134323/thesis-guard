# 📊 Pre-Market Briefing · 开盘前简报 — schema + 行元数据

> 来源：Notion 数据库「📊 Pre-Market Briefing · 开盘前简报」，2026-08-01 只读拉取定格（notion-fetch 数据库 schema + notion-query-database-view「全部简报」视图行元数据）。
> 父页面：FinAgent · 港美股个人量化 Agent 执行平台。
> 本仓库用途：每日简报机制参考 + 条件判定 eval（W2）的逐日上下文索引。
> ⚠️ **单日正文（每日简报的完整 body）留在 Notion 活库**，需要时按 Briefing Date 检索单日页面再拉——本文件只存 schema + 行元数据索引，不抄正文。

## Schema（属性定义）

| 属性 | 类型 | 说明 |
|---|---|---|
| Briefing | title | 格式：YYYY-MM-DD 周X · Market，例如 2026-05-27 周三 · US |
| Briefing Date | date | 简报对应的交易日 |
| Market | select: US / HK / CN | 市场 |
| Status | select: 待发送 / 已发送 / 已查看 / 跳过 | 发送状态 |
| Alert Count | number | 当日警报总数 |
| Critical Alerts | multi_select | 命中的红线警报，决定是否要 caca 立刻看。取值：`thesis_invalidated` / `stop_loss_breach` / `position_concentration` / `over_trading` / `macro_event_today` / `earnings_today` / `vix_spike` |
| Action Suggested | checkbox | 今日是否有具体操作建议（false = 建议空仓观察） |
| Holdings Health | text | 一句话摘要：浮盈/亏 · 几个红线 · 几个浮盈未保护 · 几个重亏 |
| Generated At | date | 简报生成时间（ISO-8601） |
| Source Version | text | 脚本版本号，便于回溯哪一版生成的 |

## 视图（Views）

- **全部简报** — 按 Briefing Date DESC，全量。
- **US 简报** — Market=US，按 Briefing Date DESC。
- **按市场分组**（board）— 按 Market 分组看板。
- **需要关注（有警报）** — Alert Count > 0，按 Briefing Date DESC。

## 行元数据（72 条：71 条有效简报 + 1 条空 orphan 行）

> 按 Briefing Date DESC、Generated At DESC 排列（与「全部简报」视图一致）。Critical Alerts 列「—」表示该字段在原库为空（早期简报未填）。Act = Action Suggested（YES=建议操作 / NO=空仓观察）。

| Briefing | Generated At | Status | Alerts | Critical Alerts | Act | Holdings Health | SrcVer |
|---|---|---|---|---|---|---|---|
| 2026-07-31 周五 · US | 2026-07-31T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +16.8% · 1 重亏 | d6c7066 |
| 2026-07-30 周四 · US | 2026-07-30T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +16.8% · 1 重亏 | d6c7066 |
| 2026-07-29 周三 · US | 2026-07-29T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +17.7% · 1 重亏 | 925db10 |
| 2026-07-28 周二 · US | 2026-07-28T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.2% · 1 重亏 | 0d786fa |
| 2026-07-27 周一 · US | 2026-07-27T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.2% · 1 重亏 | 0d786fa |
| 2026-07-26 周日 · US | 2026-07-26T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +10.7% · 2 重亏 | e072359 |
| 2026-07-25 周六 · US | 2026-07-25T14:47 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +10.7% · 2 重亏 | e072359 |
| 2026-07-24 周五 · US | 2026-07-24T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +9.0% · 2 重亏 | aaa051a |
| 2026-07-23 周四 · US | 2026-07-23T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +9.4% · 1 重亏 | 3c0a3fa |
| 2026-07-22 周三 · US | 2026-07-22T12:30 | 待发送 | 3 | earnings_today, position_concentration | YES | 持仓 13 只 · 浮盈 +10.3% · 1 红线 · 1 重亏 | 81e6eca |
| 2026-07-21 周二 · US | 2026-07-21T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.2% · 1 重亏 | b241c55 |
| 2026-07-20 周一 · US | 2026-07-20T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +12.8% · 1 重亏 | 2f9775f |
| 2026-07-19 周日 · US | 2026-07-19T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +13.5% · 1 重亏 | 179f080 |
| 2026-07-18 周六 · US | 2026-07-18T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +13.5% · 1 重亏 | 179f080 |
| 2026-07-17 周五 · US | 2026-07-17T12:40 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +13.5% · 1 重亏 | 179f080 |
| 2026-07-16 周四 · US | 2026-07-16T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +12.0% · 1 重亏 | ee4c3fd |
| 2026-07-15 周三 · US | 2026-07-15T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +12.1% · 1 重亏 | b4aff3f |
| 2026-07-14 周二 · US | 2026-07-14T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +13.6% · 1 重亏 | c087534 |
| 2026-07-13 周一 · US | 2026-07-13T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +10.8% · 1 重亏 | 217ac05 |
| 2026-07-12 周日 · US | 2026-07-12T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +9.8% · 1 重亏 | e417714 |
| 2026-07-11 周六 · US | 2026-07-11T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +9.8% · 1 重亏 | e417714 |
| 2026-07-10 周五 · US | 2026-07-10T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +9.8% · 1 重亏 | e417714 |
| 2026-07-08 周三 · US | 2026-07-08T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.6% · 1 重亏 | 6d7693e |
| 2026-07-07 周二 · US | 2026-07-07T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.6% · 1 重亏 | 6d7693e |
| 2026-07-06 周一 · US | 2026-07-06T12:31 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.6% · 1 重亏 | 6d7693e |
| 2026-07-05 周日 · US | 2026-07-05T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.6% · 1 重亏 | 6d7693e |
| 2026-07-04 周六 · US | 2026-07-04T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.6% · 1 重亏 | 6d7693e |
| 2026-07-03 周五 · US | 2026-07-03T12:40 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +11.6% · 1 重亏 | 6d7693e |
| 2026-07-02 周四 · US | 2026-07-02T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +10.1% · 1 重亏 | ab43dea |
| 2026-07-01 周三 · US | 2026-07-01T12:30 | 待发送 | 4 | earnings_today, position_concentration | YES | 持仓 13 只 · 浮盈 +5.5% · 1 红线 · 1 重亏 | 02f08f9 |
| 2026-06-30 周二 · US | 2026-06-30T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +7.7% · 1 重亏 | 24900f2 |
| 2026-06-29 周一 · US | 2026-06-29T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 13 只 · 浮盈 +6.0% · 1 重亏 | c59fa5d |
| 2026-06-28 周日 · US | 2026-06-28T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +0.5% · 1 重亏 | 3d74bd7 |
| 2026-06-27 周六 · US | 2026-06-27T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +0.5% · 1 重亏 | 3d74bd7 |
| 2026-06-26 周五 · US | 2026-06-26T12:37 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +0.5% · 1 重亏 | 3d74bd7 |
| 2026-06-25 周四 · US | 2026-06-25T12:30 | 待发送 | 4 | position_concentration | NO | 持仓 13 只 · 浮盈 +2.5% · 2 重亏 | 961a5d1 |
| 2026-06-24 周三 · US | 2026-06-24T12:30 | 待发送 | 4 | position_concentration | NO | 持仓 13 只 · 浮盈 +2.5% · 2 重亏 | 961a5d1 |
| 2026-06-23 周二 · US | 2026-06-23T12:30 | 待发送 | 4 | position_concentration | NO | 持仓 13 只 · 浮盈 +2.5% · 2 重亏 | 961a5d1 |
| 2026-06-22 周一 · US | 2026-06-22T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +3.5% · 1 重亏 | 1fb89a2 |
| 2026-06-21 周日 · US | 2026-06-21T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +5.2% · 1 重亏 | a78d919 |
| 2026-06-20 周六 · US | 2026-06-20T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +5.2% · 1 重亏 | a78d919 |
| 2026-06-19 周五 · US | 2026-06-19T12:30 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +5.2% · 1 重亏 | a78d919 |
| 2026-06-18 周四 · US | 2026-06-18T14:16 | 待发送 | 3 | position_concentration | NO | 持仓 13 只 · 浮盈 +5.2% · 1 重亏 | a78d919 |
| 2026-06-17 周三 · US | 2026-06-17T12:30 | 待发送 | 1 | position_concentration | NO | 持仓 12 只 · 浮盈 +7.7% | 7a99624 |
| 2026-06-16 周二 · US | 2026-06-16T12:30 | 待发送 | 2 | position_concentration | NO | 持仓 12 只 · 浮盈 +7.4% | cca83d1 |
| 2026-06-15 周一 · US | 2026-06-15T12:30 | 待发送 | 2 | position_concentration | YES | 持仓 12 只 · 浮盈 +7.8% · 2 红线 | 8955fd8 |
| 2026-06-14 周日 · US | 2026-06-14T12:30 | 待发送 | 2 | position_concentration | YES | 持仓 12 只 · 浮盈 +6.7% · 2 红线 | c7a5b5d |
| 2026-06-13 周六 · US | 2026-06-13T12:30 | 待发送 | 2 | position_concentration | YES | 持仓 12 只 · 浮盈 +6.7% · 2 红线 | c7a5b5d |
| 2026-06-12 周五 · US | 2026-06-12T12:30 | 待发送 | 2 | position_concentration | YES | 持仓 12 只 · 浮盈 +6.7% · 2 红线 | c7a5b5d |
| 2026-06-11 周四 · US | 2026-06-11T12:30 | 待发送 | 2 | position_concentration | YES | 持仓 12 只 · 浮盈 +7.9% · 2 红线 | ad1a9df |
| 2026-06-10 周三 · US | 2026-06-10T12:30 | 待发送 | 3 | position_concentration | YES | 持仓 12 只 · 浮盈 +7.2% · 3 红线 | 0401cb5 |
| 2026-06-09 周二 · US | 2026-06-09T12:30 | 待发送 | 2 | position_concentration | YES | 持仓 11 只 · 浮盈 +8.9% · 2 红线 | 1861edd |
| 2026-06-08 周一 · US | 2026-06-08T12:30 | 待发送 | 3 | position_concentration | YES | 持仓 11 只 · 浮盈 +19.3% · 3 红线 | d9dc502 |
| 2026-06-07 周日 · US | 2026-06-07T12:30 | 待发送 | 4 | position_concentration | YES | 持仓 10 只 · 浮盈 +20.1% · 4 红线 | dbd94d3 |
| 2026-06-06 周六 · US | 2026-06-06T12:30 | 待发送 | 4 | position_concentration | YES | 持仓 10 只 · 浮盈 +20.1% · 4 红线 | dbd94d3 |
| 2026-06-05 周五 · US | 2026-06-05T12:30 | 待发送 | 3 | position_concentration | YES | 持仓 10 只 · 浮盈 +20.1% · 3 红线 | dbd94d3 |
| 2026-06-04 周四 · US | 2026-06-04T13:20 | 待发送 | 4 | position_concentration, thesis_invalidated | YES | 持仓 11 只 · 浮盈 +6.6% · 3 红线 · 1 重亏 | 39addd7 |
| 2026-06-03 周三 · US | 2026-06-03T12:30 | 待发送 | 4 | position_concentration, thesis_invalidated | YES | 持仓 11 只 · 浮盈 +7.8% · 3 红线 · 1 重亏 | 34ed7e9 |
| 2026-06-02 周二 · US | 2026-06-02T13:46 | 待发送 | 3 | position_concentration, thesis_invalidated | YES | 持仓 11 只 · 浮盈 +9.8% · 2 红线 · 1 重亏 | db10d49 |
| 2026-06-01 周一 · US | 2026-06-01T12:30 | 待发送 | 4 | position_concentration, thesis_invalidated | YES | 持仓 11 只 · 浮盈 +8.2% · 3 红线 · 1 重亏 | 56297c0 |
| 2026-05-31 周日 · US | 2026-05-31T12:30 | 待发送 | 4 | position_concentration, thesis_invalidated | YES | 持仓 10 只 · 浮盈 +6.6% · 3 红线 · 1 重亏 | f687f63 |
| 2026-05-30 周六 · US（12:30 版） | 2026-05-30T12:30 | 待发送 | 4 | position_concentration, thesis_invalidated | YES | 持仓 10 只 · 浮盈 +6.6% · 3 红线 · 1 重亏 | f687f63 |
| 2026-05-30 周六 · US（08:39 早版） | 2026-05-30T08:39 | 待发送 | 3 | thesis_invalidated | YES | 持仓 10 只 · 浮盈 +6.6% · 1 红线 · 1 浮盈未保护 · 1 重亏 | d9b9263 |
| 2026-05-29 周五 · US | 2026-05-29T12:30 | 待发送 | 2 | — | NO | 持仓 10 只 · 浮盈 +6.6% · 3 浮盈未保护 · 1 重亏 | e99ab24 |
| 2026-05-28 周四 · US | 2026-05-28T12:30 | 待发送 | 2 | — | NO | 持仓 10 只 · 浮盈 +4.0% · 2 浮盈未保护 · 1 重亏 | 85de2e5 |
| 2026-05-27 周三 · US（12:30 版） | 2026-05-27T12:30 | 待发送 | 2 | — | NO | 持仓 28 只 · 浮盈 +1.4% · 4 浮盈未保护 · 1 重亏 | c6858d6 |
| 2026-05-27 周三 · US（11:43 版） | 2026-05-27T11:43 | 待发送 | 2 | — | NO | 持仓 28 只 · 浮盈 +1.9% · 4 浮盈未保护 · 1 重亏 | 4bc37bb |
| 2026-05-27 周三 · US（05:04 版） | 2026-05-27T05:04 | 待发送 | 2 | — | NO | 持仓 28 只 · 浮盈 +1.9% · 4 浮盈未保护 · 1 重亏 | b54396d |
| 2026-05-27 周三 · US（03:49 版） | 2026-05-27T03:49 | 待发送 | 4 | — | NO | 持仓 28 只 · 浮盈 +1.9% · 4 浮盈未保护 | 1dae18b |
| 2026-05-27 周三 · US（03:11 版） | 2026-05-27T03:11 | 待发送 | 4 | — | NO | 持仓 28 只 · 浮盈 +1.9% · 4 浮盈未保护 | 8882528 |
| 2026-05-26 周二 · US | 2026-05-26T15:42 | 待发送 | 5 | — | NO | 持仓 28 只 · 浮盈 +2.0% · 5 浮盈未保护 | ab9d9bf |
| （空 orphan 行） | — | — | — | — | — | （空） | （空） |

## 元数据观察（供 eval 与机制参考，非正文摘录）

- **持仓数 28 → 13 的跳变**：5/26–5/27 简报显示持仓 28 只，5/28 起降到 10–13 只并稳定至今。对应台账里 5/27 SPGI 砍仓、GDXU/DPZ 清仓的集中清理期——caca 把组合从 28 只砍到核心 ~13 只。**条件判定 eval 若取 5/27 前的复盘备注，需注意彼时持仓结构与现在不同。**
- **`position_concentration` 几乎每日命中**：caca 长期有单一持仓超集中度阈值（Skill v4 标注 FDS 现 41.5% 为硬档顶格高信念仓，非破红线；代码层 position_concentration 已降为 info）。这条警报是常态噪音，eval 时不应计为 thesis 事件。
- **`thesis_invalidated` 窗口 5/30–6/4**：连续 6 天命中，之后消失。对应某持仓 thesis 被判破后的清仓收尾期（台账 SPGI 5/27 砍仓决定、GDXU 6/6 清仓）。这是条件判定 eval 的高价值窗口——有人工「破」标注可对。
- **`earnings_today` + Action Suggested=YES**：出现在 7/1 与 7/22，是某持仓财报日（季频 thesis 测试时刻）。
- **`2026-05-30` 有两条简报**（08:39 早版 + 12:30 重生成版）：早版 Critical Alerts 只有 thesis_invalidated、Health 含「1 浮盈未保护」；12:30 版补上 position_concentration。同日多版本是 cron 重跑，eval 取最新 Generated At。
- **空 orphan 行**：库尾有一条 Briefing/Health 全空的行（url `...3a025feea790808da731f0609d50f4bc`），疑为脚本残留，eval 时跳过。
- **早期简报（5/26–5/29）无 Critical Alerts 字段**：Critical Alerts 列原库为空，非「无警报」——是当时字段尚未启用。Health 用「N 浮盈未保护」表述，与后期「N 红线」口径不同。
