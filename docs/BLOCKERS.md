# BLOCKERS

> 维护本文件直到所有阻塞项清零。每项含：现象、影响、缓解、状态。

## B1 — 外网直连被 reset（GitHub / Notion / SEC.gov）

- **现象**：本机 shell 无代理配置（`git config http.proxy` / 环境变量均空）。直连测试：
  - `api.github.com` → 000 / Connection reset
  - `api.notion.com` → 000 / Connection reset（MCP `post-search` 报 `read ECONNRESET`）
  - `www.sec.gov` → 000（reset）
  - `www.baidu.com` → 200（国内网络正常）
  - 结论：典型 GFW 直连阻断，非瞬时抖动。
- **影响**：
  1. 无法 clone 私有库 `hhaa134323/pre-market-briefing` → 拿不到复用源码（sec_edgar / news / thesis / alerts / sinks）。
  2. 无法用 Notion MCP 只读拉台账/简报/Skill/spec 快照 → **eval 基准无法定格**，两层 eval 都跑不了。
  3. 无法做竞品 web 调研（`docs/competitor-teardown.md`）。
  4. 核对 Agent 的 SEC EDGAR 在线抓取同样受阻（产品核心数据源）。
- **缓解（待作者选一）**：
  - (a) 启用系统级 VPN（TUN 模式，无需 env proxy 即可全局生效），完成后告知；
  - (b) 提供代理地址，我在 shell 设 `HTTPS_PROXY`/`git config http.proxy` 后重试；
  - (c) 作者自行 `git clone https://github.com/hhaa134323/pre-market-briefing D:/AgentProjects/pre-market-briefing`，我直接从本地复用；
  - (d) 作者把 5 个 Notion 快照内容粘贴/导出到 `assets/`，我跳过 MCP 拉取。
- **状态**：未解决，阻塞第 1–2 周可执行部分。

## B2 — 0 号用户使用记录缺失

- **现象**：PRD「需求证据」需要 0 号用户数月日常使用记录作为基线，当前无数据。
- **影响**：PRD 需求证据章节为占位，无法支撑优先级排序的真实依据。
- **缓解**：作者提供记录（哪怕是原始便签/截图转述），我结构化进 PRD。
- **状态**：未解决，不阻塞动工，但阻塞 PRD 定稿。

## B3 — assets/ 快照缺失，与目标描述不符

- **现象**：目标文本假设「eval 基准已快照定格」，但 `assets/` 实际为空，5 个快照文件均不存在。
- **影响**：对话抽取 eval、条件判定 eval、录入 Agent 行为 spec 全部失去基线。
- **缓解**：B1 解除后立即从 Notion 只读拉取并定格（2026-07-31 为定格日）；或走 B1 (d)。
- **状态**：未解决。已与目标描述的差异记录在案。

## 依赖 B1 的待办（解除后按序执行）

1. clone `pre-market-briefing` 到 `D:/AgentProjects/pre-market-briefing`（或作者指定位置）。
2. 核对复用模块清单是否与目标一致（sec_edgar / news / thesis / alerts / sinks / config / README）。
3. Notion 只读拉取 5 个快照到 `assets/`，定格不再更新。
4. 用 `thesis.py` 的 schema 对齐 `docs/thesis-card-schema.md` v1 提案。
5. 基于 `skill_thesis_review_v4.md` 起草核对 Agent 提示词。
6. 基于 `onboarding_dryrun_0731.md` 起草 `docs/entry-agent-spec.md`。
7. 跑双层 eval，出 `docs/eval-report.md`。
8. 竞品 web 调研，出 `docs/competitor-teardown.md`。
