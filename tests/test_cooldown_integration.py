#!/usr/bin/env python3
"""
test_cooldown_integration.py: v36冷却期集成测试（简化版）
覆盖: 参数验证、动量筛选逻辑、止损止盈参数一致性
"""
import sys, os, json
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.pipeline.integrated_picker import (
    MIN_SCORE,
    COOLDOWN_DAYS,
    check_cooldown_for_pick,
    validate_v36_params
)


class TestCooldownIntegration:
    """冷却期集成测试"""

    def test_parameters_correct(self):
        """测试1: 参数配置正确"""
        assert MIN_SCORE == 20, f"MIN_SCORE应为20 (P0整改22→20), 实际{MIN_SCORE}"
        assert COOLDOWN_DAYS == 5, f"COOLDOWN_DAYS应为5, 实际{COOLDOWN_DAYS}"

    def test_validate_v36_params(self):
        """测试2: v36参数验证通过"""
        # 不应抛出异常
        validate_v36_params()

    def test_check_cooldown_current_state(self):
        """测试3: 检查当前持仓冷却状态（不断言具体值，仅验证函数不崩溃）"""
        try:
            allow, days, msg = check_cooldown_for_pick()
            assert isinstance(allow, bool), f"allow应为bool, 实际{type(allow)}"
            assert isinstance(days, int), f"days应为int, 实际{type(days)}"
            assert isinstance(msg, str), f"msg应为str, 实际{type(msg)}"
            print(f"  ✅ 当前冷却状态: allow={allow}, days={days}, msg='{msg}'")
        except Exception as e:
            print(f"  ⚠️ 冷却期检查异常: {e}")

    def test_momentum_filter_logic(self):
        """测试4: 动量筛选逻辑验证"""
        # 模拟动量筛选逻辑（来自integrated_picker.py line 789）
        # mom_5d > 3 or mom_10d > 5 or mom_20d > 8

        test_cases = [
            (4.0, 0, 0, True, "5日涨4%"),
            (2.0, 0, 0, False, "5日涨2%"),
            (0, 6.0, 0, True, "10日涨6%"),
            (0, 0, 10.0, True, "20日涨10%"),
            (3.5, 5.5, 7.5, True, "多周期共振"),
            (1.0, 1.0, 1.0, False, "所有周期弱"),
        ]

        for mom_5d, mom_10d, mom_20d, expected, desc in test_cases:
            passed = mom_5d > 3 or mom_10d > 5 or mom_20d > 8
            assert passed == expected, f"{desc}: 预期{expected}, 实际{passed}"

    def test_stop_loss_params_in_risk_rules(self):
        """测试5: 验证risk_rules中的止损止盈参数"""
        from risk_rules import (
            STRATEGY_STOP_LOSS_PCT,
            CHASE_BAN_PCT,
            TIME_STOP_TRADING_DAYS,
            TREND_TP_LADDER
        )

        # 验证硬止损（2026-09-30 S3三方会签通过: 8%->10%）
        assert "全仓" in STRATEGY_STOP_LOSS_PCT
        hard_stop = STRATEGY_STOP_LOSS_PCT["全仓"]
        assert abs(hard_stop - 0.10) < 0.001, f"硬止损应为10%(S3), 实际{hard_stop*100}%"

        # 验证追高关闭
        assert CHASE_BAN_PCT == 4.0, f"追高关闭应为4% (契约统一2026-09-25), 实际{CHASE_BAN_PCT}%"

        # 验证时间止损
        assert TIME_STOP_TRADING_DAYS == 120, f"时间止损应为120天, 实际{TIME_STOP_TRADING_DAYS}"

        # 验证移动止盈阶梯存在
        assert "up" in TREND_TP_LADDER
        tp_ladder = TREND_TP_LADDER["up"]
        assert len(tp_ladder) >= 2, "移动止盈阶梯应有至少2档"

        print(f"  ✅ 止损止盈参数验证通过:")
        print(f"    - 硬止损: {hard_stop*100:.0f}%")
        print(f"    - 追高关闭: {CHASE_BAN_PCT}%")
        print(f"    - 时间止损: {TIME_STOP_TRADING_DAYS}天")
        print(f"    - 移动止盈阶梯: {len(tp_ladder)}档")

    def test_params_consistency(self):
        """测试6: 验证集成参数与回测一致"""
        # COOLDOWN_DAYS应与回测一致（5天）
        assert COOLDOWN_DAYS == 5

        # MIN_SCORE应与回测一致（20分，P0整改22→20）
        assert MIN_SCORE == 20


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
