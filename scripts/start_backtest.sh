#!/bin/bash
# 回测后台启动脚本
# 用法: bash scripts/start_backtest.sh [strategy]

STRATEGY=${1:-S3}
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/backtest_${STRATEGY}_$(date +%Y%m%d_%H%M%S).log"

echo "=== Starting Backtest ==="
echo "Strategy: $STRATEGY"
echo "Log: $LOG_FILE"
echo ""

# 创建日志目录
mkdir -p "$LOG_DIR"

# 后台运行
PYTHONIOENCODING=utf-8 C:/Users/WIN10/AppData/Local/Programs/Python/Python311/python.exe -E backtest_rotation.py --strategy "$STRATEGY" > "$LOG_FILE" 2>&1 &

BACKTEST_PID=$!
echo "PID: $BACKTEST_PID"
echo "Monitoring: tail -f $LOG_FILE"
echo ""

# 显示进度
sleep 5
if ps -p $BACKTEST_PID > /dev/null; then
    echo "[OK] Backtest started successfully"
    echo "[INFO] Use 'tail -f $LOG_FILE' to monitor progress"
else
    echo "[ERROR] Backtest failed to start"
    cat "$LOG_FILE"
fi
