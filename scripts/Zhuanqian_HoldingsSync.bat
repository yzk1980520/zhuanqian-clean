@echo off
rem Zhuanqian_HoldingsSync - holdings.json -> QSP real_holdings.json + real_trade_log.json
rem Carrier added 2026-10-23 (laosan, P1#5 adjacent finding): QSP-side real
rem source was stale since 10/14 (no scheduled carrier existed; 9-day lag =
rem QSP risk layer deciding on stale prices). Idempotent, atomic write+verify.
rem
rem ASCII ONLY: cmd parses a BOM-less .bat as GBK; non-ASCII bytes corrupt lines.
set PYTHONPATH=
cd /d "D:\open code\zhuanqian"
"D:\open code\zhuanqian\.venv\Scripts\python.exe" "D:\open code\zhuanqian\scripts\sync_holdings.py" >> "D:\open code\zhuanqian\data\holdings_sync.log" 2>&1
