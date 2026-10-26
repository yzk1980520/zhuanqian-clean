#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""board_watchdog.py — 选股看板服务看门狗 (2026-10-15 总管)

定位: 静默监控 http://127.0.0.1:3011/onboarding 健康状态，
      服务掉线时自动拉起 board_server 进程（无窗口）。
      
v3 (2026-10-15): 修复 boot popup 事故
  - 候选链检查 pythonw.exe + pyvenv.cfg 双存（缺 cfg 会弹窗）
  - 全失败时显式抛 RuntimeError（不得静默吞异常，SOUL 准则9）
  - argv 单元素免转义（防空格路径 bug）

运行方式:
  - 手动: python board_watchdog.py
  - 计划任务: board_watchdog_launcher.vbs → pythonw board_watchdog.py (无窗口)
  - 单实例锁: data/dashboards/board_watchdog.lock
"""
import json
import os
import socket
import subprocess
import sys
import time
import datetime as dt
from pathlib import Path

# ---------- 配置 ----------
PROJECT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT / "dashboards"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOCK_FILE = DATA_DIR / "board_watchdog.lock"
LOG_FILE = DATA_DIR / "board_watchdog.log"
SERVER = "http://127.0.0.1:3011/onboarding"
CHECK_INTERVAL = 30  # 秒
TIMEOUT = 5  # 秒

# ---------- 候选 Python 路径 ----------
# v3: 候选链 + pyvenv.cfg 双检（10-15 弹窗事故修复）
HERMES_HOME = Path(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home")
_ENVS_BASE = HERMES_HOME / "installs" / "729b2843d1f89bbe" / "environments"

_PYWIN_ENV = [
    str(_ENVS_BASE / "351dee8343924f4ea7169bdb1c7d97ae" / "venv" / "Scripts" / "pythonw.exe"),
]
_PYWIN_TOOLS = []
_PYEXE_CANDIDATES = []


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def log(msg: str):
    """追加日志到文件（幂等，防并发覆盖）"""
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {msg}\n")
    except Exception as e:
        print(f"🔴 [board_watchdog.py:58] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        pass
    print(msg, file=sys.stderr, flush=True)


def is_port_listening(port: int, host: str = "127.0.0.1") -> bool:
    """检查端口是否在监听"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        result = s.connect_ex((host, port))
        s.close()
        return result == 0
    except Exception as e:
        print(f"🔴 [board_watchdog.py:71] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return False


def http_get(url: str, timeout: int = TIMEOUT) -> bool:
    """简单 HTTP GET 检查（不依赖第三方库）"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "board-watchdog/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"🔴 [board_watchdog.py:82] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return False


def resolve_launcher():
    """
    解析可用的 pythonw/python 路径。
    返回 (path, kwargs) 或 (None, {})。
    
    v3 候选链:
    1. 现役 venv pythonw.exe (需 pyvenv.cfg 存在，否则跳过 — 防弹窗)
    2. tools 目录 pythonw.exe
    3. tools 目录 python.exe (带 CREATE_NO_WINDOW)
    """
    CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    
    # 候选1: venv pythonw
    for pyw_path in _PYWIN_ENV:
        if os.path.isfile(pyw_path):
            cfg_path = os.path.join(os.path.dirname(os.path.dirname(pyw_path)), "pyvenv.cfg")
            if os.path.isfile(cfg_path):
                log(f"resolve_launcher: 启用 venv pythonw {pyw_path}")
                return pyw_path, {}
            else:
                log(f"resolve_launcher: 跳过损坏 venv (缺 pyvenv.cfg): {pyw_path}")
                continue
    
    # 候选2: tools pythonw
    for pyw_path in _PYWIN_TOOLS:
        if os.path.isfile(pyw_path):
            log(f"resolve_launcher: 启用 tools pythonw {pyw_path}")
            return pyw_path, {}
    
    # 候选3: tools python.exe (带无窗口标志)
    for py_path in _PYEXE_CANDIDATES:
        if os.path.isfile(py_path):
            log(f"resolve_launcher: 启用 tools python.exe {py_path}")
            return py_path, {"creationflags": CREATE_NO_WINDOW}
    
    log("resolve_launcher: 所有候选路径均不存在")
    return None, {}


def start_board():
    """
    启动 onboarding 服务 (无窗口)。
    成功返回 pid，失败抛 RuntimeError。
    """
    py, kw = resolve_launcher()
    if py is None:
        raise RuntimeError("无法解析任何有效的 Python 启动器 (见 resolve_launcher)")

    try:
        # onboarding 服务在 dashboards/ 目录
        server_script = PROJECT / "dashboards" / "board_onboarding.py"
        log(f"start_board: 启动 {py} {server_script} (target={SERVER})")
        popen_kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(PROJECT),
        }
        # pythonw 自身无窗口 → 不传 creationflags；python.exe 回退才传
        if kw.get("creationflags"):
            popen_kwargs["creationflags"] = kw["creationflags"]
        proc = subprocess.Popen([py, str(server_script)], **popen_kwargs)
        log(f"start_board: 已拉起 onboarding 服务 pid={proc.pid}")
        return proc.pid
    except Exception as e:
        log(f"start_board: 启动失败 {e}")
        raise


def acquire_lock() -> bool:
    """单实例锁：获取锁文件或退出"""
    try:
        if LOCK_FILE.exists():
            older = (time.time() - LOCK_FILE.stat().st_mtime) > 300  # 5分钟
            if not older:
                log("acquire_lock: 检测到已有存活的 watchdog 实例, 本实例退出")
                return False
            log("acquire_lock: 清除过期锁文件")
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        log(f"acquire_lock: 锁操作异常 {e}")
        return False


def release_lock():
    """释放单实例锁"""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception as e:
        print(f"🔴 [board_watchdog.py:175] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        pass


def main():
    log(f"watchdog 启动 pid={os.getpid()}")
    
    if not acquire_lock():
        sys.exit(0)
    
    # 启动时先检查一次
    if not is_port_listening(3011):
        log("看板掉线, 已静默拉起 board_server")
        try:
            start_board()
        except RuntimeError as e:
            log(f"拉起失败: {e}")
    
    # 主循环
    while True:
        try:
            if not is_port_listening(3011):
                log("看板掉线, 已静默拉起 board_server")
                try:
                    start_board()
                except RuntimeError as e:
                    log(f"拉起失败: {e}")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            log("watchdog 收到中断信号, 退出")
            break
        except Exception as e:
            log(f"watchdog 循环异常: {e}")
            time.sleep(CHECK_INTERVAL)
    
    release_lock()
    log("watchdog 已停止")


if __name__ == "__main__":
    sys.exit(main())
