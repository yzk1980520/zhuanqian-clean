# =============================================================================
# fix-silent-carriers.ps1
#
# Purpose:
#   Convert scheduled tasks that violate the "silent carrier" standard into
#   the standard form, without rebuilding triggers or principals.
#
#   Standard form:
#     <Command>   %SystemRoot%\System32\wscript.exe
#     <Arguments> "<repo>\scripts\run_path_hidden.vbs" "<full path to target bat>"
#     <Settings><Hidden>true</Hidden>
#
#   Rationale: pointing <Command> straight at a .bat/.cmd under InteractiveToken
#   pops a visible cmd window (and the python window it spawns). Routing through
#   wscript.exe + run_path_hidden.vbs suppresses the window.
#
# IMPORTANT - run this from an ELEVATED (administrator) PowerShell.
#   On a standard account the Register-ScheduledTask calls fail with
#   "Access is denied." (Win32 error 5 / HRESULT 0x80070005).
#
# Idempotent: safe to run repeatedly. Tasks already in the standard form are
#   detected and skipped.
#
# This script is ASCII-only on purpose (non-ASCII paths/content get mangled
#   by PowerShell 5.1 encoding on Windows). Do NOT add Chinese text to it.
#
# Coverage note (QSP_ZLJWatch):
#   Its trigger is a TimeTrigger with EndBoundary=2026-08-20T23:30:00, which is
#   already expired (Missed=1, no NextRun). This script does NOT repair or
#   delete that trigger - it only adds <Hidden>true</Hidden>. Whether the task
#   is still needed must be confirmed by the owner. If it is no longer needed,
#   delete it manually:
#     Unregister-ScheduledTask -TaskName 'QSP_ZLJWatch' -Confirm:$false
# =============================================================================

[CmdletBinding()]
param()

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
$Repo      = 'D:\open code\zhuanqian'
$Runner    = Join-Path $Repo 'scripts\run_path_hidden.vbs'
$BackupDir = Join-Path $Repo 'deliverables\scheduled-tasks-backup-20261021'
$WsExe     = '%SystemRoot%\System32\wscript.exe'
$NsUri     = 'http://schemas.microsoft.com/windows/2004/02/mit/task'

# Preferred insertion order for Settings children.
# Only a hint: the Task Scheduler schema uses xs:all for SettingsType, so child
# order is NOT enforced (proved by the exported XML itself, where IdleSettings
# already appears after MultipleInstancesPolicy). Inserting Hidden at the
# ExecutionTimeLimit / IdleSettings position still keeps the output tidy.
$SchemaOrder = @(
    'AllowDemandStart',
    'AllowHardTerminate',
    'Compatibility',
    'DeleteExpiredTaskAfter',
    'DisallowStartIfOnBatteries',
    'Enabled',
    'ExecutionTimeLimit',
    'Hidden',
    'IdleSettings',
    'MaintenanceSettings',
    'MultipleInstancesPolicy',
    'Priority',
    'RestartOnFailure',
    'RunOnlyIfIdle',
    'RunOnlyIfNetworkAvailable',
    'StartWhenAvailable',
    'StopIfGoingOnBatteries',
    'WakeToRun',
    'NetworkSettings',
    'Volatile',
    'UseUnifiedSchedulingEngine'
)
$HiddenIndex = [array]::IndexOf($SchemaOrder, 'Hidden')

$Plan = @(
    @{ Name = 'Zhuanqian_DailyAuto';     Mode = 'Convert'    }
    @{ Name = 'Zhuanqian_FactorIC132d';  Mode = 'Convert'    }
    @{ Name = 'Zhuanqian_WalkForward';   Mode = 'Convert'    }
    @{ Name = 'QSP_PreMarket';           Mode = 'HiddenOnly' }
    @{ Name = 'Zhuanqian_BoardWatchdog'; Mode = 'HiddenOnly' }
    @{ Name = 'QSP_ZLJWatch';            Mode = 'HiddenOnly' }
)

$Results = New-Object System.Collections.ArrayList

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
function New-NsMgr {
    param([System.Xml.XmlDocument]$Doc)
    $m = New-Object System.Xml.XmlNamespaceManager($Doc.NameTable)
    $m.AddNamespace('t', $NsUri)
    # -NoEnumerate is mandatory: XmlNamespaceManager implements IEnumerable,
    # and a plain return would get unrolled into an Object[] by the pipeline.
    Write-Output -NoEnumerate $m
}

function Get-ChildText {
    param($Parent, [System.Xml.XmlNamespaceManager]$Ns, [string]$LocalName)
    $n = $Parent.SelectSingleNode('t:' + $LocalName, $Ns)
    if ($null -eq $n) { return $null }
    return $n.InnerText
}

function Set-ChildText {
    param(
        [System.Xml.XmlDocument]$Doc,
        $Parent,
        [System.Xml.XmlNamespaceManager]$Ns,
        [string]$LocalName,
        [string]$Value
    )
    $n = $Parent.SelectSingleNode('t:' + $LocalName, $Ns)
    if ($null -eq $n) {
        $n = $Doc.CreateElement($LocalName, $NsUri)
        $Parent.AppendChild($n) | Out-Null
    }
    $n.InnerText = $Value
    # -NoEnumerate: XmlElement is IEnumerable too
    Write-Output -NoEnumerate $n
}

function Get-HiddenState {
    param($Doc, [System.Xml.XmlNamespaceManager]$Ns)
    $h = $Doc.SelectSingleNode('//t:Settings/t:Hidden', $Ns)
    if ($null -eq $h) { return 'NO_NODE' }
    return $h.InnerText
}

function Set-HiddenTrue {
    param([System.Xml.XmlDocument]$Doc, [System.Xml.XmlNamespaceManager]$Ns)

    $settings = $Doc.SelectSingleNode('//t:Settings', $Ns)
    if ($null -eq $settings) { return 'NO_SETTINGS_NODE' }

    $hidden = $settings.SelectSingleNode('t:Hidden', $Ns)
    if ($null -ne $hidden) {
        if ($hidden.InnerText -eq 'true') { return 'ALREADY_TRUE' }
        $hidden.InnerText = 'true'
        return 'FALSE_TO_TRUE'
    }

    $node = $Doc.CreateElement('Hidden', $NsUri)
    $node.InnerText = 'true'

    $insertBefore = $null
    foreach ($child in $settings.ChildNodes) {
        $pos = [array]::IndexOf($SchemaOrder, $child.LocalName)
        if ($pos -gt $HiddenIndex) {
            $insertBefore = $child
            break
        }
    }
    if ($null -ne $insertBefore) {
        $settings.InsertBefore($node, $insertBefore) | Out-Null
    } else {
        $settings.AppendChild($node) | Out-Null
    }
    return 'NODE_ADDED'
}

function Normalize-Xml {
    param($Node)
    $s = $Node.InnerXml
    $s = $s -replace '\s+', ' '
    $s = $s -replace '\s*xmlns="[^"]*"', ''
    return $s.Trim()
}

function Get-TriggerFingerprint {
    param($Doc, [System.Xml.XmlNamespaceManager]$Ns)

    $parts = New-Object System.Collections.ArrayList
    foreach ($t in $Doc.SelectNodes('//t:Triggers/*', $Ns)) {
        $sb  = $t.SelectSingleNode('t:StartBoundary', $Ns)
        $eb  = $t.SelectSingleNode('t:EndBoundary', $Ns)
        $rep = $t.SelectSingleNode('t:Repetition', $Ns)

        # Only compare the repetition Interval. Re-registering can materialise
        # extra default children (StopAtDurationEnd etc.); comparing the whole
        # node would then report a false TRIGGER_CHANGED.
        $repText = ''
        if ($null -ne $rep) {
            $iv = $rep.SelectSingleNode('t:Interval', $Ns)
            if ($null -ne $iv) { $repText = $iv.InnerText }
        }

        $sched = ''
        foreach ($c in $t.ChildNodes) {
            if ($c.LocalName -like 'ScheduleBy*') {
                $sched = $c.LocalName + '(' + (Normalize-Xml $c) + ')'
            }
        }

        $text = $t.LocalName +
                '|start=' + $(if ($sb)  { $sb.InnerText  } else { '' }) +
                '|end='   + $(if ($eb)  { $eb.InnerText  } else { '' }) +
                '|rep='   + $repText +
                '|sched=' + $sched
        $parts.Add($text) | Out-Null
    }
    return ($parts -join ' ;; ')
}

function Resolve-TargetBat {
    # $Args is a PowerShell automatic variable - never use it as a param name.
    param([string]$Cmd, [string]$Arguments)

    if ($null -eq $Cmd)       { $Cmd = '' }
    if ($null -eq $Arguments) { $Arguments = '' }

    # Already in standard form: "<...>\run_path_hidden.vbs" "<...>\foo.bat"
    if ($Cmd -match 'wscript\.exe' -and $Arguments -match 'run_path_hidden\.vbs') {
        if ($Arguments -match '"([^"]+\.bat)"\s*$') { return $Matches[1] }
    }

    # cmd /c "D:\...\foo.bat"
    if ($Arguments -match '/c\s+"([^"]+\.bat)"') { return $Matches[1] }
    if ($Arguments -match '"([^"]+\.bat)"')      { return $Matches[1] }

    # Command points straight at the bat
    if ($Cmd -match '\.bat\s*$') { return $Cmd.Trim() }

    # Bare bat path in Arguments
    if ($Arguments -match '^"?([^"]+\.bat)"?\s*$') { return $Matches[1] }

    return $null
}

function Add-Result {
    param([string]$Name, [string]$Status, [string]$Detail)
    $o = New-Object PSObject
    $o | Add-Member -MemberType NoteProperty -Name Task    -Value $Name   -Force
    $o | Add-Member -MemberType NoteProperty -Name Status  -Value $Status -Force
    $o | Add-Member -MemberType NoteProperty -Name Detail  -Value $Detail -Force
    $Results.Add($o) | Out-Null
}

# -----------------------------------------------------------------------------
# 0. Preflight
# -----------------------------------------------------------------------------
Write-Host ''
Write-Host '================ fix-silent-carriers.ps1 ================'

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host 'WARNING: not elevated. Register-ScheduledTask will most likely fail'
    Write-Host '         with "Access is denied." (0x80070005). Re-run as administrator.'
} else {
    Write-Host 'Elevated: yes'
}

if (-not (Test-Path $Repo)) {
    Write-Host ('FATAL: repo not found: ' + $Repo)
    exit 1
}
if (-not (Test-Path $Runner)) {
    Write-Host ('FATAL: runner not found: ' + $Runner)
    Write-Host '       Do not invent a second runner. Restore scripts/run_path_hidden.vbs first.'
    exit 1
}
Write-Host ('Runner: ' + $Runner + ' (present)')

# -----------------------------------------------------------------------------
# 1. Backup all QSP_* / Zhuanqian_* tasks (existing files are kept untouched so
#    the pristine snapshot always survives re-runs)
# -----------------------------------------------------------------------------
Write-Host ''
Write-Host '---------- step 1: backup ----------'

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$allNames = @()
$allNames += (Get-ScheduledTask -ErrorAction SilentlyContinue |
              Where-Object { $_.TaskName -like 'QSP_*' -or $_.TaskName -like 'Zhuanqian_*' } |
              Select-Object -ExpandProperty TaskName)

foreach ($item in $Plan) {
    if ($allNames -notcontains $item.Name) { $allNames += $item.Name }
}
$allNames = $allNames | Where-Object { $_ } | Sort-Object -Unique

$backupWritten = 0
$backupSkipped = 0
$backupFailed  = 0
foreach ($n in $allNames) {
    $file = Join-Path $BackupDir ($n + '.xml')
    if (Test-Path $file) {
        $backupSkipped++
        continue
    }
    try {
        $xml = Export-ScheduledTask -TaskName $n -ErrorAction Stop
        [System.IO.File]::WriteAllText($file, $xml, (New-Object System.Text.UTF8Encoding($true)))
        $backupWritten++
    } catch {
        $backupFailed++
        Write-Host ('  BACKUP FAIL: ' + $n + ' :: ' + $_.Exception.Message)
    }
}
Write-Host ('  total: ' + $allNames.Count +
            '  written: ' + $backupWritten +
            '  already-present: ' + $backupSkipped +
            '  failed: ' + $backupFailed)
Write-Host ('  dir: ' + $BackupDir)

# -----------------------------------------------------------------------------
# 2. Convert
# -----------------------------------------------------------------------------
Write-Host ''
Write-Host '---------- step 2: convert ----------'

foreach ($item in $Plan) {
    $name = $item.Name
    $mode = $item.Mode

    Write-Host ''
    Write-Host ('### ' + $name + '  [mode=' + $mode + ']')

    try {
        $raw = Export-ScheduledTask -TaskName $name -ErrorAction Stop
        if (-not $raw) { throw 'Export-ScheduledTask returned empty (task not found?)' }

        [xml]$doc = $raw
        $ns = New-NsMgr $doc

        $exec = $doc.SelectSingleNode('//t:Exec', $ns)
        if ($null -eq $exec) { throw 'No single <Exec> action found; not safe to auto-convert.' }

        $oldCmd  = Get-ChildText $exec $ns 'Command'
        $oldArgs = Get-ChildText $exec $ns 'Arguments'
        if ($null -eq $oldCmd)  { $oldCmd  = '' }
        if ($null -eq $oldArgs) { $oldArgs = '' }
        $oldHidden  = Get-HiddenState $doc $ns
        $trigBefore = Get-TriggerFingerprint $doc $ns

        Write-Host ('  before Command  = [' + $oldCmd  + ']')
        Write-Host ('  before Arguments= [' + $oldArgs + ']')
        Write-Host ('  before Hidden   = ' + $oldHidden)

        $wantCmd  = $oldCmd
        $wantArgs = $oldArgs

        if ($mode -eq 'Convert') {
            # Locate the real bat from the ORIGINAL XML. Never guess.
            $bat = Resolve-TargetBat -Cmd $oldCmd -Arguments $oldArgs
            if ([string]::IsNullOrWhiteSpace($bat)) {
                throw ('Cannot locate target bat from Command=[' + $oldCmd + '] Arguments=[' + $oldArgs + ']')
            }
            $wantCmd  = $WsExe
            $wantArgs = '"' + $Runner + '" "' + $bat + '"'
            if (-not (Test-Path $bat)) {
                Write-Host ('  WARNING: target bat does not exist on disk: ' + $bat)
            }
        }

        $needCmd   = ($oldCmd  -ne $wantCmd)
        $needArgs  = ($oldArgs -ne $wantArgs)
        $needHide  = ($oldHidden -ne 'true')
        $needChange = $needCmd -or $needArgs -or $needHide

        if (-not $needChange) {
            Write-Host '  already compliant, nothing to do.'
            Add-Result $name 'SKIPPED_COMPLIANT' 'Command/Arguments/Hidden already in standard form'
            continue
        }

        Write-Host ('  about to modify: ' + $name)
        Write-Host ('    want Command  = [' + $wantCmd  + ']')
        Write-Host ('    want Arguments= [' + $wantArgs + ']')
        Write-Host ('    want Hidden   = true')

        if ($needCmd)  { Set-ChildText $doc $exec $ns 'Command'   $wantCmd  | Out-Null }
        if ($needArgs) { Set-ChildText $doc $exec $ns 'Arguments' $wantArgs | Out-Null }
        $hiddenResult = Set-HiddenTrue $doc $ns

        Register-ScheduledTask -TaskName $name -Xml $doc.OuterXml -Force -ErrorAction Stop | Out-Null

        # ---------- verify by re-exporting (never trust the return code) ----------
        [xml]$doc2 = Export-ScheduledTask -TaskName $name -ErrorAction Stop
        $ns2 = New-NsMgr $doc2
        $exec2 = $doc2.SelectSingleNode('//t:Exec', $ns2)

        $newCmd  = Get-ChildText $exec2 $ns2 'Command'
        $newArgs = Get-ChildText $exec2 $ns2 'Arguments'
        if ($null -eq $newCmd)  { $newCmd  = '' }
        if ($null -eq $newArgs) { $newArgs = '' }
        $newHidden  = Get-HiddenState $doc2 $ns2
        $trigAfter  = Get-TriggerFingerprint $doc2 $ns2

        Write-Host ('  after  Command  = [' + $newCmd  + ']')
        Write-Host ('  after  Arguments= [' + $newArgs + ']')
        Write-Host ('  after  Hidden   = ' + $newHidden + '  (' + $hiddenResult + ')')

        $cmdOk   = ($newCmd  -eq $wantCmd)
        $argsOk  = ($newArgs -eq $wantArgs)
        $hideOk  = ($newHidden -eq 'true')
        $trigOk  = ($trigAfter -eq $trigBefore)

        if ($cmdOk -and $argsOk -and $hideOk -and $trigOk) {
            Write-Host '  VERIFY: PASS (triggers unchanged)'
            Add-Result $name 'FIXED' ('verified; hidden=' + $hiddenResult + '; triggers unchanged')
        } else {
            $why = @()
            if (-not $cmdOk)  { $why += 'command' }
            if (-not $argsOk) { $why += 'arguments' }
            if (-not $hideOk) { $why += 'hidden' }
            if (-not $trigOk) { $why += 'TRIGGER_CHANGED' }
            Write-Host ('  VERIFY: FAIL -> ' + ($why -join ','))
            Add-Result $name 'VERIFY_FAIL' ('mismatch: ' + ($why -join ','))
        }

    } catch {
        $msg = $_.Exception.Message
        $hresult = ''
        try { $hresult = '0x' + '{0:X8}' -f [uint32][System.Runtime.InteropServices.Marshal]::GetHRForException($_.Exception) } catch {}
        Write-Host ('  ERROR: ' + $msg + $(if ($hresult) { ' (hresult ' + $hresult + ')' }))
        if ($msg -match 'denied' -or $msg -match 'Access is denied') {
            Write-Host '  -> Access is denied. This script must be run as administrator.'
        }
        Add-Result $name 'FAILED' $msg
    }
}

# -----------------------------------------------------------------------------
# 3. Summary
# -----------------------------------------------------------------------------
Write-Host ''
Write-Host '---------- summary ----------'
foreach ($r in $Results) {
    Write-Host ('  ' + $r.Status.PadRight(18) + ' ' + $r.Task.PadRight(26) + ' ' + $r.Detail)
}

$fixed    = @($Results | Where-Object { $_.Status -eq 'FIXED' }).Count
$skip     = @($Results | Where-Object { $_.Status -eq 'SKIPPED_COMPLIANT' }).Count
$bad      = @($Results | Where-Object { $_.Status -eq 'VERIFY_FAIL' }).Count
$failed   = @($Results | Where-Object { $_.Status -eq 'FAILED' }).Count

Write-Host ''
Write-Host ('FIXED=' + $fixed + '  SKIPPED_ALREADY_COMPLIANT=' + $skip +
            '  VERIFY_FAIL=' + $bad + '  FAILED=' + $failed)

Write-Host ''
Write-Host 'Reminder: QSP_ZLJWatch has an expired TimeTrigger (EndBoundary=2026-08-20T23:30:00).'
Write-Host '          This script did NOT touch that trigger. Confirm with the owner whether the'
Write-Host '          task is still needed; if not, delete it:'
Write-Host "          Unregister-ScheduledTask -TaskName 'QSP_ZLJWatch' -Confirm:`$false"
Write-Host ''
