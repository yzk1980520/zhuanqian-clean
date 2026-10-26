@echo off
rem QSP_DrainWatch wrapper - alert-ring meta monitor M-1 (Hermes governance plan v1 T2, 2026-10-15 zongguan)
rem Every 5 min: watch QSP_MsgDrain liveness via data/drain_state.json (stale >=15min x2 -> P0 bot-API bypass)
rem Output appended to data/drain_meta.log
rem NOTE: keep this file ASCII-only - cmd.exe batch parser uses CP936, mangles UTF-8 comments
set PYTHONPATH=
set PYTHONUTF8=1
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "D:\open code\zhuanqian\scripts\drain_meta_check.py" >> "D:\open code\zhuanqian\data\drain_meta.log" 2>&1
