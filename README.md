# A股单票轮动选股系统

> 全仓1只 + 移动止盈吃大波段 + 本金安全第一

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/ -v

# 每日选股
python scripts/daily_pick.py
```

## 策略核心

| 模块 | 说明 | 真源 |
|------|------|------|
| 止损 | 10% 硬止损 | `core.risk.risk_rules_impl.STRATEGY_STOP_LOSS_PCT` |
| 止盈 | 移动止盈阶梯 S3 | `core.risk.risk_rules_impl.TREND_TP_LADDER` |
| 追高关闭 | 信号日涨幅 >4% 不买 | `core.risk.risk_rules_impl.CHASE_BAN_PCT` |
| 时间止损 | 120 交易日 | `core.risk.risk_rules_impl.TIME_STOP_TRADING_DAYS` |

## 目录结构

```
.
├── scripts/           # 运行脚本（入口层）
│   ├── daily_pick.py  # 每日选股
│   └── ...
├── core/             # 核心模块（基地化后）
│   ├── risk/         # 风控模块
│   ├── pipeline/     # 选股流水线
│   ├── scoring/      # 评分引擎
│   └── ops/          # 运维模块
├── tests/            # 测试套件
├── config/           # 配置文件
├── docs/             # 文档
└── archive/          # 历史归档
```

## 角色架构

| 角色 | 职责 |
|------|------|
| 总管 (Hermes) | 调度/验收/cron/实盘合入 |
| 老三 (opencode) | 代码/回测/数据工程 |
| 老五 (atomcode) | 独立评审/合规把关 |
| 老四 (laosi) | 自审巡检/异常告警 |

## CI/CD

- GitHub Actions: 每次 push 自动运行测试
- 本地测试: `python -m pytest tests/ -v`
- 门禁测试: `pytest tests/test_contract_docs_consistency.py tests/test_doc_freshness.py tests/test_walk_forward_backtest.py -v`

## 风控红线

- ❌ 不得修改 `core/risk/risk_rules_impl.py` 止损止盈参数
- ❌ 不得修改 `TIME_STOP_TRADING_DAYS=120`
- ❌ 不得修改 `CHASE_BAN_PCT=4%`
- ❌ 全仓不得超过1只
- ❌ 数据不得出本机（Wind Alice 公开数据除外）

## 相关链接

- [契约真源](core/risk/risk_rules_impl.py)
- [系统规格](mainline/docs/specs/002-system-overview/spec.md)
- [宪法](.specify/memory/constitution.md)
