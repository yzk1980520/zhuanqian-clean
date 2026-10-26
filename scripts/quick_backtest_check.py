import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""快速验证因子权重优化效果"""
import json, io, os, sys

zhuanqian = r"D:\open code\zhuanqian"

# 读取旧回测结果
result_file = os.path.join(zhuanqian, "backtest_result.json")
if not os.path.exists(result_file):
    print(f"❌ 找不到回测结果: {result_file}")
    sys.exit(1)

with io.open(result_file, encoding='utf-8') as f:
    result = json.load(f)

trades = result.get('trades', [])
print(f"=== 回测结果分析 ===")
print(f"总交易数: {len(trades)}")

wins = [t for t in trades if t.get('pnl_pct', 0) > 0]
losses = [t for t in trades if t.get('pnl_pct', 0) < 0]
stops = [t for t in trades if t.get('reason') == '止损']

if trades:
    win_rate = len(wins) / len(trades) * 100
    stop_rate = len(stops) / len(trades) * 100
    avg_pnl = sum(t.get('pnl_pct', 0) for t in trades) / len(trades)
    
    print(f"\n【关键指标】")
    print(f"  胜率: {len(wins)}/{len(trades)} = {win_rate:.1f}%")
    print(f"  止损占比: {len(stops)}/{len(trades)} = {stop_rate:.1f}%")
    print(f"  平均收益: {avg_pnl:+.2f}%")
    print(f"  最大收益: {max(t.get('pnl_pct', 0) for t in trades):+.2f}%")
    print(f"  最大亏损: {min(t.get('pnl_pct', 0) for t in trades):+.2f}%")

# 对比优化建议中的目标
print(f"\n【与目标对比】")
print(f"  胜率目标: >35% | 当前: {win_rate:.1f}% {'✅' if win_rate > 35 else '❌'}")
print(f"  止损目标: <50% | 当前: {stop_rate:.1f}% {'✅' if stop_rate < 50 else '❌'}")
