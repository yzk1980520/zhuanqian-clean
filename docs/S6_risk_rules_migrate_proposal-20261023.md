# S6 三方讨论：risk_rules.py 迁移至 core/risk/

**发起人**: 总管  
**日期**: 2026-10-23  
**状态**: 三方讨论中 (kanban t_303fc7e3)

## 背景
基地化 S0-S5 已完成，根级 .py 从 644 降至 74。
`risk_rules.py`（905行）是最后未被迁入包的根级核心模块。

## 现状数据
| 指标 | 数值 |
|------|------|
| TSS戳 | `7c35cf9a638f`（红线，不得修改逻辑） |
| import引用文件 | 77个 |
| 导出符号 | 31个常量+函数 |
| 子模块 | config(95L)/adapter(103L)/engine(217L) |
| 循环依赖 | engine延迟import risk_rules打破 |

## 方案对比

### 方案A: Shim-only（已验证可行 ✅）
- 4文件迁入 `core/risk/`
- 根级 `risk_rules.py` 改为 re-export shim (~15行)
- **77个文件 import 0改写**
- 技术验证: ALL PASS ✅

```python
# 根级 risk_rules.py (shim)
from core.risk.risk_rules_impl import *
from core.risk.risk_rules_impl import (
    STRATEGY_STOP_LOSS_PCT, CHASE_BAN_PCT, TIME_STOP_TRADING_DAYS,
    TREND_TP_LADDER, TP_SELL_LADDER, calculate_stop_loss, evaluate_exit,
    RiskEngine, RiskConfig, MockMarketState, ...
)
```

### 方案B: 全量迁移
- 迁入 + 改写77文件 import
- 高风险，违反"改契约必留痕+广播"流程

### 方案C: Hybrid
- 子模块迁入 + 部分改写
- 需逐文件评估

## 技术验证结果
```
✅ CHASE_BAN_PCT = 4.0
✅ STRATEGY_STOP_LOSS_PCT['全仓'] = 0.10
✅ TIME_STOP_TRADING_DAYS = 120
✅ TREND_TP_LADDER keys = ['up','down','sideways','swing','up_contract']
✅ calculate_stop_loss(100,'全仓','强') = 正确返回值
✅ evaluate_exit callable
✅ RiskEngine/RiskConfig/MockMarketState accessible
```

## 待讨论问题
1. **老五**: 方案A是否触碰契约红线？shim re-export vs 原文件改动
2. **老三**: 技术细节确认（路径锚点/循环依赖/shim设计）
3. **老大**: 拍板方案A/B/C

## 验收标准
1. `python -m py_compile core/risk/*.py` 全过
2. 77文件 import 不变仍工作
3. risk_rules 逻辑不变（TSS语义一致）
4. 核心回归测试通过
5. 契约广播（AGENTS §4.0）
