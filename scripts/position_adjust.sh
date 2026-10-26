#!/bin/bash
# hermes cron wrapper for position adjustment
cd /mnt/d/open\ code/zhuanqian && /mnt/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe scripts/positioner.py --dry-run --json 2>&1 | tail -30
