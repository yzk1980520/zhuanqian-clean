' W3 提权补刀: VBS 本身无法触发 UAC(4参sh.Run在本机引擎无效), 改由 PowerShell 原生 Start-Process -Verb RunAs 弹 UAC
' 双击本 VBS → 桌面右下角 UAC 确认框 → 点"是" → 逐项证据落 mainline\logs\w3_repoint_elevated.log
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -Command ""Start-Process powershell -Verb RunAs -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy Bypass','-File','D:\open code\zhuanqian\scripts\w3_repoint_elevated.ps1' -Wait"""
