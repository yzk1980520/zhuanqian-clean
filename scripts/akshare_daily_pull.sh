#!/bin/bash
# AkshareDailyPull — 盘后拉取龙虎榜/行业资金流/新闻
# cron: 16:00 工作日
# 直接调用 akshare 函数，无需 mcp 依赖

cd "D:/open code/zhuanqian"
/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe "scripts/akshare_daily_pull.py" 2>&1
