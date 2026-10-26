# C2: risk_rules.py 深化实施计划

**时间**: 2026-10-06 06:40 (UTC+8)  
**状态**: Phase 1启动  
**负责人**: 老三 (opencode)

---

## 决策总结（5个Round全部完成）

| # | 决策项 | 选择 | 深度 |
|---|--------|------|------|
| D1 | Interface定义 | A - RiskEngine类 | 高 |
| D2 | Config注入 | A - RiskConfig数据类 | 高 |
| D3 | MarketState传递 | A - MarketStateAdapter接口 | 高 |
| D4 | 常量迁移 | A - 保留向后兼容层 | 低 |
| D5 | 实施顺序 | A - 核心→适配层→调用方 | 低 |

---

## Phase 1: 核心类创建（Day 1）

### 1.1 创建RiskConfig数据类

**文件**: `risk_rules_config.py`

```python
"""RiskConfig - 风控配置数据类"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class RiskConfig:
    """风控参数配置"""
    
    # 止损参数
    stop_loss_base: float = 0.10  # 基础止损10%
    
    # 止盈参数
    tp_ladder: list = None  # 移动止盈阶梯
    
    # 追高关闭
    chase_ban_pct: float = 4.0  # 信号日涨幅>4%不买
    
    # 时间止损
    time_stop_days: int = 120  # 持有超120日强制平仓
    time_stop_warning_days: int = 5  # 剩余5日预警
    
    def validate(self) -> bool:
        """验证配置合法性"""
        assert 0 < self.stop_loss_base <= 0.5, "止损幅度应在0-50%"
        assert 0 < self.chase_ban_pct <= 10, "追高关闭应在0-10%"
        assert self.time_stop_days > 0, "时间止损应大于0"
        assert self.time_stop_warning_days < self.time_stop_days, "预警应早于止损"
        return True
    
    @classmethod
    def default(cls) -> 'RiskConfig':
        """默认配置（与现有常量对齐）"""
        return cls()
```

### 1.2 创建MarketStateAdapter接口

**文件**: `risk_rules_adapter.py`

```python
"""MarketStateAdapter - 市场状态适配器接口"""
from typing import Protocol

class MarketStateAdapter(Protocol):
    """市场状态适配器（解耦RiskEngine与MarketStateEngine）"""
    
    def get_regime(self) -> str:
        """获取市场状态（强/偏暖/震荡/偏弱/恐慌）"""
        ...
    
    def get_confidence(self) -> float:
        """获取置信度"""
        ...
```

### 1.3 创建RiskEngine类骨架

**文件**: `risk_rules_engine.py`

```python
"""RiskEngine - 风控引擎（深度模块）"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from risk_rules_config import RiskConfig
from risk_rules_adapter import MarketStateAdapter

@dataclass
class Position:
    """持仓信息"""
    stock_code: str
    entry_price: float
    entry_date: date
    quantity: int
    strategy: str = "全仓"

@dataclass
class ExitDecision:
    """退出决策"""
    should_exit: bool
    reason: str
    exit_price: Optional[float] = None

class RiskEngine:
    """风控引擎深度模块"""
    
    def __init__(self, config: RiskConfig = None, market_state: MarketStateAdapter = None):
        self.config = config or RiskConfig.default()
        self.market_state = market_state
    
    def evaluate_exit(self, position: Position, current_price: float) -> ExitDecision:
        """评估是否退出持仓"""
        # 硬止损检查
        loss_pct = (current_price - position.entry_price) / position.entry_price
        if loss_pct <= -self.config.stop_loss_base:
            return ExitDecision(
                should_exit=True,
                reason=f"硬止损触发: 亏损{loss_pct:.2%}",
                exit_price=current_price
            )
        
        # 时间止损检查
        holding_days = (date.today() - position.entry_date).days
        if holding_days >= self.config.time_stop_days:
            return ExitDecision(
                should_exit=True,
                reason=f"时间止损触发: 已持有{holding_days}日",
                exit_price=current_price
            )
        
        # 市场状态恶化检查（待实现）
        # ...
        
        return ExitDecision(
            should_exit=False,
            reason="继续持仓"
        )
    
    def calculate_stop_loss(self, entry_price: float, strategy: str = "全仓") -> float:
        """计算止损价格"""
        # TODO: 实现复杂的风控规则计算
        return entry_price * (1 - self.config.stop_loss_base)
    
    def generate_trade_plan(self, signal) -> dict:
        """生成交易计划"""
        # TODO: 实现交易计划生成
        pass
```

---

## Phase 2: 适配层实现（Day 2）

### 2.1 实现RiskEngine内部逻辑

- [ ] 移动止盈计算
- [ ] 市场状态调整因子
- [ ] 断层/北向信号奖励

### 2.2 添加向后兼容层

**文件**: `risk_rules.py` (重构)

```python
"""risk_rules.py - 向后兼容层"""
from risk_rules_config import RiskConfig
from risk_rules_adapter import MarketStateAdapter
from risk_rules_engine import RiskEngine

# 向后兼容层（保留旧常量）
CHASE_BAN_PCT = RiskConfig().chase_ban_pct
TIME_STOP_TRADING_DAYS = RiskConfig().time_stop_days

# 旧函数包装（保持API兼容）
def calculate_stop_loss(entry_price: float, strategy: str = "全仓", market_state: str = "强") -> float:
    """旧接口包装（调用新RiskEngine）"""
    engine = RiskEngine(config=RiskConfig())
    return engine.calculate_stop_loss(entry_price, strategy)

def evaluate_exit(entry, current_price: float, market_state: str = "强") -> tuple:
    """旧接口包装（调用新RiskEngine）"""
    # ... 实现包装逻辑
    pass
```

### 2.3 编写单元测试

**文件**: `tests/test_risk_engine.py`

```python
"""RiskEngine单元测试"""
import pytest
from datetime import date
from risk_rules_config import RiskConfig
from risk_rules_engine import RiskEngine, Position, ExitDecision

class TestRiskEngine:
    def test_stop_loss_trigger(self):
        """测试硬止损触发"""
        config = RiskConfig(stop_loss_base=0.10)
        engine = RiskEngine(config=config)
        
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        
        # 价格下跌11%，应触发止损
        decision = engine.evaluate_exit(position, current_price=89.0)
        assert decision.should_exit is True
        assert "硬止损" in decision.reason
    
    def test_no_stop_loss(self):
        """测试未触发止损"""
        config = RiskConfig(stop_loss_base=0.10)
        engine = RiskEngine(config=config)
        
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        
        # 价格下跌5%，不应触发止损
        decision = engine.evaluate_exit(position, current_price=95.0)
        assert decision.should_exit is False
    
    def test_time_stop_trigger(self):
        """测试时间止损触发"""
        config = RiskConfig(time_stop_days=120)
        engine = RiskEngine(config=config)
        
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 6, 1),  # 120天前
            quantity=100
        )
        
        decision = engine.evaluate_exit(position, current_price=105.0)
        assert decision.should_exit is True
        assert "时间止损" in decision.reason
```

---

## Phase 3: 调用方迁移（Day 3）

### 3.1 integrated_picker.py迁移

- [ ] 导入新RiskEngine
- [ ] 替换calculate_stop_loss调用
- [ ] 替换evaluate_exit调用
- [ ] 验证测试通过

### 3.2 backtest_rotation.py迁移

- [ ] 导入新RiskEngine
- [ ] 替换风控逻辑
- [ ] 验证回测结果一致

### 3.3 验证测试通过

```bash
python -m pytest tests/test_risk_engine.py -v
python -m pytest tests/test_risk_rules.py -v
```

---

## Phase 4: 清理（Day 4）

### 4.1 删除旧常量（可选）

- [ ] 移除`CHASE_BAN_PCT`全局常量
- [ ] 移除`TIME_STOP_TRADING_DAYS`全局常量
- [ ] 更新所有引用

### 4.2 更新文档

- [ ] 更新CONTEXT.md
- [ ] 创建ADR-0012（RiskEngine深度模块重构）

### 4.3 运行全量回归测试

```bash
python .agent/regression/__init__.py .
python -m pytest tests/ -v --tb=short
```

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

**执行开始时间**: 2026-10-06 06:40 (UTC+8)  
**预计完成时间**: 2026-10-09 18:00 (UTC+8)
