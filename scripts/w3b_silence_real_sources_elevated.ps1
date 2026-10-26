# W3b: silence the tasks that REALLY pop a console window onto the boss's desktop.
# Boss ruling 2026-10-17: system runs must never pop a terminal panel.
# Boss ruling 2026-10-18: the W3 scope was wrong - re-scope to the measured real sources.
#
# Source of truth: full scan of ALL scheduled tasks via Export-ScheduledTask XML
# (PS5.1 Get-ScheduledTask does NOT expose the action command, so XML is required).
# Measured rule:
#   python.exe            -> pops   (pythonw.exe does not)
#   cmd / cmd.exe with /c -> pops
#   a .bat/.cmd as Command-> pops
#   powershell without -WindowStyle Hidden -> pops
#   wscript.exe launcher  -> does not pop
#
# MUST BE RUN FROM AN ELEVATED (Run as administrator) POWERSHELL:
#   powershell -ExecutionPolicy Bypass -File scripts\w3b_silence_real_sources_elevated.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\w3b_silence_real_sources_elevated.ps1 -Apply
#
# This script does NOT self-elevate on purpose: a UAC prompt popping onto the boss's
# desktop is exactly what the silent-mode rule forbids. ASCII only. 20261018.
param([switch]$Apply)

Import-Module ScheduledTasks

$NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
$VBS = '"D:\open code\zhuanqian\scripts\run_path_hidden.vbs"'
$VENVW = 'C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\pythonw.exe'
$PY311W = 'C:\Users\WIN10\AppData\Local\Programs\Python\Python311\pythonw.exe'

# Block A: measured as REALLY popping. Command gets replaced + Hidden -> true.
$Fix = @{
    'AOCI_Daily_Check' = @{
        Cmd  = 'wscript.exe'
        Args = $VBS + ' "D:\open code\zhuanqian\scripts\aoci_daily_check.bat"'
        Note = 'python.exe -> repo .bat via hidden vbs launcher'
    }
    'AOCI_Weekly_Score' = @{
        Cmd  = $VENVW
        Args = '"D:\open code\zhuanqian\scripts\aoci_weekly_score.py"'
        Note = 'python.exe -> pythonw.exe'
    }
    'fetch_industry_open' = @{
        Cmd  = $PY311W
        Args = '"D:\open code\zhuanqian\mainline\fetch_industry_at_open.py"'
        Note = 'python.exe -> pythonw.exe'
    }
    'HealthCheck_L1_5min' = @{
        Cmd  = $VENVW
        Args = 'health_monitor_cli.py --mode full'
        Note = 'python.exe -> pythonw.exe'
    }
    'HealthCheck_L3_Evening' = @{
        Cmd  = $VENVW
        Args = 'health_monitor_cli.py --mode evening'
        Note = 'python.exe -> pythonw.exe'
    }
    'HealthCheck_L3_Morning' = @{
        Cmd  = $VENVW
        Args = 'health_monitor_cli.py --mode morning'
        Note = 'python.exe -> pythonw.exe'
    }
    'HealthCheck_L4_Weekly' = @{
        Cmd  = $VENVW
        Args = 'health_monitor_cli.py --mode full'
        Note = 'python.exe -> pythonw.exe'
    }
    'Hermes_StockBoard' = @{
        Cmd  = 'wscript.exe'
        Args = $VBS + ' "D:\open code\zhuanqian\dashboards\open_board.bat"'
        Note = 'cmd /c -> hidden vbs launcher; browser still opens'
    }
    'mainline-retry-cons' = @{
        Cmd  = 'powershell.exe'
        Args = '-NoProfile -WindowStyle Hidden -Command "cd /d ''D:\open code\zhuanqian''; python mainline\retry_industry_cons.py"'
        Note = 'powershell: add -WindowStyle Hidden'
    }
    'P3_DailyMonitor' = @{
        Cmd  = 'wscript.exe'
        Args = $VBS + ' "D:\open code\zhuanqian\scripts\run_p3_monitor.bat"'
        Note = 'cmd /c -> hidden vbs launcher'
    }
    'Zhuanqian_DailyAuto' = @{
        Cmd  = 'wscript.exe'
        Args = $VBS + ' "D:\open code\zhuanqian\scripts\daily_auto.bat"'
        Note = 'cmd /c -> hidden vbs launcher (bat keeps its own >>log)'
    }
    'Zhuanqian_FactorIC132d' = @{
        Cmd  = 'wscript.exe'
        Args = $VBS + ' "D:\open code\zhuanqian\scripts\Zhuanqian_FactorIC132d.bat"'
        Note = 'bare .bat Command -> hidden vbs launcher (bat keeps its own >>log)'
    }
    'Zhuanqian_WalkForward' = @{
        Cmd  = 'wscript.exe'
        Args = $VBS + ' "D:\open code\zhuanqian\scripts\Zhuanqian_WalkForward.bat"'
        Note = 'bare .bat Command -> hidden vbs launcher (bat keeps its own >>log)'
    }
}

# Block B: already a wscript silent launcher, only the Hidden marker is missing.
# Belt and braces - costs nothing, does not pop today.
$HiddenOnly = @('QSP_PreMarket', 'QSP_ZLJWatch', 'Zhuanqian_BoardWatchdog')

if (-not ([bool](([System.Security.Principal.WindowsIdentity]::GetCurrent()).Groups | Where-Object { $_.Value -eq 'S-1-5-32-544' }))) {
    Write-Output "NOT-ELEVATED: unable to modify these tasks."
    Write-Output "Run PowerShell as Administrator and retry:"
    Write-Output "  powershell -ExecutionPolicy Bypass -File scripts\w3b_silence_real_sources_elevated.ps1 -Apply"
    exit 1
}
Write-Output "ELEVATED-OK"

function SetHidden($x, $nm, $ns) {
    $settings = $x.SelectSingleNode("//t:Settings", $nm)
    if ($null -eq $settings) { return "no-Settings" }
    $h = $settings.SelectSingleNode("t:Hidden", $nm)
    if ($null -eq $h) {
        $h = $x.CreateElement("Hidden", $ns)
        $anchor = $settings.SelectSingleNode("t:StopIfGoingOnBatteries", $nm)
        if ($null -eq $anchor) { $anchor = $settings.SelectSingleNode("t:DisallowStartIfOnBatteries", $nm) }
        if ($null -ne $anchor) { [void]$settings.InsertAfter($h, $anchor) } else { [void]$settings.PrependChild($h) }
    }
    $h.InnerText = "true"
    return "Hidden->true"
}

function Apply-Plan($names, $replaceCommand) {
    foreach ($n in ($names | Sort-Object)) {
        $t = Get-ScheduledTask -TaskName $n -TaskPath '\' -ErrorAction SilentlyContinue
        if ($null -eq $t) { Write-Output ("MISSING " + $n); continue }

        $xml = Export-ScheduledTask -TaskName $n -TaskPath '\' -ErrorAction SilentlyContinue
        if (-not $xml) { Write-Output ("EXPORT-FAIL " + $n); continue }

        $x = New-Object System.Xml.XmlDocument
        $x.PreserveWhitespace = $true
        $x.LoadXml($xml)
        $nm = New-Object System.Xml.XmlNamespaceManager($x.NameTable)
        $nm.AddNamespace("t", $NS)

        $note = SetHidden $x $nm $NS

        if ($replaceCommand) {
            $p = $Fix[$n]
            $c = $x.SelectSingleNode("//t:Actions/t:Exec/t:Command", $nm)
            $a = $x.SelectSingleNode("//t:Actions/t:Exec/t:Arguments", $nm)
            $old = $(if ($c) { $c.InnerText } else { '' }) + " " + $(if ($a) { $a.InnerText } else { '' })
            $note = $note + " | " + $p.Note + " | old=" + $old.Trim()

            if ($null -eq $c) { Write-Output ("NO-EXEC " + $n); continue }
            $c.InnerText = $p.Cmd
            if ($null -eq $a) {
                $e = $x.SelectSingleNode("//t:Actions/t:Exec", $nm)
                $a = $x.CreateElement("Arguments", $NS)
                [void]$e.AppendChild($a)
            }
            $a.InnerText = $p.Args
        }

        if (-not $Apply) { Write-Output ("[DRY] " + $n + "  " + $note); continue }

        try {
            Register-ScheduledTask -Xml $x.OuterXml -TaskName $n -TaskPath '\' -Force -ErrorAction Stop | Out-Null
            Write-Output ("[OK ] " + $n + "  " + $note)
        } catch {
            Write-Output ("[ERR] " + $n + " " + $_.Exception.Message.Trim())
        }
    }
}

Write-Output "--- Block A: measured real pop-up sources ---"
Apply-Plan $Fix.Keys $true

Write-Output ""
Write-Output "--- Block B: silent launcher already, Hidden marker only ---"
Apply-Plan $HiddenOnly $false

if ($Apply) {
    Write-Output ""
    Write-Output "Verify with:"
    Write-Output "  powershell -ExecutionPolicy Bypass -File scripts\check_silent_scheduled_tasks.ps1"
}
