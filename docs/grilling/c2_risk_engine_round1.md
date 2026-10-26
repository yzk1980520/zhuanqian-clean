# C2: risk_rules.py 深化设计 - Grilling会话记录

**时间**: 2026-10-06 06:30 (UTC+8)  
**参与者**: 总管(设计), 老大(决策)  
**状态**: Round 1进行中

---

## 当前进度

- [x] Round 1: 确认Interface定义方式
- [ ] Round 2: 确认Config注入方式
- [ ] Round 3: 确认MarketState传递方式
- [ ] Round 4: 确认常量迁移策略
- [ ] Round 5: 确认实施顺序

---

## Round 1: Interface定义

**问题**: RiskEngine采用类接口还是静态函数集合？

**选项A: RiskEngine类（推荐）**
```python
class RiskEngine:
    def __init__(self, config: RiskConfig):
        self.config = config
    
    def evaluate_exit(self, position: Position) -> ExitDecision:
        """评估是否退出持仓"""
        ...
    
    def calculate_stop_loss(self, entry_price: float, strategy: str) -> float:
        """计算止损价格"""
        ...
```

**优点**:
- 符合深度模块原则（小接口+大实现）
- 便于扩展和维护
- 支持依赖注入

**缺点**:
- 需要修改调用方代码

**选项B: 静态函数集合**
```python
def evaluate_exit(position, config):
    ...
```

**优点**:
- 向后兼容好
- 改动小

**缺点**:
- 不符合深度模块原则
- 难以扩展

**决策**: ?

---

## 后续问题（待Round 1确认后解锁）

### Round 2: Config注入方式
- 选项A: RiskConfig数据类（推荐）
- 选项B: 模块级常量（现有方式）

### Round 3: MarketState传递方式
- 选项A: 接口抽象(MarketStateAdapter)（推荐）
- 选项B: 直接传入字符串（现有方式）

### Round 4: 常量迁移策略
- 选项A: 保留向后兼容（推荐）
- 选项B: 立即破坏性变更

### Round 5: 实施顺序
- 顺序A: 核心类 → 适配层 → 调用方迁移
- 顺序B: 并行开发所有部分

---

## 决策影响矩阵

| 决策 | 影响范围 | 风险等级 | 预估工作量 |
|------|---------|---------|-----------|
| Interface定义 | 所有调用方 | 中 | 2h |
| Config注入 | RiskEngine内部 | 低 | 1h |
| MarketState抽象 | RiskEngine内部 | 低 | 1h |
| 常量迁移 | 所有调用方 | 高 | 4h |

**总计**: 约8小时，风险可控

---

## 下一步

请老大确认Round 1决策，我将继续推进后续轮次。