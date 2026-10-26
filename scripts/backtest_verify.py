import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""因子权重优化验证 - 对比报告"""
import json, io, os

zhuanqian = r"D:\open code\zhuanqian"
result_file = os.path.join(zhuanqian, "backtest_result.json")

if not os.path.exists(result_file):
    print(f"❌ 回测结果不存在: {result_file}")
    exit(1)

with io.open(result_file, encoding='utf-8') as f:
    result = json.load(f)

trades = result.get('trades', [])
print(f"=== 回测结果分析 ===")
print(f"总交易数: {len(trades)}")
print(f"数据来源: {os.path.getmtime(result_file)}")

if trades:
    wins = [t for t in trades if t.get('pnl_pct', 0) > 0]
    losses = [t for t in trades if t.get('pnl_pct', 0) < 0]
    stops = [t for t in trades if t.get('reason') == '止损']
    
    win_rate = len(wins) / len(trades) * 100
    stop_rate = len(stops) / len(trades) * 100
    avg_pnl = sum(t.get('pnl_pct', 0) for t in trades) / len(trades)
    
    print(f"\n【指标对比】")
    print(f"{'指标':<15} {'当前值':<10} {'目标值':<10} {'状态':<10}")
    print(f"{'-'*45}")
    print(f"{'胜率':<15} {win_rate:<10.1f}% {'>35%':<10} {'✅' if win_rate > 35 else '❌':<10}")
    print(f"{'止损占比':<15} {stop_rate:<10.1f}% {'<50%':<10} {'✅' if stop_rate < 50 else '❌':<10}")
    print(f"{'平均收益':<15} {avg_pnl:<10.2f}% {'>2%':<10} {'✅' if avg_pnl > 2 else '❌':<10}")
    
    # 按策略分组统计
    print(f"\n【按策略分组】")
    from collections import defaultdict
    strategy_stats = defaultdict(lambda: {'total': 0, 'wins': 0, 'stops': 0})
    for t in trades:
        s = t.get('strategy', 'unknown')
        strategy_stats[s]['total'] += 1
        if t.get('pnl_pct', 0) > 0:
            strategy_stats[s]['wins'] += 1
        if t.get('reason') == '止损':
            strategy_stats[s]['stops'] += 1
    
    for s, stats in sorted(strategy_stats.items()):
        if stats['total'] > 0:
            wr = stats['wins'] / stats['total'] * 100
            sr = stats['stops'] / stats['total'] * 100
            print(f"  {s}: {stats['total']}笔 胜率{wr:.1f}% 止损{sr:.1f}%")

print(f"\n=== 说明 ===")
print(f"⚠️  此回测使用旧权重（8月9日前）")
print(f"✅ 新权重已应用到tdx_core.py:")
print(f"   - max_ret5_low: 10（新增）")
print(f"   - rsi_strong: 5（原8，降37.5%）")
print(f"   - chg5_gt8: 5（原8，降37.5%）")
print(f"⏳ 新回测正在运行中（Python 3.12）")
