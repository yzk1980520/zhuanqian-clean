@echo off
@set "PY=D:\open code\zhuanqian\.venv\Scripts\python.exe"
chcp 65001 >nul
cd /d D:\open code\zhuanqian
set PYTHONPATH=
echo [%date% %time%] 开始每日自动化 >> mainline/logs/daily_auto_cron.log
"%PY%" scripts\automation_scheduler.py >> mainline/logs/daily_auto_cron.log 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] 每日自动化完成 (RC=%RC%) >> mainline/logs/daily_auto_cron.log
exit /b %RC%
