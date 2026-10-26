# 老三任务板刷新器 — 注册 Windows 计划任务（幂等）
$ErrorActionPreference = "Stop"
$py      = "D:\open code\zhuanqian\.venv\Scripts\python.exe"
$script  = "D:\open code\zhuanqian\scripts\refresh_task_board.py"
$workdir = "D:\open code\zhuanqian"
$task    = "Zhuanqian_RefreshTaskBoard"

# 幂等: 移除旧任务
$existing = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
if ($existing) { Unregister-ScheduledTask -TaskName $task -Confirm:$false }

$act  = New-ScheduledTaskAction -Execute $py -Argument ("`"" + $script + "`"" ) -WorkingDirectory $workdir
$trg  = New-ScheduledTaskTrigger -Daily -At 08:00
$set  = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $act -Trigger $trg -Settings $set -Description "laosan task board refresh (daily 08:00, detect-only, no auto state flip)" | Out-Null
$t = Get-ScheduledTask -TaskName $task
"task=" + $t.TaskName + " state=" + $t.State + " nextRun=" + $t.NextRunTime
