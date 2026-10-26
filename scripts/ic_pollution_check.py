#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ic_pollution_check.py — P-F1 IC 数据源污染检测 (自愈引擎 v1.0, 老五认领, 2026-10-24)
===============================================================================
只读断言, quarantine 语义 (总则 R2: 污染源只隔离告警, 不自动"修复"status):
  Q1 valid 因子 sample_size 完整性 — 缺失/非正整数 = P0 (10/21 注入签名)
  Q2 回滚因子再注入 — rollback_audit.rolled_back_factors 中因子当前 status=valid = P0
  Q3 IC 夸张度 — 因子 |ic| ≥ 5× .bak 基线 且 ≥0.05 = P0 (伪造签名: -0.2782 vs 历史-0.0382)
  Q4 icir 异常 — |icir| ≥ 1.0 = P1 (伪造 icir 标记, 132d 正常带 0.1~0.6)
命中项进台账 quarantine 态, 处置=人工会签重积累, 引擎不得自动改 status。
输出与 carrier_check 同构 {pass,p0,p1,detail,items[]} 供老六台账 schema 消费。
用法: python scripts/ic_pollution_check.py [--selftest]; 退出码 0=无P0 / 1=有P0
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
AUTHORITY = "data/factor_ic/factor_ic_latest.json"
BAK_NAME = "factor_ic_latest.json.bak_20261021_factorrollback"
INFLATION_RATIO = 5.0
INFLATION_ABS_FLOOR = 0.05
ICIR_ALERT = 1.0


def load_factors(d):
    fs = d.get("factors", [])
    if isinstance(fs, dict):
        fs = [dict(v, name=k) if isinstance(v, dict) else {"ic": v} for k, v in fs.items()]
    return [f for f in fs if isinstance(f, dict) and f.get("name")]


def q1_sample_size(factors):
    bad = [f["name"] for f in factors
           if f.get("status") == "valid"
           and (not isinstance(f.get("sample_size"), int) or f.get("sample_size", 0) <= 0)]
    return ("P0" if bad else "ok", f"valid 因子缺 sample_size: {bad}" if bad else "valid 因子 sample_size 全完整")


def q2_rollback_reinject(d, factors):
    audit = d.get("rollback_audit") or {}
    rolled = set(audit.get("rolled_back_factors", []))
    now_valid = {f["name"] for f in factors if f.get("status") == "valid"}
    hit = sorted(rolled & now_valid)
    return ("P0" if hit else "ok",
            f"回滚因子再注入: {hit} (rollback_audit 名单, 自动改 status=洗白通道)" if hit
            else "回滚名单因子当前均未 valid")


def q3_ic_inflation(bak_factors, factors):
    bak = {f["name"]: f.get("ic") for f in (bak_factors or [])}
    bad = []
    for f in factors:
        cur = f.get("ic")
        if not isinstance(cur, (int, float)):
            continue
        base = bak.get(f["name"])
        if base is None or not isinstance(base, (int, float)) or abs(base) < 1e-9:
            continue
        if abs(cur) >= INFLATION_RATIO * abs(base) and abs(cur) >= INFLATION_ABS_FLOOR:
            bad.append(f"{f['name']} (cur={cur} vs bak={base})")
    return ("P0" if bad else "ok", f"IC 夸张度超签名: {bad}" if bad else "无 5x 夸张 IC")


def q4_icir(factors):
    bad = [f"{f['name']}(icir={f.get('icir')})" for f in factors
           if isinstance(f.get("icir"), (int, float)) and abs(f["icir"]) >= ICIR_ALERT]
    return ("P1" if bad else "ok", f"|icir|≥1.0 异常: {bad}" if bad else "icir 全在正常带")


def run_check():
    p = PROJECT / AUTHORITY
    if not p.exists():
        return {"pass": True, "p0": 0, "p1": 0,
                "detail": "权威源缺失 — 污染检测不适用 (gate_check 会 fail-loud), 0 告警",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"pass": False, "p0": 1, "p1": 0, "detail": f"权威源 JSON 损坏: {e}",
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "items": [{"check": "authority_readable", "status": "P0", "detail": str(e)}]}
    factors = load_factors(d)
    bak_factors = None
    bak_path = p.parent / BAK_NAME
    if bak_path.exists():
        try:
            bak_factors = load_factors(json.loads(bak_path.read_text(encoding="utf-8")))
        except Exception:
            bak_factors = None
    items = [
        {"check": "Q1_sample_size", **{k: q1_sample_size(factors)[i] for i, k in enumerate(["status", "detail"])}},
        {"check": "Q2_rollback_reinject", **{k: q2_rollback_reinject(d, factors)[i] for i, k in enumerate(["status", "detail"])}},
        {"check": "Q3_ic_inflation", **{k: q3_ic_inflation(bak_factors, factors)[i] for i, k in enumerate(["status", "detail"])}},
        {"check": "Q4_icir_anomaly", **{k: q4_icir(factors)[i] for i, k in enumerate(["status", "detail"])}},
    ]
    p0 = sum(1 for i in items if i["status"] == "P0")
    p1 = sum(1 for i in items if i["status"] == "P1")
    return {"pass": p0 == 0, "p0": p0, "p1": p1,
            "detail": "quarantine 语义: 命中仅告警, 不自动改 status (总则 R2)",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": items}


def selftest():
    """P-C2 对照组: 注入 fixture 必须命中, 防断言空转"""
    global PROJECT
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data/factor_ic").mkdir(parents=True)
        auth = tmp / "data/factor_ic" / AUTHORITY.split("/")[-1]
        bak = tmp / "data/factor_ic" / BAK_NAME
        clean = {"factors": [
            {"name": "a", "ic": 0.04, "status": "valid", "sample_size": 192, "icir": 0.2},
            {"name": "b", "ic": -0.03, "status": "dead", "sample_size": None, "icir": None},
        ], "rollback_audit": {"rolled_back_factors": ["b"]}}
        auth.write_text(json.dumps(clean), encoding="utf-8")
        bak.write_text(json.dumps(clean), encoding="utf-8")
        PROJECT = tmp
        r = run_check()
        assert r["p0"] == 0 and r["p1"] == 0, f"clean 应全绿, 得 {r['items']}"
        # 篡改1: valid 缺 sample_size (10/21 注入签名) -> Q1 P0
        tampered = json.loads(json.dumps(clean))
        tampered["factors"][0]["sample_size"] = None
        auth.write_text(json.dumps(tampered), encoding="utf-8")
        assert run_check()["p0"] >= 1, "缺 sample_size 应 P0"
        # 篡改2: 回滚因子改回 valid -> Q2 P0
        tampered2 = json.loads(json.dumps(clean))
        tampered2["factors"][1]["status"] = "valid"
        tampered2["factors"][1]["sample_size"] = 192
        auth.write_text(json.dumps(tampered2), encoding="utf-8")
        assert run_check()["p0"] >= 1, "回滚再注入应 P0"
        # 篡改3: IC 夸张 (0.04 -> 0.278, 5x+且≥0.05) -> Q3 P0
        tampered3 = json.loads(json.dumps(clean))
        tampered3["factors"][0]["ic"] = -0.278
        auth.write_text(json.dumps(tampered3), encoding="utf-8")
        assert run_check()["p0"] >= 1, "夸张 IC 应 P0"
        # 篡改4: icir=1.5 -> Q4 P1 (非 P0)
        tampered4 = json.loads(json.dumps(clean))
        tampered4["factors"][0]["icir"] = 1.5
        auth.write_text(json.dumps(tampered4), encoding="utf-8")
        r4 = run_check()
        assert r4["p1"] >= 1 and r4["p0"] == 0, f"icir 异常应 P1 非 P0, 得 p0={r4['p0']}"
        print("SELFTEST PASS: clean全绿 / 缺sample_size P0 / 回滚再注入 P0 / 夸张IC P0 / icir P1 全命中")
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
