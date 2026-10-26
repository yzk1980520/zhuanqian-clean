#!/bin/bash
# IndustryRefresh — 开盘后拉取申万/东财行业成分数据
# cron: 09:35 工作日
# 直接调用 Python 主程序，venv 环境

SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/../mainline/fetch_industry_at_open.py"

# 调用 venv Python 执行行业数据拉取脚本
/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe "$SCRIPT_PATH" 2>&1
