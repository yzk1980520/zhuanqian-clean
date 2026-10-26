@echo off
rem Zhuanqian_HistoryRefresh - incremental TDX .day -> data/history_daily backfill
rem Carrier for P1#5 (2026-10-23, laosan): the 8/30 original refresh script was
rem never committed and was lost, leaving the extended library frozen at 10/20.
rem Rebuilt script: scripts/refresh_extended_data.py (idempotent, append-only,
rem atomic writes). Runs after TDX post-market download (16:00) and before the
rem 20:00 daily_auto chain. Appends to data/history_refresh.log.
rem
rem ASCII ONLY: cmd parses a BOM-less .bat as GBK; non-ASCII bytes corrupt lines.
set PYTHONPATH=
cd /d "D:\open code\zhuanqian"
"D:\open code\zhuanqian\.venv\Scripts\python.exe" "D:\open code\zhuanqian\scripts\refresh_extended_data.py" >> "D:\open code\zhuanqian\data\history_refresh.log" 2>&1
