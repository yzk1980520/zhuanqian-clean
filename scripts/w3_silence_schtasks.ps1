# W3 helper: set Hidden=True on all Zhuanqian_*/QSP_* tasks and re-wire the ones
# that launched .bat/.cmd/python.exe directly (those pop a console window on the
# boss's desktop). ASCII only. 20261017.
#
#   powershell -ExecutionPolicy Bypass -File scripts\w3_silence_schtasks.ps1            # dry run
#   powershell -ExecutionPolicy Bypass -File scripts\w3_silence_schtasks.ps1 -Apply     # apply
#
# Rollback: backups\schtasks-xml-20261017\<name>.xml -> Register-ScheduledTask -Xml
param(
    [switch]$Apply,
    [string]$Repo = "D:\open code\zhuanqian"
)

Import-Module ScheduledTasks

$NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
$VBS = '"D:\open code\zhuanqian\scripts\run_path_hidden.vbs"'

# task name -> new arguments. (command stays wscript.exe for all of them)
$Rewire = @{
    'QSP_ConfigGC'             = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\config_gc.cmd"' })
    'QSP_SysWatchdog'          = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\sys_watchdog.cmd"' })
    'Zhuanqian_DailyAuto'      = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\daily_auto.bat"' })
    'Zhuanqian_ICMonitor_20d'  = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\Zhuanqian_ICMonitor_20d.bat"' })
    'Zhuanqian_Rotation132d'   = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\Zhuanqian_Rotation132d.bat"' })
    'Zhuanqian_SanityGate'     = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\Zhuanqian_SanityGate.bat"' })
    'Zhuanqian_SanityGate_Night' = (@{ Cmd='wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\Zhuanqian_SanityGate.bat"' })
    'Zhuanqian_RefreshTaskBoard' = (@{ Cmd='D:\open code\zhuanqian\.venv\Scripts\pythonw.exe'; Args = '"D:\open code\zhuanqian\scripts\refresh_task_board.py"' })
}

$names = @(
    'QSP_ConfigGC','QSP_DrainWatch','QSP_GitSync','QSP_Intraday','QSP_LoopWatch','QSP_MsgDrain',
    'QSP_PostMarket','QSP_PreMarket','QSP_RemoteFreshness','QSP_SelfHeal','QSP_SysWatchdog',
    'QSP_Verify','QSP_Watchdog','QSP_Weekly','QSP_ZLJWatch',
    'Zhuanqian_BoardWatchdog','Zhuanqian_DailyAuto','Zhuanqian_ICMonitor_20d',
    'Zhuanqian_RefreshTaskBoard','Zhuanqian_Rotation132d','Zhuanqian_SanityGate','Zhuanqian_SanityGate_Night'
)

$ok = 0
$failed = New-Object System.Collections.ArrayList

foreach ($n in $names) {
    try {
        $xml = Export-ScheduledTask -TaskName $n -ErrorAction Stop
    } catch {
        [void]$failed.Add($n + " [export] " + $_.Exception.Message)
        continue
    }

    $x = New-Object System.Xml.XmlDocument
    $x.PreserveWhitespace = $true
    $x.LoadXml($xml)
    $nm = New-Object System.Xml.XmlNamespaceManager($x.NameTable)
    $nm.AddNamespace("t", $NS)

    # ---------- 1) Hidden = true ----------
    $settings = $x.SelectSingleNode("//t:Settings", $nm)
    if ($null -eq $settings) {
        [void]$failed.Add($n + " [no-Settings]")
        continue
    }
    $hiddenNode = $settings.SelectSingleNode("t:Hidden", $nm)
    if ($null -eq $hiddenNode) {
        $hiddenNode = $x.CreateElement("Hidden", $NS)
        # insert after the battery settings (same position Windows itself emits)
        $anchor = $settings.SelectSingleNode("t:StopIfGoingOnBatteries", $nm)
        if ($null -eq $anchor) { $anchor = $settings.SelectSingleNode("t:DisallowStartIfOnBatteries", $nm) }
        if ($null -ne $anchor) { [void]$settings.InsertAfter($hiddenNode, $anchor) }
        else { [void]$settings.PrependChild($hiddenNode) }
    }
    $hiddenNode.InnerText = "true"

    # ---------- 2) silent launcher for the pop-up tasks ----------
    $rewired = ""
    if ($Rewire.ContainsKey($n)) {
        $cmdNode = $x.SelectSingleNode("//t:Actions/t:Exec/t:Command", $nm)
        $argNode = $x.SelectSingleNode("//t:Actions/t:Exec/t:Arguments", $nm)
        if ($null -eq $cmdNode) {
            [void]$failed.Add($n + " [no-ExecAction]")
            continue
        }
        $oldCmd = $cmdNode.InnerText
        $oldArg = if ($argNode) { $argNode.InnerText } else { "" }
        if ($cmdNode.InnerText -ne $Rewire[$n].Cmd -or $oldArg -ne $Rewire[$n].Args) {
            $rewired = ("  old: " + $oldCmd + " " + $oldArg)
        }
        $cmdNode.InnerText = $Rewire[$n].Cmd
        if ($null -eq $argNode) {
            $execNode = $x.SelectSingleNode("//t:Actions/t:Exec", $nm)
            $argNode = $x.CreateElement("Arguments", $NS)
            [void]$execNode.AppendChild($argNode)
        }
        $argNode.InnerText = $Rewire[$n].Args
    }

    $newXml = $x.OuterXml

    if (-not $Apply) {
        Write-Output ("[DRY] " + $n + " Hidden->true" + $(if ($rewired) { " | Exec->" + $Rewire[$n].Cmd + " " + $Rewire[$n].Args + " " + $rewired } else { "" }))
        continue
    }

    try {
        Register-ScheduledTask -Xml $newXml -TaskName $n -TaskPath '\' -Force -ErrorAction Stop | Out-Null
        $ok++
        Write-Output ("[OK ] " + $n + $(if ($rewired) { " (rewired)" } else { "" }))
    } catch {
        [void]$failed.Add($n + " [register] " + $_.Exception.Message)
        Write-Output ("[ERR] " + $n + " " + $_.Exception.Message)
    }
}

Write-Output ""
Write-Output ("APPLIED=" + $ok + " FAILED=" + $failed.Count)
foreach ($f in $failed) { Write-Output ("FAIL: " + $f) }
