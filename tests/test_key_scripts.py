#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试补充执行器 - 九哥任务

补充5个关键脚本的单元测试：
1. factor_calculator.py
2. factor_ic_monitor_v3.py
3. simulation_runner.py
4. batch_optimizer.py
5. position_manager_mvp.py

[t_laosan_c1_test_alignment] 2026-10-24 (裁决日 2026-10-23):
10/23 大归档 (archive/scripts-20261023/) 后, 本文件按"测试侧对齐归档后真源"处置:
  - factor_ic_monitor_v3 → 重定向到活跃等价 scripts/factor_ic_daily_monitor.run_ic_monitor
  - simulation_runner   → 重定向到活跃等价 backtest/backtest_rotation.simulate_rotation
                          (SimulationAccount 类无活跃等价, 权益状态内嵌于轮动状态机, 删测试挂理由)
  - position_manager_mvp→ 重定向到活跃等价 core/pipeline/positioner (Positioner + main)
  - factor_calculator / batch_optimizer → 无活跃等价 API, 测试删除挂理由
      (归档源: archive/scripts-20261023/factor_calculator.py,
               archive/scripts-20261023/batch_optimizer.py; 裁决日 2026-10-23。
       因子计算现分散于 scripts/factor_ic_132d_refresh.py + core/scoring/*,
       批量参数寻优现由 scripts/walk_forward_backtest.py + backtest/ 引擎承担)
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

    [t_laosan_c1_test_alignment] 原 2 测试 (test_main_execution / test_factor_calculator_class,
    import scripts.factor_calculator.calculate_all_factors_parallel / FactorCalculator) 已删除:
    归档源 archive/scripts-20261023/factor_calculator.py (2026-10-23 裁决),
    calculate_all_factors_parallel / FactorCalculator(calculate_all_factors, load_factors)
    无活跃等价 API; 因子计算现分散于 scripts/factor_ic_132d_refresh.py + core/scoring/*。
    因子可用性覆盖现由 tests/test_factor_ic.py (活跃真源) 承担。
    """
    pass


class TestFactorICMonitor:
    """IC监控单元测试"""

    def test_main_execution(self):
        """测试主函数可导入 (对齐活跃等价: scripts/factor_ic_daily_monitor.run_ic_monitor)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/factor_ic_monitor_v3.py
        (2026-10-23 裁决); 活跃 20d/每日生产监控 = scripts/factor_ic_daily_monitor.py。
        """
        from scripts.factor_ic_daily_monitor import run_ic_monitor
        assert callable(run_ic_monitor)

    # [t_laosan_c1_test_alignment] 原 test_load_all_factors (scripts.factor_ic_monitor_v3.load_all_factors)
    # 已删除: 归档源同上, load_all_factors 无活跃等价 (因子数据加载现由
    # scripts/factor_ic_132d_refresh._load_universe / core/scoring/factor_cache.py 承担, API 不同)。


class TestSimulationRunner:
    """仿真交易单元测试"""

    def test_main_execution(self):
        """测试主函数可导入 (对齐活跃等价: backtest/backtest_rotation.simulate_rotation)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/simulation_runner.py
        (2026-10-23 裁决); 活跃轮动仿真引擎 = backtest/backtest_rotation.py
        (空仓→扫描选TOP1→全仓买入→逐日检查退出 状态机, 132日全量扫描口径)。
        """
        from backtest.backtest_rotation import simulate_rotation
        assert callable(simulate_rotation)

    # [t_laosan_c1_test_alignment] 原 test_simulation_account (scripts.simulation_runner.SimulationAccount)
    # 已删除: 归档源同上, SimulationAccount 类无活跃等价 (账户/权益状态内嵌于
    # backtest_rotation 状态机与 core/ops/rotation_from_trades.simulate_from_trades)。


class TestBatchOptimizer:
    """批量优化单元测试

    [t_laosan_c1_test_alignment] 原 2 测试 (test_main_execution / test_batch_optimizer_class,
    import scripts.batch_optimizer.main / BatchOptimizer) 已删除:
    归档源 archive/scripts-20261023/batch_optimizer.py (2026-10-23 裁决),
    无活跃等价 API; 参数寻优/扫描现由 scripts/walk_forward_backtest.py +
    backtest/ 引擎承担。
    """
    pass


class TestPositionManager:
    """仓位管理单元测试 (对齐活跃等价: core/pipeline/positioner)"""

    def test_main_execution(self):
        """测试主函数可导入 (对齐活跃等价 core/pipeline/positioner.main)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/position_manager_mvp.py
        (2026-10-23 裁决); 活跃仓位管理 = core/pipeline/positioner.py。
        """
        from core.pipeline.positioner import main
        assert callable(main)

    def test_position_manager_class(self):
        """测试仓位管理类存在 (对齐活跃等价 core.pipeline.positioner.Positioner)。

        [t_laosan_c1_test_alignment] 归档源同上; 原 PositionManager 类 → 活跃 Positioner。
        """
        from core.pipeline.positioner import Positioner
        pm = Positioner()
        assert pm is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
