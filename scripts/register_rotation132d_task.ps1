# =============================================================
# register_rotation132d_task.ps1
# Registers the Windows scheduled task: Zhuanqian_Rotation132d
# Maps to cron_config.json -> events.rotation_132d_full
# Schedule: monthly, day 1, 04:00. NO immediate run.
# ASCII ONLY. PowerShell 5.1 parses a BOM-less .ps1 as GBK and
# non-ASCII bytes eat string terminators -> parse errors.
#
# Note: this machine's ScheduledTasks module has no -Monthly /
# -DaysOfMonth on New-ScheduledTaskTrigger, so the task is
# registered from an explicit XML (same shape as the backups in
# .workbuddy/schtasks-backup-20261017/) via Register-ScheduledTask -Xml.
# =============================================================
# -Force: overwrite an EXISTING task of this exact name only (re-registration
#         after the bat changed). Never touches any other task.
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Zhuanqian_Rotation132d'
$Root     = 'D:\open code\zhuanqian'
$BatPath  = Join-Path $Root 'scripts\Zhuanqian_Rotation132d.bat'
$XmlOut   = Join-Path $Root 'scripts\Zhuanqian_Rotation132d.task.xml'

Write-Host '=== Zhuanqian_Rotation132d registration ==='

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
    # Deferred: the old task is only removed AFTER the new XML validates, otherwise a
    # bad XML would leave us with the old task deleted and no new one registered.
    $doReplace = $true
}

# --- 3. entry point must exist ---
if (-not (Test-Path $BatPath)) {
    Write-Host ('[ABORT] Entry point not found: ' + $BatPath)
    exit 4
}
Write-Host ('[OK] Entry point: ' + $BatPath)

# --- 4. build the task XML ---
# Monthly day 1 at 04:00: avoids the 15:30-15:40 post-close peak and the 22:35 sanity run.
$nextRun = (Get-Date).AddMonths(1).ToString('yyyy-MM') + '-01T04:00:00'
$now     = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')

$xmlTemplate = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{0}</Date>
    <Author>DESKTOP-THU5BUJ\WIN10</Author>
    <Description>rotation_132d_full + rotation_132d_verify chained in one task: scripts/Zhuanqian_Rotation132d.bat runs (0) audit_delisted_coverage.py [read-only, ~1min, refreshes the gitignored data/delisted_audit.json; on rc!=0 the stale file is renamed to .stale_TIMESTAMP (kept) + [AUDIT-FAILED] logged, so the gate fails loudly instead of passing on expired evidence], (1) stamp the run-start time, (2) "auto_pipeline.py --wait" [blocks until the backtest really finishes], (3) freshness gate check_backtest_result_fresh.py [result file mtime must be newer than the stamp, blocks fake-green], (4) "check_backtest_sanity.py data/rotation_backtest_result.json". Ledger: cron_config.json events.rotation_132d_full / events.rotation_132d_verify.</Description>
    <URI>\Zhuanqian_Rotation132d</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{1}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByMonth>
        <DaysOfMonth>
          <Day>1</Day>
        </DaysOfMonth>
        <Months>
          <January />
          <February />
          <March />
          <April />
          <May />
          <June />
          <July />
          <August />
          <September />
          <October />
          <November />
          <December />
        </Months>
      </ScheduleByMonth>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
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
      <WorkingDirectory>{3}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'@

$xml = $xmlTemplate -f $now, $nextRun, $BatPath, $Root

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

# --- 6. verify ---
$check = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($check) {
    Write-Host '[OK] Verified via Get-ScheduledTask.'
    Write-Host ('     State   : ' + $check.State)
    Write-Host ('     Trigger : ' + (($check.Triggers | ForEach-Object { $_.StartBoundary }) -join ', '))
    Write-Host '[NOTE] No immediate run was scheduled. Next run: day 1 of next month, 04:00.'
    exit 0
} else {
    Write-Host '[FAIL] Task not found after registration.'
    exit 6
}
