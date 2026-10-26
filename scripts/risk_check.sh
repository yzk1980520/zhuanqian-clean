#!/bin/bash
# hermes cron wrapper for risk check
cd /mnt/d/open\ code/zhuanqian && /mnt/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe scripts/risk_manager.py --check --json 2>&1 | tail -30
