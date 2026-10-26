# A12修复脚本：设置任务Hidden=true
# 需要管理员权限运行

$tasks = @('Zhuanqian_BoardWatchdog', 'QSP_PreMarket', 'QSP_ZLJWatch')

foreach ($t in $tasks) {
    try {
        $svc = New-Object -ComObject Schedule.Service
        $svc.Connect()
        $root = $svc.GetFolder('\')
        $task = $root.GetTask($t)
        
        $old = $task.Definition.Settings.Hidden
        Write-Host "$t : Hidden=$old → " -NoNewline
        
        $task.Definition.Settings.Hidden = $true
        $task.Save()
        
        Write-Host "OK (Hidden=true)"
    } catch {
        Write-Host "FAIL : $_"
    }
}
