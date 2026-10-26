#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
config_drift_check.py — P-F3 三方会签 config 漂移守卫 (自愈引擎 v1.0, 老五认领, 2026-10-23)
===============================================================================
只读断言: 因子裁定资产双通道防未会签漂移。今晚样本: 10/5 两轮
"Fundamentals+ vs 综合" 策略混淆 + factor_weights 静默清零 (4b7803df 型事件),
10/21 IC 注入前科。输出与 carrier_check 同构 {pass,p0,p1,detail,items[]}。

断言:
  R1 未固化漂移: factor_weights.json / config.json 工作区 vs HEAD 有未 commit 变更 -> P1
     (归档轮/清理轮误伤前最后一道闸, 与 P-C1 fixguard 同型, 因子裁定资产专检)
  R2 仲裁基线一致性: factor_weights.json v2.6 仲裁数值 (文件 evidence 段自证):
     chg10=2.0 / overnight_sum20=1.6 / chg5=1.4 / momentum_20=0.5, 净和=5.5
     任一不符 -> P0 (未会签篡改, 10/5 型事件机械拦截)
  R3 策略通道: 根 config.json strategy == "综合" (S3 门禁验证策略) -> 不符 P0
     factor_layer_enabled 缺失/非 bool -> P1
  已 commit 的变更默认=已会签 (会签记录在 commit 链), 本守卫不复审历史, 只管:
     ① 未 commit 的悬置漂移 ② 活跃数值被改动的实时拦截。

用法: python scripts/config_drift_check.py [--selftest]
退出码: 0=无P0, 1=有P0。
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
GW_FILE = "factor_weights.json"
CFG_FILE = "config.json"

# v2.6 仲裁基线 (来源: factor_weights.json evidence.ruling, t_2a214e5b + 老五 R0 t_69d56592)
ARBITRATION = {
    "chg10": 2.0,
    "overnight_sum20": 1.6,
    "chg5": 1.4,
    "momentum_20": 0.5,
}
TOTAL_WEIGHT = 5.5
EXPECTED_STRATEGY = "综合"
EPS = 1e-9


def r1_uncommitted():
    r = subprocess.run(
        ["git", "-C", str(PROJECT), "status", "--porcelain", GW_FILE, CFG_FILE],
        capture_output=True, text=True, timeout=30)
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    return [l for l in lines]


def r2_arbitration():
    p = PROJECT / GW_FILE
    if not p.exists():
        return {"issue": "P0", "detail": "factor_weights.json 缺失 — 生产权重真源丢失 (loud fail 同型)"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"issue": "P0", "detail": f"factor_weights.json JSON 损坏: {e}"}
    w = d.get("weights", {})
    diffs = []
    for k, v in ARBITRATION.items():
        cur = w.get(k)
        if not isinstance(cur, (int, float)) or abs(cur - v) > EPS:
            diffs.append(f"{k}: 期望{v} 实际{cur}")
    total = sum(v for v in w.values() if isinstance(v, (int, float)))
    if abs(total - TOTAL_WEIGHT) > 1e-6:
        diffs.append(f"净和: 期望{TOTAL_WEIGHT} 实际{total}")
    if diffs:
        return {"issue": "P0", "detail": "未会签漂移实锤: " + "; ".join(diffs)}
    return {"issue": "ok", "detail": f"v{d.get('version', '?')} 仲裁数值 4项+净和全等"}


def r3_strategy_channel():
    p = PROJECT / CFG_FILE
    if not p.exists():
        return {"issue": "P0", "detail": "config.json 缺失"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"issue": "P0", "detail": f"config.json JSON 损坏: {e}"}
    issues = []
    strat = d.get("strategy")
    if strat != EXPECTED_STRATEGY:
        issues.append(f"P0: strategy={strat!r} != '{EXPECTED_STRATEGY}' (10/5 型策略混淆)")
    ffe = d.get("factor_layer_enabled")
    if not isinstance(ffe, bool):
        issues.append(f"P1: factor_layer_enabled={ffe!r} 非 bool — 开关语义脱钩")
    if issues:
        sev = "P0" if any(i.startswith("P0") for i in issues) else "P1"
        return {"issue": sev, "detail": "; ".join(issues)}
    return {"issue": "ok", "detail": f"strategy='{strat}', factor_layer={ffe}"}


def run_check():
    r1 = r1_uncommitted()
    r2 = r2_arbitration()
    r3 = r3_strategy_channel()
    items = [
        {"check": "R1_uncommitted_drift", "status": "P1" if r1 else "ok",
         "detail": f"未commit变更 {len(r1)} 件" + (f": {r1}" if r1 else "")},
        {"check": "R2_arbitration_values", "status": r2["issue"], "detail": r2["detail"]},
        {"check": "R3_strategy_channel", "status": r3["issue"], "detail": r3["detail"]},
    ]
    p0 = sum(1 for i in items if i["status"] == "P0")
    p1 = sum(1 for i in items if i["status"] == "P1")
    return {"pass": p0 == 0, "p0": p0, "p1": p1,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "baseline": "v2.6 (t_7819f7e3, 2026-10-20) + 9/30 三方会签, 引擎=factor_weights.json 单源",
            "items": items}


def selftest():
    """P-C2 对照组: 篡改 fixture 必须被 R2/R3 命中, 防断言空转"""
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    try:
        gw = tmp / GW_FILE
        gw.parent.mkdir(parents=True, exist_ok=True)
        cfg = tmp / CFG_FILE
        global PROJECT
        proj_backup = PROJECT
        PROJECT = tmp
        # clean fixture -> ok
        w = {**ARBITRATION, **{f"z{k}": 0.0 for k in range(18)}}
        gw.write_text(json.dumps({"version": "2.6", "weights": w}), encoding="utf-8")
        cfg.write_text(json.dumps({"strategy": "综合", "factor_layer_enabled": False}), encoding="utf-8")
        assert r2_arbitration()["issue"] == "ok"
        assert r3_strategy_channel()["issue"] == "ok"
        # tamper 1: 活跃值被清零 (10/5 型 chg5_rev=0 漂移) -> P0
        w2 = dict(w); w2["chg10"] = 0.0
        gw.write_text(json.dumps({"version": "2.6", "weights": w2}), encoding="utf-8")
        assert r2_arbitration()["issue"] == "P0", "清零篡改应P0"
        # tamper 2: 策略被换 (Fundamentals+ 型) -> P0
        gw.write_text(json.dumps({"version": "2.6", "weights": w}), encoding="utf-8")
        cfg.write_text(json.dumps({"strategy": "基本面+", "factor_layer_enabled": False}), encoding="utf-8")
        assert r3_strategy_channel()["issue"] == "P0", "策略混淆应P0"
        # tamper 3: 开关脱钩 -> P1
        cfg.write_text(json.dumps({"strategy": "综合", "factor_layer_enabled": "false"}), encoding="utf-8")
        assert r3_strategy_channel()["issue"] == "P1"
    finally:
        PROJECT = proj_backup
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELFTEST PASS: 清零篡改P0 / 策略混淆P0 / 开关脱钩P1 / 清洁fixture全ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    report = run_check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["pass"] else 1)
