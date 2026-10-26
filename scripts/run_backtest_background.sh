#!/bin/bash
# 后台运行回测脚本
# 用法: bash scripts/run_backtest_background.sh [strategy]

STRATEGY=${1:-S3}
LOG_DIR="logs"
BACKTEST_LOG="$LOG_DIR/backtest_${STRATEGY}_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="$LOG_DIR/backtest_${STRATEGY}.pid"

# 创建日志目录
mkdir -p "$LOG_DIR"

echo "=== Starting Backtest (Background) ==="
echo "Strategy: $STRATEGY"
echo "Log: $BACKTEST_LOG"
echo ""

# 使用项目虚拟环境
PYTHON_PATH=".venv/Scripts/python.exe"

if [ ! -f "$PYTHON_PATH" ]; then
    echo "ERROR: Venv Python not found at $PYTHON_PATH"
    exit 1
fi

# 后台运行
PYTHONIOENCODING=utf-8 $PYTHON_PATH -E backtest_rotation.py --strategy "$STRATEGY" > "$BACKTEST_LOG" 2>&1 &

# 保存PID
echo $! > "$PID_FILE"
echo "PID: $(cat "$PID_FILE")"
echo ""
echo "[INFO] Backtest running in background"
echo "[INFO] Monitor: tail -f $BACKTEST_LOG"
echo "[INFO] Check: cat $PID_FILE | xargs ps"
echo ""

# 显示最后10行（如果有内容）
sleep 3
if [ -f "$BACKTEST_LOG" ]; then
    echo "=== Last 10 lines of log ==="
    tail -10 "$BACKTEST_LOG"
fi
