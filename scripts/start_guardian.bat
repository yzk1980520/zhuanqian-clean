@echo off
echo 启动Gateway守护进程...
cd /d "D:\open code\zhuanqian"
start /B python scripts/gateway_guardian.py
echo 守护进程已后台启动
timeout /t 3 >nul
echo 日志:
type logs\gateway_guardian.log
