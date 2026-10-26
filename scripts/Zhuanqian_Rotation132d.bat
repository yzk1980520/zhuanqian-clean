@echo off
chcp 65001 >nul
rem rotation_132d_full + rotation_132d_verify, chained in ONE scheduled task.
rem Windows scheduled task: Zhuanqian_Rotation132d (monthly, day 1, 04:00)
rem Maps to cron_config.json -> events.rotation_132d_full and events.rotation_132d_verify
rem
rem Step order matters:
rem   0. audit_delisted_coverage.py  - read-only, ~1 min. data/delisted_audit.json is
rem      gitignored, so on a fresh machine / cleaned data dir the sanity gate would fall
rem      back to a missing file and FAIL. Refreshing it monthly also keeps the 14-day
rem      freshness guard in tests/test_delisted_coverage.py from going red.
rem      Non-fatal on purpose: the authoritative evidence is the delisted_coverage field
rem      inside the fresh result JSON, so an audit hiccup must not burn the monthly slot.
rem      BUT non-fatal must not mean silent: if the audit fails, the OLD delisted_audit.json
rem      would still be on disk and the gate would judge expired evidence and pass in green.
rem      So on rc!=0 the stale file is renamed (kept, not deleted) to .stale_<timestamp>
rem      and an [AUDIT-FAILED] line is logged -> the gate then fails loudly instead.
rem   1. stamp                       - check_backtest_result_fresh.py --now prints the
rem      run-start timestamp (Python, not cmd: %date%/%time% is locale-fragile).
rem   2. auto_pipeline.py --wait     - MUST have --wait. Default (no --wait) returns as
rem      soon as the child is spawned, so later steps would read the PREVIOUS run's file.
rem   3. freshness gate              - result file must be newer than the step-1 stamp.
rem      Blocks the "backtest exited 0 but wrote nothing" hole: without it the sanity
rem      gate would judge last round's file and go fake-green. Non-zero -> verify skipped.
rem   4. check_backtest_sanity.py    - runs only after 2 really exited AND 3 passed.
rem ASCII only. Do not add non-ASCII characters to this file.
set PYTHONPATH=
set PYTHONUNBUFFERED=1
cd /d "D:\open code\zhuanqian"
".venv\Scripts\python.exe" scripts\audit_delisted_coverage.py >> "%~dp0..\logs\scheduler.log" 2>&1
set AU_RC=%ERRORLEVEL%
if "%AU_RC%"=="0" goto audit_ok
echo [AUDIT-FAILED] audit_rc=%AU_RC% delisted audit did not refresh -- quarantining stale evidence >> "%~dp0..\logs\scheduler.log"
if not exist "data\delisted_audit.json" goto audit_ok
for /f "delims=" %%i in ('".venv\Scripts\python.exe" scripts\check_backtest_result_fresh.py --now') do set AUD_TS=%%i
if "%AUD_TS%"=="" set AUD_TS=no-timestamp
if not "%AUD_TS%"=="no-timestamp" set AUD_TS=%AUD_TS::=%
move /y "data\delisted_audit.json" "data\delisted_audit.json.stale_%AUD_TS%" >> "%~dp0..\logs\scheduler.log" 2>&1
echo [AUDIT-FAILED] moved stale file to data\delisted_audit.json.stale_%AUD_TS% (kept for evidence) >> "%~dp0..\logs\scheduler.log"
:audit_ok
for /f "delims=" %%i in ('".venv\Scripts\python.exe" scripts\check_backtest_result_fresh.py --now') do set START_TS=%%i
".venv\Scripts\python.exe" scripts\auto_pipeline.py --wait >> "%~dp0..\logs\scheduler.log" 2>&1
set BT_RC=%ERRORLEVEL%
if not "%BT_RC%"=="0" goto bt_failed
".venv\Scripts\python.exe" scripts\check_backtest_result_fresh.py --since %START_TS% --file data\rotation_backtest_result.json >> "%~dp0..\logs\scheduler.log" 2>&1
set FR_RC=%ERRORLEVEL%
if not "%FR_RC%"=="0" goto not_fresh
".venv\Scripts\python.exe" backtest/check_backtest_sanity.py data\rotation_backtest_result.json >> "%~dp0..\logs\scheduler.log" 2>&1
set VE_RC=%ERRORLEVEL%
echo [rotation_132d] audit_rc=%AU_RC% backtest_rc=%BT_RC% fresh_rc=%FR_RC% verify_rc=%VE_RC% >> "%~dp0..\logs\scheduler.log"
exit /b %VE_RC%
:bt_failed
echo [rotation_132d] audit_rc=%AU_RC% backtest_rc=%BT_RC% verify=SKIPPED reason=backtest_failed >> "%~dp0..\logs\scheduler.log"
exit /b %BT_RC%
:not_fresh
echo [rotation_132d] audit_rc=%AU_RC% backtest_rc=%BT_RC% fresh_rc=%FR_RC% verify=SKIPPED reason=result_not_fresh >> "%~dp0..\logs\scheduler.log"
exit /b %FR_RC%
