@echo off
rem QSP_MsgDrain wrapper - zhuanqian message queue drain (P0-1 fix, 2026-10-14)
rem Scheduled every 5 min: drain data/message_queue.json via lark-cli, fallback bot API / webhook
rem Output appended to data/drain.log (watch for P0-ALERT lines)
set PYTHONPATH=
rem 2026-10-24 P1修复: ServiceAccount上下文无USERPROFILE → lark-cli not_configured; 强制WIN10 profile
set "USERPROFILE=C:\Users\WIN10"
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "D:\open code\zhuanqian\cron_message_sender.py" >> "D:\open code\zhuanqian\data\drain.log" 2>&1
