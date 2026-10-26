# 🐎 老五（atomcode）· 持仓日报交付质量独立审查

> 审查视角：数据准确性 + 用户（老大）视角
> 审查对象：`dashboards/warroom.html`（作战台）+ `dashboards/warroom_v2.html` + `dashboards/warroom_safe.html` + `dashboards/holding.html` / `holding_vchart.html` + 飞书边框盒日报（`scripts/daily_stock_report_v2.py` 输出）
> 生成时间基准：2026-09-02
> 只读审查，未修改任何核心文件；本次仅新增本文件。

---

## 一、总体评分

| 维度 | 权重 | 得分 | 加权 |
|------|------|------|------|
| 数据准确性（TDX/缓存口径一致） | 25 | 52 | 13.0 |
| VChart / 可视化交付完整度 | 25 | 58 | 14.5 |
| 飞书边框盒日报排版 | 20 | 68 | 13.6 |
| 止损/止盈与 `risk_rules.py` 一致性 | 15 | 45 | 6.75 |
| 用户视角（决策支持） | 15 | 48 | 7.2 |
| **总分** | **100** | | **55.05 ≈ 55** |

**一句话结论：数据能交付，但不准确；风控展示与 `risk_rules.py` 契约存在口径背离；用户拿到的是一份"数据清单"而非"可决策日报"。**

---

## 二、P0 阻断性问题

### P0-1 🔴 `warroom_safe.html` 存在 HTML/JS 注入 bug，文件不可用

**位置**：`dashboards/warroom_safe.html` 第 52–56 行。

**证据**（原文摘取）：

```
52| const V=window.VChart;
53| var <div class='hold-card'>...中牧股份...</div>_DATA = {...};
54| for (var k in <div class='hold-card'>...中牧股份...</div>_DATA) {
55|   var d = <div class='hold-card'>...中牧股份...</div>_DATA[k];
```

**诊断**：模板字符串里把"持仓卡 HTML 片段"和"JS 变量名"做了错误的替换，`%hold_js%` 与 `%holdings%` 占位符被同一份 HTML 片段污染，把整段 `<div class='hold-card'>...</div>` 直接嵌进了 `var XXXX = {...}` 的位置。该文件浏览器打开时**立即报 SyntaxError，所有图不渲染**，是一条死链。

**影响**：如果这份 HTML 被当作"安全可发版本"推送给老大，用户看到的是一张空白页面，日报交付直接失败。

**建议**：
- 立刻从发布路径移除 `warroom_safe.html` 或打上"废弃"标签，别让自动化误发；
- 根因在 `build_dashboard.py` 模板的占位符名冲突，须修正后重新生成；
- 交付前对输出 HTML 加一条 `python -c "import html.parser"` + 关键字段存在性的 smoke test。

---

### P0-2 🔴 VChart / ECharts 交付口径混乱，作战台并非"VChart"

**位置**：`dashboards/warroom.html` vs `dashboards/warroom_v2.html` vs `dashboards/warroom_safe.html` vs `dashboards/holding_vchart.html`。

**证据对比**：

| 文件 | 库 | 版本 | 可用性 |
|------|----|------|--------|
| `warroom.html` | ECharts | 5.4.3 | ✅ 可渲染 |
| `warroom_v2.html` | ECharts + VChart CSS | 5.4.3 | ✅ 可渲染 |
| `warroom_safe.html` | VChart + ECharts（混装） | 2.1.6 + 混 | ❌ JS 报错 |
| `holding_vchart.html` | VChart | 2.1.6 | ✅ 可渲染 |
| `holding.html` | VChart | 2.1.6 | ⚠️ JS 中有 `initChart(chart-0, ...)`，`chart-0` 是无引号的裸标识符，浏览器会报 SyntaxError |

**诊断**：
- 文件名 `warroom`/`holding_vchart` 承诺的是 VChart，实际主力在跑 ECharts；两个 CDN 都在同页时还会因为 `VChart` 未定义而静默报错（`warroom_safe.html` 里 `const V=window.VChart` 拿到 undefined）；
- `holding.html` 第 99/100 行的 `initChart(chart-0, ...)` 是**同样致命的 JS 语法错误**（`chart-0` 被解释为 `chart 减 0`），这个文件实际也是不可渲染的。

**影响**：用户视角里"看作战台"这一动作，**当前有两个文件是死的、一个口径与文件名不符**。交付路径不清晰，老大点开的是哪一份？

**建议**：
- 明确"单一作战台"权威文件路径（建议 `dashboards/warroom_v2.html`），其他历史版本归档到 `dashboards/archive/`；
- `holding.html` 立刻修掉 `initChart(chart-0, ...)` → `initChart('chart-0', ...)`；
- 统一渲染库（VChart 或 ECharts 二选一），避免同页多 CDN。

---

### P0-3 🔴 持仓报告数据来源是"前一日收盘缓存"，不是"TDX 实时价"

**位置**：`warroom.html` 生成时间 `2026-09-02 04:28`，但持仓最新 K 线日期截止到 **`2026-09-01`**（即 T+0 前一交易日收盘）。

**证据**：
- `warroom.html` K 线数据 x 轴：`["2026-07-22", ..., "2026-09-01"]`（30 日），当日 09/02 无 K 线；
- `warroom.html` 现价 `6.85` = 2026-09-01 收盘；`daily_signal.json` 的 `timestamp` 也是 `2026-09-01 15:31`；
- `build_dashboard.py` 调 `get_tdx_data(code, days=30)`，TDX 日线接口**本身只返回到上一交易日**——这不是 bug，但也不是"实时价"。

**诊断**：报告在 `meta` 里写"生成 2026-09-02 04:28"，但所有持仓价格都是 T-1 收盘缓存。**对老大而言**，"04:28 看到现价 6.85"是误导性的——盘中真实价可能完全不同。这是用户视角里最容易被投诉的点。

**建议**（不改风控）：
- `warroom.html` 的 meta 里显式标注 `数据时效: T-1 收盘 (2026-09-01 15:00)`；
- 盘前日报在头条注明"此为 T-1 复盘，盘中请对照 TDX 实时"；
- 如需"实时价"，应改走 TDX 实时行情接口（`tdx_core` 的 real_time 分支），而不是复用日线缓存。

---

## 三、P1 严重问题

### P1-1 🟠 止损/止盈展示与 `risk_rules.py` 契约不一致

**位置**：`scripts/build_dashboard.py` 第 14/43 行 与 `scripts/holding_dashboard.py` 第 16/49 行。

**证据对比**：

| 项目 | `risk_rules.py` 契约 | Dashboard 展示 | 差异 |
|------|----------------------|----------------|------|
| 基础硬止损 | `STRATEGY_STOP_LOSS_PCT["综合"]=0.08` | `STOP_LOSS_PCT = 0.08` ✅ | 一致 |
| 市场状态调整 | `MARKET_STOP_ADJUST` 按 label 乘系数（偏暖=1.0, 强=1.1, 弱=0.85, 恐慌=0.7） | **完全忽略** | ❌ |
| 信号加分 | `SIGNAL_BONUS_ADJUST` 按 gap/nb_score 放宽 | **完全忽略** | ❌ |
| ATR 波动率修正 | ATR 高波动时放大止损 | **完全忽略** | ❌ |
| 止损限幅 | `final_pct = max(0.03, min(final_pct, 0.15))` | **无** | ❌ |
| 分级移动止盈 | `GRADED_TP_LADDER = [(10,0.08),(20,0.12),(40,0.18),(999,0.25)]` | **未展示** | ❌ |
| 时间止损 | `TIME_STOP_TRADING_DAYS = 60` | **未展示** | ❌ |
| 回本抛压 | 已冻结 `if False` | 未展示（正确） | ✅ |

**诊断**：`warroom.html` 显示的止损 6.26 = `6.81 × 0.92`，用的是"裸 8%"。**这个价在"偏暖"市场状态下数值恰好对**（×1.0），但**逻辑上是错的**——一旦市场标签切到"强"（×1.1 → 8.8%），真实止损应是 6.23 而不是 6.26，用户看到 6.26 会觉得"还离得很远"，实际已经过了真实止损线。

**影响**：用户视角里这是**误导信息**——展示的数字和实际风控引擎触发点不一样，最坏情况下用户以为还有安全垫、其实已经触发止损。

**建议**（不修改 `risk_rules.py`）：
- `build_dashboard.py` 与 `holding_dashboard.py` 应该 `from risk_rules import calculate_stop_loss`，传入 `market_label`/`gap_score`/`nb_score` 得到真实止损价；
- 展示文案加一行："本止损按 risk_rules.py 综合策略 + 偏暖市场调整（×1.00）计算"，让用户知道口径来源；
- 展示分级移动止盈 `8/12/18/25` 和目标价 `TP1=7.49`/`TP2=8.17`/`TP3=9.11`（按 GRADED_TP_LADDER 折算自 6.81）；
- 补充时间止损剩余交易日数（当前 08-21 买入 → 09-01 已约 6 个交易日，剩余 54 日）。

---

### P1-2 🟠 "环境门 CLOSED" 与 "仓位建议 全仓1只" 自相矛盾

**位置**：`warroom.html` gate-box 与 KPI 行。

**证据**：
- `warroom.html`：`环境门 CLOSED` 同时 `仓位建议 全仓1只`；
- `daily_signal.json`：`gate`="闭"、`gate_detail.position_ratio=0.3`（建议 ≤30%）；
- `market_state_cache.json`：`position_ratio=1.0`（全仓）、`position_advice=全仓1只`。

**诊断**：两个源文件的仓位建议**打架**——环境门说"≤30%"、市场评分说"100%"。作战台把两者放在同一屏却未解释优先级，用户会困惑："到底全仓还是空仓？"

**建议**：
- 作战台明确优先级规则（建议：环境门 CLOSED 时仓位建议 ≤30%，压制市场评分的仓位建议）；
- 加一句醒目说明：`⚠️ 环境门 CLOSED，按门禁规则上限 30% 仓位，市场评分的"全仓1只"仅作为趋势参考`。

---

### P1-3 🟠 飞书边框盒日报缺"今日建议"结论条，决策价值低

**位置**：飞书日报（`scripts/daily_stock_report_v2.py` 输出）。

**诊断**（参照后备评审牛马的审查结论，我独立验证了结构）：
- 边框盒按 "📈 市场概况 / 💰 持仓明细 / 📊 因子表现 / ⚠️ 风险提示" 平铺，**没有"今日建议：持有/减仓/观望"** 这样的结论头；
- 用户视角：老大每天第一反应是"今天该不该动"，日报不给结论就要自己脑内推理；
- 胜率 37.8% 是明显弱信号，日报里没有警示文案（如"当前胜率低于 50%，建议降低单笔仓位"）；
- 环境门 CLOSED 时，只说"严禁新增"，未说"何时重新进场"。

**建议**：
- 日报开篇第一条固定为：`🎯 今日建议：持有 / 减仓 / 观望（置信度 X%），理由：...`
- 胜率 < 50% 自动加 🔴 警示文案；
- 环境门 CLOSED 时给出"进场条件"（如：`环境门重开条件：上证站稳 MA250 且 5 日涨幅 < 1%`）。

---

### P1-4 🟠 数据时效声明缺失，用户无法判断可信度

**位置**：所有日报 & 作战台。

**证据**：
- `warroom.html`：`生成 2026-09-02 04:28 | 全仓1只`——只写生成时间，不写数据时效；
- `holding_vchart.html`：`"generated_at": "2026-09-02 03:53:02"`，同样没标"K 线截止到 T-1"；
- 用户拿到 09-02 04:28 的日报，看到"现价 6.85"，会以为这是最新价——但那是 09-01 收盘。

**建议**：所有日报/看板 meta 行统一格式：
`生成 2026-09-02 04:28 | K 线时效 T-1 收盘 2026-09-01 | 持仓源 holdings.json`

---

## 四、P2 改进建议

### P2-1 🟡 可视化层面
- 雷达图（趋势65 / 赚钱效应50 / 量能55 / 资金50 / 板块60）缺**60 分及格圈**和**上周同比**，用户不知道"50 是好还是差"；
- `WEAK_PASS` / `WEAK_PASS` 结论列对非量化用户不友好，应本地化为"可用偏弱 🟡"；
- KPI 行 4 个指标（胜率/超额/持仓数/环境门）单位各异，建议分上下两行展示。

### P2-2 🟡 决策支持层面
- 缺"距止损还有 X%"的百分比表达，只给"止损 6.26" 不直观；
- 缺持仓标的所属**板块归属 + 板块当日涨跌**（当前最强板块 +6.8% 是有的，但没和持仓关联）；
- 缺**北向/主力净流入**一句话（当前资金维度写"获取失败，中性"，应直接对用户说"今日资金面信号缺失，仅供参考"）；
- 缺**大盘指数当日行情**（上证/深成/创业板涨跌幅）——这是老大最基础的参照。

### P2-3 🟡 文件治理层面
- `dashboards/` 下有 5 个 warroom/holding 变体（warroom.html / warroom_v2.html / warroom_safe.html / holding.html / holding_vchart.html），无 README 说明权威版本；
- 建议清理为：`warroom.html`（权威版）+ `archive/` 归档旧版本；
- 交付前加**自动化 smoke test**（HTML 语法 + JS 无语法错误 + 关键占位符已替换）。

---

## 五、审查结论

| 项 | 结论 |
|----|------|
| 数据准确性 | ⚠️ 口径正确但有时效误导（T-1 被呈现为"实时"） |
| 可视化交付 | ⚠️ 主力可用，但 `warroom_safe.html` 和 `holding.html` **JS 报错不可渲染**；文件命名与库不符 |
| 飞书日报排版 | ✅ 边框盒结构清晰，配色统一 |
| 飞书日报决策价值 | ❌ 只有数据没有建议 |
| 风控一致性 | ❌ dashboard 硬编码 8%，未走 `risk_rules.py` 完整计算链 |
| 用户视角 | ❌ 老大需要自己脑内做 5 步推理才能"看懂并决策" |

**最终判定：55 分，不建议原样交付。**

**最低改动路线（按优先级）**：
1. **P0**：修掉 `warroom_safe.html` 和 `holding.html` 的 JS 语法错误，或从发布路径移除；
2. **P0**：meta 行显式标注数据时效（T-1 vs 实时）；
3. **P1**：`build_dashboard.py` / `holding_dashboard.py` 调 `risk_rules.calculate_stop_loss(...)` 拿真实止损价，展示分级止盈 8/12/18/25 和时间止损 60 日；
4. **P1**：作战台澄清"环境门 vs 仓位建议"优先级；
5. **P1**：飞书日报加一行"今日建议：持有/减仓/观望"结论条。

---

*老五（atomcode）| 2026-09-02 | 只读审查，仅新增本文件 `dashboards/review-laowu.md`，未修改任何核心/风控文件*
