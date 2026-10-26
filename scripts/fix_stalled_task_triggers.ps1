# =============================================================================
# fix_stalled_task_triggers.ps1  (ASCII ONLY - PS5 reads GBK, avoid CJK)
# Fix 3 stalled (267011=0x41303) scheduled tasks: triggers were mis-set as
# one-shot(onetime), restore to daily/periodic.
#
# Root cause (2026-10-26 zongguan deep analysis, first-hand evidence):
#   Zhuanqian_HistoryRefresh  StartBoundary=2026-10-24T16:30 no-repeat -> stopped after 10-24
#   Zhuanqian_BoardWatchdog   StartBoundary=empty, no valid trigger    -> never runs
#   Zhuanqian_WalkForward     StartBoundary=2026-11-01T06:30 no-repeat -> deferred to 11-1
#   (healthy control Zhuanqian_DailyAuto: daily 20:00 repeat, LastRun continuous, Result=0)
#   runners smoke-tested healthy (refresh_extended_data.py exit=0, 9671 .day caught up),
#   so the fault is trigger config only, NOT the scripts.
#
# Usage (run as ADMIN PowerShell):
#   powershell.exe -ExecutionPolicy Bypass -File "D:\open code\zhuanqian\scripts\fix_stalled_task_triggers.ps1"
# =============================================================================
$ErrorActionPreference = 'Stop'

$backup = "D:\open code\zhuanqian\data\backup\tasks_20261026"
New-Item -ItemType Directory -Force -Path $backup | Out-Null

$targets = @('Zhuanqian_HistoryRefresh','Zhuanqian_BoardWatchdog','Zhuanqian_WalkForward')

# --- 1. backup current task XML (rollback path; needs admin to read .Xml) ---
foreach ($tn in $targets) {
    $t = Get-ScheduledTask -TaskName $tn
    if ($null -ne $t -and $null -ne $t.Xml) {
        [xml]$x = $t.Xml
        $x.Save("$backup\$tn.xml")
        Write-Host "[backup] $tn OK"
    } else {
        Write-Host "[backup] $tn SKIP (.Xml null -> re-run as ADMIN to backup+apply)"
    }
}

# --- 2. rebuild triggers (keep Action + Settings, replace Trigger only) ---
# HistoryRefresh: daily 16:30 (after TDX post-market 16:00 download, before 20:00 daily_auto)
$t = Get-ScheduledTask -TaskName 'Zhuanqian_HistoryRefresh'
$t.Triggers = @((New-ScheduledTaskTrigger -Daily -At '16:30'))
Set-ScheduledTask -TaskName 'Zhuanqian_HistoryRefresh' -InputObject $t
Write-Host "[trigger] Zhuanqian_HistoryRefresh -> Daily 16:30"

# BoardWatchdog: daily hourly 09:00-21:00 (covers trading session)
$t = Get-ScheduledTask -TaskName 'Zhuanqian_BoardWatchdog'
$t.Triggers = @((New-ScheduledTaskTrigger -Daily -At '09:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 60) `
    -RepetitionDuration (New-TimeSpan -Hours 12)))
Set-ScheduledTask -TaskName 'Zhuanqian_BoardWatchdog' -InputObject $t
Write-Host "[trigger] Zhuanqian_BoardWatchdog -> Hourly 09:00-21:00"

# WalkForward: daily 06:30 (pre-market walk-forward backtest)
$t = Get-ScheduledTask -TaskName 'Zhuanqian_WalkForward'
$t.Triggers = @((New-ScheduledTaskTrigger -Daily -At '06:30'))
Set-ScheduledTask -TaskName 'Zhuanqian_WalkForward' -InputObject $t
Write-Host "[trigger] Zhuanqian_WalkForward -> Daily 06:30"

# --- 3. fire once to prove runners start ---
foreach ($tn in $targets) {
    Start-ScheduledTask -TaskName $tn
    Write-Host "[start] $tn"
}
Start-Sleep -Seconds 10

# --- 4. verify: LastRun no longer 1999 sentinel + NextRun sensible ---
Write-Host ""
Write-Host "=== VERIFY ==="
foreach ($tn in $targets) {
    $i = Get-ScheduledTaskInfo -TaskName $tn
    $yr = $i.LastRunTime.Year
    if ($yr -lt 2000) { $lr = "1999-sentinel(never-ran!)" } else { $lr = $i.LastRunTime }
    Write-Host ("$tn : LastRun=" + $lr + " NextRun=" + $i.NextRunTime + " LastResult=" + $i.LastTaskResult)
}
Write-Host ""
Write-Host "PASS = LastRun no longer 1999 AND NextRun is near-term"
Write-Host "rollback: original configs saved to $backup (use Import-ScheduledTask)"
Write-Host "Done."
