@echo off
@set "PY=C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe"
chcp 65001 >nul
cd /d D:\open code\zhuanqian
set PYTHONPATH=
echo [%date% %time%] AOCI weekly score start >> mainline\logs\aoci_weekly_score_cron.log
%PY% scripts\aoci_weekly_score.py >> mainline\logs\aoci_weekly_score_cron.log 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] AOCI weekly score done (RC=%RC%) >> mainline\logs\aoci_weekly_score_cron.log
exit /b %RC%
