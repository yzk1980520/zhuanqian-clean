# W3 self-check: list every Zhuanqian_*/QSP_* scheduled task that can still pop a
# console window on the desktop. ASCII only. 20261017.
#
# NOTE: the ScheduledTasks CIM objects expose an empty Action.Command in PS 5.1,
# so every task is read through Export-ScheduledTask XML instead. Do not go back
# to Get-ScheduledTask .Actions.Command - it silently yields blank.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\check_silent_scheduled_tasks.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\check_silent_scheduled_tasks.ps1 -WriteCsv
#
# Exit codes: 0 = all silent-compliant, 2 = at least one task still at pop-up risk.
# Docs: see the silent-run specification doc under docs/ (Chinese filename, this
# .ps1 must stay pure ASCII so it is not referenced here by name).

param(
    [switch]$WriteCsv,
    [string]$OutCsv = "data\w3_silent_task_report.csv"
)

Import-Module ScheduledTasks

$NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# Interpreters / binaries that DO have a console -> must never be a task's direct
# Exec command; everything else goes through a silent launcher (vbs / pythonw).
$consoleApps = @('cmd.exe', 'cmd', 'python.exe', 'powershell.exe', 'powershell',
                 'pwsh.exe', 'bash.exe', 'conhost.exe')

$tasks = @(Get-ScheduledTask | Where-Object {
        $_.TaskName -like 'Zhuanqian_*' -or $_.TaskName -like 'QSP_*'
} | Sort-Object TaskName)

$rows = New-Object System.Collections.ArrayList

foreach ($t in $tasks) {
    $n = $t.TaskName
    $xml = Export-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $xml) { continue }
    $x = New-Object System.Xml.XmlDocument
    $x.LoadXml($xml)
    $nm = New-Object System.Xml.XmlNamespaceManager($x.NameTable)
    $nm.AddNamespace("t", $NS)

    $hidNode = $x.SelectSingleNode("//t:Settings/t:Hidden", $nm)
    $hidden = ($null -ne $hidNode) -and ($hidNode.InnerText -eq 'true')

    $execs = $x.SelectNodes("//t:Actions/t:Exec", $nm)
    foreach ($e in $execs) {
        $cmdN = $e.SelectSingleNode("t:Command", $nm)
        $argN = $e.SelectSingleNode("t:Arguments", $nm)
        $cmd = if ($cmdN) { $cmdN.InnerText } else { '' }
        $args = if ($argN) { $argN.InnerText } else { '' }
        $base = ''
        if ($cmd) { $base = [System.IO.Path]::GetFileName($cmd.Trim('"')).ToLower() }

        $verdict = 'CHECK'
        $why = ''
        if ([string]::IsNullOrWhiteSpace($cmd)) {
            $verdict = 'UNKNOWN'; $why = 'empty Command'
        }
        elseif ($consoleApps -contains $base) {
            $verdict = 'POPUP'; $why = "direct console binary ($base)"
        }
        elseif ($base -eq 'wscript.exe' -or $base -eq 'wscript') {
            $verdict = 'OK'; $why = 'hidden vbs launcher'
        }
        elseif ($base -eq 'pythonw.exe' -or $base -eq 'pythonw') {
            $verdict = 'OK'; $why = 'pythonw (no console)'
        }
        elseif ($base.EndsWith('.bat') -or $base.EndsWith('.cmd')) {
            $verdict = 'POPUP'; $why = 'direct .bat/.cmd in Exec'
        }
        else {
            $verdict = 'CHECK'; $why = "non-whitelisted command ($base)"
        }

        if (-not $hidden) {
            if ($verdict -eq 'OK') { $verdict = 'CHECK' }
            $why = $why + '; Hidden<>true'
        }

        [void]$rows.Add([PSCustomObject]@{
                Task    = $n
                Verdict = $verdict
                Hidden  = $hidden
                Command = $cmd
                Args    = $args
                Note    = $why
            })
    }
}

$bad = @($rows | Where-Object { $_.Verdict -ne 'OK' })

Write-Output ("scanned=" + $tasks.Count + " actions=" + $rows.Count + " non-compliant=" + $bad.Count)
Write-Output ""

foreach ($r in $rows) {
    $flag = '   '
    if ($r.Verdict -ne 'OK') { $flag = '>> ' }
    Write-Output ($flag + $r.Verdict.PadRight(8) + ' H=' + $(if ($r.Hidden) { 'true ' } else { 'false' }) + ' ' + ($r.Task + ' ').PadRight(29) + $r.Command + ' ' + $r.Args)
}

if ($WriteCsv) {
    $dir = Split-Path -Parent $OutCsv
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $OutCsv
    Write-Output ""
    Write-Output ("csv -> " + $OutCsv)
}

Write-Output ""
if ($bad.Count -gt 0) {
    Write-Output "NON-COMPLIANT:"
    foreach ($r in $bad) { Write-Output ("  " + $r.Task + " [" + $r.Verdict + "] " + $r.Note) }
    exit 2
}
Write-Output "ALL SILENT-COMPLIANT."
exit 0
