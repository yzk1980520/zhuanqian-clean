@echo off
rem Zhuanqian_ClosedLoopHealth - daily closed-loop health report
rem Entry point for the Windows scheduled task of the same name.
rem Runs scripts/closedloop_health.py, appends to data/closedloop.log
rem ASCII ONLY: cmd parses a BOM-less .bat as GBK; non-ASCII bytes eat
rem string terminators and corrupt the following line.
set PYTHONPATH=
"D:\open code\zhuanqian\.venv\Scripts\python.exe" "D:\open code\zhuanqian\scripts\closedloop_health.py" >> "D:\open code\zhuanqian\data\closedloop.log" 2>&1
