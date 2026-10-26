# W3  (v3  2026-10-23):  mainline-retry-cons(Unregister/Disable) + 
# : ; ; ;  = mainline\logs\w3_repoint_elevated.log
$log = 'D:\open code\zhuanqian\mainline\logs\w3_repoint_elevated.log'
function note($m) { Add-Content -Path $log -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) }
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
note ("final-batch-start isadmin=$isAdmin")

# --- : mainline-retry-cons ( mainline\retry_industry_cons.py =, W3) ---
$ml = Get-ScheduledTask -TaskName 'mainline-retry-cons' -ErrorAction SilentlyContinue
if (-not $ml) {
    note 'mainline-already-gone'
} else {
    try {
        Unregister-ScheduledTask -TaskName 'mainline-retry-cons' -Confirm:$false -ErrorAction Stop | Out-Null
        note 'mainline-UNREGISTER-OK'
    } catch {
        note ("mainline-unregister-FAIL({0}) -> Disable" -f $_.Exception.Message)
        try {
            Disable-ScheduledTask -TaskName 'mainline-retry-cons' -ErrorAction Stop | Out-Null
            note 'mainline-DISABLE-OK'
        } catch {
            note ("mainline-DISABLE-FAIL({0}) P0" -f $_.Exception.Message)
        }
    }
}

# --- () ---
$all = @('AOCI_Daily_Check','AOCI_Weekly_Score','Zhuanqian_FactorIC132d','Zhuanqian_WalkForward','P3_DailyMonitor','Zhuanqian_DailyAuto','AtomCode_CodingPlan_Claim','mainline-retry-cons','QSP_SelfHeal')
foreach ($n in $all) {
    $t = Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    if (-not $t) { note ("VERIFY {0} | GONE" -f $n) }
    else {
        $act = $t.Actions[0]
        $cmd = [string]$act.Execute
        $silent = ($cmd -like '*wscript*' -or $t.State -eq 'Disabled' -or $n -eq 'QSP_SelfHeal')
        note ("VERIFY {0} | {1} | {2} {3} | silent-or-off={4}" -f $n, $t.State, $cmd, [string]$act.Arguments, $silent)
    }
}
note 'final-batch-finished'