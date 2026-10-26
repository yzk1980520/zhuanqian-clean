#!/usr/bin/env python3
"""
运行回测并输出进度
"""
import os
import sys
import time

os.chdir(r"D:/open code/zhuanqian")

# Clear PYTHONPATH
if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

print("开始回测...")
print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 50)

start = time.time()

# Import and run backtest
from backtest.backtest_rotation import main

result = main()

elapsed = time.time() - start
print("=" * 50)
print(f"回测完成! 耗时: {elapsed:.1f}秒")
print(result)
