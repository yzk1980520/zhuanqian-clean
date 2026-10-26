#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试补充执行器 - 九哥任务（修正版）

补充5个关键脚本的单元测试

[t_laosan_c1_test_alignment] 2026-10-24 (裁决日 2026-10-23):
10/23 大归档后, 各 import 对齐到归档后活跃真源:
  - factor_ic_monitor_v3 → scripts/factor_ic_daily_monitor.run_ic_monitor
  - simulation_runner   → backtest/backtest_rotation.simulate_rotation
  - position_manager_mvp→ core/pipeline/positioner.main
  - factor_calculator / batch_optimizer → 无活跃等价 API, 测试删除挂理由
"""

import json
import pytest
from pathlib import Path
from datetime import datetime
import sys

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestFactorCalculator:
    """因子计算单元测试

    [t_laosan_c1_test_alignment] 原 test_main_execution (import
    scripts.factor_calculator.calculate_all_factors_parallel) 已删除:
    归档源 archive/scripts-20261023/factor_calculator.py (2026-10-23 裁决),
    无活跃等价 API (因子计算现分散于 scripts/factor_ic_132d_refresh.py + core/scoring/*)。
    """
    pass


class TestFactorICMonitor:
    """IC监控单元测试"""

    def test_main_execution(self):
        """测试主函数可导入 (对齐活跃等价 scripts/factor_ic_daily_monitor.run_ic_monitor)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/factor_ic_monitor_v3.py
        (2026-10-23 裁决)。
        """
        from scripts.factor_ic_daily_monitor import run_ic_monitor
        assert callable(run_ic_monitor)


class TestSimulationRunner:
    """仿真交易单元测试"""

    def test_main_execution(self):
        """测试主函数可导入 (对齐活跃等价 backtest/backtest_rotation.simulate_rotation)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/simulation_runner.py
        (2026-10-23 裁决); 活跃轮动仿真引擎 = backtest/backtest_rotation.py。
        """
        from backtest.backtest_rotation import simulate_rotation
        assert callable(simulate_rotation)


class TestBatchOptimizer:
    """批量优化单元测试

    [t_laosan_c1_test_alignment] 原 test_main_execution (import scripts.batch_optimizer.main)
    已删除: 归档源 archive/scripts-20261023/batch_optimizer.py (2026-10-23 裁决),
    无活跃等价 API (参数寻优现由 scripts/walk_forward_backtest.py + backtest/ 引擎承担)。
    """
    pass


class TestPositionManager:
    """仓位管理单元测试"""

    def test_main_execution(self):
        """测试主函数可导入 (对齐活跃等价 core/pipeline/positioner.main)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/position_manager_mvp.py
        (2026-10-23 裁决); 活跃仓位管理 = core/pipeline/positioner.py。
        """
        from core.pipeline.positioner import main
        assert callable(main)


class TestRiskRules:
    """风控规则单元测试"""

    def test_stop_loss_config(self):
        """测试止损配置"""
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        assert STRATEGY_STOP_LOSS_PCT['全仓'] == 0.10

    def test_trend_tp_ladder(self):
        """测试止盈阶梯"""
        from risk_rules import TREND_TP_LADDER
        # ⚠️ TREND_TP_LADDER 是**回撤容忍**阶梯, 不是卖出比例阶梯(2026-10-17 澄清)。
        # "留一半以上仓位吃大波段"卡在 risk_rules.TP_SELL_LADDER 上,
        # 由 tests/test_tp_ladder_contract.py 守卫; 这里只卡形制下界。
        assert len(TREND_TP_LADDER['up']) >= 4
        total = sum(r for _, r in TREND_TP_LADDER['up'])
        assert total >= 0.45  # 至少45%


class TestConfig:
    """配置单元测试"""

    def test_min_score(self):
        """测试MIN_SCORE"""
        with open(ROOT / "config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
        assert config.get('selection', {}).get('pick_min_score') == 20

    def test_stop_loss(self):
        """测试止损配置"""
        with open(ROOT / "config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
        assert config.get('stop_loss_pct') == 0.10
        assert config.get('exit_conditions', {}).get('hard_stop_pct') == 0.10

    def test_trailing_ladder(self):
        """测试止盈阶梯"""
        with open(ROOT / "config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
        ladder = config.get('trailing', {}).get('ladder', [])
        assert len(ladder) >= 4
        total = sum(r for _, r in ladder)
        assert total >= 0.45


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
