"""验证回测结果并生成摘要"""
import json, os

result_file = r"D:\open code\zhuanqian\backtest_analysis\backtest_result.json"

with open(result_file, encoding='utf-8') as f:
    result = json.load(f)

print("=" * 50)
print("  回测结果摘要")
print("=" * 50)
print(f"回测区间: {result.get('回测区间', 'N/A')}")
print(f"扫描次数: {result.get('扫描次数', 'N/A')}")
print(f"总交易数: {result.get('总交易次数', 'N/A')}")
print(f"胜率: {result.get('胜率', 'N/A')}%")
print(f"5日收益: {result.get('平均持仓5日收益', 'N/A')}%")
print(f"超额收益5日: {result.get('超额收益5日', 'N/A')}%")
print(f"10日超额: {result.get('超额收益10日', 'N/A')}%")
print(f"20日超额: {result.get('超额收益20日', 'N/A')}%")
print("=" * 50)
print("结论: 策略跑输全市场，需优化")
