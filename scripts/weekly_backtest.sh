#!/bin/bash
# weekly_backtest.sh - 每周回测脚本wrapper
# Windows compatible path handling

cd "D:/open code/zhuanqian" || exit 1

# Use quant venv Python (Windows native path)
PYTHON="C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe"

# Check Python exists
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: Python not found at $PYTHON"
    exit 1
fi

# Run weekly backtest
"$PYTHON" scripts/auto_backtest_pipeline.py --mode weekly
exit $?
