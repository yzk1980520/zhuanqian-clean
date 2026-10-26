' run_path_hidden.vbs - run any .cmd/.bat hidden, no desktop window (2026-10-15 zongguan, silent-order fix)
' Usage: wscript.exe "D:\open code\zhuanqian\scripts\run_path_hidden.vbs" "D:\open code\zhuanqian\scripts\self_heal_task.cmd"
' Same convention as run_qsp_hidden.vbs (WshShell.Run cmd /c ..., 0 = hidden, False = do not wait)
' Single source of truth stays in the repo; this VBS is the hidden runner.
Set WshShell = CreateObject("WScript.Shell")
If WScript.Arguments.Count >= 1 Then
    Dim cmdPath
    cmdPath = """" & WScript.Arguments(0) & """"
    WshShell.Run "cmd /c " & cmdPath, 0, False
End If
