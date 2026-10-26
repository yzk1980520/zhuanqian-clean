#!/bin/bash
# Hermes_SkillHealthWeekly - 每周技能健康检查脚本
# 检查agent创建的skills使用情况，输出统计报告

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOG_FILE="$HERMES_HOME/logs/skill_health_weekly.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# 确保日志目录存在
mkdir -p "$(dirname "$LOG_FILE")"

echo "[$TIMESTAMP] === Skill Health Weekly Check Started ===" >> "$LOG_FILE"

# 检查usage.json是否存在
USAGE_FILE="$HERMES_HOME/skills/.usage.json"
if [ ! -f "$USAGE_FILE" ]; then
    echo "[$TIMESTAMP] ⚠️  .usage.json不存在，首次运行或无agent创建的skills" >> "$LOG_FILE"
    echo "{'status': 'no_usage_file'}"
    exit 0
fi

# 解析usage数据（如果python可用）
if command -v python3 &> /dev/null; then
    python3 << 'EOF'
import json
import os
from datetime import datetime

usage_file = os.path.expanduser("~/.hermes/skills/.usage.json")
try:
    with open(usage_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    skills = data.get('skills', []) if isinstance(data, dict) else data
    
    total = len(skills)
    active = sum(1 for s in skills if s.get('state') == 'active')
    idle = sum(1 for s in skills if s.get('state') == 'idle')
    stale = sum(1 for s in skills if s.get('state') == 'stale')
    pinned = sum(1 for s in skills if s.get('pinned'))
    
    print(f"=== Skill Health Report ===")
    print(f"Total: {total}")
    print(f"Active: {active}")
    print(f"Idle: {idle}")
    print(f"Stale: {stale}")
    print(f"Pinned: {pinned}")
    print(f"Status: {'HEALTHY' if stale == 0 else 'NEEDS_ATTENTION'}")
except Exception as e:
    print(f"Error reading usage file: {e}")
    print("{'status': 'error'}")
EOF
elif command -v python &> /dev/null; then
    python << 'EOF'
import json
import os

usage_file = os.path.expanduser("~/.hermes/skills/.usage.json")
try:
    with open(usage_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    skills = data.get('skills', []) if isinstance(data, dict) else data
    
    total = len(skills)
    active = sum(1 for s in skills if s.get('state') == 'active')
    idle = sum(1 for s in skills if s.get('state') == 'idle')
    stale = sum(1 for s in skills if s.get('state') == 'stale')
    pinned = sum(1 for s in skills if s.get('pinned'))
    
    print(f"=== Skill Health Report ===")
    print(f"Total: {total}")
    print(f"Active: {active}")
    print(f"Idle: {idle}")
    print(f"Stale: {stale}")
    print(f"Pinned: {pinned}")
    print(f"Status: {'HEALTHY' if stale == 0 else 'NEEDS_ATTENTION'}")
except Exception as e:
    print(f"Error reading usage file: {e}")
    print("{'status': 'error'}")
EOF
else
    echo "⚠️ Python不可用，跳过详细分析"
    echo "{'status': 'python_not_available'}"
fi

echo "[$TIMESTAMP] === Skill Health Weekly Check Completed ===" >> "$LOG_FILE"
