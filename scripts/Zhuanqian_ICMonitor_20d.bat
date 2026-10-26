@echo off
@setlocal
REM ============================================================================
REM Zhuanqian_ICMonitor_20d — v2因子 20日滚动IC 生产监控 (总管 2026-09-27 注册)
REM 老五第3件锚点: 任务名=Zhuanqian_ICMonitor_20d, 脚本 scripts\factor_ic_monitor_20d.py
REM 口径: 复用 factor_ic_scan.spearman (与门禁同算术), 只写告警标志+建议, 不自动翻 factor_v2.json
REM 退出码: 0=无告警 / 3=有因子告警(需人工复核) / 2=样本不足
REM 解释器: Python311 (numpy/pandas/scipy 齐), 清 PYTHONPATH, 无窗口
REM ============================================================================
@set "PY=C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe"
chcp 65001 >nul
cd /d "D:\open code\zhuanqian" || exit /b 1
set PYTHONPATH=
if not exist "scripts\factor_ic_monitor_20d.py" (
    echo [%date% %time%] ERR factor_ic_monitor_20d.py missing >> mainline\logs\ic_monitor_20d.log
    exit /b 1
)
echo [%date% %time%] === Zhuanqian_ICMonitor_20d 开始 === >> mainline\logs\ic_monitor_20d.log
"%PY%" scripts\factor_ic_monitor_20d.py 100 >> mainline\logs\ic_monitor_20d.log 2>&1
@set RC=%ERRORLEVEL%
echo [%date% %time%] === 结束 exit=%RC% (0正常/3因子告警/2样本不足) >> mainline\logs\ic_monitor_20d.log
exit /b %RC%
