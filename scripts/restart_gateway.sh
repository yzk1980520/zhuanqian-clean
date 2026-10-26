#!/bin/bash
# 网关重启脚本

cd /d/open\ code/zhuanqian

echo "=== 开始重启网关 ==="

# 1. 停止现有进程
echo "1. 停止现有网关进程..."
pkill -f "feishu_gateway.py" 2>/dev/null
sleep 2
echo "   ✓ 现有进程已停止"

# 2. 检查端口占用
echo ""
echo "2. 检查端口占用..."
netstat -tlnp 2>/dev/null | grep -E ":(8642|8080)" || echo "   ✓ 端口空闲"

# 3. 启动网关
echo ""
echo "3. 启动网关..."
nohup .venv/Scripts/python.exe scripts/feishu_gateway.py > logs/gateway.log 2>&1 &
GATEWAY_PID=$!
echo "   ✓ 网关已启动，PID: $GATEWAY_PID"

# 4. 等待启动
echo ""
echo "4. 等待网关启动..."
sleep 3

# 5. 检查进程
if ps -p $GATEWAY_PID > /dev/null 2>&1; then
    echo "   ✓ 网关进程运行中"
    echo ""
    echo "=== 网关重启成功 ==="
    echo "PID: $GATEWAY_PID"
    echo "日志: logs/gateway.log"
else
    echo "   ✗ 网关启动失败"
    echo "查看日志: tail -50 logs/gateway.log"
    exit 1
fi
