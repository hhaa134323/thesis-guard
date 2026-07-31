# Spec ｜ 通用版持仓 Thesis 监控（公开产品 v1）

> 来源：Notion 同名页面，写于 2026-06-10，2026-07-31 导出。
> 状态：**历史参考，参考后归档**。thesis-guard 项目在两点上有意偏离本 spec：
> ① 形态：用户自部署 → 托管 PWA；② 输出：四判决（HOLD/ADD/CUT）→ 只核对不判决。
> PRD 沿革章节需记录这次 pivot。

---

**目标用户（已定）**：公开产品 / 作品集。形态 = **用户自部署**——clone repo + 复制本 Notion 台账模板 + 填自己的 DB id 与 API key，自己跑。产品**不托管**任何用户数据。

## ① 一句话
让任意价值投资者填入自己的 watchlist + 可证伪的 break_condition，系统每个交易日盘前抓一手披露/新闻 → 比对 → 出 HOLD / ADD / CUT / PASS 判决并回写台账。

## ② 范围 v1
**In**
- 输入层：可复制的 Notion 台账模板（已建）
- 信息层：repo 抓 SEC filing（10-K / 10-Q / Form 4 / 13D / 20-F / 6-K）+ Google News，72h lookback
- 判决层：复查 skill 出四判决（HOLD / ADD / CUT / PASS）并回写

**Out（v1 明确不做）**
- 托管 SaaS、多用户登录、托管 UI（自部署即可）
- 实时 / 盘中盯盘
- break_condition 自动审稿（v2）
- 付费

## ③ 输入契约（每行）
- 必填：Ticker、Market、持仓周期、Thesis、**Thesis 破的条件**
- 选填：关注词、搜索名（填了才抓新闻）、加仓价、下次复盘日
- `Status=待补`（没写 thesis）→ 输出 PASS 提醒，不瞎判

## ④ 核心流程（沿用现有管线，不重写）
拉新披露/新闻（72h）→ 逐条比对 break_condition → 三态（破 / 逼近 / 未动）→ 四判决 → 回写「复盘备注 / Status / 最近更新」

## ⑤ 不变量（原则）
- 代码只做信息层，判断全交 AI 复查层
- 产品价值 100% 押在 break_condition 可证伪性
- 任何样例 / 默认数据不得含真实持仓

## ⑥ 配置 / 部署
- 环境变量：`NOTION_THESIS_DB_ID`、lookback 天数、市场范围、是否抓新闻、SEC/News 凭证
- 部署方式：本地脚本 或 定时（cron / GitHub Action）——默认形态待定

## ⑦ 公开产品额外要求（因选了"公开"）
- README + 使用说明（setup：复制模板 → 填 key → 跑）
- 数据边界声明：用户的持仓/thesis 数据只留在用户自己的 Notion + 运行环境，产品不集中存储
- 零真实持仓样例：已备 KO / V 示范行
- License（待定：MIT / 仅展示不开源 / …）

## ⑧ 验收（v1 算成功）
一个**不是你**的人，按 README 自部署，填自己的 watchlist + break_condition，当天能拿到有用且可滯源的复查判决，且零个人数据泄露。先用 KO / V 样例自测。

## ⑨ 已知风险 → v2
陌生人写不出可证伪 break_condition → 复查变噪音。**v2 做 break_condition 审稿/教练**，这才是真护城河。

## ⑩ v1 里程碑
1. ✅ 通用台账模板 + KO/V 示范（已建）
2. repo `NOTION_THESIS_DB_ID` 可配置 + 跑通 KO/V 验证
3. README / 使用说明
4. 数据边界声明 + License

## ✨ 还差这几个口（待拍板）
- License 选哪种
- 部署默认形态：本地手跑 / GitHub Action 定时
- 抓取默认值：lookback 天数、默认抓不抓新闻
