$ErrorActionPreference = 'SilentlyContinue'
$d = Get-ChildItem D:\ -Directory
$results = @()
foreach ($i in $d) {
    try {
        $s = (Get-ChildItem $i.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        if ($s -gt 0) {
            $results += [PSCustomObject]@{Name=$i.Name; SizeGB=[math]::Round($s/1GB,2)}
        }
    } catch {}
}
$results | Sort-Object SizeGB -Descending | Format-Table -AutoSize
$disk = Get-WmiObject Win32_LogicalDisk -Filter "DeviceID='D:'"
Write-Host "`nD: Total: $([math]::Round($disk.Size/1GB,2)) GB  Free: $([math]::Round($disk.FreeSpace/1GB,2)) GB  Used: $([math]::Round(($disk.Size-$disk.FreeSpace)/1GB,2)) GB"
