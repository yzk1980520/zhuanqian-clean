@echo off
REM AOCI每日巡检任务
REM 触发方式: Windows Task Scheduler
REM 计划: 每天 22:00 执行

cd /d "D:\open code\zhuanqian"

REM 设置Python路径
set PYTHON_PATH=C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe

REM 清空Python环境变量（避免冲突）
set PYTHONPATH=

REM 执行巡检
echo [%date% %time%] Starting AOCI daily check...
%PYTHON_PATH% scripts\aoci_daily_check.py

REM 记录执行结果
if %ERRORLEVEL% EQU 0 (
    echo [%date% %time%] AOCI daily check completed successfully
) else (
    echo [%date% %time%] AOCI daily check completed with issues (exit code: %ERRORLEVEL%)
)
