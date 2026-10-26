@echo off
chcp 65001 >nul
rem ------------------------------------------------------------------
rem G5 anti-overfit: walk-forward mandatory run.
rem Windows scheduled task: Zhuanqian_WalkForward
rem   quarterly: Jan/Apr/Jul/Oct day 1, 06:30
rem Maps to cron_config.json -> events.walk_forward_quarterly
rem
rem Runs scripts/walk_forward_backtest.py (train 252 / test 63 / step 63)
rem and echoes the IS/OOS Sharpe decay into the scheduler log so the
rem overfit signal is visible without opening the result JSON.
rem
rem 2026-10-17 W8 (boss ruling): the decay is now a REAL blocking gate.
rem scripts/walk_forward_report.py delegates to scripts/walk_forward_gate.py
rem and propagates its exit code; this bat already exits with %RP_RC%, so the
rem scheduled task now FAILS when the decay gate blocks.
rem   exit 0 = gate passed
rem   exit 2 = no usable walk-forward result (fail loud)
rem   exit 3 = BLOCKED by the decay gate
rem NOTE: walk_forward_backtest.py itself still exits 0 on overfit warning -
rem it is a measurement script; the gate decision lives in walk_forward_gate.py.
rem
rem ASCII only. Do not add non-ASCII characters to this file.
rem ------------------------------------------------------------------
set PYTHONPATH=
set PYTHONUNBUFFERED=1
cd /d "D:\open code\zhuanqian"
".venv\Scripts\python.exe" scripts\walk_forward_backtest.py >> "%~dp0..\logs\scheduler.log" 2>&1
set WF_RC=%ERRORLEVEL%
if not "%WF_RC%"=="0" goto wf_failed
".venv\Scripts\python.exe" scripts\walk_forward_report.py >> "%~dp0..\logs\scheduler.log" 2>&1
set RP_RC=%ERRORLEVEL%
echo [walk_forward] wf_rc=%WF_RC% report_rc=%RP_RC% >> "%~dp0..\logs\scheduler.log"
exit /b %RP_RC%
:wf_failed
echo [walk_forward] wf_rc=%WF_RC% report=SKIPPED reason=walkforward_failed >> "%~dp0..\logs\scheduler.log"
exit /b %WF_RC%
