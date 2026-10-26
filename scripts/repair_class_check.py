#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
repair_class_check.py — 自愈引擎 v1.0 P-C4 repair_class 四态标注审计（2026-10-24 老三落地）
=============================================================================
2026-10-24 破圈实锤: 老三此前报的 P-C4 commit d9477868 全 remote 不可达(cat-file 不存在,
reflog 无载) = 虚报。本件为 P-C4 真实落地: 把"repair_class 四态 + 防洗白路由"从纸面
总则变成机器门禁, 对 P-B4 配方注册表 (scripts/selfheal_recipes.json) 做只读审计。

四态 (老六台账 schema v1 + 老五 quarantine 输入):
  fixable        可自动修复 (dry-run 先行)          → 自动执行准入
  source_gap     数据源缺口 (不可修)                → 豁免打标, 引擎不碰
  checker_defect 检查器缺陷 (该修 checker)          → 告警修复 checker, 不修数据
  quarantine     污染源 (10/21 IC 注入型)          → 只隔离不修复, 人工会签

断言 (对注册表逐件, 只读):
  C1 每件 recipe 必须有 repair_class ∈ 四态封闭集 — 缺失/第五态 = P0 (schema 漂移)
  C2 防洗白路由: repair_class=quarantine|source_gap|checker_defect 的件
     必须 enabled=false — 非 fixable 件开闸自动执行 = 洗白通道, 命中 P0
  C3 见证规则: enabled=true (未来开闸件) 必须带 witness 或 spec 引见证 — 缺见证 P1
     (总则1: 见证人≠修复人)
  C4 owner_slice 路由: 每件必须有 owner_slice ∈ {connect,data,code,factor,risk}
     — 缺失 P1 (引擎无法路由自动修)
  C5 gating.auto_enable=false 期间 enabled=true 的件 = P1 "开闸锁失效件"
     (开闸须经 @atomcode 三项验收, 引擎侧防先行偷跑)

输出与 carrier_check 同构 {pass,p0,p1,detail}, 老六台账 schema 直接消费。
exit: 0=全过, 1=P1, 2=P0/自检异常(fail-close)。
用法: python scripts/repair_class_check.py [--root <仓库根>]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

CLASSES = ("fixable", "source_gap", "checker_defect", "quarantine")
OWNERS = ("connect", "data", "code", "factor", "risk")
NON_AUTO = ("source_gap", "checker_defect", "quarantine")
RECIPE_FILE = "scripts/selfheal_recipes.json"


def run(root: str) -> dict:
    p0, p1 = [], []
    p = Path(root) / RECIPE_FILE
    if not p.exists():
        p0.append(f"注册表缺失: {RECIPE_FILE} — P-C4 审计无对象, 开闸前置件断链")
        return {"domain": "repair_class", "pass": False, "p0": p0, "p1": p1,
                "detail": {"recipes": [], "gating": {}}}
    reg = json.loads(p.read_text(encoding="utf-8"))
    recipes = reg.get("recipes", [])
    gating = reg.get("gating", {})
    auto = gating.get("auto_enable")

    detail_rows = []
    for r in recipes:
        rid = r.get("id", "<no-id>")
        cls = r.get("repair_class")
        owner = r.get("owner_slice")
        enabled = bool(r.get("enabled"))
        row = {"id": rid, "class": cls, "owner": owner, "enabled": enabled}
        detail_rows.append(row)

        # C1 封闭集
        if cls not in CLASSES:
            sev = p0 if cls is not None else p0
            sev.append(f"C1 {rid}: repair_class={cls!r} 缺失或越出四态封闭集"
                      f"{list(CLASSES)} — schema 漂移, 引擎路由失明")
        # C2 防洗白路由
        if cls in NON_AUTO and enabled:
            p0.append(f"C2 {rid}: repair_class={cls} 非自动可修件却 enabled=true — "
                      f"洗白通道, 开闸即假修复")
        # C3 见证规则 (开闸件才生效, 当前全 enabled=false 不触发)
        if enabled and not ("witness" in r or "spec" in r):
            p1.append(f"C3 {rid}: enabled=true 但无 witness/spec 见证引用 — 违反总则1")
        # C4 owner 路由
        if owner not in OWNERS:
            p1.append(f"C4 {rid}: owner_slice={owner!r} 缺失或越界{list(OWNERS)} — 引擎无法路由")
        # C5 开闸锁
        if enabled and auto is not False:
            p1.append(f"C5 {rid}: enabled=true 但 gating.auto_enable={auto!r} — 开闸锁失效件, 未走验收先行偷跑")

    ok = not (p0 or p1)
    return {
        "domain": "repair_class",
        "playbook": "P-C4 repair_class 四态标注审计(只读版)",
        "pass": ok,
        "p0": p0,
        "p1": p1,
        "detail": {
            "recipes": detail_rows,
            "gating": {"auto_enable": auto,
                        "witness_rule": gating.get("witness_rule")},
            "recipe_count": len(recipes),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    try:
        result = run(args.root)
    except Exception as exc:
        print(json.dumps({"domain": "repair_class", "pass": False, "p0": [], "p1": [],
                          "error": f"repair_class 自检异常: {exc}"},
                         ensure_ascii=False, indent=1))
        sys.exit(2)
    print(f"[P-C4 repair_class] 配方 {result['detail']['recipe_count']} 件 "
          f"auto_enable={result['detail']['gating']['auto_enable']} | "
          f"P0={len(result['p0'])} P1={len(result['p1'])}")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(2 if result["p0"] else (0 if result["pass"] else 1))


if __name__ == "__main__":
    main()
