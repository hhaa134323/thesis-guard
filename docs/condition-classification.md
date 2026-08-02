# 破局条件分类表（v0.3，**待作者人工确认后固化**）

> 由 `condition_classify.classify_condition`（multi-label）+ `_split_conditions`（剥离结构行+condition_tier+续行合并）跑。
> **不截断**（输出全文）——作者逐条确认对象必须是完整原文。
> 确认后：v1 可自动（`xbrl_structured` / `press_release_text`）→ 不进 manual_items；其余 → manual_items。
> 分类错 → 改 `src/thesis_watch/condition_classify.py` 规则后重跑本表。

## NVDA
> **统计**: 55 条件, v1 可自动 20/55 = 36%
- **[—]** 生态被绕过：CUDA 锁定被打破——主流大厂自研芯片（TPU / Trainium / MTIA）或开放软件栈（ROCm / Triton 等）普及，使训练/推理大规模迁出 NVIDIA，数据中心营收份额连续多季结构性流失（区别于单季订单波动）
  - 分类: market_share, xbrl_structured | v1 可自动: False | 缺口: v1 无市占率/份额数据源（data-sources ①）

- **[—]** AI capex 周期结构性见顶：超大规模厂商资本开支连续多季下修、且推理需求未接棒，营收与毛利同步回落（区别于短期去库存）
  - 分类: xbrl_structured | v1 可自动: True

- **[—]** 定价权丧失：数据中心 GPU 毛利率（历史约 70%+）持续下移且回不来
  - 分类: xbrl_structured | v1 可自动: True

- **[—]** 地缘 / 出口管制实质性切断关键市场且无法以新品替代。注：单纯的短期股价回撤、单季增速放缓不算破，只是周期/情绪
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** 某季 hyperscaler capex 指引环比转负
  - 分类: xbrl_structured | v1 可自动: True

- **[lagging]** 自研 ASIC 拿下某大客户主力份额
  - 分类: market_share | v1 可自动: False | 缺口: v1 无市占率/份额数据源（data-sources ①）

- **[lagging]** GAAP 毛利率跌破 70%
  - 分类: xbrl_structured | v1 可自动: True

- **[lagging]** 循环融资实锤（NVDA 投资的 AI 公司回头买卡撑需求）。其一触发 → thesis 动摇，重走核数
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## VEEV
- **[—]** 丢失标志性大型药企客户；垂直护城河被通用平台（如 Salesforce 生态）侵蚀；或核心 CRM 迁移项目失败
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## MCO
- **[lagging]** MIS（评级）剔除发行量周期后的经常性 / 交易性收入连续 2 季 YoY 负增长
  - 分类: press_release_text, xbrl_structured | v1 可自动: True

- **[lagging]** Moody's 全球评级市占率较基准（约 40%）掉 ≥3pct 且连续 2 季不回
  - 分类: market_share | v1 可自动: False | 缺口: v1 无市占率/份额数据源（data-sources ①）

- **[lagging]** 监管落地（非提案）：美 / 欧通过强制竞争性评级，或实质限制发行人付费模式的法案
  - 分类: regulatory_process | v1 可自动: False | 缺口: 监管立法进程 v1 不覆盖（data-sources ④）

- **[leading]** SEC / ESMA / EU 启动针对发行人付费模式或评级竞争的正式立法 / 规则草案（提案阶段即进观察项）
  - 分类: regulatory_process | v1 可自动: False | 缺口: 监管立法进程 v1 不覆盖（data-sources ④）

- **[leading]** MA（Moody's Analytics 订阅侧）ARR / 经常性收入增速掉到 <8%（订阅护城河领先信号）
  - 分类: xbrl_structured, qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** 一级市场发行量连续多月放缓（周期性，但极端时压 MIS 交易性收入）
  - 分类: press_release_text, xbrl_structured | v1 可自动: True

## GOOGL
- **[—]** 分发被绕过:对话式 AI 入口(ChatGPT 等)成为用户新的默认起点,绕开 Google 的 Search/Chrome/Android 分发,且 Gemini 嵌入留不住人——搜索 query 量/广告营收连续多季下滑且份额持续流失
  - 分类: market_share, xbrl_structured | v1 可自动: False | 缺口: v1 无市占率/份额数据源（data-sources ①）

- **[—]** 反垄断强拆分发资产:判决强制剥离默认搜索协议 / Chrome / Android,分发渠道本身被掐断
  - 分类: regulatory_process | v1 可自动: False | 缺口: 监管立法进程 v1 不覆盖（data-sources ④）

- **[—]** 推导前提反转:模型质量差异大到普通用户能明显感知,「足够好 + 默认」不再成立,且 Gemini 在能力上决定性落后于前沿——此时分发也救不回来
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## CGNX
- **[—]** 护城河被通用视觉大模型 + 通用摄像头商品化，专用机器视觉硬件/软件不再必要，营收与份额连续多季结构性下滑（区别于下游 capex 周期性波动）
  - 分类: market_share, xbrl_structured, qualitative | v1 可自动: False | 缺口: v1 无市占率/份额数据源（data-sources ①）; 主观定性，无可自动核对的数据

- **[—]** 高端份额被 Keyence 等持续蚕食，或大客户长期转向自研/低价竞品，市占率连续多季流失
  - 分类: non_us_listed, market_share | v1 可自动: False | 缺口: 非美上市主体不报 SEC（data-sources ②）; v1 无市占率/份额数据源（data-sources ①）

- **[—]** 结构性失去定价权，毛利率（历史约 70%+）持续下移且回不来
  - 分类: xbrl_structured | v1 可自动: True

- **[—]** 商业模式被颠覆，机器视觉从「卖硬件+软件」白菜化为纯软件/开源、Cognex 没卡住价值环节。注：单纯的下游 capex 周期下行（电子/汽车/物流走弱致营收波动）不算破，只是周期
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## NOW
- **[—]** 净留存率（NRR）连续多季下滱至显著低于历史水平；大客户（≥$1M ACV）增长失速；或平台被新一代 AI 原生工作流明显替代 [sic: 台账原文「下滱」疑为「下滑」]
  - 分类: press_release_text | v1 可自动: True

## NFLX
- **[—]** 订阅增长停滞同时内容成本失控（自由现金流再次转负）；提价导致 churn 明显抬升（定价权丧失）；或竞争把内容军备竞赛拖入长期亏损
  - 分类: press_release_text, xbrl_structured | v1 可自动: True

## CRM
- **[—]** 【量化版 · 基线按 2026-06-21 一手（FY27 Q1，press release 5/
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[—]** 每季复盘用最新一手刷新基线】
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** 硬滞后线（季报数字踩中 → 🔴 CUT；均需「连续 2 季」确认窗口）
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** 有机订阅增速失速—基线：FY27 指引订阅&支持收入 +约12% Y/Y（含约 3pct Informatica 并表 → 有机约 8–9%）。触发：扣除并表后有机 YoY 连续 2 季 ≤5%。取数：press release "subscription & support revenue" Y/Y(CC)
  - 分类: xbrl_structured | v1 可自动: True

- **[lagging]** cRPO（未来 12 个月已签约收入）失速—基线：近季 YoY 约11%（FY26 Q1 +12% / Q2 +11%）。触发：YoY(CC) 连续 2 季 ≤6%。取数："current remaining performance obligation" Y/Y CC
  - 分类: press_release_text, xbrl_structured | v1 可自动: True

- **[lagging]** 利润率叙事破裂—基线：FY27 指引 Non-GAAP 营业利润率 34.3%（已连续十季扩张）。触发：Non-GAAP 营业利润率连续 2 季同比收缩（任意幅度）。取数："non-GAAP operating margin" YoY
  - 分类: xbrl_structured | v1 可自动: True

- **[lagging]** 客户留存崩—基线：dollar attrition 历史约 8%（公司口径 low；⚠ 待下次 10-K 核实基线）。触发：年度 dollar attrition 升破 10%，或公司停披露该指标（= 红旗）。取数：10-K / 季报 supplemental attrition rate
  - 分类: press_release_text | v1 可自动: True

- **[lagging]** seat 计价被 agentic 替代且接不上—基线：Agentforce ARR $800M（+169% Y/Y，FY26 Q
  - 分类: press_release_text | v1 可自动: True

- **[lagging]** 触发：同时出现
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** net new ARR / 大客户订阅净新增连续 2 季负增长 且
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** Agentforce ARR YoY <50%。取数：季报 Agentforce ARR + net new ARR / RPO 拆分
  - 分类: press_release_text | v1 可自动: True

- **[leading]** 领先代理（→ 🔭 观察项，不直接 CUT）
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** 竞品抢旗舰：微软 Copilot+Dynamics / HubSpot / agent-native CRM 单季 ≥1 个公开披露的 Salesforce 现有旗舰 logo 流失
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** Agentforce 预警：公司下修 Agentforce 相关指引，或 ARR 增速单季环比腰斩。

注：阈值为 2026-06-21 设定，可调；attrition 基线待 10-K 核实
  - 分类: press_release_text | v1 可自动: True

## FIS
- **[—]** 核心银行处理市占率连续多季流失；被云原生新一代核心系统明显替代；或继续高杠杆收购毁灭价值（再现大额减值 / 分拆失败）
  - 分类: market_share | v1 可自动: False | 缺口: v1 无市占率/份额数据源（data-sources ①）

## FDS
- **[lagging]** ASV 有机增速连续 2 季 <4%，或任一季转负（FDS 常态约 5–6%，跌破 4% ＝结构性放缓坐实）
  - 分类: press_release_text | v1 可自动: True

- **[lagging]** ASV 年化续约率跌破 95%（长期 >95% 的黏性破了）
  - 分类: press_release_text | v1 可自动: True

- **[lagging]** 调整后营业利润率连续 2 季 <30%（价格战 / AI 投入吞噬利润）
  - 分类: xbrl_structured | v1 可自动: True

- **[lagging]** 订阅分发模式被结构性颠覆（数据免费化 / 平台脱媒）
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** AI 原生竞品（AlphaSense / Perplexity Finance / OpenAI 金融等）拿下买方旗舰客户的公开案例，或 Bloomberg BMC 重回强增长
  - 分类: private_company | v1 可自动: False | 缺口: 私人公司竞品无公开财报（data-sources ③）

- **[leading]** FDS 自己下修 ASV guidance 区间（公司先认放缓）
  - 分类: press_release_text | v1 可自动: True

- **[leading]** 买方裁员潮——终端席位是 FDS 计价单位，盯大行 / 资管 headcount
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## HSBC
- **[—]** 净息差长期收窄且无法转嫁；坏账拨备显著恶化（信贷成本跳升）；地缘 / 监管重创亚洲核心业务；或被迫长期削减股息
  - 分类: regulatory_process | v1 可自动: False | 缺口: 监管立法进程 v1 不覆盖（data-sources ④）

## BRK.B
- **[lagging]** 单笔 ≥10 亿美元商誉或资产减值（Abel 任内重大配置失误坐实）
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** 保险综合成本率（combined ratio）连续 2 年 >100%（承保持续亏损）
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** Abel 主导的重大资本配置满 2 年回报跑输同期短期国库券
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[lagging]** 净杠杆显著上升 / 大额举债收购，偏离历史稳健区间
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** Abel 主导大额收购公布后首年的整合信号——盯收购脚注的商誉测试 / ROIC
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** 现金长期堆积且无大额回购或收购（资本配置能力存疑的早期信号）
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

- **[leading]** 关键子公司（BNSF / BHE / 保险）管理层异动或承保纪律松动迹象
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## QQQ
- **[—]** 仅当「大盘长期向上」的底层逻辑被结构性颠覆时才动（指数成分长期盈利能力系统性恶化）；不因短期回撤清仓
  - 分类: qualitative | v1 可自动: False | 缺口: 主观定性，无可自动核对的数据

## SPGI
（台账确认为空——该标的无「Thesis 破的条件」字段）

## GDXU
（台账确认为空——该标的无「Thesis 破的条件」字段）

