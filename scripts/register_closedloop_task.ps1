# =============================================================
# register_closedloop_task.ps1
# Registers the Windows scheduled task: Zhuanqian_ClosedLoopHealth
# Entry: wscript.exe run_path_hidden.vbs -> Zhuanqian_ClosedLoopHealth.bat
#        -> closedloop_health.py
# Schedule: DAILY 07:30. NO immediate run.
#
# SILENT EXECUTION (rule 1, no terminal popup ever):
#   Do NOT point the task at the .bat directly. A .bat runs under cmd.exe and
#   its python.exe child opens a console window in the interactive session.
#   The repo already owns the fix: scripts\run_path_hidden.vbs calls
#   WshShell.Run "cmd /c <bat>", 0, False  (0 = hidden window, False = no wait).
#   Reusing that VBS is mandatory - do not write a second silent runner.
#   Task-level <Hidden>true</Hidden> is set as a second layer, matching the
#   convention used by the other Zhuanqian/QSP tasks.
# ASCII ONLY. PowerShell 5.1 parses a BOM-less .ps1 as GBK and
# non-ASCII bytes eat string terminators -> parse errors.
#
# WHY THIS TASK EXISTS (2026-10-19):
#   closedloop_health.py had NO scheduling carrier at all - 24 checked
#   scheduled tasks, none of them invoked it. It had been stalled 36h20m
#   while still reporting a perfect 10/10, because A6 only checked that
#   the string "self_audit" appeared in cron_config.json (a ledger that
#   does not execute anything). A0 can DETECT the stall; only this task
#   can PREVENT it.
#
# Run from an ELEVATED PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\register_closedloop_task.ps1
# =============================================================
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Zhuanqian_ClosedLoopHealth'
$Root     = 'D:\open code\zhuanqian'
$BatPath  = Join-Path $Root 'scripts\Zhuanqian_ClosedLoopHealth.bat'
$XmlOut   = Join-Path $Root 'scripts\Zhuanqian_ClosedLoopHealth.task.xml'

Write-Host '=== Zhuanqian_ClosedLoopHealth registration ==='

# --- 1. privilege check (fail loudly, never silently) ---
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '[WARN] Current session is NOT elevated (no Administrator token).'
    Write-Host '[WARN] Register-ScheduledTask normally requires an elevated PowerShell.'
    Write-Host '[WARN] If registration fails below, re-run from an Administrator PowerShell:'
    Write-Host ('         powershell -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"')
    Write-Host ('[WARN] Admin fallback (no cmdlet needed):')
    Write-Host ('         schtasks /Create /TN ' + $TaskName + ' /XML "' + $XmlOut + '" /F')
} else {
    Write-Host '[OK] Elevated (Administrator token present).'
}

# --- 2. guard: never clobber a task other than this exact one ---
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$doReplace = $false
if ($existing) {
    if ($existing.TaskName -ne $TaskName) {
        Write-Host ('[ABORT] Name mismatch, refusing to touch: ' + $existing.TaskName)
        exit 8
    }
    if (-not $Force) {
        Write-Host ('[ABORT] Task "' + $TaskName + '" already exists. Refusing to modify it.')
        Write-Host ('[ABORT] Re-run with -Force to overwrite ONLY "' + $TaskName + '":')
        Write-Host ('         powershell -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Force')
        exit 3
    }
    Write-Host ('[WARN] -Force given: will overwrite existing task "' + $TaskName + '" (this name only).')
    $doReplace = $true
}

# --- 3. entry point must exist ---
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
# Daily 07:30: after the 05:00 factor IC slot, before the 09:30 git sync,
# and clear of the 20:00 laosi self-audit that A6 depends on.
$nextRun = ((Get-Date).Date.AddDays(1)).ToString('yyyy-MM-dd') + 'T07:30:00'
$now     = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')

$xmlTemplate = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{0}</Date>
    <Author>DESKTOP-THU5BUJ\WIN10</Author>
    <Description>Daily closed-loop health report. Runs scripts/closedloop_health.py via scripts/Zhuanqian_ClosedLoopHealth.bat and appends to data/closedloop.log. Without this task the health checker has no execution carrier: it stalled 36h on 2026-10-17..18 while still reporting a perfect score. A0 detects such stalls; this task is what prevents them.</Description>
    <URI>\Zhuanqian_ClosedLoopHealth</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{1}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
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

# Silent chain: wscript.exe run_path_hidden.vbs "<bat>"  (hidden, no wait)
$WscriptPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$VbsPath     = Join-Path $Root 'scripts\run_path_hidden.vbs'
$TaskArgs    = '&quot;' + $VbsPath + '&quot; &quot;' + $BatPath + '&quot;'
$xml = $xmlTemplate -f $now, $nextRun, $WscriptPath, $Root, $TaskArgs

# XML must parse before we hand it to Task Scheduler
try {
    $null = [xml]$xml
    Write-Host '[OK] Task XML parses.'
} catch {
    Write-Host ('[ABORT] Task XML is invalid: ' + $_.Exception.Message)
    exit 7
}

# persist it so an admin can import it with schtasks /Create /XML if the cmdlet is blocked
try {
    [System.IO.File]::WriteAllText($XmlOut, $xml, [System.Text.Encoding]::Unicode)
    Write-Host ('[OK] Task XML written: ' + $XmlOut)
} catch {
    Write-Host ('[WARN] Could not persist task XML: ' + $_.Exception.Message)
}

# --- 5. remove the previous registration only now that the XML is known-good ---
if ($doReplace) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false | Out-Null
    Write-Host '[OK] Previous registration removed.'
}

# --- 6. register ---
try {
    Register-ScheduledTask -TaskName $TaskName -Xml $xml | Out-Null
    Write-Host ('[OK] Registered: ' + $TaskName)
} catch {
    Write-Host ('[FAIL] Register-ScheduledTask threw: ' + $_.Exception.Message)
    Write-Host '[FAIL] Most likely cause: insufficient privileges (access denied).'
    Write-Host ('[FAIL] Admin fallback: schtasks /Create /TN ' + $TaskName + ' /XML "' + $XmlOut + '" /F')
    exit 5
}

# --- 7. verify ---
$check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($check) {
    Write-Host '[OK] Verified via Get-ScheduledTask.'
    Write-Host ('     State   : ' + $check.State)
    Write-Host ('     Trigger : ' + (($check.Triggers | ForEach-Object { $_.StartBoundary }) -join ', '))
    Write-Host '[NOTE] No immediate run was scheduled.'
    exit 0
} else {
    Write-Host '[FAIL] Task not found after registration.'
    exit 6
}
