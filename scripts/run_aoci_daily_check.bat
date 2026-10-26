@echo off
@set "PY=C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe"
chcp 65001 >nul
cd /d D:\open code\zhuanqian
set PYTHONPATH=
echo [%date% %time%] AOCI daily check start >> mainline\logs\aoci_daily_check_cron.log
%PY% scripts\aoci_daily_check.py >> mainline\logs\aoci_daily_check_cron.log 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] AOCI daily check done (RC=%RC%) >> mainline\logs\aoci_daily_check_cron.log
exit /b %RC%
