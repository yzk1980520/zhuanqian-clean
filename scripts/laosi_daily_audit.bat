@echo off
REM 老四每日自检脚本 - Windows原生版本
REM 路径: D:/open code/zhuanqian/scripts/laosi_daily_audit.bat

cd /d "D:\open code\zhuanqian"
python scripts/laosi_audit.py --mode task
