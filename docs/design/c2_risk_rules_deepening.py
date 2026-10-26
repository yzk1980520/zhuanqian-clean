#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C2: risk_rules.py 深化设计方案

## 目标
将risk_rules.py从"散乱常量+函数"重构为"深度模块"，提供清晰的Seam和Interface。

## 当前问题
1. 风控参数散落各处（CHASE_BAN_PCT, TIME_STOP_TRADING_DAYS等）
2. 函数接口复杂（calculate_stop_loss参数过多）
3. Seam不清晰（配置、计算、验证混在一起）
4. .agent/regression/__init__.py用AST解析验证常量（暗示接口设计缺陷）

## 深化方案
创建RiskEngine类，封装所有风控逻辑：
- Interface: 简洁的evaluate_exit(), calculate_stop_loss()等
- Implementation: 内部封装复杂的规则计算
- Seam: RiskEngine接口作为测试边界

## 实施步骤
1. Round 1: 确认接口边界（本阶段）
2. Round 2: 设计内部Adapter（如MarketStateAdapter）
3. Round 3: 编写测试用例（Red阶段）
4. Round 4: 实现RiskEngine（Green阶段）
5. Round 5: 重构调用方（迁移至新接口）

## 测试策略
- 单元测试: 每个风控规则独立测试
- 集成测试: evaluate_exit()完整流程
- 契约测试: 验证P0常量值不变

## 影响范围
- 直接调用方: integrated_picker.py, backtest_rotation.py
- 间接影响: 所有调用calculate_stop_loss/calculate_tp_levels的脚本
"""

# 设计决策树
# ┌─────────────────────────────────────────────────────────────────┐
# │ C2: risk_rules.py 深化                                          │
# ├─────────────────────────────────────────────────────────────────┤
# │ Q1: Interface定义？                                              │
# │   ├── A: RiskEngine类（推荐）                                   │
# │   │   ├── evaluate_exit(position, current_price) -> ExitDecision│
# │   │   ├── calculate_stop_loss(entry_price, strategy) -> float  │
# │   │   └── generate_trade_plan(signal) -> TradePlan             │
# │   └── B: 静态函数集合                                           │
# │       ├── evaluate_exit(...)                                     │
# │       └── calculate_stop_loss(...)                             │
# │                                                                │
# │ Q2: Config如何注入？                                            │
# │   ├── A: RiskConfig数据类（推荐）                               │
# │   │   ├── stop_loss_base: float = 0.10                         │
# │   │   ├── chase_ban_pct: float = 4.0                           │
# │   │   └── time_stop_days: int = 120                            │
# │   └── B: 模块级常量（现有方式）                                 │
# │       ├── CHASE_BAN_PCT = 4.0                                  │
# │       └── TIME_STOP_TRADING_DAYS = 120                         │
# │                                                                │
# │ Q3: MarketState如何传递？                                       │
# │   ├── A: 通过接口抽象（推荐）                                   │
# │   │   ├── class MarketStateAdapter:                            │
> │   │   │   ├── get_regime() -> str                              │
> │   │   │   └── get_confidence() -> float                        │
> │   └── B: 直接传入字符串（现有方式）                              │
> │       ├── evaluate_exit(..., market_state="强")                │
> │       └── 耦合MarketStateEngine实现                            │
> │                                                                │
> │ Q4: 常量迁移策略？                                              │
> │   ├── A: 保留向后兼容（推荐）                                   │
> │   │   ├── CHASE_BAN_PCT = RiskConfig().chase_ban_pct           │
> │   │   └── 新代码使用RiskEngine                                 │
> │   └── B: 立即破坏性变更                                         │
> │       └── 删除旧常量，所有调用方改为新接口                      │
> │                                                                │
> └─────────────────────────────────────────────────────────────────┘