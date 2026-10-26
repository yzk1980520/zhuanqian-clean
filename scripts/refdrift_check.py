#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
refdrift_check.py — 自愈引擎 v1.0 P-C3 分支/ref 漂移自检（2026-10-23 夜 老三认领）
=============================================================================
背景样本: main 落后 336 提交 + 探测层"86 提交滞后"陈旧 ref 误报 (T7 报的是本地陈旧
          main, 非 server 真值) — 检测信号自身漂移会喂死引擎, 需每日机械断言。

断言(默认只读本地 ref, 无网络; FETCH_HEAD 新鲜度监控 fetch 通道健康):
  R1 main ↔ origin/main  0/0, 否则 P1 (落后=陈价风险, 超前=未推)
  R2 github-main ↔ origin/main: ahead>0 → P1 "工作线未推 server 灾备缺口";
     behind>0 → P0 "server 领先本地, 本地工作线可能丢提交"
  R3 .git/FETCH_HEAD 龄 >26h → P1 "ref 快照陈旧, 漂移断言盲区"
     (fetch 通道=老六 T7 承接; 本断言只监控不代发网络请求, 保门禁侧无网络副作用)

输出: 与 carrier_check/fixguard_check 同构 JSON {pass, p0, p1, detail},
      供老六台账 schema 直接消费。
exit: 0=无告警, 1=P1, 2=P0 或自检异常(fail-close)。
用法: python scripts/refdrift_check.py [--root <仓库根>]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

FETCH_MAX_AGE_H = 26.0


def _git(root: str, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", "-C", root] + list(args),
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _ahead_behind(root: str, local: str, remote: str) -> tuple[int, int, int]:
    """left-right count: (ahead, behind, rc)。本地 ref 缺失 → rc=128 由调用方 fail-close。"""
    rc, out = _git(root, "rev-list", "--left-right", "--count",
                   f"{local}...{remote}")
    if rc != 0:
        return 0, 0, rc
    l, r = out.strip().split()
    return int(l), int(r), 0


def _fetch_head_age_h(root: str) -> float | None:
    fh = Path(root) / ".git" / "FETCH_HEAD"
    if not fh.exists():
        return None
    return (time.time() - fh.stat().st_mtime) / 3600


def run(root: str) -> dict:
    p0, p1, commits = [], [], []

    ahead1, behind1, rc1 = _ahead_behind(root, "main", "origin/main")
    if rc1 != 0:
        p1.append(f"R1 断言不可执行: main 或 origin/main 本地 ref 缺失(rc={rc1}) "
                 f"— fetch 通道断了, 漂移不可见")
    elif ahead1 or behind1:
        p1.append(f"R1 main↔origin/main 漂移: ahead={ahead1} behind={behind1} "
                 f"— 落后=陈价风险, 超前=未推 server")

    ahead2, behind2, rc2 = _ahead_behind(root, "github-main", "origin/main")
    if rc2 != 0:
        p1.append(f"R2 断言不可执行: github-main 或 origin/main 本地 ref 缺失(rc={rc2})")
    else:
        if behind2 > 0:
            p0.append(f"R2 github-main 落后 origin/main {behind2} 提交 — "
                     f"本地工作线缺 server 提交, 继续工作=丢提交")
        if ahead2 > 0:
            rc_, out = _git(root, "log", "--oneline",
                            f"origin/main..github-main", f"-n{min(ahead2,10)}")
            commits = [l for l in out.strip().splitlines() if l]
            p1.append(f"R2 github-main 领先 origin/main {ahead2} 提交未推 — "
                     f"server 灾备缺口, 推送通道(老六 T7)应尽快推平")

    age = _fetch_head_age_h(root)
    if age is None:
        p1.append("R3 FETCH_HEAD 不存在 — 从未 fetch, 全部 ref 断言为盲区")
    elif age > FETCH_MAX_AGE_H:
        p1.append(f"R3 FETCH_HEAD 龄 {age:.1f}h > {FETCH_MAX_AGE_H:.0f}h — "
                 f"ref 快照陈旧, 漂移断言不可信 (fetch 通道=老六 T7)")

    return {
        "domain": "refdrift",
        "playbook": "P-C3 ref 漂移自检(只读断言版)",
        "pass": not (p0 or p1),
        "p0": p0,
        "p1": p1,
        "detail": {
            "main_ahead_origin": ahead1, "main_behind_origin": behind1,
            "ghmain_ahead_origin": ahead2, "ghmain_behind_origin": behind2,
            "unpushed_commits": commits,
            "fetch_head_age_h": round(age, 1) if age is not None else None,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    try:
        result = run(args.root)
    except Exception as exc:  # fail-close: 自检异常不许静默绿
        print(json.dumps({"domain": "refdrift", "pass": False, "p0": [], "p1": [],
                          "error": f"refdrift 自检异常: {exc}"},
                         ensure_ascii=False, indent=1))
        sys.exit(2)
    d = result["detail"]
    print(f"[P-C3 refdrift] main a/b={d['main_ahead_origin']}/{d['main_behind_origin']} "
          f"ghmain a/b={d['ghmain_ahead_origin']}/{d['ghmain_behind_origin']} "
          f"FETCH={d['fetch_head_age_h']}h | P0={len(result['p0'])} P1={len(result['p1'])}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(2 if result["p0"] else (0 if result["pass"] else 1))


if __name__ == "__main__":
    main()
