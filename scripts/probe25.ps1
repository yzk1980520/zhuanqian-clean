# 看板 watchdog 守护脚本（总管 2026-09-26�?# 作用：循环检�?8666 端口看板服务，掉线自动静默拉起，不弹任何终端窗口
# 原理：board_server.py 仅依赖标准库 http.server，无定时任务，页面请求实时重读数�?$ErrorActionPreference = "Continue"

# 当前看板实际使用的解释器（PID 18024 同源，纯标准库够用）
$py     = "D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\installs\729b2843d1f89bbe\environments\c5158a71878a4e71baff487393e934ef\venv\Scripts\python.exe"
$server = "D:\open code\zhuanqian\dashboards\board_server.py"
$log    = "D:\open code\zhuanqian\dashboards\board_watchdog.log"
$errlog = "D:\open code\zhuanqian\dashboards\board_server.err.log"
$outlog = "D:\open code\zhuanqian\dashboards\board_server.out.log"

function Test-Board {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8666/board" -TimeoutSec 4 -UseBasicParsing
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Start-BoardHidden {
  # 静默启动，不弹窗口；-ArgumentList 用数组传路径，PowerShell 自动给含空格路径加引�?  Start-Process -FilePath $py -ArgumentList @($server) -WindowStyle Hidden -RedirectStandardOutput $outlog -RedirectStandardError $errlog
}

Add-Content $log ("$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') watchdog 启动 (PID " + $PID + ")")
while ($true) {
  if (-not (Test-Board)) {
    Start-BoardHidden
