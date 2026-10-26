#!/bin/bash
# 测试脚本：验证 cron no_agent 的 stdin/参数/exit code/超时处理
# 用法: bash test_cron_smoke.sh [消息内容]
# 注意: cron 的 workdir 设为 D:/open code/zhuanqian/scripts

set -e

# 显示脚本运行环境
echo "=== Cron no_agent 测试脚本 ==="
echo "时间: $(date +%Y-%m-%d\ %H:%M:%S)"
echo "工作目录: $(pwd)"
echo "参数数量: $#"
echo "参数: $@"
echo "=== 环境验证 ==="

# 检查关键路径
PYTHON="/c/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Python: $PYTHON (exists: $(test -f "$PYTHON" && echo yes || echo no))"
echo "lark-cli: D:/npm-global/lark-cli.cmd (exists: $(test -f "D:/npm-global/lark-cli.cmd" && echo yes || echo no))"
echo "当前目录脚本: $SCRIPT_DIR"

# 测试消息内容（优先用参数，否则默认）
TEXT="${1:-🟢 cron no_agent 进阶验证 - $(date +%H:%M:%S)}"
echo "消息内容: $TEXT"

# 调用飞书发送脚本
if [ -f "$SCRIPT_DIR/send_to_feishu.py" ]; then
    echo "执行 send_to_feishu.py..."
    "$PYTHON" "$SCRIPT_DIR/send_to_feishu.py" "$TEXT"
else
    echo "错误: send_to_feishu.py 不存在于 $SCRIPT_DIR"
    exit 1
fi

echo "=== 脚本正常结束 ==="
exit 0
