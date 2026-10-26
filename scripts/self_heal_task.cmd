@echo off
rem QSP_SelfHeal wrapper - self-healing ops engine (2026-10-15 老六)
rem Every 15 min: probe(9 rules) -> repair(known failures) -> recheck -> escalate
rem Output appended to data/self_heal.log; repairs in data/repair_log.jsonl
set PYTHONPATH=
set PYTHONUTF8=1
"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe" "D:\open code\zhuanqian\self_heal_check.py" >> "D:\open code\zhuanqian\data\self_heal.log" 2>&1
