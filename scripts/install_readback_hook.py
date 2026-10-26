#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_readback_hook.py — P-B2 post-commit 钩子安装器 (carrier 件, commit 固化, 幂等)
把 P-B2 read-back 断言接进 .git/hooks/post-commit:
  - 链式追加 (git-lfs 等既有 hook 不动), 标记块防重
  - 钩子失败仅告警不阻断 commit (read-back 是事后校验, 不卡提交链路)
重跑 = 0 写入 (幂等); 新 clone 后跑一次即重建钩子。
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".git" / "hooks" / "post-commit"
MARK_START = "# >>> P-B2 commit read-back (carrier: scripts/install_readback_hook.py)"
MARK_END = "# <<< P-B2 commit read-back"
BLOCK = f"""{MARK_START}
# 闭环资产 read-back 断言 (失败仅告警, 不阻断 commit; 告警进飞书 5min SLA)
PY=("{ROOT}/.venv/Scripts/python.exe")
if [ -x "$PY" ]; then
  "$PY" "{ROOT}/scripts/commit_readback_check.py" >/dev/null 2>&1 || \\
    echo "[P-B2 read-back] WARNING: 闭环资产固化断言失败 (见 check_all readback 域) — exit 1" >&2
fi
{MARK_END}
"""


def main():
    if not HOOK.exists():
        print("[install_readback_hook] 无既有 post-commit, 新建")
        HOOK.parent.mkdir(parents=True, exist_ok=True)
        HOOK.write_text("#!/bin/sh\n")
    cur = HOOK.read_text(encoding="utf-8", errors="replace")
    if MARK_START in cur:
        print("[install_readback_hook] P-B2 块已在位, 0 写入 (幂等)")
        return 0
    if not (cur.startswith("#!/bin/sh") or "#!/bin/bash" in cur.splitlines()[0:1][0]):
        # 非 sh 头部: 仍追加, 但提示
        print("[install_readback_hook] 注: 既有 hook 头部非常规, 仍按 sh 语义追加")
    new = cur.rstrip("\n") + "\n" + BLOCK
    HOOK.write_text(new, encoding="utf-8")
    subprocess.run(["chmod", "+x", str(HOOK)], check=False)
    print(f"[install_readback_hook] P-B2 块已追加到 {HOOK} (链式, lfs 段保留)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
