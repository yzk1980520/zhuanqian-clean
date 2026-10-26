@echo off
rem QSP_GitSync wrapper - daily code sync ring T1 (Hermes governance plan v1, 2026-10-15 zongguan)
rem Weekdays 09:30: pytest gate -> push dual remotes -> verify remote main tip==HEAD
rem Output appended to data/git_sync.log (watch for P0 lines)
rem NOTE: keep this file ASCII-only - cmd.exe batch parser uses CP936, mangles UTF-8 comments
set PYTHONPATH=
rem Root-cause fix 2026-10-15: task env had no PYTHONUTF8 -> default CP936 made 4-6 tests raise
rem UnicodeDecodeError; interactive env (PYTHONUTF8=1) gives 85/85 green = verified baseline
set PYTHONUTF8=1
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "D:\open code\zhuanqian\scripts\git_sync_task.py" >> "D:\open code\zhuanqian\data\git_sync.log" 2>&1
