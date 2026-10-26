# -*- coding: utf-8 -*-
"""run_backtest_hidden.py — 无窗口后台跑回测脚本（防弹窗 + 防死机）。
用法: python run_backtest_hidden.py <cmd...>
例:   python run_backtest_hidden.py python scripts_tmp/hermes-verify-factor-prune.py --scans 136
特点:
- CREATE_NO_WINDOW 无窗口后台运行（不弹黑框）
- 输出重定向到 data/<name>_hidden.log
- 子进程 env 注入 HERMES_LOW_MEM=1（脚本内可读以限制 worker）
"""
import os
import subprocess
import sys
import time

CREATE_NO_WINDOW = 0x08000000
os.environ["HERMES_LOW_MEM"] = "1"

cmd = sys.argv[1:]
if not cmd:
    print("用法: python run_backtest_hidden.py <cmd...>")
    sys.exit(2)

# 日志名取"实际干活的目标"：解释器(python.exe)后跟脚本 → 用脚本名，否则用 cmd[0] 基名
_py = os.path.basename(cmd[0]).lower()
if _py in ("python", "python.exe", "py", "py.exe") and len(cmd) > 1 and cmd[1].endswith(".py"):
    _base = os.path.basename(cmd[1])
else:
    _base = os.path.basename(cmd[0])
name = os.path.splitext(_base)[0]
logdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(logdir, exist_ok=True)
log = open(os.path.join(logdir, f"{name}_hidden.log"), "w", encoding="utf-8")
err = open(os.path.join(logdir, f"{name}_hidden.log.err"), "w", encoding="utf-8")

p = subprocess.Popen(cmd, cwd=os.getcwd(), stdout=log, stderr=err,
                     creationflags=CREATE_NO_WINDOW,
                     env={**os.environ})
print(f"已无窗口后台启动: {' '.join(cmd)} (pid={p.pid})")
print(f"日志: data\\{name}_hidden.log")
