# assets/ · 外部资产（Notion 导出 + 演练记录）

> 本目录文件由 Notion AI 助手于 2026-07-31 从 caca 的 Notion 工作区导出并提交。
> Claude Code 读这里的文件即可，不需要、也不能访问 Notion。

## ⚠️ 隐私警告（重要）

- `notion/thesis_db_part*.md` 含**真实持仓**的 thesis、加仓价/安全边际、复盘判断记录
- `notion/briefing_db_overview.md` 含真实组合规模与每日浮盈
- 本仓库当前为 private。**翻 public 之前必须先移除或脱敏本目录并清理 git history**
  （或本仓库永久 private，另建干净的展示仓库）

## 文件清单与用途

| 文件 | 来源 | 在 /goal 中的用途 |
|---|---|---|
| `notion/thesis_db_part1.md` ~ `part4.md` | Notion 数据库「🧭 持仓 Thesis · 价值投资台账」全量 15 行（2026-07-31 导出） | thesis 卡 schema 基线；对话抽取 eval（目标 ≥85%）与条件判定 eval（目标 ≥80%）的人工基准集。「复盘备注」列是两个月的人工判断记录，是 eval 金矿 |
| `notion/briefing_db_overview.md` | Notion 数据库「📊 Pre-Market Briefing · 开盘前简报」schema + 近 45 行元数据 | 每日简报机制参考；判定 eval 的逐日上下文索引。单日正文留在 Notion，需要时找 caca 再拉 |
| `notion/skill_thesis_review_v4.md` | Notion 页面「Skill · 每日持仓 thesis 复查（记忆闭环版 v4）」全文 | 核对 Agent 系统提示词的起点：三态、噪音过滤表、触发式深挖、轮值深挖、硬红线、回写规则 |
| `notion/spec_public_v1_20260610.md` | Notion 页面「Spec ｜ 通用版持仓 Thesis 监控（公开产品 v1）」（2026-06-10） | 历史参考。本项目在两点上有意偏离：自部署 → 托管 PWA；四判决（HOLD/ADD/CUT）→ 只核对不判决。PRD 需记录这次 pivot |
| `onboarding_dryrun_0731.md` | 2026-07-31 录入演练 transcript（6 轮对话，AI 演产品、caca 演用户） | 录入 Agent 的行为 spec + 首批 eval 用例 |

## 相关代码资产（不在本目录）

复用自 `hhaa134323/pre-market-briefing`（私有 repo，clone 到本地）：
- `src/fetchers/sec_edgar.py` — SEC EDGAR 多表单抓取
- `src/fetchers/news.py` — Yahoo 按 ticker 头条 RSS
- `src/fetchers/thesis.py` — 读 Notion 台账的只读实现（schema 参考）
- `src/sinks/` — Gmail SMTP 发送
- `README.md` — 「AI 边界（硬规则）」表，即本项目产品红线
- 不复用：`tools/snapshot_pusher.py`、`src/fetchers/holdings.py`（OpenD 持仓链路，本产品改为用户手录）
