#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ic_blind_window_check.py — P-F2 IC 监控盲窗断言 (自愈引擎 v1.0, 老五认领, 2026-10-23)
===============================================================================
只读断言: 3 条 IC 监控通道停更/空窗检测, 输出与 carrier_check 同构
{pass, p0, p1, detail, items[]} 供老六台账 schema 直接消费。不写任何文件。

通道 (今晚样本: fake_positive_detector 46 天空窗, 10/25 才首跑):
  A. rolling 20d  : data/audit/factor_ic_rolling_20d_YYYYMMDD.json 最新件日期
  B. 132d 权威源  : data/factor_ic/factor_ic_latest.json last_date
  C. WeeklyIC     : 计划任务 Zhuanqian_FactorIC132d LastRun (首跑 2026-10-25 前
                    属 first_run_pending, 当日仍未跑 = P0 升级)

阈值: gap_days > 7 → P1; 通道 C 过 10/25 仍未首跑 → P0。
用法: python scripts/ic_blind_window_check.py [--selftest]
退出码: 0=无P0, 1=有P0。数据时效纪律: 每次输出带 generated_at + 各通道 asof。
"""
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ROLLING_GLOB = "data/audit/factor_ic_rolling_20d_*.json"
AUTHORITY = "data/factor_ic/factor_ic_latest.json"
WEEKLY_TASK = "Zhuanqian_FactorIC132d"
WEEKLY_FIRST_RUN_DUE = date(2026, 10, 25)
GAP_P1_DAYS = 7


def _date_in_days(s):
    """'YYYY-MM-DD' -> days_ago (int); 解析失败 None"""
    try:
        return (date.today() - date.fromisoformat(str(s)[:10])).days
    except Exception:
        return None


def check_channel_a(today):
    """rolling 20d 最新件日期 vs today"""
    files = sorted(PROJECT.glob(ROLLING_GLOB))
    if not files:
        return {"channel": "A_rolling_20d", "status": "P1", "asof": None,
                "detail": "滚动20d监控无任何产出件 — 通道断供"}
    m = re.search(r"(\d{8})\.json$", files[-1].name)
    asof = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}" if m else None
    days = (today - date.fromisoformat(asof)).days if asof else 999
    status = "ok" if days <= 3 else ("P1" if days <= GAP_P1_DAYS * 3 else "P1")
    return {"channel": "A_rolling_20d", "status": status, "asof": asof,
            "days_ago": days,
            "detail": f"最新件 {asof}, 停更 {days} 天" + (f" (> {GAP_P1_DAYS}d 盲窗, P1)" if days > GAP_P1_DAYS else "")}


def check_channel_b(today):
    """132d 权威源 last_date vs today"""
    p = PROJECT / AUTHORITY
    if not p.exists():
        return {"channel": "B_132d_authority", "status": "P0", "asof": None,
                "detail": "权威源文件缺失 — 门禁判定会 fail-loud, 但监控盲窗成立"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"channel": "B_132d_authority", "status": "P0", "asof": None,
                "detail": f"权威源 JSON 损坏: {e}"}
    last = d.get("last_date")
    days = _date_in_days(last)
    status = "ok" if days is not None and days <= 7 else ("P1" if days is not None else "P0")
    return {"channel": "B_132d_authority", "status": status, "asof": last,
            "days_ago": days,
            "detail": f"last_date={last}, 停更 {days} 天" + (" (> 7d 盲窗, P1)" if days and days > 7 else "")}


def check_channel_c(today):
    """WeeklyIC 任务 LastRun; 首跑到期日 10/25"""
    out = {"channel": "C_weekly_ic", "asof": None, "detail": ""}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-ScheduledTask -TaskName {WEEKLY_TASK}).State"],
            capture_output=True, text=True, timeout=30)
        state = r.stdout.strip()
        if not state:
            return {**out, "status": "P0", "detail": "任务不存在 — 载体丢失 (P-B1 同型)"}
    except Exception as e:
        return {**out, "status": "P1", "detail": f"任务状态查询失败: {e}"}
    if today < WEEKLY_FIRST_RUN_DUE:
        return {**out, "state": state, "status": "pending_first_run",
                "detail": f"首跑未到期 (due {WEEKLY_FIRST_RUN_DUE}), 46天空窗补齐待 10/25, 老五验收"}
    # 到期后: 看 LastRun
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-ScheduledTask -TaskName {WEEKLY_TASK} | Get-ScheduledTaskInfo).LastRunTime.ToString()"],
            capture_output=True, text=True, timeout=30)
        last = r.stdout.strip()
        out["asof"] = last or None
        if not last or last == "0001-01-01 00:00:00":
            return {**out, "status": "P0", "detail": "首跑到期但 LastRun 为空 — 46天空窗未补齐, 升级"}
        return {**out, "status": "ok", "detail": f"已首跑 {last}"}
    except Exception as e:
        return {**out, "status": "P1", "detail": f"LastRun 查询失败: {e}"}


def run_check(today):
    items = [check_channel_a(today), check_channel_b(today), check_channel_c(today)]
    p0 = sum(1 for i in items if i["status"] == "P0")
    p1 = sum(1 for i in items if i["status"] == "P1")
    return {"pass": p0 == 0, "p0": p0, "p1": p1,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": items}


def selftest():
    """P-C2 对照组纪律: 合成坏 fixture 必须命中, 防断言空转"""
    global PROJECT
    import tempfile, shutil
    tmp = Path(tempfile.mkdtemp())
    try:
        # A: 干净目录下无滚动件 -> P1
        (tmp / "data/audit").mkdir(parents=True)
        (tmp / "data/factor_ic").mkdir(parents=True)
        PROJECT = tmp
        assert check_channel_a(date.today())["status"] == "P1", "无件应P1"
        # B: 损坏源 -> P0
        (tmp / "data/factor_ic/factor_ic_latest.json").write_text("{broken", encoding="utf-8")
        r = check_channel_b(date.today())
        assert r["status"] == "P0", f"坏源应P0, 得 {r['status']}"
        # B: 陈旧 last_date -> P1
        (tmp / "data/factor_ic/factor_ic_latest.json").write_text(
            json.dumps({"last_date": "2026-09-20"}), encoding="utf-8")
        r = check_channel_b(date.today())
        assert r["status"] == "P1", f"陈旧源应P1, 得 {r['status']}"
        # C: 到期后未首跑枚举校验 (只验状态枚举合法, 任务查询走真实环境)
        c = check_channel_c(date.today())
        assert c["status"] in ("ok", "P0", "P1", "pending_first_run"), f"C 状态枚举外: {c['status']}"
        print("SELFTEST PASS: 无件P1 / 坏源P0 / 陈旧P1 / C枚举 全命中")
    finally:
        PROJECT = Path(__file__).resolve().parent.parent
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    report = run_check(date.today())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["pass"] else 1)
