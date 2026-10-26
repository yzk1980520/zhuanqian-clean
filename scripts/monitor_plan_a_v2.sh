#!/bin/bash
# 方案A回测监控
echo "=== 方案A回测监控启动 ==="
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"

while true; do
  if [ -f "/d/open code/zhuanqian/data/backtest_plan_a.log" ]; then
    LINES=$(wc -l < "/d/open code/zhuanqian/data/backtest_plan_a.log")
    SIZE=$(stat -c%s "/d/open code/zhuanqian/data/backtest_plan_a.log" 2>/dev/null || echo "unknown")
    echo "[$(date '+%H:%M:%S')] 日志: ${LINES}行, ${SIZE}字节"
    
    # 检查完成信号
    if grep -qE "回测完成|Total trades|策略表现|exit code|=====|结果已保存" "/d/open code/zhuanqian/data/backtest_plan_a.log" 2>/dev/null; then
      echo "✅ 回测完成!"
      ls -la "/d/open code/zhuanqian/data/rotation_backtest_result.json" 2>/dev/null
      tail -40 "/d/open code/zhuanqian/data/backtest_plan_a.log"
      exit 0
    fi
    
    # 检查错误
    if grep -qiE "Error|Exception|MemoryError|Traceback" "/d/open code/zhuanqian/data/backtest_plan_a.log" 2>/dev/null; then
      ERRORS=$(grep -ciE "Error|Exception|MemoryError" "/d/open code/zhuanqian/data/backtest_plan_a.log")
      echo "⚠️ 检测到错误: ${ERRORS}次"
      tail -20 "/d/open code/zhuanqian/data/backtest_plan_a.log"
    fi
  fi
  sleep 30
done
