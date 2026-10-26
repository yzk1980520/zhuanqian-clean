# 注册看板 watchdog 计划任务（登录自启 + 无窗口）
# 幂等: 先删同名旧任务再建
# 2026-10-15 总管: 任务动作改为自解析 launcher VBS (候选链+护栏), 不再硬编码 env 路径
# (旧版指向 c5158a71 venv pythonw: 该 env 环境重建后丢 pyvenv.cfg -> 登录弹窗事故;
#  c5158a71 已于 10-15 隔离至 hermes-home\.trash_envs\)
$ErrorActionPreference = "Stop"

$taskName = "Zhuanqian_BoardWatchdog"
$launcher = "D:\open code\zhuanqian\scripts\board_watchdog_launcher.vbs"
$script   = "D:\open code\zhuanqian\scripts\board_watchdog.py"

# 路径存在性校验, 缺任一则中止
if (-not (Test-Path $launcher)) { Write-Output "ABORT: launcher 不存在"; exit 1 }
if (-not (Test-Path $script))   { Write-Output "ABORT: watchdog 脚本不存在"; exit 1 }

# 删旧任务 (若存在)
$old = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($old) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false | Out-Null
  Write-Output "已删除旧任务 $taskName"
}

# 构建动作: wscript 跑 launcher VBS (自解析 pythonw 候选链, 全程静默)
$action  = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$launcher`""

# 触发器: 登录时 (交互, session1, 端口可正常绑定 localhost)
$trigger = New-ScheduledTaskTrigger -AtLogOn

# 设置: 任务已运行期间不启动新实例 (配合 watchdog 内单实例锁双保险)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Yulongjue board watchdog (pythonw, no window, auto-start at logon)" -Force | Out-Null

# 启用并验证
$reg = Get-ScheduledTask -TaskName $taskName
Write-Output ("注册结果: " + $reg.State + " | Execute=" + $reg.Actions.Execute + " | Args=" + $reg.Actions.Arguments)
