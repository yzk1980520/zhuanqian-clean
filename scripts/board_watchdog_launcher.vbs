' board watchdog launcher v3 (2026-10-15)
' candidate pythonw chain + FileExists guards (incl. pyvenv.cfg sanity), silent exit
' fixes boot popup: "Python venv launcher ... failed to locate pyvenv.cfg"
' (env c5158a71 venv lost pyvenv.cfg after env rebuild; task was stuck at MessageBox)
Set fso = CreateObject("Scripting.FileSystemObject")
Set ws = CreateObject("WScript.Shell")
HOME = "D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
ENVS = HOME & "\installs\729b2843d1f89bbe\environments"
scr = "D:\open code\zhuanqian\scripts\board_watchdog.py"
IF NOT fso.FileExists(scr) THEN WScript.Quit 0

' venv launcher shim needs pyvenv.cfg next to the venv root, else it shows a dialog.
' So candidate check = pythonw.exe exists AND venv\pyvenv.cfg exists.
Function VenvPywOk(envid)
    Dim p, cfg
    p = ENVS & "\" & envid & "\venv\Scripts\pythonw.exe"
    cfg = ENVS & "\" & envid & "\venv\pyvenv.cfg"
    VenvPywOk = fso.FileExists(p) And fso.FileExists(cfg)
End Function

pyw = ""
IF VenvPywOk("351dee8343924f4ea7169bdb1c7d97ae") THEN
    pyw = ENVS & "\351dee8343924f4ea7169bdb1c7d97ae\venv\Scripts\pythonw.exe"
' legacy env c5158a71 quarantined 2026-10-15 to hermes-home\.trash_envs (venv had no Lib)
ELSE
    ' fallback: tools full-python glob python-3.14*\pythonw.exe
    ' (guarded: GetFolder on missing dir raises -> WSH error dialog, 2026-10-15 review fix)
    On Error Resume Next
    SET tf = fso.GetFolder(HOME & "\tools")
    IF Err.Number <> 0 THEN
        Err.Clear
        tf = Nothing
    END IF
    On Error Goto 0
    IF tf IS NOT NULL THEN
        FOR EACH d IN tf.SubFolders
            IF InStr(d.Name, "python-3.14") = 1 AND fso.FileExists(d.Path & "\pythonw.exe") THEN
                pyw = d.Path & "\pythonw.exe"
                EXIT FOR
            END IF
        NEXT
    END IF
END IF
IF pyw = "" THEN WScript.Quit 0
' launch failure must stay silent (never a WSH error dialog)
On Error Resume Next
ws.Run """" & pyw & """ """ & scr & """", 0, False
IF Err.Number <> 0 THEN Err.Clear
On Error Goto 0
