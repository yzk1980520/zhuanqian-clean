@echo off
rem Zhuanqian_WeeklyIC - weekly IC monitor + fake-positive detection
rem Entry point for the Windows scheduled task of the same name.
rem Runs scripts/cron_dispatcher.py --event weekly_ic and appends to
rem data/weekly_ic.log
rem ASCII ONLY: cmd parses a BOM-less .bat as GBK; non-ASCII bytes eat
rem string terminators and corrupt the following line.
set PYTHONPATH=
"D:\open code\zhuanqian\.venv\Scripts\python.exe" "D:\open code\zhuanqian\scripts\cron_dispatcher.py" --event weekly_ic >> "D:\open code\zhuanqian\data\weekly_ic.log" 2>&1
