' W3 提权补刀入口: 双击 → UAC 确认框 → 点"是" → 逐项证据落 mainline\logs\w3_repoint_elevated.log
' 使用经证实可用的 Shell.Application.ShellExecute "runas"(4参 sh.Run 在本机引擎无效)
Set sh = CreateObject("Shell.Application")
sh.ShellExecute "powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File ""D:\open code\zhuanqian\scripts\w3_repoint_elevated.ps1""", "D:\open code\zhuanqian", "runas", 1
Set sh = Nothing
