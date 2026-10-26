' 选股看板启动器 v4 - 直接 Run python -E (隐藏窗口)
Set sh = CreateObject("WScript.Shell")
py = "C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe"
script = "D:\open code\zhuanqian\dashboards\board_server.py"
sh.CurrentDirectory = "D:\open code\zhuanqian"
sh.Run py & " -E """ & script & """", 0, False
