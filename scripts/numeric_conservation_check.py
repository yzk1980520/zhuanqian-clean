#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
numeric_conservation_check.py — P-F4 回测结论数字守恒校验 (自愈引擎 v1.0, 老五认领, 2026-10-24)
===============================================================================
只读断言: 回测结果 JSON 被引用前, 三要素必须在场 (数字守恒纪律: 说不出样本范围+
计算路径+数据截至日的数字, 引用即作废风险):
  N1 引擎版本: engine_commit 非空 hex ref (>=8位)
  N2 等价性锚点: engine_equivalence_anchor 非空; 含"需人工审查"= P1 提示(非阻断)
  N3 数据截至日: generated 时间戳在场, 距今 >7d = P1 陈旧
  N4 引用拦截: data/backtest_report_blocker.json blocked=true = P0 禁止引用
  N5 门禁态: gate.status != PASS = P0 (结果在门禁 FAIL 态, 引用前必须重跑)
输出与 carrier_check 同构 {pass,p0,p1,detail,items[]}。
用法: python scripts/numeric_conservation_check.py [--selftest]; 退出码 0=无P0 / 1=有P0
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
RESULT = "data/rotation_backtest_result.json"
BLOCKER = "data/backtest_report_blocker.json"
STALE_DAYS = 7


def check_result(d, now):
    items = []
    # N1
    ec = str(d.get("engine_commit") or "")
    n1 = "ok" if len(ec) >= 8 and all(c in "0123456789abcdef" for c in ec.lower()) else "P0"
    items.append({"check": "N1_engine_version", "status": n1,
                  "detail": f"engine_commit={ec[:12]}..." if n1 == "ok" else f"engine_commit 缺失/非法: {ec!r}"})
    # N2
    ea = str(d.get("engine_equivalence_anchor") or "")
    n2 = "ok" if ea else "P0"
    if n2 == "ok" and "需人工审查" in ea:
        n2 = "P1"
    items.append({"check": "N2_equivalence_anchor", "status": n2, "detail": ea[:80]})
    # N3
    g = d.get("generated")
    days = None
    n3 = "P0"
    detail = "generated 缺失 — 数字无截至日, 禁止引用"
    if g:
        try:
            days = (now - datetime.fromisoformat(str(g))).total_seconds() / 86400
            n3 = "ok" if days <= STALE_DAYS else "P1"
            detail = f"generated={g[:19]} ({days:.1f}d 前" + (f" > {STALE_DAYS}d 陈旧" if days > STALE_DAYS else "") + ")"
        except Exception:
            detail = f"generated 解析失败: {g!r}"
    items.append({"check": "N3_data_cutoff", "status": n3, "detail": detail})
    # N5
    gate = d.get("gate") or {}
    n5 = "P0" if gate.get("status") != "PASS" else "ok"
    items.append({"check": "N5_gate_state", "status": n5,
                  "detail": f"gate={gate.get('status')} (gate_id={gate.get('gate_id', 'n/a')})"
                  if n5 == "ok" else "门禁非 PASS — 结果引用前须重跑 gate"})
    return items


def run_check():
    now = datetime.now()
    p = PROJECT / RESULT
    if not p.exists():
        return {"pass": True, "p0": 0, "p1": 0, "detail": "回测结果文件不存在, 无引用面, 0 告警",
                "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"), "items": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"pass": False, "p0": 1, "p1": 0, "detail": f"结果 JSON 损坏: {e}",
                "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "items": [{"check": "result_readable", "status": "P0", "detail": str(e)}]}
    items = check_result(d, now)
    # N4 拦截件
    bp = PROJECT / BLOCKER
    if bp.exists():
        try:
            blk = json.loads(bp.read_text(encoding="utf-8"))
            if blk.get("blocked"):
                items.append({"check": "N4_blocker", "status": "P0",
                              "detail": f"blocker 生效: {blk.get('reason', 'n/a')} — 禁止引用该结果"})
            else:
                items.append({"check": "N4_blocker", "status": "ok", "detail": "blocker 存在但 blocked=false"})
        except Exception as e:
            items.append({"check": "N4_blocker", "status": "P1", "detail": f"blocker 解析失败: {e}"})
    else:
        items.append({"check": "N4_blocker", "status": "ok", "detail": "无 blocker 文件"})
    p0 = sum(1 for i in items if i["status"] == "P0")
    p1 = sum(1 for i in items if i["status"] == "P1")
    return {"pass": p0 == 0, "p0": p0, "p1": p1,
            "detail": f"三要素 N1/N2/N3 + 拦截 N4 + 门禁态 N5, 对象 {RESULT}",
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "items": items}


def selftest():
    """P-C2 对照组: 缺要素/陈旧/blocker/FAIL 态 fixture 必须命中"""
    global PROJECT
    tmp = Path(tempfile.mkdtemp())
    now = datetime.now()
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        result = tmp / "data" / "rotation_backtest_result.json"
        result.parent.mkdir(parents=True, exist_ok=True)
        PROJECT = tmp
        clean = {"engine_commit": "046f72c12a2558fe3c3b46b78e652ca57d7e738a",
                 "engine_equivalence_anchor": "3fe5227e (0文件变化)",
                 "generated": now.isoformat(),
                 "gate": {"status": "PASS", "gate_id": "SG-TEST"}}
        result.write_text(json.dumps(clean), encoding="utf-8")
        r = run_check()
        assert r["p0"] == 0 and r["p1"] == 0, f"clean 应全绿: {r['items']}"
        # N1: 缺引擎版本
        bad = dict(clean); bad["engine_commit"] = ""
        result.write_text(json.dumps(bad), encoding="utf-8")
        assert run_check()["p0"] >= 1, "缺 engine_commit 应 P0"
        # N3: 陈旧 30d
        bad = dict(clean); bad["generated"] = (now - __import__("datetime").timedelta(days=30)).isoformat()
        result.write_text(json.dumps(bad), encoding="utf-8")
        r = run_check()
        assert r["p1"] >= 1 and r["p0"] == 0, f"陈旧应 P1: {r['items']}"
        # N4: blocker 生效
        bad = dict(clean); result.write_text(json.dumps(bad), encoding="utf-8")
        (tmp / "data/backtest_report_blocker.json").write_text(json.dumps({"blocked": True, "reason": "sanity FAIL"}), encoding="utf-8")
        assert run_check()["p0"] >= 1, "blocker 生效应 P0"
        # N5: gate FAIL
        (tmp / "data/backtest_report_blocker.json").unlink()
        bad = dict(clean); bad["gate"] = {"status": "FAIL"}
        result.write_text(json.dumps(bad), encoding="utf-8")
        assert run_check()["p0"] >= 1, "gate FAIL 应 P0"
        print("SELFTEST PASS: clean全绿 / 缺引擎P0 / 陈旧P1 / blocker P0 / gateFAIL P0 全命中")
    finally:
        PROJECT = Path(__file__).resolve().parent.parent
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    report = run_check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["pass"] else 1)
