Set sh = CreateObject("Shell.Application")
sh.ShellExecute "cmd.exe", "/c ""D:\open code\zhuanqian\scripts\elevate_task_wrap.bat" > ""D:\open code\zhuanqian\logs\elevate_task_wrap.out" 2>&1 && exit", "", "runas", True
