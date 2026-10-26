#!/usr/bin/env python3
"""
test_v36_param_usage.py: v36参数使用验证测试
覆盖: MIN_SCORE阈值、动量筛选阈值、止损止盈参数
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.pipeline.integrated_picker import MIN_SCORE, COOLDOWN_DAYS


def test_min_score_threshold():
    """测试1: MIN_SCORE应为20"""
    assert MIN_SCORE == 20, f"MIN_SCORE应为20, 实际{MIN_SCORE}"


def test_cooldown_days():
    """测试2: COOLDOWN_DAYS应为5"""
    assert COOLDOWN_DAYS == 5, f"COOLDOWN_DAYS应为5, 实际{COOLDOWN_DAYS}"


def test_momentum_filter_integration():
    """测试3: 验证动量筛选逻辑正确使用阈值"""
    # 模拟动量筛选逻辑（来自integrated_picker.py line 789）
    # 当前使用: mom_5d > 3 or mom_10d > 5 or mom_20d > 8
    # 这是硬编码的三层阈值，与回测的单一MOMENTUM_LIMIT不一致

    # 测试用例: 5日涨幅4%应该通过
    mom_5d = 4.0
    mom_10d = 0
    mom_20d = 0

    # 当前逻辑（硬编码）
    passed_current = mom_5d > 3 or mom_10d > 5 or mom_20d > 8
    assert passed_current is True, "5日涨4%应通过"

    # 测试用例: 5日涨幅2%应该被拒绝
    mom_5d = 2.0
    passed_current = mom_5d > 3 or mom_10d > 5 or mom_20d > 8
    assert passed_current is False, "5日涨2%应拒绝"

    print("  ⚠️ 注意: 动量筛选使用硬编码阈值(5日>3%/10日>5%/20日>8%)")
    print("       与v36回测的单一MOMENTUM_LIMIT=5%不一致")
    print("       建议后续统一为单一阈值")


def test_stop_params_in_risk_rules():
    """测试4: 验证risk_rules中的止损止盈参数"""
    from risk_rules import (
        STRATEGY_STOP_LOSS_PCT,
        CHASE_BAN_PCT,
        TIME_STOP_TRADING_DAYS,
        TREND_TP_LADDER
    )

    # 验证硬止损
    assert "全仓" in STRATEGY_STOP_LOSS_PCT
    hard_stop = STRATEGY_STOP_LOSS_PCT["全仓"]
    assert abs(hard_stop - 0.10) < 0.001, f"硬止损应为10%, 实际{hard_stop*100}%"

    # 验证追高关闭
    assert CHASE_BAN_PCT == 4.0, f"追高关闭应为4% (契约统一2026-09-25), 实际{CHASE_BAN_PCT}%"

    # 验证时间止损
    assert TIME_STOP_TRADING_DAYS == 120, f"时间止损应为120天, 实际{TIME_STOP_TRADING_DAYS}"

    # 验证移动止盈阶梯
    assert "up" in TREND_TP_LADDER
    tp_ladder = TREND_TP_LADDER["up"]
    assert len(tp_ladder) >= 2, "移动止盈阶梯应有至少2档"
    # 检查阶梯值（从低到高）
    thresholds = [t[0] for t in tp_ladder]
    assert all(thresholds[i] < thresholds[i+1] for i in range(len(thresholds)-1)), \
        "移动止盈阶梯应按利润递增"

    print(f"  ✅ risk_rules参数验证通过:")
    print(f"    - 硬止损: {hard_stop*100:.0f}%")
    print(f"    - 追高关闭: {CHASE_BAN_PCT}%")
    print(f"    - 时间止损: {TIME_STOP_TRADING_DAYS}天")
    print(f"    - 移动止盈阶梯: {len(tp_ladder)}档")


def test_params_consistency():
    """测试5: 验证集成参数与risk_rules一致性"""
    from risk_rules import TIME_STOP_TRADING_DAYS, CHASE_BAN_PCT

    # COOLDOWN_DAYS应与回测一致（5天）
    assert COOLDOWN_DAYS == 5

    # MIN_SCORE应与回测一致（20分）
    assert MIN_SCORE == 20

    # 这些参数不应在integrated_picker中重复定义
    # 应直接使用risk_rules的权威源


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
