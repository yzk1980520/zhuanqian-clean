"""T056: pre-commit 红线门禁（FR-004, T049）回归测试。

运行真实 hooks/pre-commit（bash），用 FR004 测试缝（FR004_TEST_STAGED +
FR004_TEST_MODE=1 双标记护栏）模拟暂存区，不触碰真实 git staging：

- test_opencode_blocked_on_risk_rules: HERMES_PROFILE=opencode + staged risk_rules.py → exit=1
- test_default_allowed:                HERMES_PROFILE=default + staged risk_rules.py → exit=0
- test_dual_mark_guard:                FR004_TEST_STAGED 设值但 FR004_TEST_MODE!=1 → 测试缝无效，
                                       按真实暂存区判定（WARN 透出，exit=0）

环境假设：测试运行时无真实暂存 .py 红线文件（AOCI ①/依赖图 ④ 因此跳过）；
hook 侧治理审计 ② 非阻断，governance jsonl / message_queue 为未追踪再生件，
P1 告警副作用在本测试内做存-还卫生。
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parent.parent
HOOK = PROJ_ROOT / "hooks" / "pre-commit"
MSG_QUEUE = PROJ_ROOT / "data" / "message_queue.json"


def _find_bash() -> str | None:
    """定位 bash（hook 为 bash 脚本；Windows 上从 Git/MSYS 工具链找）。"""
    cands = []
    if os.environ.get("PRECOMMIT_TEST_BASH"):
        cands.append(os.environ["PRECOMMIT_TEST_BASH"])
    w = shutil.which("bash")
    if w:
        cands.append(w)
    # Hermes 托管的 git 工具链（MSYS bash）
    hh = os.environ.get("HERMES_HOME")
    if hh:
        cands.extend(str(p) for p in sorted(Path(hh).glob("tools/git-*/usr/bin/bash.exe")))
    cands += [
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\msys64\usr\bin\bash.exe",
        r"C:\msys64\bin\bash.exe",
        r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\tools\git-2.53.0+3-win32-x64\usr\bin\bash.exe",
    ]
    for c in cands:
        if c and Path(c).is_file():
            return c
    return None


def _run_hook(profile: str | None, staged: str | None = None, test_mode: str | None = None) -> subprocess.CompletedProcess:
    """跑一次真实 hook。staged/test_mode 走 FR004 测试缝；None = 不用测试缝。"""
    bash = _find_bash()
    assert bash, (
        "FR-004 门禁测试需要 bash（Git/MSYS 工具链）；"
        "设置 PRECOMMIT_TEST_BASH 指向 bash.exe 或安装 Git for Windows"
    )
    env = os.environ.copy()
    env.pop("FR004_TEST_STAGED", None)
    env.pop("FR004_TEST_MODE", None)
    env.pop("HERMES_PROFILE", None)
    if profile is not None:
        env["HERMES_PROFILE"] = profile
    if staged is not None:
        env["FR004_TEST_STAGED"] = staged
        env["FR004_TEST_MODE"] = "1" if test_mode is None else test_mode
    # 用 venv python 跑 hook 内的维护脚本，行为与实盘 commit 一致
    env["PYTHON"] = str(__import__("sys").executable)
    return subprocess.run(
        [bash, str(HOOK)],
        cwd=str(PROJ_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _queue_snapshot():
    if MSG_QUEUE.exists():
        try:
            return MSG_QUEUE.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    return None


def _queue_restore(raw):
    if raw is None:
        MSG_QUEUE.unlink(missing_ok=True)
    else:
        MSG_QUEUE.write_text(raw, encoding="utf-8")


def test_opencode_blocked_on_risk_rules():
    """opencode（受限 profile）+ 暂存 risk_rules.py（红线）→ 门禁拦截 exit=1。"""
    raw = _queue_snapshot()
    try:
        r = _run_hook("opencode", staged="risk_rules.py")
        assert r.returncode == 1, (
            f"期望 exit=1（红线拦截），实际 exit={r.returncode}\n"
            f"stdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}"
        )
        assert "FR-004" in r.stderr, f"stderr 缺 FR-004 拦截标记: {r.stderr[-500:]}"
        assert "opencode" in r.stderr
    finally:
        _queue_restore(raw)


def test_default_allowed():
    """default（总管 profile，红线独占方）+ 暂存 risk_rules.py → 放行 exit=0。"""
    r = _run_hook("default", staged="risk_rules.py")
    assert r.returncode == 0, (
        f"期望 exit=0（default 放行），实际 exit={r.returncode}\n"
        f"stdout: {r.stdout[-500:]}\nstderr: {r.stderr[-500:]}"
    )
    assert "OK:" in r.stderr, f"default 放行应打印 OK 行: {r.stderr[-500:]}"


def test_dual_mark_guard():
    """双标记护栏：FR004_TEST_STAGED 设值但 FR004_TEST_MODE!=1 → 测试缝无效。

    护栏生效时：按真实暂存区判定（当前无红线暂存）→ exit=0 且 WARN 透出；
    护栏失效时：测试缝被误认 → risk_rules.py 计入违例 → opencode exit=1。
    故 exit=0 + WARN 双断言即证明护栏生效。
    """
    r = _run_hook("opencode", staged="risk_rules.py", test_mode="0")
    assert "FR004_TEST_STAGED 设值但 FR004_TEST_MODE!=1" in r.stderr, (
        f"护栏 WARN 未透出:\nstderr: {r.stderr[-800:]}"
    )
    assert r.returncode == 0, (
        f"护栏失效：测试缝被误认（risk_rules.py 越界本应 exit=1，实际 exit={r.returncode}）"
    )
