---
name: risk-engine-deepening
description: C2深化设计决策记录 - risk_rules.py重构为RiskEngine深度模块
status: in-progress
created: 2026-10-06
related_adr: ADR-0003
---

# C2: risk_rules.py 深化设计决策

## 决策背景

risk_rules.py是当前系统P0级别的风控模块，但存在以下架构问题：
1. 接口复杂度≈实现复杂度（浅层模块）
2. 常量散落各处，无集中管理
3. Seam不清晰，测试困难
4. 调用方直接依赖内部实现细节

## 决策结果

### D1: Interface定义方式
**选择**: A - RiskEngine类 ✅

**理由**:
- 类接口可隐藏内部复杂性（深度原则）
- 支持Future扩展（如添加新的风控规则）
- 便于Mock测试

**接口设计**:
```python
class RiskEngine:
    def __init__(self, config: RiskConfig):
        ...
    
    def evaluate_exit(self, position: Position) -> ExitDecision:
        """评估是否退出持仓"""
        ...
    
    def calculate_stop_loss(self, entry_price: float, strategy: str) -> float:
        """计算止损价格"""
        ...
    
    def generate_trade_plan(self, signal: Signal) -> TradePlan:
        """生成交易计划"""
        ...
```

### D2: Config注入方式 ✅ 已完成

| 选项 | 描述 | 深度 | 推荐 |
|------|------|------|------|
| A | RiskConfig数据类 | 高 | ✅ |
| B | 模块级常量 | 低 | ❌ |

**选择**: A - RiskConfig数据类 ✅

**理由**:
- Config与Engine分离，便于测试时注入MockConfig
- 可添加validate()方法保证配置合法
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
        ...
```

### D3: MarketState传递方式（进行中...）

| 选项 | 描述 | 深度 | 推荐 |
|------|------|------|------|
| A | RiskEngine类 | 高 | ✅ |
| B | 静态函数集合 | 低 | ❌ |

**选择**: A - RiskEngine类

**理由**:
- 类接口可隐藏内部复杂性（深度原则）
- 支持Future扩展（如添加新的风控规则）
- 便于Mock测试

**接口设计**:
```python
class RiskEngine:
    def __init__(self, config: RiskConfig):
        ...
    
    def evaluate_exit(self, position: Position) -> ExitDecision:
        """评估是否退出持仓"""
        ...
    
    def calculate_stop_loss(self, entry_price: float, strategy: str) -> float:
        """计算止损价格"""
        ...
    
    def generate_trade_plan(self, signal: Signal) -> TradePlan:
        """生成交易计划"""
        ...
```

### D2: Config注入方式

| 选项 | 描述 | 深度 | 推荐 |
|------|------|------|------|
| A | RiskConfig数据类 | 高 | ✅ |
| B | 模块级常量 | 低 | ❌ |

**选择**: A - RiskConfig数据类

**理由**:
- Config与Engine分离，便于测试时注入MockConfig
- 符合依赖注入原则

**Config设计**:
```python
@dataclass
class RiskConfig:
    stop_loss_base: float = 0.10
    chase_ban_pct: float = 4.0
    time_stop_days: int = 120
    # ... 其他参数
```

### D3: MarketState传递方式 ✅ 已完成

| 选项 | 描述 | 深度 | 推荐 |
|------|------|------|------|
| A | 接口抽象(MarketStateAdapter) | 高 | ✅ |
| B | 直接传入字符串 | 低 | ❌ |

**选择**: A - MarketStateAdapter接口 ✅

**理由**:
- 解耦RiskEngine与MarketStateEngine实现
- 便于测试时注入MockMarketState
- 符合依赖倒置原则

**Adapter设计**:
```python
class MarketStateAdapter(Protocol):
    def get_regime(self) -> str:
        ...
    def get_confidence(self) -> float:
        ...
```

### D4: 常量迁移策略（进行中...）

**理由**:
- 解耦RiskEngine与MarketStateEngine实现
- 便于测试时注入MockMarketState

**Adapter设计**:
```python
class MarketStateAdapter(Protocol):
    def get_regime(self) -> str:
        ...
    def get_confidence(self) -> float:
        ...
```

### D4: 常量迁移策略 ✅ 已完成

| 选项 | 描述 | 风险 | 推荐 |
|------|------|------|------|
| A | 保留向后兼容 | 低 | ✅ |
| B | 立即破坏性变更 | 高 | ❌ |

**选择**: A - 保留向后兼容层 ✅

**理由**:
- 避免影响现有调用方
- 渐进式迁移，降低风险
- 现有测试无需修改

**迁移方案**:
```python
# 向后兼容层
CHASE_BAN_PCT = RiskConfig().chase_ban_pct
TIME_STOP_TRADING_DAYS = RiskConfig().time_stop_days

# 新接口
class RiskEngine:
    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
```

### D5: 实施顺序 ✅ 已完成

| 选项 | 描述 | 风险 | 推荐 |
|------|------|------|------|
| A | 核心→适配层→调用方 | 低 | ✅ |
| B | 并行开发 | 高 | ❌ |
| C | 一次性替换 | 极高 | ❌ |

**选择**: A - 核心→适配层→调用方 ✅

**理由**:
- 风险可控（每阶段可独立验证）
- 渐进式交付（每阶段有可工作代码）
- 易于回滚（每阶段可撤销）

**实施计划**:
```
Phase 1: 核心类创建（Day 1）
  ├── 创建RiskConfig数据类
  ├── 创建MarketStateAdapter接口
  └── 创建RiskEngine类骨架

Phase 2: 适配层实现（Day 2）
  ├── 实现RiskEngine内部逻辑
  ├── 添加向后兼容层
  └── 编写单元测试

Phase 3: 调用方迁移（Day 3）
  ├── integrated_picker.py迁移
  ├── backtest_rotation.py迁移
  └── 验证测试通过

Phase 4: 清理（Day 4）
  ├── 删除旧常量（可选）
  └── 更新文档
```

## 实施计划

### Phase 1: 核心重构（本阶段）
- [ ] 创建RiskEngine类
- [ ] 创建RiskConfig数据类
- [ ] 创建MarketStateAdapter接口
- [ ] 迁移常量到Config
- [ ] 保留向后兼容层

### Phase 2: 调用方迁移
- [ ] integrated_picker.py迁移
- [ ] backtest_rotation.py迁移
- [ ] 验证测试通过

### Phase 3: 清理
- [ ] 删除旧常量
- [ ] 更新文档
- [ ] 运行全量回归测试

## 验收标准

1. ✅ 所有现有测试通过
2. ✅ RiskEngine接口简洁（≤5个公共方法）
3. ✅ Config可注入（支持MockConfig）
4. ✅ MarketState解耦（支持MockMarketState）
5. ✅ 向后兼容（旧代码无需修改）

## 相关ADR

- ADR-0003: 架构Monolith模块化重构方向

## 更新日志

- 2026-10-06: 初始设计，完成Round 1决策