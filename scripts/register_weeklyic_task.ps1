# =============================================================
# register_weeklyic_task.ps1
# Registers the Windows scheduled task: Zhuanqian_WeeklyIC
# Entry: wscript.exe run_path_hidden.vbs -> Zhuanqian_WeeklyIC.bat
#        -> cron_dispatcher.py --event weekly_ic
#        -> fake_positive_detector.py (the fake-green detector)
# Schedule: WEEKLY Sunday 04:30. NO immediate run.
# ASCII ONLY. PowerShell 5.1 parses a BOM-less .ps1 as GBK and
# non-ASCII bytes eat string terminators -> parse errors.
#
# WHY THIS TASK EXISTS (2026-10-19):
#   fake_positive_detector.py had NO execution carrier. The weekly_ic event
#   was only registered in cron_config.json - a ledger that nothing executes.
#   The nearest existing task, QSP_Weekly, belongs to a DIFFERENT project
#   (.quant-stock-picker) and its run_weekly.py never touches weekly_ic or
#   the detector (grep: zero hits). Measured stall: 1104.7h (46 days).
#
# SILENT EXECUTION (rule 1, no terminal popup ever):
#   Never point the task at the .bat directly - cmd.exe and its python child
#   open a console window in the interactive session. Reuse the repo's
#   existing silent runner scripts\run_path_hidden.vbs
#   (WshShell.Run "cmd /c <bat>", 0, False). Do not write a second runner.
#   <Hidden>true</Hidden> is set as a second layer.
#
# Run from an ELEVATED PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\register_weeklyic_task.ps1
# =============================================================
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Zhuanqian_WeeklyIC'
$Root     = 'D:\open code\zhuanqian'
$BatPath  = Join-Path $Root 'scripts\Zhuanqian_WeeklyIC.bat'
$XmlOut   = Join-Path $Root 'scripts\Zhuanqian_WeeklyIC.task.xml'

Write-Host '=== Zhuanqian_WeeklyIC registration ==='

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
# Weekly Sunday 04:30: clear of Friday 15:15 (QSP_Weekly, other project),
# Saturday 05:00 (FactorIC132d) and the daily 07:30 health check.
$nextRun = ((Get-Date).Date.AddDays(1)).ToString('yyyy-MM-dd') + 'T04:30:00'
$now     = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')

$xmlTemplate = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{0}</Date>
    <Author>DESKTOP-THU5BUJ\WIN10</Author>
    <Description>Weekly fake-positive detection + IC monitor. Runs scripts/cron_dispatcher.py --event weekly_ic (which invokes scripts/fake_positive_detector.py) via the silent VBS runner. Without this task the detector has no execution carrier: it stalled 1104.7h (46 days) while cron_config.json still listed weekly_ic, because that ledger executes nothing.</Description>
    <URI>\Zhuanqian_WeeklyIC</URI>
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
    Write-Host '[NOTE] No immediate run was scheduled.'
    exit 0
} else {
    Write-Host '[FAIL] Task not found after registration.'
    exit 6
}
