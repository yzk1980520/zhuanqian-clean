#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fixguard_check.py — 自愈引擎 v1.0 P-C1 未固化修复守卫（2026-10-23 夜 老三认领）
=============================================================================
背景样本: 2026-10-23 归档轮 490/119/8 脚本三轮擦肩未固化 diff;
          23 处锚点修复 + L57 修复长期 uncommitted, 差一轮归档全丢。

断言(只读, git plumbing, 无网络无副作用):
  A1 核心面 M 件龄 >48h (core/ scripts/ backtest/ 下 modified 且 mtime 超龄) → P1
     "修复未固化, 归档轮误伤风险" (新鲜 M=在途批次, 仅 info 不告警)
  A2 核心面 untracked 代码/数据件 (core/ backtest/ 下未忽略的 .py/.json;
     scripts/ 同) → P1 "代码未固化" (*.bak_* / *.pyc / __pycache__ 豁免)
  A3 元数据白名单 M (data/review_status.json, data/factor_gate.json,
     data/jev_*_ruling.json, data/factor_ic/factor_gate.json) → P1
     "metadata 未固化=闭环缺口" (10/23 review_status 72行 diff 悬置两天样本)

输出: 与 carrier_check 同构 JSON {pass, p0, p1, detail}, 供老六台账 schema 直接消费。
exit: 0=无 P0/P1, 1=有告警, 2=自检异常(fail-close)。
用法: python scripts/fixguard_check.py [--root <仓库根>]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# 核心面 (归档轮高危区): 修改/新增代码必须固化
# 元数据白名单 (总管更正版: metadata 必须 commit, raw 数据永远 untracked)
METADATA_WHITELIST = (
    "data/review_status.json",
    "data/factor_gate.json",
    "data/factor_ic/factor_gate.json",
)
METADATA_GLOB = re.compile(r"^data/jev_[a-z0-9]+_ruling\.json$")
# 豁免模式 (备份件/字节码, 非固化目标)
EXEMPT = re.compile(r"(\.bak_[0-9]{8}$|\.pyc$|__pycache__|\.log$)")
STALE_HOURS = 48
CODE_EXTS = re.compile(r"\.(py|json)$")


def _git(root: str, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", "-C", root] + list(args),
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _parse_porcelain(root: str):
    """返回 (modified[], untracked[]) — M 走 porcelain v1;
    untracked 走 ls-files --others --exclude-standard(逐文件不折叠目录, 尊重 gitignore;
    porcelain 会把只含新文件的目录折叠成 `core/` 逃过扩展名检查 — 20261024 对照组抓出)。"""
    rc, out = _git(root, "status", "--porcelain=v1", "--untracked-files=normal")
    if rc != 0:
        raise RuntimeError(f"git status 失败 rc={rc}: {out[:200]}")
    rc2, out2 = _git(root, "ls-files", "--others", "--exclude-standard")
    if rc2 != 0:
        raise RuntimeError(f"git ls-files 失败 rc={rc2}: {out2[:200]}")
    untracked = [l for l in out2.splitlines() if l.strip()]
    modified = []
    for line in out.splitlines():
        if not line.strip() or line[:3] == "?? ":
            continue
        code, path = line[:2], line[3:]
        if code[0] == "M" or "M" in code:  # M?  / MM 均视为未固化
            modified.append(path)
    return modified, untracked


def run(root: str) -> dict:
    now = time.time()
    p1, p0 = [], []
    modified, untracked = _parse_porcelain(root)

    # A1: 核心面 M 件龄
    stale, fresh = [], []
    for rel in modified:
        if not any(rel.startswith(s) for s in ("core/", "scripts/", "backtest/")):
            continue
        absp = Path(root) / rel
        if absp.exists():
            age_h = (now - absp.stat().st_mtime) / 3600
            (stale if age_h > STALE_HOURS else fresh).append(
                {"file": rel, "mtime_age_h": round(age_h, 1)})
    for it in stale:
        p1.append(f"A1 核心面修复未固化({STALE_HOURS}h超龄): {it['file']} "
                 f"(mtime {it['mtime_age_h']}h) — 归档轮误伤风险, 必须 commit 固化")

    # A2: 核心面 untracked 代码件
    loose = []
    for rel in untracked:
        if EXEMPT.search(rel):
            continue
        if not any(rel.startswith(s) for s in ("core/", "scripts/", "backtest/")):
            continue
        if CODE_EXTS.search(rel):
            loose.append(rel)
    for rel in loose:
        p1.append(f"A2 核心面未固化代码件(untracked): {rel} — 载体/代码丢失即断链")

    # A3: 元数据白名单 M
    meta_m = []
    for rel in modified:
        if rel in METADATA_WHITELIST or METADATA_GLOB.match(rel):
            meta_m.append(rel)
    for rel in meta_m:
        p1.append(f"A3 metadata 未固化(闭环缺口): {rel} — 按更正版政策 metadata 必须 commit")

    return {
        "domain": "fixguard",
        "playbook": "P-C1 未固化修复守卫(只读断言版)",
        "pass": not (p0 or p1),
        "p0": p0,
        "p1": p1,
        "detail": {
            "modified_core": [f["file"] for f in fresh],
            "stale_modified": stale,
            "untracked_core": loose,
            "metadata_modified": meta_m,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    try:
        result = run(args.root)
    except Exception as exc:  # fail-close: 自检本身异常=ERROR, 不许静默绿
        print(json.dumps({"domain": "fixguard", "pass": False, "p0": [], "p1": [],
                          "error": f"fixguard 自检异常: {exc}"},
                         ensure_ascii=False, indent=1))
        sys.exit(2)
    print(f"[P-C1 fixguard] M核心={len(result['detail']['modified_core'])} "
          f"超龄={len(result['detail']['stale_modified'])} "
          f"untracked={len(result['detail']['untracked_core'])} "
          f"metaM={len(result['detail']['metadata_modified'])} "
          f"| P0={len(result['p0'])} P1={len(result['p1'])}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
