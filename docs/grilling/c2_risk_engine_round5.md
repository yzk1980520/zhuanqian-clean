# C2: risk_rules.py 深化设计 - Grilling会话记录

**时间**: 2026-10-06 06:30 (UTC+8)  
**参与者**: 总管(设计), 老大(决策)  
**状态**: Round 5进行中

---

## 当前进度

- [x] Round 1: Interface定义 → **已决策: A (RiskEngine类)** ✅
- [x] Round 2: Config注入方式 → **已决策: A (RiskConfig数据类)** ✅
- [x] Round 3: MarketState传递方式 → **已决策: A (MarketStateAdapter接口)** ✅
- [x] Round 4: 常量迁移策略 → **已决策: A (保留向后兼容层)** ✅
- [ ] Round 5: 实施顺序

---

## Round 1-4: ✅ 已完成

**决策总结**:
- RiskEngine类接口（深度模块）
- RiskConfig数据类（依赖注入）
- MarketStateAdapter接口（解耦）
- 向后兼容层（渐进迁移）

---

## Round 5: 实施顺序

**问题**: 应该按照什么顺序实施重构？

**选项A: 核心→适配层→调用方（推荐）**
```
Phase 1: 核心类创建
  ├── Day 1: 创建RiskConfig数据类
  ├── Day 1: 创建MarketStateAdapter接口
  └── Day 1: 创建RiskEngine类骨架

Phase 2: 适配层实现
  ├── Day 2: 实现RiskEngine内部逻辑
  ├── Day 2: 添加向后兼容层
  └── Day 2: 编写单元测试

Phase 3: 调用方迁移
  ├── Day 3: integrated_picker.py迁移
  ├── Day 3: backtest_rotation.py迁移
  └── Day 3: 验证测试通过

Phase 4: 清理
  ├── Day 4: 删除旧常量（可选）
  └── Day 4: 更新文档
```

**优点**:
- ✅ 风险可控（每阶段可独立验证）
- ✅ 渐进式交付（每阶段有可工作代码）
- ✅ 易于回滚（每阶段可撤销）

**缺点**:
- ❌ 时间较长（4天）

---

**选项B: 并行开发**
```
Day 1-2: 所有模块并行开发
  ├── RiskConfig
  ├── RiskEngine
  ├── MarketStateAdapter
  └── 调用方迁移

Day 3: 集成测试
```

**优点**:
- ✅ 速度快（2天完成）

**缺点**:
- ❌ 风险高（大规模变更）
- ❌ 难以调试（多模块同时变化）
- ❌ 可能引入回归

---

**选项C: 一次性替换**
```
Day 1: 创建新架构
Day 2: 删除旧代码，直接替换
Day 3: 修复所有问题
```

**优点**:
- ✅ 速度最快（3天）

**缺点**:
- ❌ 风险极高（无过渡期）
- ❌ 调试困难（大量变化）
- ❌ 不符合深度重构原则

---

**➡️ 推荐方案: A (核心→适配层→调用方)**

**理由**:
1. **风险控制**: 每阶段可独立验证
2. **渐进交付**: 每个Phase有可工作代码
3. **易于回滚**: 任何问题可在当前Phase撤销

---

**请老大确认: 选项A（核心→适配层→调用方）还是其他？**