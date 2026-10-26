# 注册Zhuanqian_BoardWatchdog（如未注册）
$xmlPath = "D:\open code\zhuanqian\.workbuddy\schtasks-fixed-20261017\Zhuanqian_BoardWatchdog.xml"
$taskExists = $false
try {
    Get-ScheduledTask -TaskName 'Zhuanqian_BoardWatchdog' -ErrorAction Stop | Out-Null
    $taskExists = $true
} catch {
}

if (-not $taskExists -and (Test-Path $xmlPath)) {
    & schtasks /create /tn "Zhuanqian_BoardWatchdog" /xml $xmlPath /f
    Write-Host "Zhuanqian_BoardWatchdog : 已注册"
} elseif ($taskExists) {
    Write-Host "Zhuanqian_BoardWatchdog : 已存在"
}

# 设置Hidden=true
@('QSP_PreMarket', 'QSP_ZLJWatch', 'Zhuanqian_BoardWatchdog') | ForEach-Object {
    $t = Get-ScheduledTask -TaskName $_
    $t.Settings.Hidden = $true
    $t | Set-ScheduledTask
    Write-Host "$_ : Hidden=true OK"
}

Write-Host "Done!"
