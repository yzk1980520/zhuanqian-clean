#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py contract
# -*- coding: utf-8 -*-
"""
快速验证Hermes配置优化

2026-10-21 修复：本机 PATH 上的 hermes 实际解析为 .CMD 文件
(D:\\Hermes agent\\...\\bin\\hermes.CMD)，Windows CreateProcess 无法直接启动
.CMD，导致 subprocess.run(["hermes", ...]) 必抛 FileNotFoundError [WinError 2]，
contract 域因此恒定 FAIL。改为先解析真实可执行文件路径，再按扩展名决定调用方式。
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# 实测（2026-10-21，.venv）: profile list ~14-16s / gateway status ~25-26s。
# 45s 给足余量；两步最坏 90s 仍小于 check_all 对本脚本的 120s 外层超时。
HERMES_TIMEOUT_S = 45
# Windows 下需经 cmd.exe /c 才能启动的脚本型"可执行"文件
_SHELL_WRAPPED_SUFFIXES = {".cmd", ".bat"}


def _load_hermes_env() -> dict:
    """解析 ~/.hermes/.env 成 {键: 值}。文件不存在返回 {}。

    2026-10-26 P0修复(老五): Windows服务环境 Path.home() 可能解析到
    C:\\WINDOWS\\system32\\config\\systemprofile 而非用户主目录，
    导致找不到 .env → 增加 USERPROFILE 和 HERMES_HOME 多候选兜底。
    """
    import os as _os
    candidates = [
        Path.home() / ".hermes" / ".env",
        Path(_os.environ.get("USERPROFILE", "")) / ".hermes" / ".env" if _os.environ.get("USERPROFILE") else None,
        Path(_os.environ.get("HERMES_HOME", "")) / ".env" if _os.environ.get("HERMES_HOME") else None,
        # HERMES_HOME 指向 profile 子目录, .env 在 hermes-home 根目录 (parent.parent)
        Path(_os.environ.get("HERMES_HOME", "")).parent.parent / ".env" if _os.environ.get("HERMES_HOME") else None,
    ]
    env_file = next((c for c in candidates if c and c.is_file()), None)
    if env_file is None:
        # 留痕：哪个 .env 生效可追溯（t_8969284a P2）。候选序不动。
        print(f'  [verify_config.env] 未命中任何 .env 候选（候选数={sum(1 for c in candidates if c)}）→ 返回 {{}}')
        return {}
    print(f'  [verify_config.env] 命中候选 .env: {env_file}')
    data = {}
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _resolve_hermes() -> str | None:
    """
    解析 hermes 真实可执行文件路径，解析不到返回 None。

    PATH 上的 hermes 可能是 .CMD 包装脚本（CreateProcess 不能直接启动），
    因此只负责"找到文件"，调用方式交给 _run_hermes 按扩展名决定。
    """
    candidates = [
        os.environ.get("HERMES_BIN"),
        shutil.which("hermes"),
        _load_hermes_env().get("HERMES_BIN"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _run_hermes(args: list) -> tuple:
    """
    调用 hermes 子命令。

    返回 (rc, stdout, stderr)；若 hermes 不可用（找不到可执行文件 / 超时 /
    启动失败）返回 (None, "", reason)，由调用方降级为 WARN —— 绝不静默当 PASS。
    """
    exe = _resolve_hermes()
    if exe is None:
        return None, "", "找不到 hermes 可执行文件（HERMES_BIN / PATH 均未命中）"

    if Path(exe).suffix.lower() in _SHELL_WRAPPED_SUFFIXES:
        # .CMD/.BAT 必须经 cmd.exe /c 启动。用列表形式传参，由 Python 负责
        # 引号转义，路径含空格也不会被 cmd 拆开。
        cmd = [os.environ.get("COMSPEC") or "cmd", "/c", exe] + list(args)
    else:
        cmd = [exe] + list(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=HERMES_TIMEOUT_S,
            stdin=subprocess.DEVNULL,  # 避免子命令等待 stdin 悬挂
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return None, "", f"hermes 调用超时（>{HERMES_TIMEOUT_S}s）"
    except OSError as exc:
        return None, "", f"hermes 调用失败：{type(exc).__name__}: {exc}"


def check_env():
    """检查环境变量"""
    data = _load_hermes_env()
    if not data:
        print("  ❌ ~/.hermes/.env 不存在或为空")
        return False

    # 原判据逐条保留，但改为"按 key 取值"：旧实现用 `"sk-" in content` 做全文件
    # 子串匹配，AGNES_API_KEY=sk-... 会让 DEEPSEEK_API_KEY 误报 ✅（假绿）。
    checks = {
        "DEEPSEEK_API_KEY": lambda v: v.startswith("sk-"),
        "OPENROUTER_API_KEY": lambda v: v.startswith("sk-or"),
        "AGNES_API_KEY": lambda v: v.startswith("cpk-") or v.startswith("sk-"),
        "ZAI_API_KEY": lambda v: bool(v) and v.lower() != "null",
    }

    all_ok = True
    for key, predicate in checks.items():
        ok = predicate(data.get(key, ""))
        status = "✅" if ok else "❌"
        print(f"  {status} {key}")
        if not ok:
            all_ok = False

    return all_ok


def check_profiles():
    """检查Profile状态"""
    rc, stdout, err = _run_hermes(["profile", "list"])
    if rc is None:
        # 降级：不可判定 → WARN，不计 PASS
        print(f"  ⚠️  hermes profile list 不可判定（{err}）→ WARN")
        return False
    if rc != 0:
        print(f"  ❌ hermes profile list 返回 rc={rc}")
        if err.strip():
            print(f"     {err.strip()[:300]}")
        return False

    lines = stdout.strip().split("\n")
    profiles = []
    for line in lines[2:]:  # 跳过标题行
        if "running" in line:
            parts = line.split()
            if parts:
                profiles.append(parts[0])

    print(f"\n📋 运行中的Profiles: {len(profiles)}")
    for p in profiles:
        print(f"  ✅ {p}")

    return len(profiles) >= 4  # default + 3个角色


def check_gateway():
    """检查Gateway状态"""
    rc, stdout, err = _run_hermes(["gateway", "status"])
    if rc is None:
        print(f"  ⚠️  hermes gateway status 不可判定（{err}）→ WARN")
        return False
    if rc != 0:
        print(f"  ❌ hermes gateway status 返回 rc={rc}")
        if err.strip():
            print(f"     {err.strip()[:300]}")
        return False

    return "running" in stdout


def main():
    env_ok = check_env()
    profiles_ok = check_profiles()
    gateway_ok = check_gateway()

    print(f"\n环境配置: {'✅' if env_ok else '❌'}")
    print(f"Profile:   {'✅' if profiles_ok else '❌'}")
    print(f"Gateway:   {'✅' if gateway_ok else '❌'}")

    return 0 if (env_ok and profiles_ok and gateway_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
