@echo off
rem Zhuanqian_CalendarRefresh - forward trading-calendar refresh
rem Entry point for the Windows scheduled task of the same name.
rem Runs _refresh_trading_calendar.py (project root, NOT scripts/) and appends
rem to data/calendar_refresh.log
rem
rem WHY THIS EXISTS (2026-10-20, laoliu):
rem   trading_hours.py now enforces a REAL fail-close on calendar staleness.
rem   pulled_at older than 7 days => every weekday intraday slot returns False
rem   => the whole pick/buy chain halts. That is the intended fail-close
rem   semantics, but it turns "forgot to refresh" into "system stops".
rem   Therefore a scheduled carrier is MANDATORY, not optional.
rem   Prior state: pulled_at was 11 days stale (2026-10-09) with ZERO carrier
rem   among all scheduled tasks.
rem
rem ASCII ONLY: cmd parses a BOM-less .bat as GBK; non-ASCII bytes eat
rem string terminators and corrupt the following line.
set PYTHONPATH=
cd /d "D:\open code\zhuanqian"
"D:\open code\zhuanqian\.venv\Scripts\python.exe" "D:\open code\zhuanqian\_refresh_trading_calendar.py" >> "D:\open code\zhuanqian\data\calendar_refresh.log" 2>&1
