# C2: risk_rules.py 深化设计 - Grilling会话记录

**时间**: 2026-10-06 06:30 (UTC+8)  
**参与者**: 总管(设计), 老大(决策)  
**状态**: Round 4进行中

---

## 当前进度

- [x] Round 1: Interface定义 → **已决策: A (RiskEngine类)** ✅
- [x] Round 2: Config注入方式 → **已决策: A (RiskConfig数据类)** ✅
- [x] Round 3: MarketState传递方式 → **已决策: A (MarketStateAdapter接口)** ✅
- [ ] Round 4: 常量迁移策略
- [ ] Round 5: 实施顺序

---

## Round 1: ✅ 已完成

**问题**: RiskEngine采用类接口还是静态函数集合？

**决策**: A - RiskEngine类

**理由**: 符合深度模块原则，便于扩展和测试

---

## Round 2: ✅ 已完成

**问题**: RiskConfig应该如何定义和注入？

**决策**: A - RiskConfig数据类

**理由**: 
- Config与Engine分离，便于测试
- 可添加validate()方法
- 符合依赖注入原则

---

## Round 3: ✅ 已完成

**问题**: MarketState应该如何传递给RiskEngine？

**决策**: A - MarketStateAdapter接口

**理由**: 
- 解耦RiskEngine与MarketStateEngine
- 支持MockMarketState测试
- 符合依赖倒置原则

---

## Round 4: 常量迁移策略

**问题**: 如何将现有常量迁移到新架构，同时保持向后兼容？

**选项A: 保留向后兼容层（推荐）**
```python
# risk_rules.py - 新架构
@dataclass
class RiskConfig:
    stop_loss_base: float = 0.10
    chase_ban_pct: float = 4.0
    time_stop_days: int = 120
    time_stop_warning_days: int = 5

class RiskEngine:
    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
    
    def evaluate_exit(self, position: Position) -> ExitDecision:
        ...

# 向后兼容层
CHASE_BAN_PCT = RiskConfig().chase_ban_pct
TIME_STOP_TRADING_DAYS = RiskConfig().time_stop_days

# 调用方无需修改
from risk_rules import CHASE_BAN_PCT  # 依然可用
```

**优点**:
- ✅ 零破坏性变更
- ✅ 渐进式迁移
- ✅ 旧代码继续工作

**缺点**:
- ❌ 需维护两套接口

---

**选项B: 立即破坏性变更**
```python
# risk_rules.py - 新架构
@dataclass
class RiskConfig:
    stop_loss_base: float = 0.10
    chase_ban_pct: float = 4.0
    # ... 删除所有旧常量

class RiskEngine:
    def __init__(self, config: RiskConfig = None):
        ...

# 删除旧常量
# CHASE_BAN_PCT = 4.0  # 已删除
```

**优点**:
- ✅ 代码简洁
- ✅ 无技术债

**缺点**:
- ❌ 破坏所有调用方
- ❌ 需一次性修改所有代码
- ❌ 高风险

---

**➡️ 推荐方案: A (保留向后兼容层)**

**理由**:
1. **风险控制**: 避免大规模重构风险
2. **渐进迁移**: 可逐步替换调用方
3. **测试保障**: 现有测试无需修改

---

**请老大确认: 选项A（保留向后兼容层）还是选项B（立即破坏性变更）？**