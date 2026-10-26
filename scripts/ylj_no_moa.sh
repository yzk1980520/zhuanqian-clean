#!/bin/bash
# P0修复(2026-09-15): WSL路径/mnt/d/ → MSYS路径/d/
cd /d/open\ code/zhuanqian
/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe \
  "D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/scripts/ylj_orchestrator.py" \
  --no-moa 2>&1
