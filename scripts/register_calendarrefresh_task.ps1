# =============================================================
# register_calendarrefresh_task.ps1
# Registers the Windows scheduled task: Zhuanqian_CalendarRefresh
# Entry: wscript.exe run_path_hidden.vbs -> Zhuanqian_CalendarRefresh.bat
#        -> _refresh_trading_calendar.py  (project ROOT, not scripts/)
# Schedule: WEEKLY Sunday 05:45. NO immediate run.
# ASCII ONLY. PowerShell 5.1 parses a BOM-less .ps1 as GBK and
# non-ASCII bytes eat string terminators -> parse errors.
#
# WHY THIS TASK EXISTS (2026-10-20, laoliu):
#   trading_hours.py ENFORCES a real fail-close on calendar staleness:
#   pulled_at older than 7 days => every weekday intraday slot returns False
#   => the pick/buy chain halts. Before today the check was DECORATIVE:
#   _check_calendar_freshness() printed "all weekday intraday will fail-CLOSE
#   (system locked)" but its return value was DISCARDED at the call site, and
#   worse, `_calendar_warned` short-circuited to `return True`, so from the
#   2nd call onwards it reported "fresh" no matter what. Measured: calendar
#   pulled_at 2026-10-09 (11 days stale) yet is_trading_hours() still True.
#   Fixing that turns "forget to refresh" into "system stops", so a scheduled
#   carrier is now MANDATORY - not a nice-to-have.
#   Prior state: ZERO of the existing scheduled tasks ran the calendar refresh.
#
# SILENT EXECUTION (rule 1, no terminal popup ever):
#   Never point the task at the .bat directly - cmd.exe and its python child
#   open a console window in the interactive session. Reuse the repo's
#   existing silent runner scripts\run_path_hidden.vbs
#   (WshShell.Run "cmd /c <bat>", 0, False). Do not write a second runner.
#   <Hidden>true</Hidden> is set as a second layer.
#
# Run from an ELEVATED PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\register_calendarrefresh_task.ps1
# =============================================================
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Zhuanqian_CalendarRefresh'
$Root     = 'D:\open code\zhuanqian'
$BatPath  = Join-Path $Root 'scripts\Zhuanqian_CalendarRefresh.bat'
$XmlOut   = Join-Path $Root 'scripts\Zhuanqian_CalendarRefresh.task.xml'

Write-Host '=== Zhuanqian_CalendarRefresh registration ==='

# --- 1. privilege check ---
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '[WARN] Current session is NOT elevated (no Administrator token).'
    Write-Host '[WARN] Re-run from an Administrator PowerShell:'
    Write-Host ('         powershell -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
    Write-Host ('[WARN] Admin fallback: schtasks /Create /TN ' + $TaskName + ' /XML "' + $XmlOut + '" /F')
} else {
    Write-Host '[OK] Elevated (Administrator token present).'
}

# --- 2. guard: never clobber a task other than this exact one ---
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$doReplace = $false
if ($existing) {
    if ($existing.TaskName -ne $TaskName) {
        Write-Host ('[ABORT] Name mismatch: ' + $existing.TaskName)
        exit 8
    }
    if (-not $Force) {
        Write-Host ('[ABORT] Task "' + $TaskName + '" already exists. Use -Force to overwrite.')
        Write-Host ('         powershell -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Force')
        exit 3
    }
    Write-Host ('[WARN] -Force: will overwrite ONLY "' + $TaskName + '".')
    $doReplace = $true
}

# --- 3. entry points must exist ---
if (-not (Test-Path $BatPath)) {
    Write-Host ('[ABORT] Entry point not found: ' + $BatPath)
    exit 4
}
Write-Host ('[OK] Entry point: ' + $BatPath)
$SilentVbs = Join-Path $Root 'scripts\run_path_hidden.vbs'
if (-not (Test-Path $SilentVbs)) {
    Write-Host ('[ABORT] Silent runner not found: ' + $SilentVbs)
    Write-Host '[ABORT] Refusing to register a task that would pop a console window.'
    exit 9
}
Write-Host ('[OK] Silent runner: ' + $SilentVbs)

# --- 4. build the task XML ---
# Weekly Sunday 05:45: clear of Sunday 04:30 (Zhuanqian_WeeklyIC),
# Saturday 05:00 (FactorIC132d) and the daily 07:30 health check.
$today    = (Get-Date).Date
$delta    = ([int][DayOfWeek]::Sunday - [int]$today.DayOfWeek + 7) % 7
if ($delta -eq 0) { $delta = 7 }   # today is Sunday: take next week
$nextRun  = $today.AddDays($delta).ToString('yyyy-MM-dd') + 'T05:45:00'
$now      = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')

$xmlTemplate = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{0}</Date>
    <Author>DESKTOP-THU5BUJ\WIN10</Author>
    <Description>Forward trading-calendar refresh. Runs _refresh_trading_calendar.py via the silent VBS runner. MANDATORY since 2026-10-20: trading_hours.py now enforces a real fail-close, so a stale calendar (pulled_at older than 7 days) halts the entire pick/buy chain. Before this task existed zero scheduled tasks refreshed the calendar and pulled_at went 11 days stale.</Description>
    <URI>\Zhuanqian_CalendarRefresh</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{1}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Sunday />
        </DaysOfWeek>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <Hidden>true</Hidden>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <IdleSettings>
      <Duration>PT10M</Duration>
      <WaitTimeout>PT1H</WaitTimeout>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{2}</Command>
      <Arguments>{4}</Arguments>
      <WorkingDirectory>{3}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'@

$WscriptPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$VbsPath     = Join-Path $Root 'scripts\run_path_hidden.vbs'
$TaskArgs    = '&quot;' + $VbsPath + '&quot; &quot;' + $BatPath + '&quot;'
$xml = $xmlTemplate -f $now, $nextRun, $WscriptPath, $Root, $TaskArgs

try {
    $null = [xml]$xml
    Write-Host '[OK] Task XML parses.'
} catch {
    Write-Host ('[ABORT] Task XML invalid: ' + $_.Exception.Message)
    exit 7
}

try {
    [System.IO.File]::WriteAllText($XmlOut, $xml, [System.Text.Encoding]::Unicode)
    Write-Host ('[OK] Task XML written: ' + $XmlOut)
} catch {
    Write-Host ('[WARN] Could not persist XML: ' + $_.Exception.Message)
}

if ($doReplace) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false | Out-Null
    Write-Host '[OK] Previous registration removed.'
}

try {
    Register-ScheduledTask -TaskName $TaskName -Xml $xml | Out-Null
    Write-Host ('[OK] Registered: ' + $TaskName)
} catch {
    Write-Host ('[FAIL] Register-ScheduledTask threw: ' + $_.Exception.Message)
    Write-Host ('[FAIL] Admin fallback: schtasks /Create /TN ' + $TaskName + ' /XML "' + $XmlOut + '" /F')
    exit 5
}

$check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($check) {
    Write-Host '[OK] Verified via Get-ScheduledTask.'
    Write-Host ('     State   : ' + $check.State)
    Write-Host ('     NextRun : ' + $nextRun)
    Write-Host '[NOTE] No immediate run was scheduled.'
    exit 0
} else {
    Write-Host '[FAIL] Task not found after registration.'
    exit 6
}
