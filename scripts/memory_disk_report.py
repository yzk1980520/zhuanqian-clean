import os
import shutil
print("=== MEMORY SNAPSHOT ===")
os_info = os.popen('powershell -NoProfile -Command "$os = Get-CimInstance Win32_OperatingSystem; $t=[math]::Round($os.TotalVisibleMemorySize/1MB,2); $f=[math]::Round($os.FreePhysicalMemory/1MB,2); $u=[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB,2); $p=[math]::Round($u/$t*100,1); Write-Output \"Total=${t}GB Used=${u}GB (${p}%) Free=${f}GB\""'  , 'r').read().strip()
print(os_info)

pf = os.popen('powershell -NoProfile -Command "Get-CimInstance Win32_PageFileUsage | Select-Object -ExpandProperty Name,AllocatedBaseSize,CurrentUsage | ForEach-Object { [PSCustomObject]@{Name=$_.Name;Allocated=[math]::Round($_.AllocatedBaseSize,1);Used=[math]::Round($_.CurrentUsage,1)} } | Format-Table -AutoSize"'  , 'r').read().strip()
print("\n=== PAGEFILE ===")
print(pf)

top = os.popen('powershell -NoProfile -Command "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 Name, @{N=MemMB;E={[math]::Round($_.WorkingSet64/1MB,1)}}, Id | Format-Table -AutoSize"'  , 'r').read().strip()
print("\n=== TOP 15 MEMORY CONSUMERS ===")
print(top)

print("\n=== DISK USAGE ===")
for d in ['C:\\\\', 'D:\\\\']:
    try:
        s = shutil.disk_usage(d)
        free_gb = s.free / (1024**3)
        total_gb = s.total / (1024**3)
        pct = free_gb / total_gb * 100
        print(f"{d}: {free_gb:.2f} GB free / {total_gb:.2f} GB total ({pct:.1f}%)")
    except Exception as e:
        print(f"{d}: ERROR {e}")
