#!/bin/bash
# hermes cron wrapper for reporting
cd /mnt/d/open\ code/zhuanqian && /mnt/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe scripts/reporter.py --daily --send 2>&1 | tail -30
