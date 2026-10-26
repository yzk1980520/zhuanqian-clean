#!/bin/bash
# daily_backtest_check.sh — 每日回测进度检查
# 用法: crontab -e → 0 */2 * * * /path/to/daily_backtest_check.sh

LOG_DIR="/data/open_code/zhuanqian/.scratch"
RESULT_FILE="/data/open code/zhuanqian/data/rotation_backtest_result.json"
FLAGS_FILE="/data/open code/zhuanqian/.agent/TASK-BOARD.flags.json"

echo "=== 回测进度检查 $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1) 检查最新日志
LATEST_LOG=$(ls -t ${LOG_DIR}/bt_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    LINES=$(wc -l < "$LATEST_LOG")
    SIZE=$(wc -c < "$LATEST_LOG")
    echo "最新日志: $LATEST_LOG (${LINES}行, ${SIZE}字节)"
    tail -3 "$LATEST_LOG"
else
    echo "无回测日志"
fi

# 2) 检查结果文件
if [ -f "$RESULT_FILE" ]; then
    MTIME=$(stat -c %y "$RESULT_FILE" 2>/dev/null | cut -d'.' -f1)
    echo "结果文件: $RESULT_FILE (更新于 $MTIME)"
else
    echo "结果文件未生成"
fi

# 3) 检查flags
if [ -f "$FLAGS_FILE" ]; then
    DONE=$(python3 -c "import json; print(json.load(open('$FLAGS_FILE'))['summary']['done'])")
    echo "TASK-BOARD done: $DONE"
fi

echo "=== 检查完成 ==="
