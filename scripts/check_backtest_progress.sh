#!/bin/bash
# 回测进度监控脚本
# 用法: bash scripts/check_backtest_progress.sh

echo "=== Backtest Progress Monitor ==="
echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 检查回测结果文件
BACKTEST_FILE="data/rotation_backtest_result.json"
if [ -f "$BACKTEST_FILE" ]; then
    MTIME=$(stat -c "%y" "$BACKTEST_FILE" 2>/dev/null | cut -d'.' -f1)
    echo "[OK] Backtest result exists: $BACKTEST_FILE"
    echo "     Last modified: $MTIME"
    
    # 提取关键指标（如果存在）
    if command -v python3 &> /dev/null; then
        python3 -c "
import json
try:
    with open('$BACKTEST_FILE', 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' in data:
        s = data['summary']
        print('')
        print('Key Metrics:')
        print(f'  Total Return: {s.get(\"total_return_pct\", 0):.2f}%')
        print(f'  Annual Return: {s.get(\"annual_return_pct\", 0):.2f}%')
        print(f'  Max Drawdown: {s.get(\"max_drawdown_pct\", 0):.2f}%')
        print(f'  Win Rate: {s.get(\"win_rate_pct\", 0):.2f}%')
        print(f'  Total Trades: {s.get(\"total_trades\", 0)}')
    else:
        print('[INFO] No summary found, backtest may still be running')
except Exception as e:
    print(f'[ERROR] Failed to read result: {e}')
" 2>&1
    fi
else
    echo "[WAIT] Backtest result not found yet"
fi

echo ""
echo "Log files:"
ls -lt logs/backtest_*.log 2>/dev/null | head -3 || echo "  No log files found"

echo ""
echo "=== End Monitor ==="
