@echo off
chcp 65001 >nul
rem OPT-006 (2026-09-27): 回测 sanity gate 自动门禁
rem cron_config.json events.sanity_gate 对应的 Windows 计划任务入口
set PYTHONPATH=
cd /d "D:\open code\zhuanqian"
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" run_sanity_gate_cron.py >> "%~dp0..\logs\scheduler.log" 2>&1
exit /b %ERRORLEVEL%
