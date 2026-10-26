# =============================================================
# register_walkforward_task.ps1
# Registers the Windows scheduled task: Zhuanqian_WalkForward
# Maps to cron_config.json -> events.walk_forward_quarterly
# Schedule: quarterly, Jan/Apr/Jul/Oct day 1, 06:30. NO immediate run.
# ASCII ONLY. PowerShell 5.1 parses a BOM-less .ps1 as GBK and
# non-ASCII bytes eat string terminators -> parse errors.
#
# G5: walk-forward is the mandatory anti-overfit cadence check.
# Registered from an explicit XML (same shape as
# register_rotation132d_task.ps1).
# =============================================================
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$TaskName = 'Zhuanqian_WalkForward'
$Root     = 'D:\open code\zhuanqian'
$BatPath  = Join-Path $Root 'scripts\Zhuanqian_WalkForward.bat'
$XmlOut   = Join-Path $Root 'scripts\Zhuanqian_WalkForward.task.xml'

Write-Host '=== Zhuanqian_WalkForward registration ==='

# --- 1. privilege check (fail loudly, never silently) ---
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin   = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '[WARN] Current session is NOT elevated (no Administrator token).'
    Write-Host '[WARN] If registration fails below, re-run from an Administrator PowerShell:'
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
        Write-Host ('[ABORT] Name mismatch, refusing to touch: ' + $existing.TaskName)
        exit 8
    }
    if (-not $Force) {
        Write-Host ('[ABORT] Task "' + $TaskName + '" already exists. Refusing to modify it.')
        Write-Host ('[ABORT] Re-run with -Force to overwrite ONLY "' + $TaskName + '".')
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

# --- 4. build the task XML ---
# Quarterly day 1 at 06:30: after the 04:00 rotation_132d slot and well
# before the 15:30-15:40 post-close peak.
$nextRun = (Get-Date).Date.AddMonths(1).ToString('yyyy-MM') + '-01T06:30:00'
$now     = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')

$xmlTemplate = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>{0}</Date>
    <Author>DESKTOP-THU5BUJ\WIN10</Author>
    <Description>G5 anti-overfit mandatory cadence: scripts/Zhuanqian_WalkForward.bat runs scripts/walk_forward_backtest.py (train 252 / test 63 / step 63) then scripts/walk_forward_report.py, which echoes the IS/OOS Sharpe decay into logs/scheduler.log. walk_forward_backtest.py still exits 0 when decay > 0.1, so the report line is the only visible overfit signal; promoting the decay into a blocking gate is a boss policy call. Ledger: cron_config.json events.walk_forward_quarterly.</Description>
    <URI>\Zhuanqian_WalkForward</URI>
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
          <April />
          <July />
          <October />
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

try {
    $null = [xml]$xml
    Write-Host '[OK] Task XML parses.'
} catch {
    Write-Host ('[ABORT] Task XML is invalid: ' + $_.Exception.Message)
    exit 7
}

try {
    [System.IO.File]::WriteAllText($XmlOut, $xml, [System.Text.Encoding]::Unicode)
    Write-Host ('[OK] Task XML written: ' + $XmlOut)
} catch {
    Write-Host ('[WARN] Could not persist task XML: ' + $_.Exception.Message)
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
    Write-Host ('     Trigger : ' + (($check.Triggers | ForEach-Object { $_.StartBoundary }) -join ', '))
    Write-Host '[NOTE] No immediate run was scheduled.'
    exit 0
} else {
    Write-Host '[FAIL] Task not found after registration.'
    exit 6
}
