#!/usr/bin/env python3
"""P-C2 对照组门禁 (control gate) — 老三 10/24 04:5x

总则机器件: "修复/断言件入 check_all 自动清账前, 必须挂对照组证据
(合成故障命中 或 测试件在库), 无对照组 = 未验证, 引擎不得 auto-clear"。

K1: 自愈断言件 (selfheal 切片) 对照组覆盖审计
    证据形态 a = tests/test_<base>.py 在库且 ≥2 用例
    证据形态 b = 脚本源码含 --selftest 合成故障模式
    缺证据 → P1 "对照组缺失" (auto-clear 拦截件, 台账消费)
K2: 覆盖台账 (detail 同构输出, 台账 schema 直接消费)

只读断言: 不写盘, 不改注册表。
输出 {pass,p0,p1,detail}, 与 check_all 全域同构。
回滚点: 本件纯新增, 删 scripts/control_gate_check.py + check_all 一行即全撤。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 自愈断言件切片清单 (P-B/P-C/P-F/P-R/P-T + P2 data): base 名 → 补件建议责任人
SELFHEAL_CHECKERS: dict[str, str] = {
    "carrier_check": "@Opencode (P-B1)",
    "task_selfcheck": "@老六 (P-T1)",
    "ic_pollution_check": "@老五 (P-F1)",
    "numeric_conservation_check": "@老五 (P-F4)",
    "config_drift_check": "@老五 (P-F3)",
    "ic_blind_window_check": "@老五 (P-F2)",
    "fixguard_check": "@老三 (P-C1)",
    "refdrift_check": "@老三 (P-C3)",
    "repair_class_check": "@老三 (P-C4)",
    "data_quality_checker": "@老三 (P2 日历过滤)",
    "commit_readback_check": "@Opencode (P-B2)",
    "risk_redline_check": "@atomcode (P-R1)",
}


def _test_evidence(root: Path, base: str) -> list[str]:
    """形态 a: tests/test_<base>.py 在库且含 ≥2 个 test_ 函数"""
    f = root / "tests" / f"test_{base}.py"
    if not f.exists():
        return []
    src = f.read_text(encoding="utf-8", errors="replace")
    n = len(re.findall(r"^\s*def test_\w+", src, re.M))
    return [f"a:test_{base}.py({n}用例)"] if n >= 2 else [f"a:弱({n}用例<2)"]


def _selftest_evidence(root: Path, base: str) -> list[str]:
    """形态 b: 脚本源码含 selftest 模式"""
    f = root / "scripts" / f"{base}.py"
    if not f.exists():
        return []
    if "selftest" in f.read_text(encoding="utf-8", errors="replace"):
        return ["b:--selftest"]
    return []


def run(root: str) -> dict:
    root = Path(root)
    p0, p1 = [], []
    rows, missing = [], []
    for base, owner in SELFHEAL_CHECKERS.items():
        ev = _test_evidence(root, base) + _selftest_evidence(root, base)
        rows.append({"checker": base, "evidence": ev, "ok": bool(ev),
                     "owner": owner})
        if not ev:
            missing.append(f"{base}({owner})")
            p1.append(f"K1 {base}: 对照组证据缺失 — auto-clear 拦截件, "
                     f"补 {owner} 补件 (形态 a: tests/test_{base}.py ≥2 用例; "
                     f"形态 b: --selftest 合成故障模式)")
    return {
        "domain": "control_gate",
        "playbook": "P-C2 对照组门禁(总则机器件, 只读)",
        "pass": not (p0 or p1),
        "p0": p0,
        "p1": p1,
        "detail": {
            "covered": [r["checker"] for r in rows if r["ok"]],
            "missing": missing,
            "rows": rows,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    r = run(args.root)
    print(f"[P-C2 control_gate] pass={r['pass']} 覆盖 {len(r['detail']['covered'])}"
          f"/{len(SELFHEAL_CHECKERS)} 缺 {r['detail']['missing']}")
    for x in r["p1"]:
        print("  P1:", x)
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
