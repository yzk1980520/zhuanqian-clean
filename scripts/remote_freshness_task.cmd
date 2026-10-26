@echo off
rem QSP_RemoteFreshness wrapper - remote main freshness monitor (2026-10-15)
rem Hourly: check origin/gitcode main tip age + local ahead, alert to feishu via queue
rem Output appended to data/remote_freshness.log (watch for P1-ALERT lines)
set PYTHONPATH=
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "D:\open code\zhuanqian\scripts\check_remote_main_freshness.py" >> "D:\open code\zhuanqian\data\remote_freshness.log" 2>&1
