import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""分析回测结果并生成报告"""
import json, os, sys
from datetime import datetime

zhuanqian = r"D:\open code\zhuanqian"
result_file = os.path.join(zhuanqian, "backtest_result.json")

print("=" * 60)
print("  回测结果分析报告")
print("=" * 60)

if not os.path.exists(result_file):
    print("❌ 回测结果文件不存在")
    sys.exit(1)

with open(result_file, encoding='utf-8') as f:
    result = json.load(f)

print(f"\n更新时间: {result.get('updated_at', 'unknown')}")
print(f"策略: {result.get('strategy', '未知')}")

# 层1统计
if 'layers' in result and len(result['layers']) > 0:
    l1 = result['layers'][0]
    print(f"\n【层1统计】")
    print(f"  扫描天数: {l1.get('scans', 'N/A')}")
    print(f"  信号数量: {l1.get('signals', 'N/A')}")
    print(f"  机会数量: {l1.get('opportunities', 'N/A')}")

# 层2统计
if 'layers' in result and len(result['layers']) > 1:
    l2 = result['layers'][1]
    print(f"\n【层2统计】")
    print(f"  胜率: {l2.get('win_rate', 'N/A')}%")
    print(f"  平均收益: {l2.get('avg_return', 'N/A')}%")
    print(f"  止损占比: {l2.get('stop_pct', 'N/A')}%")

# 汇总统计
if 'summary' in result:
    s = result['summary']
    print(f"\n【汇总统计】")
    print(f"  胜率: {s.get('win_rate', 'N/A')}%")
    print(f"  止损占比: {s.get('stop_loss_pct', 'N/A')}%")
    print(f"  年化收益: {s.get('annual_return', 'N/A')}%")
    print(f"  最大回撤: {s.get('max_drawdown', 'N/A')}%")
    print(f"  总交易数: {s.get('total_trades', 'N/A')}")
    print(f"  总收益: {s.get('total_return', 'N/A')}%")

# 因子重要性
if 'factor_importance' in result:
    print(f"\n【因子重要性TOP5】")
    for name, weight in result['factor_importance'][:5]:
        print(f"  {name}: {weight:.3f}")

print("\n" + "=" * 60)
