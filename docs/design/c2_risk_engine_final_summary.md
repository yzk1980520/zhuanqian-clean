# C2: risk_rules.py 深化设计 - 最终决策

**时间**: 2026-10-06 06:45 (UTC+8)  
**状态**: ✅ 设计完成，待实施

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

### D5: 实施顺序 ✅
**选择**: A - 核心→适配层→调用方

---

## 最终设计

### 模块结构
```
risk_rules/
├── __init__.py           # 统一导出
├── config.py             # RiskConfig数据类
├── adapter.py            # MarketStateAdapter接口
├── engine.py             # RiskEngine深度模块
└── legacy.py             # 向后兼容层
```

### 接口设计
```python
# 新接口（深度模块）
engine = RiskEngine(
    config=RiskConfig(),
    market_state=market_state_adapter
)
decision = engine.evaluate_exit(position, current_price)

# 旧接口（向后兼容）
from risk_rules import CHASE_BAN_PCT, calculate_stop_loss
sl = calculate_stop_loss(entry_price, "全仓", "强")
```

---

## 实施计划

| Phase | 任务 | 预计时间 | 状态 |
|-------|------|---------|------|
| Phase 1 | 核心类创建 | Day 1 | ⏳ 待启动 |
| Phase 2 | 适配层实现 | Day 2 | ⏳ 待启动 |
| Phase 3 | 调用方迁移 | Day 3 | ⏳ 待启动 |
| Phase 4 | 清理 | Day 4 | ⏳ 待启动 |

**总计**: 4天

---

## 验收标准

1. ✅ 所有现有测试通过
2. ✅ RiskEngine接口简洁（≤5个公共方法）
3. ✅ Config可注入（支持MockConfig）
4. ✅ MarketState解耦（支持MockMarketState）
5. ✅ 向后兼容（旧代码无需修改）

---

## 相关ADR

- ADR-0003: 架构Monolith模块化重构方向
- ADR-0012: RiskEngine深度模块重构（待创建）

---

**设计完成时间**: 2026-10-06 06:45 (UTC+8)  
**下一步**: 等待老大授权实施
