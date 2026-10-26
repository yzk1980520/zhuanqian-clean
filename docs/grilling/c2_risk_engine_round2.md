# C2: risk_rules.py 深化设计 - Grilling会话记录

**时间**: 2026-10-06 06:30 (UTC+8)  
**参与者**: 总管(设计), 老大(决策)  
**状态**: Round 2进行中

---

## 当前进度

- [x] Round 1: Interface定义 → **已决策: A (RiskEngine类)**
- [ ] Round 2: Config注入方式
- [ ] Round 3: MarketState传递方式
- [ ] Round 4: 常量迁移策略
- [ ] Round 5: 实施顺序

---

## Round 1: ✅ 已完成

**问题**: RiskEngine采用类接口还是静态函数集合？

**决策**: A - RiskEngine类

**理由**: 符合深度模块原则，便于扩展和测试

---

## Round 2: Config注入方式

**问题**: RiskConfig应该如何定义和注入？

**选项A: RiskConfig数据类（推荐）**
```python
@dataclass
class RiskConfig:
    stop_loss_base: float = 0.10
    chase_ban_pct: float = 4.0
    time_stop_days: int = 120
    time_stop_warning_days: int = 5
    # 其他参数...
    
    def validate(self) -> bool:
        """验证配置合法性"""
        ...
```

**优点**:
- ✅ Config与Engine分离，便于测试时注入MockConfig
- ✅ 符合依赖注入原则
- ✅ 可添加validate()方法保证配置合法

**缺点**:
- ❌ 需要创建新类

---

**选项B: 模块级常量（现有方式）**
```python
# risk_rules.py
CHASE_BAN_PCT = 4.0
TIME_STOP_TRADING_DAYS = 120
```

**优点**:
- ✅ 向后兼容好
- ✅ 改动小

**缺点**:
- ❌ 不符合深度模块原则
- ❌ 难以测试（需修改模块级变量）
- ❌ 无配置验证

---

**➡️ 推荐方案: A (RiskConfig数据类)**

**理由**:
1. **可测试性**: 支持注入MockConfig测试边界场景
2. **配置验证**: 可在__init__中验证参数合法性
3. **深度原则**: Config作为独立模块，Engine作为另一个深度模块

---

**请老大确认: 选项A（RiskConfig数据类）还是选项B（模块级常量）？**