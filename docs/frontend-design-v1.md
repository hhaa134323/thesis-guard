# 前端设计基线 v1（2026-08-02）

| 项 | 值 |
|----|----|
| 版本 | v1（2026-08-02 作者弹窗拍板） |
| 状态 | 施工依据；预期两轮以上目检迭代 |
| 基线来源 | 作者侧跑完设计流程后拍板 |

## 0. 已拍板决策

- **信息架构：形态 C** —— 对话主流（居中单栏，内容最大宽约 680px）+ 确认卡抽屉（右侧约 340px，草稿存在时滑入，入库或关闭时滑出）。
- **视觉方向**：浅色克制、蓝点缀。**不做深色、不做移动端适配**。
- **技术栈（修订）**：React + Vite + shadcn/ui；后端 FastAPI 不变，**接口契约不变**；构建产物为静态文件，由 FastAPI 托管，部署中性不变。**此前「单 HTML + 原生 JS、不引入构建链」的约束作废。**
  - 理由：作者弹窗拍板——组件库管皮肤（提速 + 一致性），交互结构以本基线为准不随库变；构建产物仍静态由 FastAPI 托管，部署中立不破。
- **分工铁律**：组件库管皮肤，交互结构以本基线为准——形态 C、对话与抽屉的分布铁律、拒判呈现、三阶段进度行、状态清单**均不随组件库改变**。
- **交互分布铁律**：对话承载语言与当次选择，抽屉承载累积的卡与最终确认动作；**任何单个动作不横跨两个容器**。

## 1. 施工验收点（逐条实现并自测）

1. **「无法确定」菜单**：从对话气泡文字墙改为对话内 option 卡（checkbox + 标题 + 对应假设小字），勾选实时同步抽屉字段。
2. **三阶段进度行**：已抽取（灰点）、正在生成候选（蓝点）、正在更新卡片（蓝点），抽取全程 5–45 秒可见。
3. **抽屉**：随草稿滑入、随入库滑出；新填入 / 新勾选字段软蓝高亮（`#E5F2FC` 底 + 「刚填入」标签）；全部字段可编辑。
4. **拒判降级**：对话内橙边卡（`#D5803B` 左边条 + `#FBEBDE` 底），文案三段式——为什么接不了 / 记到哪里（人工自查）/ 何时提醒（每月 1 号）。
5. **行话全称 + tooltip**：仓位上限档显示「软（柔性上限）」并附分档说明；估值锚锚型中文名；裁判日注明「下一个能证伪 thesis 的事件」。
6. **唯一主按钮**「确认入库」（`#2783DE` 实心）+ 已入库绿态（`#46A171` / `#E8F1EC` 标签）。
7. **视觉基调**：浅色克制；以 shadcn/ui 默认 tokens 为准，主色对齐 `#2783DE`；先边框后阴影，阴影仅抽屉。
8. **对话感呈现**（2026-08-02 补充，作者设计文档 §7.7）：AI 消息以**打字机效果逐字呈现**（客户端逐字渲染，本地模拟即可，SSE 亦可），营造流式对话感。**不动 LLM 单次结构化调用架构**——抽取仍是单次调用，仅呈现层做逐字。

## 2. 明确不做

不改 loop 逻辑、prompt、schema；不做深色主题；不做移动端；不做 dashboard；不出现任何买卖建议类 UI 文案（R1/R3 在渲染层守住）。

## 3. 接口契约（不变，`serve.py`）

- `POST /api/session` `{user_id?, ticker, reason}` → view
- `POST /api/session/{id}/turn` `{text?/picks?/edits?/request_menu?}` → view
- `POST /api/session/{id}/confirm` `{edits?}` → view
- view 形状：`{stage, assistant, card, menu, open_questions, ticker, error, metrics}`

- **`assistant` 字段来源**（2026-08-02 补充，话术生成层）：追问/拒判处由 `dialogue.py` LLM 生成（锐利、有解释力——说透为什么核不了/能改成什么样才核得了，过 `redline.guard`）；**复述确认段保模板逐字保真**（确认卡文字与入库一致）。前端只渲染返回文本（打字机逐字，验收点 8），不碰话术生成。
前端只换皮肤 + 交互结构，不碰这些端点与 view 形状。

## 4. 目录与构建（部署中立）

- 前端源码：`frontend/`（React + Vite + shadcn/ui + Tailwind），独立 `package.json`。
- 构建：`npm run build` → 产物输出到 `static/`（由 FastAPI `StaticFiles` 托管，与现有 `serve.py` 的 `STATIC_DIR` 一致）。
- 旧的单 HTML/JS（`static/index.html`、`app.js`、`style.css`）由构建产物覆盖；源码归档到 `frontend/`。
- 启动脚本 `start.bat` 不变（起 FastAPI + 自动开浏览器）；FastAPI 同时托管前端静态产物 + API。
- `node_modules/`、`dist/`、`.vite/` gitignore（已有）。

## 5. 完成后

- 停下等作者目检页面（预期两轮以上迭代，每轮目检后继续）。
- 通过后 changelog 记一条：§2.5 前端打磨完成，依据设计文档 v1，技术栈 React + Vite + shadcn/ui。

## 6. 2026-08-03 前端工单（F0–F4，v1 基线上增量）

F3（卡片字段补全）挂起——entry_anchor §5 结构 / holding_horizon / 被拒条目 / 已排除方向 / 公司全名·交易所 / 来源标注块 全要后端结构化数据，后端窗口在做，落地后单独下工单。前端不解析 assistant 正文（不可靠，与"事实类不走 LLM"矛盾）。

**改了什么**：
- **F0 主题**：`index.css` `:root` 从高饱和蓝 `#2783DE` → 中性偏冷钢蓝 `215 18% 38%`，softblue→冷灰，amber/success 降饱和。只改 CSS 变量，未碰组件。
- **F1 chat**：`components/ai/chat.tsx` 手写 `Message`/`Bubble`/`MessageScroller`/`SendButton`（Message/Bubble/MessageScroller 是 Vercel AI Elements 名、依赖 `ai`/`@ai-sdk/*`，拷来撞红线，按 shadcn 风格手写等价组件，不引 SDK）。用户气泡深底白字右对齐右下小圆角，系统白底 1px 边框左对齐左下小圆角+发送者标签；MessageScroller stick-to-bottom+ResizeObserver 防跳动；发送键输入框内右下 30×30 深色圆角方钮+lucide ArrowUp（Notion 式）。来源块（R5）挂起进 F3。
- **F2 逐字段点亮**：删 `ProgressRow`；`DrawerField` 加 `state` 三态 done（行首绿勾）/ in-progress（灰底+左 2px 竖条+spinner+skeleton）/ pending（opacity 0.35+「待生成」）；卡片头 `N / 8 字段`+76px 细条；`working`（fetch 中）→全字段 in-progress。
- **F4 空态**：左栏 opening 改空态（标题+说明+三步+三张可点例子卡填入输入框+输入框/SendButton+底部 2px 浅灰竖线+红线两行）；右栏 `drawerOpen=true` 常驻、card null 渲 8 个 pending 行+禁用「确认入库」。

**三点取舍理由**：
1. **保持双栏**：卡片是主角、对话是输入。双栏边说边看卡逐格点亮，进度与结果同屏，出错一眼定位卡哪格。单栏把卡折进对话流，进度感丢失。
2. **逐字段点亮 vs 折叠思考区**：折叠把"系统在想"藏起来，用户只看最终卡；逐字段让进度=结果本身（每格 done/in-progress/pending），覆盖透明（PRD §4-A）。折叠是过程黑盒，逐格是过程即产物。
3. **固定 rubric vs 模型自由评价**：自由评价（"好不好看"）不可复现、无门槛、模型自我恭维；固定 rubric（9 条 yes/no+no 指位）把验收口径前置写死，每轮可复跑、no 必指位、修完重跑到全绿——eval 串行+门槛预注册（eval-plan §6）在视觉层的落地。

**自检**：每项 `npm run build` 过；视觉自检 chromium `--headless --screenshot` 截 `http://127.0.0.1:8001`（http.server 托管 static/，不走 serve.py 免 import 并行改的 src/），qwen3-vl-plus 跑固定 rubric（`scripts/vision_check.py` 传 rubric 作 question）。F4 空态截图 rubric 8/9 yes（#1 两栏/竖线、#2 进度行已删、#3 N/8+条、#5 待生成、#6 发送键、#7 中性无高饱和蓝、#8 无溢出、#9 无大片空白 全 yes）；#4（in-progress 字段行：灰底+左竖条）no——空态无 fetch、字段 pending 非 in-progress，该态只在 fetch 进行时出现，静态空态截不到，代码已实现（`working`→全字段 in-progress），验它需 live session。

**changelog 不再由前端写**：改动摘要列文字给作者，由后端窗口统一写 `docs/changelog.md`。

## 7. 2026-08-03 F3 卡片字段补全（v0.0.15 view 形状落地）

后端 v0.0.15（4230bc4 本地、push 待 B1）给齐 F3 数据：`broken_conditions[].source_type`+`threshold`(mirror={metric,operator,value}/redline={amount_usd|roles|forms})、`open_questions[].text`(被拒候选原文)、`menu.coverage={total,excluded,reasons[],excluded_items[{mirror_text,reasons[]}]}`、`view.ticker_title`(公司全名)、`view.sources=[{form,date,url,note}]`(confirm-SEC-ask 命中时)。

**改了什么**（App.tsx）：
- 接口对齐 v0.0.15：Stage+ticker_clarify、Cond+source_type、Source/Coverage/OpenQ 接口、MenuT+coverage、View+ticker_title+sources+open_questions→OpenQ[]；state 加 tickerTitle+sources；applyView 设之。
- #3 破局条件：每条 M/R 徽标 + 阈值（redline amount_usd→`≥ N 美元`；mirror→`metric operator value`；事件型 redline 无数值阈值只显来源）+ 数据来源（source_type=sec_filing_field→"SEC filing"）。
- #4 关键假设下：`open_questions` filter field==key_assumptions →「N 条候选未通过：原文→理由」；assumptions populated 算上 rejected（有被拒=已处理=done，免 pending 盖掉被拒块）。
- #5 菜单区：`menu.coverage` →「已排除 N 个方向（共 M）：· mirror_text — reasons」。
- #6 标的行：`ticker_title` 公司全名 + ✓一手核对（input 独占一行、title/badge 另起一行，免 w-full input 挤掉 title）。
- 来源块 R5：`view.sources` 非空时 chat 区渲来源块（分隔线+绿点+form·date+可点 URL）。
- #1 entry_anchor / #2 holding_horizon：base（bf19d0f）已渲染，不动。

**自检**：build 过；live session（NVDA→extracted）+ qwen3-vl-plus：#3/#5/#6 live 验过 ✅；#4（被拒条目）code 正确但 LLM 非确定、本轮没产被拒→未 live 验到被拒数据；#7（sources）code 正确但仅 confirm-SEC-ask 命中时有、本流程不触发→未 live 验。pre-existing：橙色提示框长文本偶发溢出（数据依赖），F3 没碰这俩组件，记下不顺手改。

**开口**：A-filter（menu A 不过滤只过滤 B→4A+1B 不对称）作者定、前端按现状（A 全展示+coverage 说清排除数）；交易所 SEC 数据无→#6 不显（不硬造）；后端 ticker_resolver 在 flux（未提交 src/ticker_resolver.py：NVDA→ONDS、HSBC→clarify），作者 mid-fix，前端不受影响按 view 渲。
