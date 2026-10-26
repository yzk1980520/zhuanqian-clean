#!/bin/bash
# 后台运行回测脚本（带通知）
# 用法: bash scripts/run_backtest_notify.sh [strategy]

STRATEGY=${1:-S3}
LOG_DIR="logs"
BACKTEST_LOG="$LOG_DIR/backtest_${STRATEGY}_$(date +%Y%m%d_%H%M%S).log"
PID_FILE="$LOG_DIR/backtest_${STRATEGY}.pid"

# 创建日志目录
mkdir -p "$LOG_DIR"

echo "=== Starting Backtest (Background with Notification) ==="
echo "Strategy: $STRATEGY"
echo "Log: $BACKTEST_LOG"
echo ""

# 使用项目虚拟环境
PYTHON_PATH=".venv/Scripts/python.exe"

if [ ! -f "$PYTHON_PATH" ]; then
    echo "ERROR: Venv Python not found at $PYTHON_PATH"
    exit 1
fi

# 后台运行并发送飞书通知
(
  PYTHONIOENCODING=utf-8 $PYTHON_PATH -E backtest_rotation.py --strategy "$STRATEGY" > "$BACKTEST_LOG" 2>&1
  EXIT_CODE=$?
  
  # 发送通知（如果飞书可用）
  if [ -f "scripts/send_feishu_notify.py" ]; then
    python scripts/send_feishu_notify.py \
      --status "$([ $EXIT_CODE -eq 0 ] && echo 'success' || echo 'failure')" \
      --message "Backtest $STRATEGY completed with exit code $EXIT_CODE" \
      --log "$BACKTEST_LOG"
  fi
  
  exit $EXIT_CODE
) &

# 保存PID
echo $! > "$PID_FILE"
echo "PID: $(cat "$PID_FILE")"
echo ""
echo "[INFO] Backtest running in background"
echo "[INFO] Monitor: tail -f $BACKTEST_LOG"
echo "[INFO] Check: bash scripts/check_backtest_progress.sh $STRATEGY"
echo ""

# 显示最后10行（如果有内容）
sleep 5
if [ -f "$BACKTEST_LOG" ]; then
    echo "=== Last 10 lines of log ==="
    tail -10 "$BACKTEST_LOG"
fi
