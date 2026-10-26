@echo off
rem QSP_LoopWatch wrapper - watchdog of watchdogs (2026-10-15 老六)
rem Daily 09:05: verify the probe layer itself is alive (SelfHeal/DrainWatch/MsgDrain/RemoteFreshness)
rem Output appended to data/loop_watch.log
set PYTHONPATH=
set PYTHONUTF8=1
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "D:\open code\zhuanqian\scripts\loop_watch.py" >> "D:\open code\zhuanqian\data\loop_watch.log" 2>&1
