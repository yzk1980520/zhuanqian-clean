# C2: risk_rules.py 深化设计 - Grilling会话记录

**时间**: 2026-10-06 06:30 (UTC+8)  
**参与者**: 总管(设计), 老大(决策)  
**状态**: Round 3进行中

---

## 当前进度

- [x] Round 1: Interface定义 → **已决策: A (RiskEngine类)** ✅
- [x] Round 2: Config注入方式 → **已决策: A (RiskConfig数据类)** ✅
- [ ] Round 3: MarketState传递方式
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

**Config设计**:
```python
@dataclass
class RiskConfig:
    stop_loss_base: float = 0.10
    chase_ban_pct: float = 4.0
    time_stop_days: int = 120
    time_stop_warning_days: int = 5
    
    def validate(self) -> bool:
        """验证配置合法性"""
        assert 0 < self.stop_loss_base <= 0.5
        assert 0 < self.chase_ban_pct <= 10
        assert self.time_stop_days > 0
        assert self.time_stop_warning_days < self.time_stop_days
        return True
```

---

## Round 3: MarketState传递方式

**问题**: MarketState应该如何传递给RiskEngine？

**选项A: 接口抽象(MarketStateAdapter)（推荐）**
```python
class MarketStateAdapter(Protocol):
    """市场状态适配器接口"""
    def get_regime(self) -> str:
        """获取市场状态（强/偏暖/震荡/偏弱/恐慌）"""
        ...
    
    def get_confidence(self) -> float:
        """获取置信度"""
        ...

# RiskEngine使用适配器
class RiskEngine:
    def __init__(self, config: RiskConfig, market_state: MarketStateAdapter):
        self.config = config
        self.market_state = market_state
    
    def evaluate_exit(self, position: Position) -> ExitDecision:
        regime = self.market_state.get_regime()
        # 根据regime调整止损参数
        ...
```

**优点**:
- ✅ 解耦RiskEngine与MarketStateEngine实现
- ✅ 便于测试时注入MockMarketState
- ✅ 符合依赖倒置原则

**缺点**:
- ❌ 需要创建新接口

---

**选项B: 直接传入字符串（现有方式）**
```python
def calculate_stop_loss(entry_price: float, strategy: str, market_state: str) -> float:
    """market_state为字符串如"强"/"震荡"/"恐慌"等"""
    ...
```

**优点**:
- ✅ 向后兼容好
- ✅ 改动小

**缺点**:
- ❌ 耦合MarketStateEngine实现
- ❌ 难以测试（需构造真实MarketStateEngine）
- ❌ 字符串魔法值（易拼写错误）

---

**➡️ 推荐方案: A (MarketStateAdapter接口)**

**理由**:
1. **解耦**: RiskEngine不依赖MarketStateEngine具体实现
2. **可测试性**: 可注入MockMarketState测试各种市场状态
3. **深度原则**: Adapter作为独立模块，RiskEngine作为另一个深度模块

---

**请老大确认: 选项A（MarketStateAdapter接口）还是选项B（直接传入字符串）？**