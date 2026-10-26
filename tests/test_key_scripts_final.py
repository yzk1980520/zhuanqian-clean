#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
单元测试补充执行器 - 九哥任务（最终版）

修正：只测试实际存在的函数

[t_laosan_c1_test_alignment] 2026-10-24 (裁决日 2026-10-23):
10/23 大归档后, 各 "脚本存在" 断言对齐到归档后活跃真源:
  - factor_calculator.py      → scripts/factor_ic_132d_refresh.py (活跃因子/IC 真源)
  - factor_ic_monitor_v3.py   → scripts/factor_ic_daily_monitor.py (活跃生产IC监控)
  - simulation_runner.py      → backtest/backtest_rotation.py (活跃轮动仿真引擎)
  - position_manager_mvp.py   → core/pipeline/positioner.py (活跃仓位管理)
  - batch_optimizer.py        → 无活跃等价, 脚本存在断言删除挂理由
"""

import json
import pytest
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


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

    def test_chase_ban(self):
        """测试追高关闭"""
        from risk_rules import CHASE_BAN_PCT
        assert CHASE_BAN_PCT == 4.0

    def test_time_stop(self):
        """测试时间止损"""
        from risk_rules import TIME_STOP_TRADING_DAYS
        assert TIME_STOP_TRADING_DAYS == 120


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

    def test_version(self):
        """测试版本"""
        with open(ROOT / "config.json", 'r', encoding='utf-8') as f:
            config = json.load(f)
        assert config.get('version') is not None
        assert float(config.get('version', 0)) >= 7.0


class TestFactorCalculator:
    """因子计算单元测试（功能测试）"""

    def test_script_exists(self):
        """测试活跃因子/IC 真源脚本存在 (原断言 scripts/factor_calculator.py)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/factor_calculator.py
        (2026-10-23 裁决); 活跃因子计算/IC 真源 = scripts/factor_ic_132d_refresh.py
        (132d 权威源刷新器, 因子函数逐字提升自 factor_ic_scan FACTORS)。
        """
        assert (ROOT / "scripts" / "factor_ic_132d_refresh.py").exists()

    def test_data_exists(self):
        """测试数据存在"""
        factor_files = list((ROOT / "data/factors").glob("*.json"))
        assert len(factor_files) > 0


class TestFactorICMonitor:
    """IC监控单元测试（功能测试）"""

    def test_script_exists(self):
        """测试活跃IC生产监控脚本存在 (原断言 scripts/factor_ic_monitor_v3.py)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/factor_ic_monitor_v3.py
        (2026-10-23 裁决); 活跃生产监控 = scripts/factor_ic_daily_monitor.py (每日/20d滚动)。
        """
        assert (ROOT / "scripts" / "factor_ic_daily_monitor.py").exists()

    def test_ic_data_exists(self):
        """测试IC数据存在"""
        ic_files = list((ROOT / "data/audit").glob("factor_ic_v3_*.json"))
        assert len(ic_files) > 0


class TestSimulationRunner:
    """仿真交易单元测试（功能测试）"""

    def test_script_exists(self):
        """测试活跃轮动仿真引擎存在 (原断言 scripts/simulation_runner.py)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/simulation_runner.py
        (2026-10-23 裁决); 活跃仿真引擎 = backtest/backtest_rotation.py (132日全量口径)。
        """
        assert (ROOT / "backtest" / "backtest_rotation.py").exists()

    def test_simulation_output(self):
        """测试仿真输出"""
        sim_files = list((ROOT / "output/simulation").glob("simulation_report_*.md"))
        assert len(sim_files) > 0


class TestBatchOptimizer:
    """批量优化单元测试（功能测试）"""

    # [t_laosan_c1_test_alignment] 原 test_script_exists (断言 scripts/batch_optimizer.py 存在)
    # 已删除: 归档源 archive/scripts-20261023/batch_optimizer.py (2026-10-23 裁决),
    # 无活跃等价脚本; 参数寻优现由 scripts/walk_forward_backtest.py + backtest/ 引擎承担。

    def test_experiment_log(self):
        """测试实验日志"""
        log_files = list((ROOT / "output/autoresearch").glob("experiment_log.json"))
        assert len(log_files) > 0


class TestPositionManager:
    """仓位管理单元测试（功能测试）"""

    def test_script_exists(self):
        """测试活跃仓位管理模块存在 (原断言 scripts/position_manager_mvp.py)。

        [t_laosan_c1_test_alignment] 归档源 archive/scripts-20261023/position_manager_mvp.py
        (2026-10-23 裁决); 活跃仓位管理 = core/pipeline/positioner.py。
        """
        assert (ROOT / "core" / "pipeline" / "positioner.py").exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
