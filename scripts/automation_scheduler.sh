#!/bin/bash
# automation_scheduler.sh - 御龙决全自动化调度wrapper
# 用于Hermes cron no_agent模式

cd /mnt/d/open\ code/zhuanqian || exit 1

# 使用量化venv Python
PYTHON="/mnt/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe"

# 运行调度器（每日完整巡检）
$PYTHON scripts/automation_scheduler.py --mode daily --json
