#!/bin/bash
# 三方讨论自动化脚本 - Cron触发
# 用法: bash scripts/trigger_team_discussion.sh "议题"

TOPIC="${1:-系统健康审查}"
CONTEXT="${2:-自动触发的定期审查}"

cd "$(dirname "$0")/.."
python3 scripts/team_discussion.py --topic "$TOPIC" --context "$CONTEXT" --mode real
