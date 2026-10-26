"""分析回测结果并生成优化建议"""
import json, os, sys
from pathlib import Path

zhuanqian = r"D:\open code\zhuanqian"
result_file = os.path.join(zhuanqian, "backtest_analysis", "backtest_result.json")

print("=" * 60)
print("  回测结果分析 - 2026-08-22")
print("=" * 60)

with open(result_file, encoding='utf-8') as f:
    result = json.load(f)

print(f"\n回测区间: {result.get('backtest_window', 'N/A')}")
print(f"扫描次数: {result.get('scan_count', 'N/A')}")
print(f"总交易数: {result.get('total_trades', 'N/A')}")

# 层1统计
if 'layers' in result and len(result['layers']) > 0:
    l1 = result['layers'][0]
    print(f"\n【层1：机会枚举】")
    print(f"  扫描天数: {l1.get('scan_days', 'N/A')}")
    print(f"  信号数量: {l1.get('total_signals', 'N/A')}")

# 层2统计
if 'layers' in result and len(result['layers']) > 1:
    l2 = result['layers'][1]
    print(f"\n【层2：价格回测】")
    print(f"  胜率: {l2.get('win_rate', 'N/A')}%")
    print(f"  平均5日收益: {l2.get('avg_return_5d', 'N/A')}%")
    print(f"  止损占比: {l2.get('stop_pct', 'N/A')}%")

# 汇总统计
if 'summary' in result:
    s = result['summary']
    print(f"\n【汇总统计】")
    print(f"  胜率: {s.get('win_rate', 'N/A')}%")
    print(f"  年化收益: {s.get('annual_return', 'N/A')}%")
    print(f"  最大回撤: {s.get('max_drawdown', 'N/A')}%")
    print(f"  总交易数: {s.get('total_trades', 'N/A')}")

# 因子重要性
if 'factor_importance' in result:
    print(f"\n【因子重要性TOP5】")
    for name, weight in result['factor_importance'][:5]:
        print(f"  {name}: {weight:.3f}")

print("\n" + "=" * 60)
print("优化建议:")
print("  1. 提高评分门槛至15")
print("  2. 加市场状态门（弱市禁开仓）")
print("  3. 修复回测bug（硬编码7%→读取config 8%）")
print("  4. 运行因子权重扫描")
print("=" * 60)
