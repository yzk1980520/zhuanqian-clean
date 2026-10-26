import os
import shutil
import time
import sys

def dir_size(path, max_depth=3):
    total = 0
    for root, dirs, files in os.walk(path, topdown=True):
        rel = os.path.relpath(root, path)
        if rel != '.' and rel.count(os.sep) >= max_depth:
            dirs.clear()
            continue
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total

def scan_drive(drive_letter):
    base = f'{drive_letter}:/'
    results = []
    try:
        for name in os.listdir(base):
            full = os.path.join(base, name)
            if os.path.isdir(full):
                size = dir_size(full, 3)
                if size > 1e8:  # > 100 MB
                    results.append((name, size))
    except PermissionError:
        pass
    results.sort(key=lambda x: x[1], reverse=True)
    return results

print("=== C盘 TOP 20 ===")
for name, size in scan_drive('C')[:20]:
    print(f'{size/1e9:8.2f} GB  {name}')

print("\n=== D盘 TOP 15 ===")
for name, size in scan_drive('D')[:15]:
    print(f'{size/1e9:8.2f} GB  {name}')

# Check cleanable items
print("\n=== 可安全清理项 ===")
cleanables = [
    (r'C:\Users\WIN10\AppData\Local\Temp', '用户临时文件'),
    (r'C:\Users\WIN10\AppData\Local\CrashDumps', '崩溃转储'),
    (r'D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\cache', 'Hermes缓存'),
    (r'C:\Users\WIN10\AppData\Local\Microsoft\Windows\INetCache', 'IE缓存'),
]
for path, desc in cleanables:
    if os.path.exists(path):
        size = dir_size(path, 4)
        print(f'{size/1e9:8.2f} GB  [{desc}]')
