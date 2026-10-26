@echo off
chcp 65001 >nul
cd /d D:\open code\zhuanqian
set PYTHONPATH=
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" scripts\factor_ic_monitor_20d.py >> mainline\logs\ic_monitor_20d.log 2>&1
