@echo off

REM elevate_task_wrap.bat - one-click elevated fix for the 3 tasks that a non-elevated

REM Set-ScheduledTask cannot rebind (2026-10-24 zongguan, popup-prohibition batch).

REM Right-click -> Run as administrator (single UAC), then it self-verifies.

setlocal

set "VBS=D:\open code\zhuanqian\scripts\run_path_hidden.vbs"

set "HH=D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"

set "ZH=D:\open code\zhuanqian"



echo [1/3] Hermes_GatewayHealthCheck -> wscript hidden wrap

schtasks /Change /TN "Hermes_GatewayHealthCheck" /TR "wscript.exe \"%VBS%\" \"%HH%\scripts\gw_supervisor_ensure.cmd\""

if errorlevel 1 (echo   !! FAIL GatewayHealthCheck) else (echo   OK)



echo [2/3] cua-driver-serve -> wscript hidden wrap

schtasks /Change /TN "cua-driver-serve" /TR "wscript.exe \"%VBS%\" \"%ZH%\scheduler\cua_driver_serve.cmd\""

if errorlevel 1 (echo   !! FAIL cua-driver-serve) else (echo   OK)



echo [3/3] Hermes_StockBoard -> wscript hidden wrap

schtasks /Change /TN "Hermes_StockBoard" /TR "wscript.exe \"%VBS%\" \"%ZH%\dashboards\open_board.bat\""

if errorlevel 1 (echo   !! FAIL StockBoard) else (echo   OK)



echo.

echo --- verify (live) ---

powershell -NoProfile -Command "foreach ($t in @('Hermes_GatewayHealthCheck','cua-driver-serve','Hermes_StockBoard')) { $a = (Get-ScheduledTask -TaskName $t).Actions | Select-Object -First 1; Write-Output ($t + ' | ' + $a.Execute + ' ' + $a.Arguments) }"

echo.


