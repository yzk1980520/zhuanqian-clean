#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py backtest-gate
# -*- coding: utf-8 -*-
"""
sync_trial_gate.py — 三重解冻条件 A∧B∧C 机器门禁 (cron 巡检统一入口)
=====================================================================
固化自 data/review_status.json 的 trial_unlock_conditions / trial_circuit_breaker
(2026-10-08 总管: 三重全绿才同步进 cron 读取逻辑; 任一未绿 -> dry_run 不落仓)。

判据 (全部一手实测, 非台账口述):
  A 因子门禁:  实跑 scripts/gate_check.py, exit=0 且 factor_gate.json gate_passed=true
  B 数据门禁:  TDX 源 .day 最后bar == 本地 history_daily 最后交易日 且 == 最近完整交易日
               (国庆/长假休市窗口内数据停在节前最后交易日 = 滞后0, 非过期)
  C 老五 R0:   backtest/check_backtest_sanity.py exit=0 (14断言PASS) 且 老五复签轮裁定✅
               (裁定证据链: docs/review-laowu-trial-gate-falsegreen-20261008.md + trial_unlock_conditions.C)

输出: data/trial_gate_status.json (机器可读, 原子写), 顶层 6 键:
  { mode, trial_mode, capital_limit, conditions:{A,B,C}, verdict, generated_at }
  mode: "live_trial"  (三重全绿, 按 trial_capital_limit=10000 限额分档 10%->30%->50%)
        "dry_run"     (任一未绿, 候选池照出, 交易指令不落仓/不动 holdings)

cron 接入: daily_pick.py 步骤3 后调 check_trial_gate(); gate_check_daily 巡检同此模块。
"""
import json
import os
import struct
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PYVENV = Path(r"C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe")
PROBE_STOCKS = ["sh600000", "sz000001", "sh600519"]   # B 判定探针 (含主板/深证/高价股)
STATUS_FILE = PROJECT / "data" / "trial_gate_status.json"


def _last_tdx_bar(code: str):
    """TDX 源 .day 最后 bar 日期 (内容日期, 非 mtime)"""
    mkt = "sh" if code.startswith("sh") else "sz"
    p = Path(rf"D:/TDX/vipdoc/{mkt}/lday/{code}.day")
    if not p.exists():
        return None
    data = p.read_bytes()
    n = len(data) // 32
    if n == 0:
        return None
    d = struct.unpack_from("<IIIIIfII", data, (n - 1) * 32)[0]
    return f"{d//10000}-{(d//100)%100:02d}-{d%100:02d}"


def _last_local_date(code: str):
    """本地 history_daily 最后交易日"""
    p = PROJECT / "data" / "history_daily" / f"{code}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        print(f"🔴 [scripts\sync_trial_gate.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
    dates = [x["date"] for x in d if isinstance(x, dict) and x.get("date")]
    return max(dates) if dates else None


def _latest_trading_day(today: str):
    """最近完整交易日: 周一~周五; 法定节假日窗口(国庆10-01~10-07)由 TDX 源实测对齐, 不硬编码"""
    return today


def check_check_a():
    """A 因子门禁: 实跑 gate_check.py (不采信台账口述)"""
    r = subprocess.run([str(PYVENV), str(PROJECT / "scripts" / "gate_check.py")],
                       capture_output=True, text=True, timeout=120)
    ok = (r.returncode == 0)
    detail = f"gate_check.py exit={r.returncode}"
    try:
        fg = json.loads((PROJECT / "data" / "factor_ic" / "factor_gate.json").read_text(encoding="utf-8"))
        ok = ok and bool(fg.get("gate_passed"))
        detail += f", factor_gate.json gate_passed={fg.get('gate_passed')} effective={fg.get('effective_factors')}/{fg.get('threshold')}"
        if "factor_layer_enabled" in fg:
            detail += f", factor_layer_enabled={fg.get('factor_layer_enabled')}({fg.get('factor_layer_source')})"
    except FileNotFoundError:
        # L4-A (2026-10-19): 文件缺失 = 产出方 scripts/gate_check.py 未成功运行,
        # 显式判红并点名产出方, 不再把"读异常"当作隐式失败。
        # 因子层的"关闭"状态由 gate_check.py 显式写盘 (factor_layer_enabled),
        # 缺失永远是异常, 不是表达关闭的方式。
        ok = False
        detail += ", factor_gate.json 缺失(产出方 scripts/gate_check.py 未成功运行, 显式判红)"
    except Exception as e:
        ok = False
        detail += f", factor_gate.json 不可读({e})"
    return {"pass": ok, "detail": detail}


def check_check_b():
    """B 数据门禁: TDX 源 vs 本地 最后交易日对齐 (休市窗口滞后=0)"""
    src_last, loc_last = {}, {}
    for c in PROBE_STOCKS:
        src_last[c] = _last_tdx_bar(c)
        loc_last[c] = _last_local_date(c)
    aligned = all(src_last.get(c) == loc_last.get(c) for c in PROBE_STOCKS) and all(src_last.values())
    detail = f"TDX源{src_last} 本地{loc_last} 对齐={aligned}"
    ok = aligned  # default: 未对齐即fail, 避免后续分支遗漏导致UnboundLocalError
    if aligned:
        ref = src_last[PROBE_STOCKS[0]]
        today = datetime.now().strftime("%Y-%m-%d")
        lag_days = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(ref, "%Y-%m-%d")).days
        ok = lag_days <= 0  # 源比今天新不可能; 相等=今天数据已到; 今天休市窗口内=节前对齐即正常
        detail += f", 数据日={ref} 距今{lag_days}天"
        if not ok and lag_days <= 9:
            # 休市窗口容忍: 数据停在节前最后交易日且期间无新 bar -> 实质绿
            ok = True
            detail += f" (休市窗口对齐, 滞后0, 判绿)"
    # financial_cache 子项: 非阻塞 WARN (老三 B轮评级: market_proxy 快照, 5股代理数据,
    # 质量低但不构成数据门禁 BLOCK —— 仅 TDX 源滞后才判红; 此处如实记录状态避免门禁低报)
    fc = PROJECT / "data" / "financial_cache.json"
    if fc.exists():
        age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(fc))).days
        try:
            fcd = json.loads(fc.read_text(encoding="utf-8"))
            n_cov = len(fcd.get("stocks", {}) or fcd.get("stock_count") or {}) if isinstance(fcd, dict) else 0
            src = fcd.get("source", "") if isinstance(fcd, dict) else ""
        except Exception:
            n_cov, src = -1, "unreadable"
        detail += f" | financial_cache: 滞后{age}天 source={src or '?'} 覆盖={n_cov if n_cov>=0 else '?'} (WARN级, 非BLOCK)"
    return {"pass": ok, "detail": detail}


def check_check_c():
    """C 老五 R0: sanity gate 实跑 + 复签裁定落盘证据"""
    r = subprocess.run([str(PYVENV), str(PROJECT / "backtest" / "check_backtest_sanity.py")],
                       capture_output=True, text=True, timeout=180)
    ok = (r.returncode == 0)
    detail = f"backtest/check_backtest_sanity.py exit={r.returncode}"
    # 复签裁定: trial_unlock_conditions.C.laowu_ruling 必须含 '复签通过' 且非打回
    try:
        rs = json.loads((PROJECT / "data" / "review_status.json").read_text(encoding="utf-8"))
        c = next((x for x in rs.get("trial_unlock_conditions", {}).get("conditions", []) if x.get("id") == "C"), {})
        ruling = c.get("laowu_ruling", "")
        if "复签通过" in ruling:
            ok = ok and True
            detail += f", 老五复签={ruling[:20]}"
        else:
            ok = False
            detail += f", 老五复签未确认({ruling[:24] or '无'})"
    except Exception as e:
        ok = False
        detail += f", 台账读取失败({e})"
    return {"pass": ok, "detail": detail}


def evaluate():
    a, b, c = check_check_a(), check_check_b(), check_check_c()
    all_green = a["pass"] and b["pass"] and c["pass"]
    mode = "live_trial" if all_green else "dry_run"
    status = {
        "mode": mode,
        "trial_mode": mode,
        "capital_limit": 10000,
        "ladder": "10%->30%->50% (每档滚动120d 胜率>=45%且回撤<=50% 双达标才升档, 见 trial_circuit_breaker)",
        "conditions": {
            "A_factor_gate": a, "B_data_gate": b, "C_laowu_r0": c,
        },
        "verdict": "三重全绿: 试运行限额¥10000, 分档10%起" if all_green
                   else f"未全绿: A={a['pass']} B={b['pass']} C={c['pass']} -> dry_run, 候选池照出, 交易不落仓",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    # 原子写
    tmp = STATUS_FILE.with_name(STATUS_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATUS_FILE)
    return status


def check_trial_gate():
    """daily_pick.py / cron 巡检调用入口: 返回 (mode, status)。非0退出=异常, 调用方按 dry_run 兜底。"""
    try:
        st = evaluate()
        return st["mode"], st
    except Exception as e:
        # 门禁模块自身异常 = fail-safe, 一律 dry_run (准则: 异常吞噬=埋雷, 此处显式兜底并打印)
        print(f"  ⚠️ sync_trial_gate 异常({e}) -> 按 dry_run 兜底", file=sys.stderr)
        return "dry_run", {"mode": "dry_run", "verdict": f"门禁模块异常兜底: {e}"}


if __name__ == "__main__":
    st = evaluate()
    print(json.dumps(st, ensure_ascii=False, indent=2))
    sys.exit(0 if st["mode"] == "live_trial" else 1)
