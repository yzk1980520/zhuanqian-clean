# 非管理员对象注册: Zhuanqian_DailyAuto(20:00) + AtomCode_CodingPlan_Claim(09:00) → wscript静默
$W = 'C:\WINDOWS\System32\wscript.exe'
$VBS = 'D:\open code\zhuanqian\scripts\run_path_hidden.vbs'
$log = 'D:\open code\zhuanqian\mainline\logs\w3_repoint_elevated.log'
function note($m) { Add-Content -Path $log -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) }

$za = @( @{Name='Zhuanqian_DailyAuto'; At='20:00'; Bat='D:\open code\zhuanqian\scripts\daily_auto.bat'},
         @{Name='AtomCode_CodingPlan_Claim'; At='09:00'; Bat='C:\Users\WIN10\AppData\Roaming\npm\atomcode-codingplan.bat'} )
foreach ($t in $za) {
    $existing = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    if ($existing) { note ("SKIP-EXISTS {0}" -f $t.Name) }
    else {
        $act = New-ScheduledTaskAction -Execute $W -Argument ('"{0}" "{1}"' -f $VBS, $t.Bat)
        $d = [datetime]$t.At
        $trg = New-ScheduledTaskTrigger -Daily -At $d
        $st = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
        $st.DisallowStartIfOnBatteries = $true
        $st.StopIfGoingOnBatteries = $true
        try {
            Register-ScheduledTask -TaskName $t.Name -Action $act -Trigger $trg -Settings $st -ErrorAction Stop | Out-Null
            note ("OBJECT-REGISTER-OK {0} daily {1}" -f $t.Name, $t.At)
        } catch {
            note ("OBJECT-REGISTER-FAIL {0} : {1}" -f $t.Name, $_.Exception.Message)
        }
    }
}
# 终验
foreach ($t in $za) {
    $x = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    if ($x) { note ("VERIFY {0} state={1} cmd={2}" -f $t.Name, $x.State, $x.Actions[0].Execute) }
    else { note ("VERIFY-FAIL {0} still-missing" -f $t.Name) }
}
note 'object-register-batch-finished'
