#!/bin/bash
# 策略空间重标定回测监控脚本
while true; do
  if [ -f "/d/open code/zhuanqian/data/backtest_plan_a.log" ]; then
    LINES=$(wc -l < "/d/open code/zhuanqian/data/backtest_plan_a.log")
    echo "$(date '+%H:%M:%S') - 日志行数: $LINES"
    
    # 检查是否完成
    if grep -q "回测完成\|backtest completed\|exit code\|Total trades" "/d/open code/zhuanqian/data/backtest_plan_a.log" 2>/dev/null; then
      echo "✅ 回测完成!"
      ls -la "/d/open code/zhuanqian/data/rotation_backtest_result.json"
      break
    fi
    
    # 检查最新进度
    tail -5 "/d/open code/zhuanqian/data/backtest_plan_a.log" | grep -E "扫描日|交易|完成" | tail -3
  fi
  sleep 60
done
echo "=== 监控结束 ==="
