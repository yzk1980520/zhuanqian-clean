# ============================================================
#  Fix remaining 4 scheduled tasks (requires ADMINISTRATOR)
#
#  Why admin: 17 of 21 tasks were fixed without credentials.
#  These 4 return "Access is denied":
#    - Zhuanqian_DailyAuto      : RunLevel=Highest -> must be elevated
#    - QSP_PreMarket            : registration protected
#    - QSP_ZLJWatch             : registration protected
#    - Zhuanqian_BoardWatchdog  : registration protected
#
#  What changes (Settings only; command/triggers/credentials untouched):
#    StartWhenAvailable=true            run missed task at next opportunity
#    WakeToRun=true                     low-frequency tasks only
#    DisallowStartIfOnBatteries=false   run on battery
#    StopIfGoingOnBatteries=false
#
#  HOW TO RUN:
#    Start menu -> PowerShell -> right click -> Run as administrator -> paste:
#    powershell -ExecutionPolicy Bypass -File "D:\open code\zhuanqian\scripts\fix_schtasks_remaining_4.ps1"
#
#  ROLLBACK: set $FixedDir to .workbuddy\schtasks-backup-20261017 and run again
#
#  NOTE: this file is intentionally pure ASCII. Windows PowerShell 5.1 parses
#        a .ps1 without BOM as GBK, which mangles UTF-8 text and can break
#        string literals. ASCII avoids the whole class of failure.
# ============================================================

$ErrorActionPreference = 'Continue'
$FixedDir = 'D:\open code\zhuanqian\.workbuddy\schtasks-fixed-20261017'
$Tasks = @('QSP_PreMarket', 'QSP_ZLJWatch', 'Zhuanqian_BoardWatchdog', 'Zhuanqian_DailyAuto')

# --- 0. elevation self-check ---
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host ''
    Write-Host '[FAIL] Not running as Administrator - changes will be denied.' -ForegroundColor Red
    Write-Host '        Start menu -> PowerShell -> right click -> Run as administrator' -ForegroundColor Yellow
    exit 1
}
Write-Host ('[OK] Elevated. Fixing {0} tasks.' -f $Tasks.Count) -ForegroundColor Green
Write-Host ''

# --- 1. re-register each task ---
foreach ($n in $Tasks) {
    $xmlPath = Join-Path $FixedDir "$n.xml"
    if (-not (Test-Path $xmlPath)) {
        Write-Host ('[FAIL] {0} : XML not found -> {1}' -f $n, $xmlPath) -ForegroundColor Red
        continue
    }
    $xml = Get-Content -Raw -Path $xmlPath
    try {
        Register-ScheduledTask -TaskName $n -Xml $xml -Force -ErrorAction Stop | Out-Null
        Write-Host ('[OK] {0} : updated (Register-ScheduledTask)' -f $n) -ForegroundColor Green
    }
    catch {
        Write-Host ('      {0} : Register-ScheduledTask failed, trying schtasks.exe' -f $n) -ForegroundColor Yellow
        $out = & schtasks.exe /Create /TN $n /XML $xmlPath /F 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host ('[OK] {0} : updated (schtasks)' -f $n) -ForegroundColor Green
        }
        else {
            Write-Host ('[FAIL] {0} : {1}' -f $n, ($out -join ' ')) -ForegroundColor Red
        }
    }
}

# --- 2. verify ---
Write-Host ''
Write-Host '=== Verify (expect SWA=True, DisallowBatt=False) ==='
foreach ($n in $Tasks) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Host ('[FAIL] {0} : task not found' -f $n) -ForegroundColor Red
        continue
    }
    $s = $t.Settings
    $ok = $s.StartWhenAvailable -and (-not $s.DisallowStartIfOnBatteries)
    $color = 'Yellow'
    if ($ok) { $color = 'Green' }
    Write-Host ('{0,-26} SWA={1,-5} Wake={2,-5} DisallowBatt={3,-5} StopBatt={4,-5} State={5}' -f `
        $n, $s.StartWhenAvailable, $s.WakeToRun, $s.DisallowStartIfOnBatteries, $s.StopIfGoingOnBatteries, $t.State) `
        -ForegroundColor $color
}
Write-Host ''
Write-Host 'Done.'
