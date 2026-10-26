#!/usr/bin/env python3
"""
止损止盈策略测试
覆盖：硬止损、移动止盈、时间止损、边界条件
"""
import sys, os
import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

from stop_loss_strategy import (
    calc_hard_stop,
    calc_trailing_stop,
    calc_take_profits,
    calc_time_stop,
    get_advice,
    analyze_position,
)


class TestHardStop:
    """硬止损测试"""

    def test_normal(self):
        """正常情况"""
        assert calc_hard_stop(100.0) == 92.0
        assert calc_hard_stop(45.70) == 42.04
        assert calc_hard_stop(10.0) == 9.2

    def test_zero_cost(self):
        """零成本"""
        assert calc_hard_stop(0) == 0
        assert calc_hard_stop(-10) == 0

    def test_custom_pct(self):
        """自定义止损比例"""
        assert calc_hard_stop(100.0, -0.05) == 95.0
        assert calc_hard_stop(100.0, -0.10) == 90.0


class TestTrailingStop:
    """移动止盈测试"""

    def test_low_profit(self):
        """浮盈<5%：不激活移动止损"""
        stop = calc_trailing_stop(100.0, 103.0)
        assert stop == 96.82  # 103 * (1-0.06)=96.82

    def test_tier1(self):
        """浮盈10%：回撤6%"""
        stop = calc_trailing_stop(100.0, 110.0)
        assert stop == round(110.0 * 0.94, 2)

    def test_tier2(self):
        """浮盈25%：回撤8%"""
        stop = calc_trailing_stop(100.0, 125.0)
        assert stop == 115.0

    def test_tier3(self):
        """浮盈50%：回撤10%"""
        stop = calc_trailing_stop(100.0, 150.0)
        assert stop == 135.0

    def test_high_profit(self):
        """高浮盈：回撤12%"""
        stop = calc_trailing_stop(100.0, 250.0)
        assert stop == 220.0

    def test_zero_input(self):
        """零输入"""
        stop = calc_trailing_stop(0, 100)
        assert stop == 0

    def test_current_below_cost(self):
        """现价低于成本"""
        stop = calc_trailing_stop(100.0, 95.0)
        assert stop == 92.0  # pnl<0，回退硬止损


class TestTakeProfits:
    """止盈目标测试"""

    def test_normal(self):
        """正常情况"""
        tps = calc_take_profits(45.70)
        assert len(tps) == 3
        assert tps[0] == 50.27
        assert tps[1] == 54.84
        assert tps[2] == 57.12

    def test_zero_cost(self):
        """零成本"""
        tps = calc_take_profits(0)
        assert tps == [0, 0, 0]


class TestTimeStop:
    """时间止损测试"""

    def test_normal(self):
        """正常情况"""
        result = calc_time_stop("2026-09-18")
        assert result == False

    def test_invalid_date(self):
        """无效日期：loud fail，抛 ValueError（禁止静默返回 False）"""
        from scripts.stop_loss_strategy import calc_time_stop
        import pytest
        with pytest.raises(ValueError, match="entry_date 解析失败"):
            calc_time_stop("invalid")

    def test_zero_days(self):
        """零天数"""
        result = calc_time_stop("2099-01-01", 0)
        assert result == False  # 未来日期，返回False


class TestAdvice:
    """建议测试"""

    def test_hard_stop(self):
        """硬止损建议"""
        assert "硬止损" in get_advice(-8)
        assert "硬止损" in get_advice(-10)

    def test_near_stop(self):
        """接近止损"""
        assert "接近" in get_advice(-5)
        assert "接近" in get_advice(-6)

    def test_activate_trailing(self):
        """激活移动止盈"""
        assert "移动止盈" in get_advice(15)
        assert "移动止盈" in get_advice(20)

    def test_low_profit(self):
        """低浮盈"""
        assert "持有" in get_advice(5)
        assert "持有" in get_advice(3)

    def test_small_loss(self):
        """微亏"""
        assert "微亏" in get_advice(-1)
        assert "观察" in get_advice(-1)


class TestAnalyzePosition:
    """综合分析测试"""

    def test_normal(self):
        """正常分析"""
        result = analyze_position(45.70, 500, 46.47, "2026-09-18")
        assert result["cost"] == 45.70
        assert result["shares"] == 500
        assert result["current"] == 46.47
        assert result["pnl_pct"] == 1.68
        assert result["pnl_value"] == 385.0
        assert result["hard_stop"] == 42.04
        assert len(result["take_profits"]) == 3

    def test_zero_cost(self):
        """零成本"""
        result = analyze_position(0, 500, 46.47, "2026-09-18")
        assert "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
