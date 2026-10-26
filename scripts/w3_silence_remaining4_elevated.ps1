# W3: finish the silent-mode job on the 4 tasks owned by BUILTIN\Administrators
# (QSP_PreMarket, QSP_ZLJWatch, Zhuanqian_BoardWatchdog, Zhuanqian_DailyAuto).
# These reject Register-ScheduledTask with 0x80070005 from a NON-ELEVATED session
# because the WIN10 account is a standard user and the task files under
# C:\Windows\System32\Tasks\ are owned by Administrators.
#
# MUST BE RUN FROM AN ELEVATED (Run as administrator) POWERSHELL:
#   powershell -ExecutionPolicy Bypass -File scripts\w3_silence_remaining4_elevated.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\w3_silence_remaining4_elevated.ps1 -Apply
#
# This script does NOT self-elevate on purpose: a UAC prompt popping onto the boss's
# desktop is exactly what the silent-mode rule forbids. ASCII only. 20261017.
param([switch]$Apply)

Import-Module ScheduledTasks

$NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
$VBS = '"D:\open code\zhuanqian\scripts\run_path_hidden.vbs"'

$Plan = @{
    'QSP_PreMarket'            = $null                                                    # already silent launcher, only Hidden
    'QSP_ZLJWatch'             = $null                                                    # already silent launcher, only Hidden
    'Zhuanqian_BoardWatchdog'  = $null                                                    # already silent launcher, only Hidden
    'Zhuanqian_DailyAuto'      = (@{ Cmd = 'wscript.exe'; Args = $VBS + ' "D:\open code\zhuanqian\scripts\daily_auto.bat"' })
}

if (-not ([bool](([System.Security.Principal.WindowsIdentity]::GetCurrent()).Groups | Where-Object { $_.Value -eq 'S-1-5-32-544' }))) {
    Write-Output "NOT-ELEVATED: unable to modify these tasks."
    Write-Output "Run PowerShell as Administrator and retry:"
    Write-Output "  powershell -ExecutionPolicy Bypass -File scripts\w3_silence_remaining4_elevated.ps1 -Apply"
    exit 1
}
Write-Output "ELEVATED-OK"

foreach ($n in ($Plan.Keys | Sort-Object)) {
    $xml = Export-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $xml) { Write-Output ("MISSING " + $n); continue }

    $x = New-Object System.Xml.XmlDocument
    $x.PreserveWhitespace = $true
    $x.LoadXml($xml)
    $nm = New-Object System.Xml.XmlNamespaceManager($x.NameTable)
    $nm.AddNamespace("t", $NS)

    $settings = $x.SelectSingleNode("//t:Settings", $nm)
    $h = $settings.SelectSingleNode("t:Hidden", $nm)
    if ($null -eq $h) {
        $h = $x.CreateElement("Hidden", $NS)
        $anchor = $settings.SelectSingleNode("t:StopIfGoingOnBatteries", $nm)
        if ($null -eq $anchor) { $anchor = $settings.SelectSingleNode("t:DisallowStartIfOnBatteries", $nm) }
        if ($null -ne $anchor) { [void]$settings.InsertAfter($h, $anchor) } else { [void]$settings.PrependChild($h) }
    }
    $h.InnerText = "true"

    $note = "Hidden->true"
    if ($null -ne $Plan[$n]) {
        $c = $x.SelectSingleNode("//t:Actions/t:Exec/t:Command", $nm)
        $a = $x.SelectSingleNode("//t:Actions/t:Exec/t:Arguments", $nm)
        $note = $note + " | old=" + $c.InnerText + " " + ($(if ($a) { $a.InnerText } else { '' }))
        $c.InnerText = $Plan[$n].Cmd
        if ($null -eq $a) {
            $e = $x.SelectSingleNode("//t:Actions/t:Exec", $nm)
            $a = $x.CreateElement("Arguments", $NS)
            [void]$e.AppendChild($a)
        }
        $a.InnerText = $Plan[$n].Args
    }

    if (-not $Apply) { Write-Output ("[DRY] " + $n + "  " + $note); continue }

    try {
        Register-ScheduledTask -Xml $x.OuterXml -TaskName $n -TaskPath '\' -Force -ErrorAction Stop | Out-Null
        Write-Output ("[OK ] " + $n + "  " + $note)
    } catch {
        Write-Output ("[ERR] " + $n + " " + $_.Exception.Message.Trim())
    }
}

if ($Apply) {
    Write-Output ""
    Write-Output "Verify with:"
    Write-Output "  powershell -ExecutionPolicy Bypass -File scripts\check_silent_scheduled_tasks.ps1"
}
