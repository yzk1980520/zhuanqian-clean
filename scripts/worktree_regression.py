#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""W4 周回归：worktree 隔离完整性检查（cron 每周一 09:00）

协议真源: docs/团队约定-主Agent子Agent-Worktrunk-并行协议-v1.0.md §三
检查项:
  A. worktree 列表与预期集合一致
  B. 主仓无 answers_*.txt / arithmetic.txt 泄漏
  C. 各 worktree seed 文件完整
  D. git status 状态码合法（无 M 在 seed 文件上）
  E. 无 orphaned worktree（目录存在但 git worktree list 未登记）

exit 0 = 全绿；exit 1 = 存在 FAIL
"""
import glob
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ---------- 路径配置 ----------
PROJECT_ROOT    = Path(r"D:\open code\zhuanqian").resolve()
SCRATCH_DIR     = Path(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\cache\scratch\agent_parallel_test").resolve()
TESTREPO_ROOT   = SCRATCH_DIR / "testrepo"   # testrepo 仓（agent worktrees 的归属仓）
REPORT_DIR      = SCRATCH_DIR

# ---------- 断言契约 ----------
EXPECTED_WT_PREFIXES = (
    "testrepo.agent-opencode",
    "testrepo.agent-atomcode",
    "testrepo.agent-hermes",
    "testrepo.agent-workbuddy",
    "testrepo.agent-fix-review",
)
SEED_FILES = ("arithmetic.txt",)
LEAK_GLOBS = (
    "answers_*.txt",
    "arithmetic.txt",
)

# 运行时快照（main() 填充，JSON 报告写入）
_wt_raw_entries = None  # list of (path_str, branch_ref, locked_bool)


# ---------- safe.directory 预置 ----------
def _ensure_git_safe():
    """预注册所有需要访问的仓/目录到 git safe.directory，避免 'dubious ownership' 报错。

    Windows CI（SYSTEM 用户）访问 WIN10 用户创建的目录时会触发此问题。
    幂等：已注册则跳过。
    """
    dirs_to_register = [str(PROJECT_ROOT), str(TESTREPO_ROOT)]
    if SCRATCH_DIR.exists():
        for d in SCRATCH_DIR.iterdir():
            if d.is_dir() and d.name.startswith("testrepo."):
                dirs_to_register.append(str(d))
    current = subprocess.run(
        ["git", "config", "--global", "--get-all", "safe.directory"],
        capture_output=True, text=True, timeout=5,
    )
    already = set(current.stdout.strip().splitlines()) if current.returncode == 0 else set()
    for d in dirs_to_register:
        if d not in already:
            subprocess.run(
                ["git", "config", "--global", "--add", "safe.directory", d],
                capture_output=True, timeout=5,
            )


class Report:
    def __init__(self):
        self.passed, self.failed, self.warned = [], [], []

    def ok(self, name, detail=""):
        self.passed.append((name, detail))
        print(f"  [PASS] {name}" + (f"（{detail}）" if detail else ""))

    def fail(self, name, detail=""):
        self.failed.append((name, detail))
        print(f"  [FAIL] {name}" + (f"——{detail}" if detail else ""))

    def warn(self, name, detail=""):
        self.warned.append((name, detail))
        print(f"  [WARN] {name}" + (f"——{detail}" if detail else ""))


# ---------- 辅助 ----------
def _git_worktree_list(repo_path):
    """返回 [(path_str, branch_ref, locked_bool), ...]

    repo_path: 要执行 git worktree list 的仓根目录（默认用 TESTREPO_ROOT）。
    """
    r = subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        return []
    entries = []
    lines = r.stdout.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("worktree "):
            wt_path = lines[i][9:].strip()
            branch = ""
            locked = False
            i += 1
            while i < len(lines) and not lines[i].startswith("worktree "):
                if lines[i].startswith("branch "):
                    branch = lines[i][7:].strip()
                elif lines[i].strip() == "locked":
                    locked = True
                i += 1
            entries.append((wt_path, branch, locked))
        else:
            i += 1
    return entries


def _ls(wt_path, pattern):
    return glob.glob(os.path.join(wt_path, pattern))


# ---------- 检查组 ----------
def check_A_wt_list(rpt):
    """A. worktree 列表与预期前缀集合对照"""
    print("\n【A 组】worktree 注册列表")
    entries = _git_worktree_list(TESTREPO_ROOT)
    registered = {e[0] for e in entries}
    missing = []
    for prefix in EXPECTED_WT_PREFIXES:
        found = [p for p in registered if Path(p).name == prefix]
        if found:
            rpt.ok(f"worktree {prefix}", f"分支={found[0].split('/')[-1]}")
        else:
            missing.append(prefix)
            rpt.fail(f"worktree {prefix}", "git worktree list 未登记")
    if missing:
        rpt.fail("worktree 缺失", f"预期 {len(EXPECTED_WT_PREFIXES)} 个，实际注册 {len(registered)} 个，缺失={missing}")
    else:
        rpt.ok("worktree 数量", f"注册 {len(registered)} 个，全部匹配预期")


def check_B_leak_main(rpt):
    """B. 主仓及 DESK 源码仓无泄漏"""
    print("\n【B 组】主仓泄漏扫描")
    deskins = str(Path(r"D:\Hermes agent\Hermes Agent CN Desktop").resolve())
    for root in [str(PROJECT_ROOT), deskins]:
        root_p = Path(root)
        for pat in LEAK_GLOBS:
            found = _ls(root, pat)
            # 排除 .git/ 目录
            real = [f for f in found if ".git" not in f]
            if real:
                rpt.fail(f"泄漏 {root_p.name}/{pat}", f"发现 {len(real)} 个: {[os.path.basename(f) for f in real]}")
            else:
                rpt.ok(f"无泄漏 {root_p.name}/{pat}")


def check_C_seed(wpt_report):
    """C. 各 worktree seed 文件完整性（只读，不修改）"""
    print("\n【C 组】seed 文件完整性")
    entries = _git_worktree_list(TESTREPO_ROOT)
    for wt_path, branch, locked in entries:
        if not wt_path.startswith(str(SCRATCH_DIR)):
            continue
        name = os.path.basename(wt_path)
        missing = []
        for sf in SEED_FILES:
            fp = os.path.join(wt_path, sf)
            if not os.path.exists(fp):
                missing.append(sf)
        if missing:
            wpt_report.fail(f"seed {name}", f"缺失: {missing}")
        else:
            wpt_report.ok(f"seed {name}", "arithmetic.txt 存在")


def check_D_status(wpt_report):
    """D. seed 文件未被修改（arithmetic.txt 等，M 前缀）"""
    print("\n【D 组】seed 文件完整性（arithmetic.txt 等）")
    entries = _git_worktree_list(TESTREPO_ROOT)
    for wt_path, branch, locked in entries:
        name = os.path.basename(wt_path)
        # 只检查 SEED_FILES 是否存在且未被修改
        for sf in SEED_FILES:
            sf_path = os.path.join(wt_path, sf)
            if not os.path.exists(sf_path):
                continue  # C组已覆盖缺失情况
            r = subprocess.run(
                ["git", "-C", wt_path, "status", "--porcelain", "--", sf_path],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode not in (0, 1):
                wpt_report.fail(f"seed 状态 {name}/{sf}", f"git status 失败: {r.stderr[:80]}")
                continue
            line = (r.stdout.strip())
            if line and (line.startswith(" M") or line.startswith("M ")):
                wpt_report.fail(f"seed 篡改 {name}/{sf}", f"文件已被修改: {line}")
            else:
                wpt_report.ok(f"seed 干净 {name}/{sf}")


def check_E_orphaned(wpt_report):
    """E. 无 orphaned worktree 目录（目录存在但 git worktree list 未登记）

    孤儿定义：SCRATCH_DIR 下以 testrepo. 开头的目录，但不在 TESTREPO_ROOT 的
    git worktree list 中。排除：
      1. 主仓 testrepo 自身（它是仓根，不是孤儿）
      2. .git 文件指向其他仓的目录（如 testrepo.agent-fix-review-main 属于
         zhuanqian 仓，不应由 testrepo 的回归检查管辖）
    """
    print("\n【E 组】孤儿 worktree 目录扫描")
    entries = _git_worktree_list(TESTREPO_ROOT)
    registered = {os.path.abspath(e[0]) for e in entries}
    orphaned = []
    if SCRATCH_DIR.exists():
        for d in sorted(SCRATCH_DIR.iterdir()):
            # 只检查 agent worktree 子目录（testrepo.* 前缀），排除主仓 testrepo 自身
            if not d.is_dir() or not d.name.startswith("testrepo."):
                continue
            # 跳过 .git 指向非 testrepo 仓的目录（如 zhuanqian 仓的 worktree）
            git_file = d / ".git"
            if git_file.is_file():
                git_content = git_file.read_text().strip()
                if git_content.startswith("gitdir:"):
                    gitdir_path = git_content.split(":", 1)[1].strip()
                    # 统一正斜杠后比较，避免 Windows 反斜杠/正斜杠混用导致匹配失败
                    if str(PROJECT_ROOT).replace("\\", "/") in gitdir_path.replace("\\", "/"):
                        wpt_report.ok(f"跨仓归属 {d.name}", f".git 指向 zhuanqian 仓，不由 testrepo 管辖")
                        continue
            if os.path.abspath(str(d)) not in registered:
                orphaned.append(d.name)
    if orphaned:
        wpt_report.fail("孤儿目录", f"发现 {len(orphaned)} 个：{orphaned}")
    else:
        wpt_report.ok("无孤儿目录", "所有 testrepo.* 目录均在 git worktree list 中")


def check_F_scratch_health(wpt_report):
    """F. scratch 目录下各 worktree 的 answers_*.txt 归属检查"""
    print("\n【F 组】answers_*.txt 归属校验")
    if not SCRATCH_DIR.exists():
        wpt_report.warn("scratch 目录", "不存在，跳过 F 组")
        return
    for d in sorted(SCRATCH_DIR.iterdir()):
        if not d.is_dir() or not d.name.startswith("testrepo"):
            continue
        ans = [f for f in d.iterdir() if f.name.startswith("answers_") and f.suffix == ".txt"]
        if ans:
            wpt_report.ok(f"answers {d.name}", f"{len(ans)} 个（均在 worktree 内）")
        else:
            wpt_report.ok(f"clean {d.name}", "无残留答案文件")


# ---------- 主流程 ----------
def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"=== worktree_regression W4 周回归 ({now_str}) ===")
    print(f"项目根：{PROJECT_ROOT}")
    print(f"scratch：{SCRATCH_DIR}")

    rpt = Report()
    wpt = Report()  # worktree 专项（C/D/E/F）

    # 前置：预注册 safe.directory（Windows SYSTEM 用户访问 WIN10 目录必需）
    _ensure_git_safe()

    # 前置：目录存在
    if not PROJECT_ROOT.exists():
        rpt.fail("项目根", f"不存在：{PROJECT_ROOT}")
        print(f"\n=== 汇总：FAIL {len(rpt.failed)} / PASS {len(rpt.passed)} ===")
        return 1
    if not SCRATCH_DIR.exists():
        rpt.warn("scratch", f"不存在：{SCRATCH_DIR}（将跳过 worktree 组检查）")

    # A/B 必跑
    check_A_wt_list(rpt)
    check_B_leak_main(rpt)

    # 捕获 testrepo 仓的 git worktree list 原始快照（防误报回溯）
    global _wt_raw_entries
    if TESTREPO_ROOT.exists():
        _wt_raw_entries = _git_worktree_list(TESTREPO_ROOT)

    # C/D/E/F 在 scratch 存在时跑
    if SCRATCH_DIR.exists():
        check_C_seed(wpt)
        check_D_status(wpt)
        check_E_orphaned(wpt)
        check_F_scratch_health(wpt)
        rpt.failed.extend(wpt.failed)
        rpt.passed.extend(wpt.passed)
        rpt.warned.extend(wpt.warned)
        print("\n--- worktree 专项 ---")
        for n, d in wpt.passed:
            print(f"  [PASS] {n}（{d}）")
        for n, d in wpt.failed:
            print(f"  [FAIL] {n}——{d}")
        for n, d in wpt.warned:
            print(f"  [WARN] {n}——{d}")

    # 写 JSON 报告
    report_obj = {
        "ts": now_str,
        "project_root": str(PROJECT_ROOT),
        "scratch_dir": str(SCRATCH_DIR),
        "testrepo_root": str(TESTREPO_ROOT),
        "pass": len(rpt.failed) == 0,
        "passed": len(rpt.passed),
        "failed": len(rpt.failed),
        "warned": len(rpt.warned),
        "details": {"passed": rpt.passed, "failed": rpt.failed, "warned": rpt.warned},
        "git_worktree_list_raw": [
            {"path": e[0], "branch": e[1], "locked": e[2]} for e in (_wt_raw_entries or [])
        ],
    }
    report_path = REPORT_DIR / f"worktree_regression_{datetime.now().strftime('%Y%m%d')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_obj, f, ensure_ascii=False, indent=2)
    print(f"\n报告写入：{report_path}")

    # 汇总
    print(f"\n=== 汇总：PASS {len(rpt.passed)} / FAIL {len(rpt.failed)} / WARN {len(rpt.warned)} ===")
    if rpt.failed:
        print("回归结论：FAIL —— 以下项必须修复：")
        for n, d in rpt.failed:
            print(f"  - {n}：{d}")
        return 1
    if rpt.warned:
        print("回归结论：PASS（带提醒）")
        for n, d in rpt.warned:
            print(f"  - {n}：{d}")
        return 0
    print("回归结论：全绿 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
