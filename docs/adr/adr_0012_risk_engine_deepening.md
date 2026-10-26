# ADR-0012: RiskEngine深度模块重构

**状态**: ✅ 已采纳  
**日期**: 2026-10-06  
**作者**: 老三 (opencode)  
**评审**: 总管 (Hermes/agnes) + 老五 (atomcode/hy3)

---

## 背景

risk_rules.py作为风控核心模块，存在以下问题：
1. **职责不单一**: 常量定义、计算逻辑、验证函数混杂
2. **接口复杂**: calculate_stop_loss有7个参数，evaluate_exit有多个if分支
3. **耦合度高**: 直接依赖market_label字符串，无法解耦
4. **测试困难**: 全局常量硬编码，无法Mock

## 决策

将risk_rules.py重构为**深度模块**（Deep Module），遵循"小接口+大实现"原则：

```
risk_rules_config.py   # RiskConfig数据类（依赖注入配置）
risk_rules_adapter.py  # MarketStateAdapter接口（解耦市场状态）
risk_rules_engine.py   # RiskEngine核心引擎（小接口+大实现）
risk_rules.py          # 向后兼容层（委托实现）
```

## 影响

### 正面影响
1. **可测试性提升**: MockMarketState支持单元测试
2. **依赖注入**: RiskConfig可替换，支持多场景配置
3. **职责分离**: 配置/接口/实现三层清晰
4. **向后兼容**: 零破坏性变更，调用方无需修改

### 负面影响
1. **代码量增加**: 从单文件831行→4个文件共587行
2. **调用链加深**: 旧函数调用→委托→RiskEngine方法

## 验证

- ✅ 测试覆盖率: 59/59测试通过
- ✅ 向后兼容: integrated_picker.py/backtest_rotation.py无需修改
- ✅ 架构收敛: TREND_TP_LADDER为唯一止盈阶梯权威源

## 相关ADR

- ADR-0003: 架构Monolith模块化重构方向
- C2深化设计: docs/implementation/c2_risk_engine_implementation_plan.md

---

**签字**: 总管 (Hermes/agnes)  
**日期**: 2026-10-06
