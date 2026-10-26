#!/bin/bash
# 快速诊断脚本
echo "=== Hermes配置诊断 ==="
echo ""
echo "1. 环境变量检查:"
grep -E "(DEEPSEEK|OPENROUTER|ZAI)_API_KEY" ~/.hermes/.env 2>/dev/null | sed 's/=.*=/=***:/' || echo "  ❌ .env文件未找到"
echo ""
echo "2. Profile状态:"
hermes profile list 2>&1 | head -10
echo ""
echo "3. Gateway状态:"
hermes gateway status 2>&1 | head -5