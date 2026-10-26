#!/bin/bash
# Hermes cron job: rebuild warroom dashboard
# P0修复(2026-09-15): WSL路径/mnt/d/ → MSYS路径/d/
cd /d/open\ code/zhuanqian
/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe scripts/build_dashboard.py
