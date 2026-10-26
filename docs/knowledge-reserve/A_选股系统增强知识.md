# 方向 A · 选股系统增强知识（针对 zhuanqian）

**作者**：总管 ｜ **日期**：2026-08-31 ｜ **用途**：储备知识，供三方评审时参考

---

## 摘要（100 字内）

本方向聚焦 A 股多因子量化选股的工程化落地：walk-forward 严格验证、硬红线机制设计、TDX 数据因子挖掘、全仓 1 只风险管理。所有建议均已对照 zhuanqian 现状（v2 MVP 5 大能力就位）标注优先级，P0 项可直接进入 09-30 EvoQuarterly 议程。

---

## 核心知识点（5 条）

### 1. Walk-Forward 严格验证是量化 Alpha 的生命线
A 股充斥"年化 30% 的机器选股"，但实盘风格切换往往摔得惨烈。严格 walk-forward 采用滚动窗口（如 12 月训练 + 2 月测试），每次只允许"未来窗口"进入测试，禁止数据窥探。**zhuanqian 现状**：R7 全量 walk-forward 09-30 前待派，当前仅有 --max-scans=10 快版；建议 09-30 EvoQuarterly 补全 132 日严格滚动验证，作为因子入库唯一门禁。

来源：https://zhuanlan.zhihu.com/p/2053809767752151563

### 2. 多因子合成"等权最诚实"是行业共识
XGBoost/ML 合成虽能挖更高 IC，但易过度拟合。因子处理链：去极值 → 标准化 → 中性化 → 等权合成 → 排序选股（Top100）→ 周频调仓。中性化（去行业/去市值）比选因子更重要。**zhuanqian 现状**：14 因子 6 大类已建（反转 3/动量 5/行业轮动 2/事件 1/择时 1/风险回避 2），但 13/14 stale=true 待 09-30 刷新；建议刷新时补一层中性化处理。

来源：https://bigquant.com/wiki/doc/3f251OEFN9

### 3. 券商金工研报复现库（QuantsPlaybook）是 TDX 因子挖掘参考
22+ 策略覆盖高质量动量、反转、低波、红利、分析师预期等方向，全部标注参考文献。**zhuanqian 现状**：TDD 9220 只 A 股（2026-08-29），因子库 14 条；建议从 QuantsPlaybook 挑 3-5 个高引用策略做 TDX 复现 POC，作为 09-30 EvoQuarterly 因子扩展池。

来源：https://github.com/hugo2046/QuantsPlaybook

### 4. A 股因子库的官方口径（优矿/通联）
优矿提供市值、行业、分析师预期、资金流等 600+ 因子，中证 500 小市值选股是经典入门案例。**zhuanqian 现状**：akshare 5208 只 + FTShare 2 只用作补数；TDX 为主数据源。建议 09-30 前评估是否接入优矿因子库作为外部校验源，避免自算因子全部失效时的"单点故障"。

来源：https://uqer.datayes.com/help/strategyManualV3/

### 5. MA250 门控策略的失效场景与硬红线设计
MA250 是趋势门控，但 2024 年以来的"轮动失效"现象显示：在震荡市 MA250 会产生反复假信号。硬红线（CHASE_BAN_PCT=4% 追高禁止 / TIME_STOP=60 日超时止损 / 黑名单机制）比 MA250 更抗失效。**zhuanqian 现状**：gate=闭（上证 3927 < MA250 3973），CHASE_BAN_PCT/TIME_STOP 已写入 risk_rules.py；建议 09-30 前评估"MA250 + 硬红线"双门控的失效联合概率。

来源：https://algolabhk.com/zh-TW/blogs/walk-forward-analysis-complete-guide

---

## 对 zhuanqian 的可落地建议（3 条）

### 建议 A1（P0）：09-30 EvoQuarterly 补全 walk-forward 严格验证
- **动作**：R7 全量 walk-forward 从 --max-scans=10 升级到 132 日严格滚动
- **验收**：每次 daily/weekly 生成 SR/DSR bootstrap CI（已有）+ walk-forward 分窗口 SR 分布
- **优先级依据**：R7 未完成前，因子入库无独立样本外验证，是"过拟合风险"最大的单点

### 建议 A2（P1）：09-30 因子刷新补中性化处理
- **动作**：14 因子刷新时加去行业/去市值中性化步骤
- **验收**：因子与行业指数/市值相关系数 |ρ|<0.3
- **优先级依据**：现状因子含行业轮动 2 条 + 动量 5 条，未中性化会放大行业暴露

### 建议 A3（P2）：QuantsPlaybook POC 作为 09-30 因子扩展池
- **动作**：挑 3-5 个高引用策略做 TDX 复现，加入因子库评估
- **验收**：至少 1 个新因子通过 IC>0.03/IR>0.3 门禁（factor-gate skill）
- **优先级依据**：14 因子已 stale 13/14，需外部策略库补充 alpha 来源

---

## 参考链接

1. https://zhuanlan.zhihu.com/p/2053809767752151563 — Walk-Forward 严格样本外验证
2. https://bigquant.com/wiki/doc/3f251OEFN9 — 多因子选股全策略拆解
3. https://github.com/hugo2046/QuantsPlaybook — 券商金工研报复现库
4. https://algolabhk.com/zh-TW/blogs/walk-forward-analysis-complete-guide — 前行分析完整指南
5. https://uqer.datayes.com/help/strategyManualV3/ — 优矿量化研究手册
