@echo off
chcp 65001 >nul
rem 选股看板一键入口 (老三 2026-08-17)
rem 1. 检测 8666 端口, 未启动则拉起服务
netstat -ano | findstr ":8666" | findstr "LISTENING" >nul
if errorlevel 1 (
  rem 使用pythonw.exe静默启动，不弹console窗口
  start "" /b "C:\Users\WIN10\AppData\Local\Programs\Python\Python311\pythonw.exe" -E "D:\open code\zhuanqian\dashboards\board_server.py"
  timeout /t 2 /nobreak >nul
)
rem 2. 打开浏览器到看板
start "" "D:\qq浏览器\QQBrowser\QQBrowser.exe" "http://127.0.0.1:8666/board"
