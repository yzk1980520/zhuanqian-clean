#!/usr/bin/env python3
"""
P19 止损率敏感性测试
覆盖：分级止盈、固定止损、时间止损、边界条件、统计计算
"""
import sys, os
import importlib.util

import pytest

# 直接加载 p19 模块（避免包路径问题）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P19_PATH = os.path.join(
    PROJECT_ROOT, 'mainline', 'backtests', 'p19_stop_loss_sensitivity.py'
)
spec = importlib.util.spec_from_file_location("p19_module", P19_PATH)
p19 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p19)

simulate_trailing = p19.simulate_trailing
calculate_statistics = p19.calculate_statistics


class TestSimulateTrailing:
    """测试分级移动止盈 + 固定止损"""

    def test_hard_stop(self):
        """硬止损触发（持续下跌不反弹）"""
        # 从45持续下跌到40.5以下（止损价=45*0.92=41.4）
        records = [{"close": 45.0 - i * 0.5} for i in range(10)]
        result = simulate_trailing(records, 0, {"ladder": [(10, 0.06), (20, 0.08), (999, 0.10)]}, -0.08)
        assert result is not None
        assert result["exit_reason"] == "hard_stop"
        assert result["pnl_pct"] < -0.07

    def test_trailing_stop(self):
        """移动止盈触发"""
        # 先涨后跌：涨到49.5(+10%)，然后回落8%到45.54
        records = [{"close": 45.0 + i * 0.5} for i in range(10)]  # 45->49.5
        records.append({"close": 45.5})  # 从49.5回撤8.08%
        result = simulate_trailing(records, 0, {"ladder": [(10, 0.06), (20, 0.08), (999, 0.10)]}, -0.12)
        assert result is not None
        assert result["exit_reason"] == "trailing"

    def test_expire(self):
        """到期止损"""
        records = [{"close": 45.0 + i * 0.1} for i in range(25)]
        result = simulate_trailing(records, 0, {"ladder": [(10, 0.06), (20, 0.08), (999, 0.10)]}, -0.08, max_hold=20)
        assert result is not None
        assert result["exit_reason"] == "expire"
        assert result["hold_days"] == 20

    def test_insufficient_data(self):
        """数据不足"""
        result = simulate_trailing([], 0, {"ladder": [(10, 0.06)]}, -0.08)
        assert result is None

    def test_invalid_buy_idx(self):
        """无效买入索引"""
        records = [{"close": 45.0}]
        result = simulate_trailing(records, 5, {"ladder": [(10, 0.06)]}, -0.08)
        assert result is None

    def test_zero_price(self):
        """零价格"""
        records = [{"close": 0.0}]
        result = simulate_trailing(records, 0, {"ladder": [(10, 0.06)]}, -0.08)
        assert result is None

    def test_all_losers(self):
        """全部下跌"""
        records = [{"close": 45.0 - i * 0.5} for i in range(20)]
        result = simulate_trailing(records, 0, {"ladder": [(10, 0.06), (20, 0.08), (999, 0.10)]}, -0.08)
        assert result is not None
        assert result["exit_reason"] == "hard_stop"
        assert result["pnl_pct"] < 0


class TestCalculateStatistics:
    """测试统计计算"""

    def test_basic(self):
        """基本统计"""
        stats = calculate_statistics([0.05, 0.10, -0.03, 0.08, -0.02])
        assert stats["n_trades"] == 5
        assert stats["win_rate"] == 60.0
        assert abs(stats["avg_pnl"] - 0.036) < 0.001

    def test_all_positive(self):
        """全正收益"""
        stats = calculate_statistics([0.10, 0.20, 0.30])
        assert stats["win_rate"] == 100.0
        assert stats["avg_pnl"] == 0.20

    def test_all_negative(self):
        """全负收益"""
        stats = calculate_statistics([-0.10, -0.20, -0.05])
        assert stats["win_rate"] == 0.0
        assert stats["avg_pnl"] == -0.1167

    def test_empty(self):
        """空输入"""
        stats = calculate_statistics([])
        assert stats["n_trades"] == 0
        assert stats["avg_pnl"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
