# W3 helper: export Zhuanqian_*/QSP_* scheduled task XML (backup before silent-mode change)
# ASCII only (script body). 20261017.
# Note: Export-ScheduledTask emits prolog encoding="UTF-16" but the payload string is Unicode.
# We rewrite the files as UTF-8 (no BOM) + prolog encoding="UTF-8" so any later reader
# / Get-Content -Encoding UTF8 round-trips correctly.
# Run: powershell -ExecutionPolicy Bypass -File scripts\w3_export_schtasks.ps1
param(
    [string]$Repo = "D:\open code\zhuanqian"
)

Import-Module ScheduledTasks

$outDir = Join-Path $Repo "backups\schtasks-xml-20261017"
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$names = @(
    'QSP_ConfigGC','QSP_DrainWatch','QSP_GitSync','QSP_Intraday','QSP_LoopWatch','QSP_MsgDrain',
    'QSP_PostMarket','QSP_PreMarket','QSP_RemoteFreshness','QSP_SelfHeal','QSP_SysWatchdog',
    'QSP_Verify','QSP_Watchdog','QSP_Weekly','QSP_ZLJWatch',
    'Zhuanqian_BoardWatchdog','Zhuanqian_DailyAuto','Zhuanqian_ICMonitor_20d',
    'Zhuanqian_RefreshTaskBoard','Zhuanqian_Rotation132d','Zhuanqian_SanityGate','Zhuanqian_SanityGate_Night'
)

$enc = New-Object System.Text.UTF8Encoding($false)
$ok = 0
$miss = New-Object System.Collections.ArrayList

foreach ($n in $names) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if ($null -eq $t) { [void]$miss.Add($n); continue }
    $xml = Export-ScheduledTask -TaskName $n
    $xml = $xml -replace 'encoding="UTF-16"', 'encoding="UTF-8"'
    if ($xml -match '^\xEF\xBB\xBF') { $xml = $xml.Substring(3) }
    $xmlFile = Join-Path $outDir ($n + ".xml")
    [System.IO.File]::WriteAllText($xmlFile, $xml, $enc)
    $ok++
}

Write-Output ("EXPORTED=" + $ok + " MISSING=" + $miss.Count + " -> " + $outDir)
if ($miss.Count -gt 0) { Write-Output ("MISSING: " + ($miss -join ',')) }
