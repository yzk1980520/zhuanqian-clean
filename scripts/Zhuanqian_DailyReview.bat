@echo off
rem Zhuanqian_DailyReview - after-close review + closed-loop feedback write
rem Entry point for the Windows scheduled task of the same name.
rem Runs scripts/daily_review.py (the ONLY writer of data/feedback_log.jsonl)
rem and appends to data/daily_review.log
rem ASCII ONLY: cmd parses a BOM-less .bat as GBK; non-ASCII bytes eat
rem string terminators and corrupt the following line.
set PYTHONPATH=
"D:\open code\zhuanqian\.venv\Scripts\python.exe" "D:\open code\zhuanqian\scripts\daily_review.py" >> "D:\open code\zhuanqian\data\daily_review.log" 2>&1
