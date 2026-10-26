@echo off
' P2-2 silent wrapper (2026-10-24 zongguan, popup-prohibition batch): runs cua-driver serve hidden; original task TR was a visible powershell one-liner on logon.
powershell -NoProfile -NonInteractive -Command "Start-Process -FilePath 'C:\Users\WIN10\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe' -ArgumentList 'serve' -WindowStyle Hidden -WorkingDirectory 'C:\Users\WIN10'"
