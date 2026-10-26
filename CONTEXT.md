# Context: zhuanqian 选股系统

## Project Overview

A股单票轮动选股系统：每日选股 → 全仓1只 → 移动止盈吃大波段 → 本金安全。

### Core Strategy

> ⚠️ **契约真源铁律（2026-10-17）**：以下所有数值**只是当前快照**，**唯一真源是 `risk_rules.py`**。
> 本文件不得作为口径依据；要取值请 import 真源或读指针。改契约必须登记
> `docs/CONTRACT-CHANGELOG-20261017.md` 并跑 `scripts/broadcast_contract_change.py`。
> 机器守卫：`tests/test_contract_docs_consistency.py`（活跃层 md 与真源比对，漂移即 FAIL）。

- **持仓**: 全仓1只股票
- **止盈**: → 指针 `risk_rules.TREND_TP_LADDER`（**回撤容忍**阶梯，非卖出比例）+ `risk_rules.TP_SELL_LADDER`（分批卖出比例）。两者**禁止混用**
- **止损**: → 指针 `risk_rules.STRATEGY_STOP_LOSS_PCT`（硬止损）+ `risk_rules.TIME_STOP_TRADING_DAYS`（时间止损）
- **追高关闭**: → 指针 `risk_rules.CHASE_BAN_PCT`（信号日涨幅超该值不买）
- **环境门**: 软提示，门关→建议仓位≤50%（2026-10-17 老大拍板统一，取代 D3 的 ≤30%），不阻塞出票

## Domain Glossary

### 核心角色（7角色分层）
| 术语 | 定义 | 层级 |
|------|------|------|
| 老大 | 最终决策者，资金所有者 | 决策层 |
| 总管 | Hermes Agent，调度/验收/cron/实盘合入 | 决策层 |
| 老五 | atomcode/hy3，独立评审/合规把关 | 决策层 |
| 老三 | opencode，代码/回测/数据工程执行 | 执行层 |
| 牛马 | prime-agent，后备执行节点 | 执行层 |
| 老六 | WorkBuddy，研究域主理人+云端仓 | 执行层 |
| opencode | 编码代理（技术实现层，不对外） | 技术层 |
| atomcode | 评审代理（技术实现层，不对外） | 技术层 |

### 协作流程
| 术语 | 定义 |
|------|------|
| 七步闭环 | 需求→讨论→任务单→执行→评审→验收→归档 |
| 三方讨论 | 总管+老三+老五对争议事项的协商机制 |
| 证据链 | 每个决策必须包含的元数据字段 |
| 任务单 | Kanban任务卡片，包含需求/验收/证据链 |

### 投资概念

### 投资概念
| 术语 | 定义 |
|------|------|
| 扫描日 | 每日选股检查点 |
| 因子 | 用于评分的股票特征（趋势/量能/反转等） |
| IC | Information Coefficient，因子信息系数 |
| IR | Information Ratio，信息比率 |
| 环境门 | 基于上证MA250的仓位控制机制（09-17取消硬拦截，现为软提示：门关→仓位≤50%，2026-10-17 老大拍板统一） |
| 追高关闭 | 信号日涨幅> risk_rules.CHASE_BAN_PCT(4%)时不买入的过滤规则 |
| 移动止盈 | 阶梯式回撤止盈策略 |
| 时间止损 | 持有超过 risk_rules.TIME_STOP_TRADING_DAYS(120个交易日)后强制平仓 |

### 因子治理（Kimi-41 落档）
| 术语 | 定义 |
|------|------|
| 因子四源 | 定义（registry description/formula）↔ 代码（实现函数）↔ IC（factor_ic / 240d 证据）↔ 权重（active/pending + config.json 实盘）。四源必须一致，**任一漂移 = 登记无效**，须走复核不得引用 |
| 双管线隔离 | PCA 研究管线（`pca_factor_synthesis.py`/`run_pca_ic_analysis.py`）与 S3 实盘（`config.json factor_weights` + `factor_gate.json`）是**有意隔离**的，数字不一致属正常，不得"顺手对齐" |
| 入库≠实盘 | `registry gate=pass` 只进研究管线；进 S3 实盘权重必须另开任务单 + 老五评审 + 回滚方案（SOP 红线 1） |
| 因子修改 SOP | `factors/FACTOR_MODIFICATION_SOP.md`：改因子四源一致性检查清单 + 4 条红线（formula 非空 / 漂移标记 / 旧 IC 隔离 / 数据排序 loud fail） |
| 成员写入标准 | `docs/成员写入输出标准-20261008.md`：每个数据源唯一合法写者 + 唯一合法写口（`atomic_json.update_json`/registry 类方法）+ schema 约束 + 写后 read-back 断言；`open('w')` 直写 data/ = P1 缺陷 |
| 成员输出标准 | 同上文档 §2：报告/回执/登记最低字段（改动+一手证据+回归+回滚点+未验证项）；禁止"已修复/已归一"用于未复核项；禁止未附 IC 数值+文件+时间戳就写"IC 反向" |
| 因子口径修正（K45） | chg5=反向（ic_mean −0.0262）；chg10=弱-死（+0.0185 < 0.03 门禁线，**不得写"反向"**）；`ic_mean=None` 为 Q1 合法隔离值，禁洗 0.0、禁当死数据删 |

### 系统组件
| 模块 | 职责 | 关键文件 |
|------|------|----------|
| 风控引擎 | RiskEngine深度模块 | risk_rules_engine.py, risk_rules_config.py, risk_rules_adapter.py |
| 向后兼容层 | 旧函数委托给RiskEngine | risk_rules.py |
| 选股器 | 三层过滤选股系统 | integrated_picker.py |
| 回测引擎 | 轮动回测模拟器 | backtest_rotation.py |
| 持仓监控 | 实盘持仓预警 | position_alerts.py |
| 评审闸仲裁 | review_status.json 唯一仲裁读法（R0b K47 §二）：final_verdict(B3) → B1 findings 硬失败否决 → 回落 laowu_approved；缺失/解析失败=fail-safe 冻结。4 消费方统一 import，禁各写各的/嵌套读 | review_gate.py |
| 术语 | 定义 |
|------|------|
| integrated_picker | 选股入口模块（已模块化拆分） |
| tdx_score | 评分核心引擎（已模块化拆分） |
| backtest_rotation | 回测引擎 |
| risk_rules | 风控规则引擎 |
| chan_engine | 缠论辅助分析 |
| market_state_engine | 市场状态评估 |
| wind-alice | Wind Alice Market Skill（全局可用） |

### 关键规则
| 术语 | 定义 |
|------|------|
| 环境门软提示 | 硬拦截已取消（09-17），仅仓位提示（门关→50%，2026-10-17 老大拍板统一）不阻塞出票 |
| 追高关闭 | 信号日涨幅> risk_rules.CHASE_BAN_PCT(4%)不买（已验证+14pp） |
| 移动止盈 | S3吃大肉五档（激活10/15/25/∞，锁5/7/9/12%；首档6%激活容15%），代码真源 risk_rules.py L227 |
| 时间止损 | 持有超过 risk_rules.TIME_STOP_TRADING_DAYS(120个交易日)后强制平仓 |

## Architecture Decisions

See `mainline/docs/adr/` for detailed decisions.

## Testing Conventions

- Tests located in `tests/` directory
- Framework: pytest
- Run: `python -m pytest tests/ -v`
- Target coverage: 80%+ for core modules

## Data Sources

1. **Primary**: TDX local daily data (binary format)
2. **Secondary**: akshare (external validation)
3. **Financial**: cached financial data

## Constraints

- Data stays local, no third-party AI platforms
- WeChat is the only external communication channel
- JSON writes use atomic_json for concurrency safety
