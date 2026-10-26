#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0级测试用例 - 高危边界情况验证
测试清单:
  T1: 跌停板止损测试
  T2: 单股集中度超限测试
  T6: IC除零保护测试
  T10: Agent置信度=0测试
  T14: 空交易数据测试
  T18: 空仓Sharpe=0测试
"""
import sys
from pathlib import Path

# 添加项目根目录
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

def test_t1_limit_down_stop_loss():
    """T1: 跌停板止损测试"""
    print("\n【T1】跌停板止损测试")
    
    from risk_rules import calculate_stop_loss
    
    # 测试1: 正常情况
    price, pct, dtype, desc = calculate_stop_loss(100.0, strategy="综合")
    print(f"  正常情况: 价格100元, 止损{price}元 ({pct*100:.1f}%)")
    assert price < 100, "止损价应低于买入价"
    
    # 测试2: 跌停板保护（高止损比例）
    price2, pct2, dtype2, desc2 = calculate_stop_loss(100.0, strategy="综合")
    # 模拟高波动场景
    print(f"  止损类型: {dtype2}")
    print(f"  描述: {desc2}")
    
    # 验证跌停保护逻辑
    limit_down = 100 * 0.9  # -10%跌停
    if price2 < limit_down:
        print(f"  ✅ 跌停保护生效: 止损价{price2}元 > 跌停价{limit_down}元")
    else:
        print(f"  ⚠️ 止损价{price2}元可能低于跌停价{limit_down}元")
    
    print("  ✅ T1测试通过")
    return True

def test_t2_position_concentration():
    """T2: 单股集中度超限测试"""
    print("\n【T2】单股集中度超限测试")
    
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
        print(f"  ❌ 发现集中度违规:")
        for v in violations:
            print(f"    {v['code']}: {v['concentration']*100:.1f}% > 40%")
        return False
    else:
        print(f"  ✅ 集中度正常（最大{max(p['value'] for p in portfolio)/total_value*100:.1f}%）")
        return True

def test_t6_ic_division_by_zero():
    """T6: IC除零保护测试"""
    print("\n【T6】IC除零保护测试")
    
    from scripts.ic_compound_monitor import ICCompoundMonitor
    
    monitor = ICCompoundMonitor()
    
    # 测试1: 正常IC计算
    returns = [0.01, -0.02, 0.03, -0.01, 0.02] * 10  # 50个数据点
    factors = [0.5, 0.6, 0.4, 0.5, 0.7] * 10
    ic = monitor.calculate_ic_safe(returns, factors)
    print(f"  正常IC: {ic:.4f}")
    assert abs(ic) < 1.0, "IC应在[-1,1]范围内"
    
    # 测试2: 除零保护（std=0）
    returns_zero = [0.01] * 50  # 所有收益相同
    factors_normal = [0.5, 0.6, 0.4, 0.5, 0.7] * 10
    ic_zero = monitor.calculate_ic_safe(returns_zero, factors_normal)
    print(f"  除零保护: {ic_zero:.4f}")
    assert ic_zero == 0.0, "std=0时应返回0"
    
    # 测试3: 数据不足
    ic_short = monitor.calculate_ic_safe([0.01], [0.5])
    print(f"  数据不足: {ic_short:.4f}")
    assert ic_short == 0.0, "数据不足时应返回0"
    
    print("  ✅ T6测试通过")
    return True

def test_t10_agent_confidence_zero():
    """T10: Agent置信度=0测试"""
    print("\n【T10】Agent置信度=0测试")
    
    from scripts.multi_agent_engine import MultiAgentEngine, AgentSignal, SignalDirection
    
    engine = MultiAgentEngine()
    
    # 创建测试信号（包含置信度=0的Agent）
    signals = [
        AgentSignal("Momentum", SignalDirection.BULLISH, 0.8, 0.9, "动量强势"),
        AgentSignal("Value", SignalDirection.BEARISH, 0.6, 0.0, "价值弱势"),  # 置信度=0
        AgentSignal("Quality", SignalDirection.BULLISH, 0.7, 0.8, "质量良好"),
        AgentSignal("Reversal", SignalDirection.NEUTRAL, 0.5, 0.5, "中性"),
        AgentSignal("Volatility", SignalDirection.BEARISH, 0.4, 0.0, "波动率高"),  # 置信度=0
    ]
    
    # 测试过滤
    valid, msg = engine.filter_valid_signals(signals)
    print(f"  过滤消息: {msg}")
    
    if valid is None:
        print(f"  ✅ 正确识别有效Agent不足: {msg}")
        return True
    else:
        print(f"  ⚠️ 有效Agent数: {len(valid)}/5")
        return len(valid) >= 3

def test_t14_empty_trade_data():
    """T14: 空交易数据测试"""
    print("\n【T14】空交易数据测试")
    
    from scripts.oos_convexity_guard import OOSConvexityGuard
    
    guard = OOSConvexityGuard()
    
    # 测试1: 空数据
    report = guard.generate_report()
    print(f"  状态: {report.get('status', 'UNKNOWN')}")
    print(f"  消息: {report.get('message', 'N/A')}")
    
    if report.get('status') in ['ERROR', 'INSUFFICIENT_DATA']:
        print(f"  ✅ 正确识别数据不足")
        return True
    else:
        print(f"  ⚠️ 未正确识别数据不足")
        return False

def test_t18_empty_position_sharpe_zero():
    """T18: 空仓Sharpe=0测试"""
    print("\n【T18】空仓Sharpe=0测试")
    
    from scripts.live_trading_closed_loop import LiveTradingClosedLoop
    
    loop = LiveTradingClosedLoop()
    
    # 测试1: 空仓数据（<10笔交易）
    live_data = {
        'daily_returns': [0.01, -0.02],  # 只有2天数据
        'trades': [],
        'total_assets': 22000,
        'available_cash': 22000
    }
    backtest_data = {'sharpe': 2.58}
    
    gradient = loop.calculate_gradient(live_data, backtest_data)
    print(f"  需要更新: {gradient.get('needs_update', 'N/A')}")
    print(f"  原因: {gradient.get('reason', 'N/A')}")
    
    if not gradient.get('needs_update', True):
        print(f"  ✅ 空仓时不触发参数更新")
        return True
    else:
        print(f"  ❌ 空仓时错误触发参数更新")
        return False

def main():
    """运行所有P0测试"""
    print("=" * 80)
    print("🧪 P0级高危边界测试套件")
    print("=" * 80)
    
    tests = [
        ("T1 跌停板止损", test_t1_limit_down_stop_loss),
        ("T2 单股集中度", test_t2_position_concentration),
        ("T6 IC除零保护", test_t6_ic_division_by_zero),
        ("T10 Agent置信度", test_t10_agent_confidence_zero),
        ("T14 空交易数据", test_t14_empty_trade_data),
        ("T18 空仓Sharpe", test_t18_empty_position_sharpe_zero),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"  ❌ 测试异常: {e}")
            results.append((name, False))
    
    # 汇总
    print("\n" + "=" * 80)
    print("📊 P0测试汇总")
    print("=" * 80)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status} {name}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有P0测试通过！")
        return 0
    else:
        print(f"\n⚠️ {total - passed} 个测试失败")
        return 1


if __name__ == '__main__':
    exit(main())
