# C2: risk_rules.py 深化设计 - 完整决策记录

**时间**: 2026-10-06 06:30 (UTC+8)  
**状态**: 设计完成，待实施

---

## 决策总结

### D1: Interface定义方式 ✅
**选择**: A - RiskEngine类

### D2: Config注入方式 ✅
**选择**: A - RiskConfig数据类

### D3: MarketState传递方式 ✅
**选择**: A - MarketStateAdapter接口

### D4: 常量迁移策略 ✅
**选择**: A - 保留向后兼容层

### D5: 实施顺序 🔄
**选择**: A - 核心→适配层→调用方（进行中）

---

## 最终设计

### 模块结构
```
risk_rules.py
├── RiskConfig (数据类)
│   ├── stop_loss_base: float
│   ├── chase_ban_pct: float
│   ├── time_stop_days: int
│   └── validate() -> bool
│
├── MarketStateAdapter (Protocol接口)
│   ├── get_regime() -> str
│   └── get_confidence() -> float
│
├── RiskEngine (深度模块)
│   ├── __init__(config: RiskConfig, market_state: MarketStateAdapter)
│   ├── evaluate_exit(position: Position) -> ExitDecision
│   ├── calculate_stop_loss(entry_price: float, strategy: str) -> float
│   └── generate_trade_plan(signal: Signal) -> TradePlan
│
└── 向后兼容层
    ├── CHASE_BAN_PCT = RiskConfig().chase_ban_pct
    └── TIME_STOP_TRADING_DAYS = RiskConfig().time_stop_days
```

### 接口设计
```python
# 新接口（深度模块）
engine = RiskEngine(
    config=RiskConfig(),
    market_state=market_state_adapter
)
decision = engine.evaluate_exit(position)

# 旧接口（向后兼容）
from risk_rules import CHASE_BAN_PCT, calculate_stop_loss
sl = calculate_stop_loss(entry_price, "全仓", "强")
```

---

## 验收标准

1. ✅ 所有现有测试通过
2. ✅ RiskEngine接口简洁（≤5个公共方法）
3. ✅ Config可注入（支持MockConfig）
4. ✅ MarketState解耦（支持MockMarketState）
5. ✅ 向后兼容（旧代码无需修改）

---

## 下一步

**老大决策**: Round 5实施顺序选择？

**推荐**: A (核心→适配层→调用方，4天完成)
