$os = Get-CimInstance Win32_OperatingSystem
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$freeGB  = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$usedGB  = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 2)
$pct     = [math]::Round($usedGB / $totalGB * 100, 1)
Write-Output "Total=$totalGB GB  Used=$usedGB ($pct%)  Free=$freeGB"

Write-Output ""
Write-Output "=== PAGEFILE ==="
Get-CimInstance Win32_PageFileUsage | ForEach-Object {
    Write-Output "$($_.Name): Allocated=$($_.AllocatedBaseSize)GB Current=$($_.CurrentUsage)GB Peak=$($_.PeakUsage)GB"
}

Write-Output ""
Write-Output "=== TOP 15 MEMORY CONSUMERS ==="
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 | ForEach-Object {
    $memMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
    Write-Output "$($_.Name) (PID $($_.Id)): ${memMB}MB"
}
