@echo off
chcp 65001 >nul
rem ------------------------------------------------------------------
rem 132d factor IC refresh (S3 gate authority source refresh).
rem Windows scheduled task: Zhuanqian_FactorIC132d (weekly, Sat 05:00)
rem Maps to cron_config.json -> events.factor_ic_132d_refresh
rem
rem WHY CANDIDATE MODE (no --apply):
rem   data/factor_ic/factor_ic_latest.json is the GATE authority source,
rem   its source tag is pure_python_v10_exact_132d, but the script that
rem   produced it was NEVER committed (whole-repo search found no producer).
rem   scripts/factor_ic_132d_refresh.py is a re-implementation and its IC
rem   values still diverge from the v10_exact baseline (see W1 report:
rem   momentum_20 +0.0382 vs -0.0293, overnight_sum20 +0.0428 vs -0.0043).
rem   Writing it over the authority automatically would silently corrupt
rem   the gate's evidence. So the scheduled run only produces a timestamped
rem   CANDIDATE + a per-factor diff vs the current authority, and prints
rem   [STALE] when the authority has not been refreshed for 14+ days.
rem   Switch to --apply ONLY after the engine is blessed (see deliverables).
rem
rem ASCII only. Do not add non-ASCII characters to this file.
rem ------------------------------------------------------------------
set PYTHONPATH=
set PYTHONUNBUFFERED=1
cd /d "D:\open code\zhuanqian"
".venv\Scripts\python.exe" scripts\factor_ic_132d_refresh.py --max-stocks 1000 --quiet --staleness-days 14 >> "%~dp0..\logs\scheduler.log" 2>&1
set IC_RC=%ERRORLEVEL%
echo [factor_ic_132d] refresh_rc=%IC_RC% mode=candidate(no --apply: engine not blessed) >> "%~dp0..\logs\scheduler.log"
exit /b %IC_RC%
