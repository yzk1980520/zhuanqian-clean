# W3 helper: build before/after state report from exported task XML
# ASCII only. 20261017. Usage: powershell -File scripts\w3_xml_state.ps1 -Mode before|after
param(
    [string]$Repo = "D:\open code\zhuanqian",
    [string]$Mode = "before"
)

$dir = Join-Path $Repo "backups\schtasks-xml-20261017"
if ($Mode -eq "after") {
    Import-Module ScheduledTasks
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $names = @(
        'QSP_ConfigGC','QSP_DrainWatch','QSP_GitSync','QSP_Intraday','QSP_LoopWatch','QSP_MsgDrain',
        'QSP_PostMarket','QSP_PreMarket','QSP_RemoteFreshness','QSP_SelfHeal','QSP_SysWatchdog',
        'QSP_Verify','QSP_Watchdog','QSP_Weekly','QSP_ZLJWatch',
        'Zhuanqian_BoardWatchdog','Zhuanqian_DailyAuto','Zhuanqian_ICMonitor_20d',
        'Zhuanqian_RefreshTaskBoard','Zhuanqian_Rotation132d','Zhuanqian_SanityGate','Zhuanqian_SanityGate_Night'
    )
    $enc0 = New-Object System.Text.UTF8Encoding($false)
    foreach ($n in $names) {
        $x = Export-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
        if ($x) { [System.IO.File]::WriteAllText((Join-Path $dir ($n + ".after.xml")), $x, $enc0) }
    }
}

# before -> only the pre-change backups (<name>.xml); after -> only <name>.after.xml
$filter = if ($Mode -eq "after") { "*.after.xml" } else { "*.xml" }
$allXml = @(Get-ChildItem -Path $dir)
$files = @($allXml | Where-Object {
        if (-not ($_.Name -like $filter)) { return $false }
        if ($Mode -ne "after" -and $_.Name -like "*.after.xml") { return $false }
        return $true
    } | Sort-Object Name)
$enc = New-Object System.Text.UTF8Encoding($false)
$out = New-Object System.Collections.ArrayList

foreach ($f in $files) {
    [xml]$x = Get-Content -Path $f.FullName -Raw -Encoding UTF8
    $ns = New-Object Xml.XmlNamespaceManager($x.NameTable)
    $ns.AddNamespace("t", "http://schemas.microsoft.com/windows/2004/02/mit/task")
    $exe = $x.SelectSingleNode("//t:Actions/t:Exec/t:Command", $ns)
    $arg = $x.SelectSingleNode("//t:Actions/t:Exec/t:Arguments", $ns)
    $hid = $x.SelectSingleNode("//t:Settings/t:Hidden", $ns)
    $pri = $x.SelectSingleNode("//t:Principals/t:Principal/t:LogonType", $ns)
    $run = $x.SelectSingleNode("//t:Principals/t:Principal/t:RunLevel", $ns)
    $c = if ($exe) { $exe.InnerText } else { "" }
    $a = if ($arg) { $arg.InnerText } else { "" }
    $h = if ($hid) { $hid.InnerText } else { "(absent)" }
    $p = if ($pri) { $pri.InnerText } else { "(absent)" }
    $r = if ($run) { $run.InnerText } else { "(absent)" }
    $c = (($c -replace '[\r\n]+', ' ') -replace '\|', '/')
    $a = (($a -replace '[\r\n]+', ' ') -replace '\|', '/')
    [void]$out.Add(($f.BaseName) + " | Hidden=" + $h + " | Logon=" + $p + " | RunLevel=" + $r + " | CMD=" + $c + " | ARGS=" + $a)
}

$dest = Join-Path $dir ("_state_" + $Mode + ".txt")
[System.IO.File]::WriteAllLines($dest, $out, $enc)
Write-Output ("WROTE " + $dest + " rows=" + $out.Count)
