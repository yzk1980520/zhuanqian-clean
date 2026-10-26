#!/bin/bash
# hermes cron wrapper for monitoring
cd /mnt/d/open\ code/zhuanqian && /mnt/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe scripts/monitor.py --check --alert 2>&1 | tail -50
