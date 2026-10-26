@echo off
REM QSP_SysWatchdog wrapper: active self-healing watchdog (15min cadence)
REM ASCII-only: scheduled-task env is CP936, Chinese in batch = mojibake
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "D:\open code\zhuanqian"
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "scripts\sys_watchdog.py" >> "data\sys_watchdog.log" 2>&1
exit /b 0
