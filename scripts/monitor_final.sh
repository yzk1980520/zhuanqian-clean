#!/bin/bash
# 方案A回测最终监控脚本
echo "=== 方案A回测监控启动 ==="
LOG="/d/open code/zhuanqian/data/backtest_plan_a.log"
RESULT="/d/open code/zhuanqian/data/rotation_backtest_result.json"

check_completion() {
  if [ -f "$LOG" ]; then
    # 检查完成信号
    if grep -qE "结果已保存|策略表现汇总|Total trades|=====|exit code 0" "$LOG" 2>/dev/null; then
      echo "✅ 回测完成!"
      return 0
    fi
    # 检查错误
    if grep -qiE "MemoryError|Traceback|Error.*Python" "$LOG" 2>/dev/null; then
      echo "❌ 检测到错误"
      tail -20 "$LOG"
      return 1
    fi
  fi
  return 2
}

while true; do
  if [ -f "$LOG" ]; then
    LINES=$(wc -l < "$LOG")
    echo "[$(date '+%H:%M:%S')] ${LINES} lines"
    
    # 显示最新进度
    tail -3 "$LOG" | grep -E "进度|完成|交易|策略" | tail -1
  fi
  
  check_completion
  status=$?
  if [ $status -eq 0 ]; then
    echo "🎉 回测成功完成!"
    ls -la "$RESULT" 2>/dev/null
    break
  elif [ $status -eq 1 ]; then
    echo "💥 回测失败，检查日志"
    break
  fi
  
  sleep 120
done

echo "=== 监控结束 ==="
