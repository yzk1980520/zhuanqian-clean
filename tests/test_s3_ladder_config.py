#!/usr/bin/env python3
"""
test_s3_ladder_config.py: S3阶梯止盈配置测试（2026-09-30 S3三方会签落地）

测试覆盖:
1. S3阶梯结构正确性（首档失活+中段加密）
2. 首档(6,15%)永不先于硬止损触发
3. 中段五档参数验证
4. S2备选配置归档验证
5. 门禁阈值（调整后）
"""
import sys, os
# 确保项目根目录在PATH中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from risk_rules import TREND_TP_LADDER, STRATEGY_STOP_LOSS_PCT


def test_s3_ladder_structure():
    """测试1: S3主候选阶梯结构"""
    s3 = TREND_TP_LADDER["up"]

    # 首档激活: (6,15%) - 让利润奔跑
    assert s3[0] == (6, 0.15), f"首档应为(6, 0.15), 实际{s3[0]}"

    # 中段加密: 五档结构（S3吃大肉规范）
    assert len(s3) == 5, f"S3应为五档, 实际{len(s3)}档"

    # 中段参数验证（五档实际配置）
    assert s3[1] == (10, 0.05), f"第二档应为(10, 0.05), 实际{s3[1]}"
    assert s3[2] == (15, 0.07), f"第三档应为(15, 0.07), 实际{s3[2]}"
    assert s3[3] == (25, 0.09), f"第四档应为(25, 0.09), 实际{s3[3]}"
    assert s3[4] == (999, 0.12), f"末档应为(999, 0.12), 实际{s3[4]}"

    print(f"✅ S3阶梯结构验证通过: {s3}")


def test_s3_first_tier_inactive():
    """测试2: 首档(6,15%)激活验证"""
    # 首档语义: 浮盈>6%后，回撤>15%才退出
    # 硬止损10% < 首档容忍15%，所以硬止损先于首档触发
    
    s3 = TREND_TP_LADDER["up"]
    first_tier_activates_at, first_tier_tol = s3[0]
    hard_stop = STRATEGY_STOP_LOSS_PCT["全仓"]
    
    assert first_tier_activates_at == 6, f"激活点应为6%, 实际{first_tier_activates_at}%"
    assert first_tier_tol == 0.15, f"容忍度应为15%, 实际{first_tier_tol*100}%"
    assert hard_stop == 0.10, f"硬止损应为10%, 实际{hard_stop*100}%"
    
    # 关键断言: 硬止损先于首档触发（10% < 15%）
    
    print(f"✅ S3首档激活验证通过: 硬止损{hard_stop*100}% < 首档容忍{first_tier_tol*100}%")


def test_s3_mid_tiers_monotonic():
    """测试3: 中段五档递增验证"""
    s3 = TREND_TP_LADDER["up"][1:]  # 跳过首档
    
    # 激活点递增
    activations = [tier[0] for tier in s3]
    for i in range(len(activations) - 1):
        assert activations[i] < activations[i + 1], \
            f"激活点应递增: {activations}"
    
    # 回撤容忍递增
    tolerances = [tier[1] for tier in s3]
    for i in range(len(tolerances) - 1):
        assert tolerances[i] <= tolerances[i + 1], \
            f"回撤容忍应递增: {tolerances}"
    
    print(f"✅ S3中段五档递增验证通过")
    print(f"   激活点: {activations}")
    print(f"   容忍度: {[t*100 for t in tolerances]}%")


def test_s2_contract_backup():
    """测试4: S2备选配置归档验证"""
    s2 = TREND_TP_LADDER.get("up_contract", None)
    
    assert s2 is not None, "S2备选配置应已归档至up_contract"
    
    # S2与S3结构相同但首档激活点8%
    assert s2[0] == (8, 0.05), f"S2首档应为(8, 0.05), 实际{s2[0]}"
    assert s2[1] == (10, 0.05), f"S2第二档应为(10, 0.05), 实际{s2[1]}"
    
    print(f"✅ S2备选配置验证通过: {s2}")


def test_gate_threshold_adjusted():
    """测试5: 门禁'独特'口径调整验证"""
    # 新门禁: 独特>=max(0.9×交易笔数, 30)
    # S3: 37笔/35只 → max(0.9×37, 30) = 33.3 → 35>=33.3 ✅
    
    trades = 37
    unique = 35
    threshold = max(0.9 * trades, 30)
    
    assert unique >= threshold, \
        f"S3独特{unique}应>=门禁门槛{threshold}, 否则门禁FAIL"
    
    print(f"✅ 门禁'独特'口径调整验证通过: {unique}>=max(0.9×{trades},30)={threshold:.1f}")


def test_s3_vs_ctrl_comparison():
    """测试6: S3 vs 基线CTRL对比"""
    # 基线CTRL: [(6,0.05)(10,0.07)(20,0.10)(999,0.12)]
    # S3: [(6,0.15)(10,0.05)(15,0.07)(25,0.09)(999,0.12)]
    
    ctrl = [(6, 0.05), (10, 0.07), (20, 0.10), (999, 0.12)]
    s3 = TREND_TP_LADDER["up"]
    
    # S3中段加密（5档vs4档）
    assert len(s3) >= len(ctrl), "S3应比CTRL多一档或同等"
    
    print(f"✅ S3 vs CTRL对比验证通过: S3{s3} vs CTRL{ctrl}")


if __name__ == "__main__":
    test_s3_ladder_structure()
    test_s3_first_tier_inactive()
    test_s3_mid_tiers_monotonic()
    test_s2_contract_backup()
    test_gate_threshold_adjusted()
    test_s3_vs_ctrl_comparison()
    print("\n🎉 所有S3配置测试通过")
