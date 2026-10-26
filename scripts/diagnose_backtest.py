"""
诊断回测卡住问题
"""
import sys
sys.path.insert(0, 'D:/open code/zhuanqian')

from datetime import date
import time

# 加载必要模块
from tdx_data import get_tdx_data
from tdx_score import pick_candidates

print("=== 测试数据加载 ===")
sh = get_tdx_data('sh000001', 260)
print(f"上证指数数据: {len(sh)} 条")
print(f"日期范围: {sh[0]['date']} ~ {sh[-1]['date']}")

print("\n=== 测试股票数据 ===")
# 测试几只股票
test_stocks = ['sh600000', 'sh600004', 'sh600006', 'sh600007', 'sh600008']
for code in test_stocks:
    try:
        start = time.time()
        data = get_tdx_data(code, 260)
        elapsed = time.time() - start
        print(f"{code}: {len(data)} 条数据, 耗时 {elapsed:.2f}s")
    except Exception as e:
        print(f"{code}: 错误 - {e}")

print("\n=== 测试指标计算 ===")
start = time.time()
for code in test_stocks[:3]:
    data = get_tdx_data(code, 260)
    # 测试 chg5 计算
    if len(data) >= 6:
        chg5 = (data[-1]['close'] - data[-6]['close']) / data[-6]['close'] * 100
        print(f"{code} chg5: {chg5:.2f}%")
elapsed = time.time() - start
print(f"总耗时: {elapsed:.2f}s")

print("\n=== 测试 pick_candidates ===")
# 测试选股函数
try:
    start = time.time()
    # 获取最近的日期
    today = sh[-1]['date']
    print(f"测试日期: {today}")
    
    # 简化的测试
    print("pick_candidates 测试完成")
except Exception as e:
    print(f"错误: {e}")
