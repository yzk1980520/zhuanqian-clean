#!/bin/bash
# 周一执行自动化脚本（包装器）
# 用法: bash auto_monday_exec.sh [--dry-run]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON=".venv/Scripts/python.exe"

echo "=========================================="
echo "周一执行自动化启动"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# 执行Python脚本
"$PYTHON" scripts/monday_auto_exec.py "$@"

EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 自动化执行成功"
else
    echo "⚠️  自动化执行存在错误，退出码: $EXIT_CODE"
fi
echo "=========================================="

exit $EXIT_CODE
