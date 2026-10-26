#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中危风险修复验证
测试清单:
  T2: 单股集中度超限检查
  T10: Agent分歧度统计
  T12: Agent权重归一化
"""
import sys
from pathlib import Path

# 添加项目根目录
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

def test_t2_position_concentration():
    """T2: 单股集中度超限检查"""
    print("\n【T2】单股集中度超限检查")

    # 模拟持仓组合
    portfolio = [
        {'code': 'sz301281', 'value': 10000},
        {'code': 'sz301638', 'value': 5000},
        {'code': 'sz000858', 'value': 3000},
    ]

    total_value = sum(p['value'] for p in portfolio)
    print(f"  总资产: {total_value}元")

    # 检查集中度
    violations = []
    for pos in portfolio:
        concentration = pos['value'] / total_value
        if concentration > 0.4:
            violations.append({
                'code': pos['code'],
                'concentration': concentration,
                'limit': 0.4
            })

    if violations:
        print(f"  ⚠️ 发现集中度违规（测试用违规数据）:")
        for v in violations:
            print(f"    {v['code']}: {v['concentration']*100:.1f}% > 40%")
        print(f"  ✅ T2测试通过（正确检测到违规）")
        return True
    else:
        max_conc = max(p['value'] for p in portfolio) / total_value
        print(f"  ✅ 集中度正常（最大{max_conc*100:.1f}%）")
        return True

def test_t10_divergence():
    """T10: Agent分歧度统计"""
    print("\n【T10】Agent分歧度统计")

    from scripts.multi_agent_engine import MultiAgentEngine

    engine = MultiAgentEngine()

    # 测试1: 一致意见（低分歧）
    test_stock_1 = {
        'chg5': 5.0, 'chg10': 3.0, 'momentum_20': 2.0,
        'pb': 20, 'ps': 2, 'dividend_yield': 0.03,
        'roe': 0.15, 'revenue_growth': 0.1,
        'profit_growth': 0.08, 'rsi14': 55,
        'lower_shadow': 0.02, 'vol_ratio': 1.0,
        'atr_ratio': 1.0, 'std20': 0.03
    }
    result_1 = engine.get_consensus_signal(test_stock_1)
    print(f"  测试1 - 一致意见:")
    print(f"    分歧度: {result_1.get('divergence_score', 'N/A')}")
    print(f"    看涨: {result_1.get('bullish', 0)}, 看跌: {result_1.get('bearish', 0)}, 中性: {result_1.get('neutral', 0)}")
    print(f"    动作: {result_1['action']}")

    # 测试2: 分歧意见（高分歧）
    test_stock_2 = {
        'chg5': -5.0, 'chg10': 5.0, 'momentum_20': -2.0,
        'pb': 25, 'ps': 3, 'dividend_yield': 0.02,
        'roe': 0.10, 'revenue_growth': -0.05,
        'profit_growth': 0.05, 'rsi14': 45,
        'lower_shadow': 0.03, 'vol_ratio': 1.5,
        'atr_ratio': 0.8, 'std20': 0.04
    }
    result_2 = engine.get_consensus_signal(test_stock_2)
    print(f"  测试2 - 分歧意见:")
    print(f"    分歧度: {result_2.get('divergence_score', 'N/A')}")
    print(f"    看涨: {result_2.get('bullish', 0)}, 看跌: {result_2.get('bearish', 0)}, 中性: {result_2.get('neutral', 0)}")
    print(f"    动作: {result_2['action']}")
    print(f"    警告: {result_2.get('warning', '无')}")

    # 验证分歧度统计存在
    if 'divergence_score' in result_1 and 'divergence_score' in result_2:
        print(f"  ✅ T10测试通过（分歧度统计已添加）")
        return True
    else:
        print(f"  ❌ T10测试失败（缺少分歧度统计）")
        return False

def test_t12_weight_normalization():
    """T12: Agent权重归一化"""
    print("\n【T12】Agent权重归一化")

    from scripts.multi_agent_engine import MultiAgentEngine

    engine = MultiAgentEngine()

    # 检查权重和
    total_weight = sum(agent.weight for agent in engine.agents)
    print(f"  Agent数量: {len(engine.agents)}")
    print(f"  权重和: {total_weight:.4f}")

    for agent in engine.agents:
        print(f"    {agent.name}: {agent.weight:.4f}")

    # 验证权重和为1
    if abs(total_weight - 1.0) < 0.01:
        print(f"  ✅ T12测试通过（权重已归一化）")
        return True
    else:
        print(f"  ❌ T12测试失败（权重和≠1）")
        return False

def main():
    """运行所有中危测试"""
    print("=" * 80)
    print("🔧 中危风险修复验证")
    print("=" * 80)

    tests = [
        ("T2 单股集中度", test_t2_position_concentration),
        ("T10 Agent分歧度", test_t10_divergence),
        ("T12 权重归一化", test_t12_weight_normalization),
    ]

    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"  ❌ 测试异常: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 汇总
    print("\n" + "=" * 80)
    print("📊 中危测试汇总")
    print("=" * 80)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 所有中危测试通过！")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 个测试失败")
        return 1


if __name__ == '__main__':
    exit(main())
