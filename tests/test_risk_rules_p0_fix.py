#!/usr/bin/env python3
"""
test_risk_rules_p0_fix.py: P0整改后风控规则验证
覆盖: S3三方会签确认的止损10%阈值
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestP0StopLossConfig:
    """P0整改: 止损从8%调整为10%"""

    def test_stop_loss_full_position_is_10pct(self):
        """测试: 全仓策略止损应为10%（S3三方会签）"""
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        # S3三方会签确认: 全仓止损从8%→10%
        assert STRATEGY_STOP_LOSS_PCT["全仓"] == 0.10, \
            f"P0整改未生效: 全仓止损={STRATEGY_STOP_LOSS_PCT['全仓']*100:.0f}%, 期望10%"

    def test_all_strategies_have_10pct_base(self):
        """测试: 所有策略基础止损应为10%"""
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        for strategy, pct in STRATEGY_STOP_LOSS_PCT.items():
            assert pct == 0.10, \
                f"策略{strategy}止损={pct*100:.0f}%, 期望10%"

    def test_stop_loss_calculation_with_10pct(self):
        """测试: 基于10%止损的止损价计算正确"""
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # 偏暖市场（系数1.0）: 10% × 1.0 = 10% → 100×(1-0.10)=90.0
        stop_price, stop_pct, _, _ = calculate_stop_loss(
            entry_price, "全仓", "偏暖"
        )
        assert stop_price == pytest.approx(90.0, abs=0.1), \
            f"期望止损价90.0, 实际{stop_price}"
        assert stop_pct == pytest.approx(0.10, abs=0.001), \
            f"期望止损比例10%, 实际{stop_pct*100:.1f}%"

    def test_stop_loss_panic_market_with_10pct_base(self):
        """测试: 恐慌市场下10%基础止损的计算"""
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # 恐慌市场: 10% × 0.55 = 5.5% → 100×(1-0.055)=94.5
        stop_price, stop_pct, _, _ = calculate_stop_loss(
            entry_price, "全仓", "恐慌"
        )
        assert stop_price == pytest.approx(94.5, abs=0.1), \
            f"期望止损价94.5, 实际{stop_price}"
        assert stop_pct == pytest.approx(0.055, abs=0.001), \
            f"期望止损比例5.5%, 实际{stop_pct*100:.1f}%"

    def test_stop_loss_strong_market_with_10pct_base(self):
        """测试: 强市场下10%基础止损的计算（S3会签：系数作用于所有路径）"""
        from risk_rules import calculate_stop_loss
        entry_price = 100.0
        # 强市场: 10% × 1.1 = 11% → 100×(1-0.11)=89.0
        # 但89.0 < 跌停价90.0，触发跌停保护 → 90×0.98=88.2
        stop_price, stop_pct, stop_type, desc = calculate_stop_loss(
            entry_price, "全仓", "强"
        )
        assert stop_price == pytest.approx(88.2, abs=0.1), \
            f"期望止损价88.2（跌停保护），实际{stop_price}"
        assert stop_pct == pytest.approx(0.11, abs=0.001), \
            f"期望止损比例11%，实际{stop_pct*100:.1f}%"
        assert stop_type == "跌停保护", \
            f"期望类型'跌停保护'，实际{stop_type}"


class TestP0TimeStopConfig:
    """时间止损配置验证（保持不变）"""

    def test_time_stop_120_days(self):
        """测试: 时间止损仍为120交易日"""
        from risk_rules import TIME_STOP_TRADING_DAYS
        assert TIME_STOP_TRADING_DAYS == 120, \
            f"时间止损={TIME_STOP_TRADING_DAYS}日, 期望120日"

    def test_time_stop_warning_5_days(self):
        """测试: 时间止损预警为5日"""
        from risk_rules import TIME_STOP_WARNING_DAYS
        assert TIME_STOP_WARNING_DAYS == 5, \
            f"时间止损预警={TIME_STOP_WARNING_DAYS}日, 期望5日"


class TestP0ChaseBanConfig:
    """追高关闭配置验证（保持不变）"""

    def test_chase_ban_4pct(self):
        """测试: 追高关闭阈值为4%"""
        from risk_rules import CHASE_BAN_PCT
        assert CHASE_BAN_PCT == 4.0, \
            f"追高关闭={CHASE_BAN_PCT}%, 期望4%"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
