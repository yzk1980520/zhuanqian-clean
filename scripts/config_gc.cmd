@echo off
REM QSP_ConfigGC wrapper: daily GC of deprecated APIs / redundant configs (09:40)
REM ASCII-only: scheduled-task env is CP936, Chinese in batch = mojibake
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "D:\open code\zhuanqian"
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "scripts\config_gc.py" >> "data\config_gc.log" 2>&1
exit /b 0
