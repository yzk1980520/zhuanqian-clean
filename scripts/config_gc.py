# -*- coding: utf-8 -*-
"""config_gc.py — 废弃 API/冗余配置垃圾回收 (2026-10-15 总管, 自主运维闭环)

每日 09:40 (QSP_ConfigGC):
  S1 台账核对: config/deprecated_ledger.json 登记项逐条探活 — 仍存在=P2 告警(未清理)
  S2 .bak 清理: 仓库内 *.bak_* 文件 >30 天 → 移入 docs/.trash/ (可回滚 30 天窗口, 自动)
  S3 告警报告清理: data/alert_report_*.json >30 天 → 移入 docs/.trash/ (自动)
  S4 死脚本提名: scripts/*.py 未被任何 .cmd/cron_config/git_sync 引用 → P2 提名(不自动删)
  S5 gitignore 白名单对账: !data/ 白名单条目 vs 文件实际存在
动作红线: 只"移入 .trash"(30天后人工确认删)与"只读扫描"; 绝不直接 rm, 不碰 data/ 业务数据
输出: data/config_gc_report.json; 新发现走 message_queue P2 (唯一出口)
"""
import json
import os
import glob
import shutil
import subprocess
import datetime as dt

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
TRASH = os.path.join(PROJECT, "docs", ".trash")
HH = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
REPORT = os.path.join(DATA, "config_gc_report.json")
LEDGER = os.path.join(PROJECT, "config", "deprecated_ledger.json")
QUEUED_FILE = os.path.join(DATA, "gc_alerts_pending.txt")


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"🔴 [scripts\config_gc.py] CR-01(return): except Exception:", file=sys.stderr)
            return None
    return None


def days_since(p):
    try:
        return (dt.datetime.now() - dt.datetime.fromtimestamp(os.path.getmtime(p))).days
    except Exception:
        print(f"🔴 [scripts\config_gc.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
def s1_ledger_stale():
    """登记过的废弃项若仍存在 → 未清理计数"""
    led = load_json(LEDGER)
    items = (led or {}).get("entries", [])
    still = []
    for e in items:
        p = e.get("path", "")
        exists = (os.path.exists(p) if os.path.isabs(p)
                  else any(glob.glob(os.path.join(PROJECT, p.replace("*", "")) ) or glob.glob(p) or glob.glob(os.path.join(PROJECT, p))))
        if exists and e.get("status") != "done":
            still.append("%s (%s, %s)" % (e.get("item"), e.get("reason", ""), p))
    return still


def s2_bak_sweep():
    moved = []
    # 只扫浅层目录(.bak 约定: 备份与原文件同层), 不全仓递归(防 TDX 数据区拖死)
    scan_dirs = [PROJECT,
                 os.path.join(PROJECT, "config"),
                 os.path.join(PROJECT, "docs"),
                 os.path.join(PROJECT, "mainline"),
                 os.path.join(PROJECT, "data")]
    for d in scan_dirs:
        for p in glob.glob(os.path.join(d, "*.bak_*")):
            if not os.path.isfile(p):
                continue
            d_age = days_since(p)
            if d_age is not None and d_age > 30:
                dest = os.path.join(TRASH, "bak_%s_%s" % (d_age, os.path.basename(p)))
                os.makedirs(TRASH, exist_ok=True)
                shutil.move(p, dest)
                moved.append("%s (%d天)" % (p, d_age))
    return moved


def s3_report_sweep():
    moved = []
    for p in glob.glob(os.path.join(DATA, "alert_report_*.json")):
        d = days_since(p)
        if d is not None and d > 30:
            dest = os.path.join(TRASH, "alert_report_%s_%s" % (d, os.path.basename(p)))
            os.makedirs(TRASH, exist_ok=True)
            shutil.move(p, dest)
            moved.append("%s (%d天)" % (p, d))
    return moved


def s4_dead_script_candidates():
    """scripts/*.py 未被引用源提及 → 提名清单(只读, 不删)
    引用源限定: 全仓 .cmd(包装器) + 根目录 *.json/*.py + scripts/ 互引 + hermes cron 注册
    60s 时间护栏 + 单文件 2MB 上限, 防全仓递归扫描拖死计划任务"""
    import time
    names = [f for f in os.listdir(os.path.join(PROJECT, "scripts")) if f.endswith(".py")]
    keep = {"git_sync_task.py", "sys_watchdog.py", "config_gc.py", "drain_meta_check.py"}
    refs = set()
    corpus = (
        glob.glob(os.path.join(PROJECT, "**", "*.cmd"), recursive=True)
        + glob.glob(os.path.join(PROJECT, "*.json"))
        + glob.glob(os.path.join(PROJECT, "*.py"))
        + glob.glob(os.path.join(PROJECT, "scripts", "*.py"))
        + glob.glob(os.path.join(HH, "cron", "*.json"))
        + glob.glob(os.path.join(HH, "profiles", "*", "cron", "*.json"))
    )
    t0 = time.time()
    for src in corpus:
        if not os.path.isfile(src) or time.time() - t0 > 60:
            break
        try:
            if os.path.getsize(src) > 2_000_000:
                continue
            txt = open(src, encoding="utf-8", errors="replace").read()
        except Exception:
            print(f"🔴 [scripts\config_gc.py] CR-01: except Exception:", file=sys.stderr)
        refs.update(f for f in names if f in txt)
    dead = [f for f in sorted(names) if f not in refs and f not in keep]
    return dead[:30]


def s5_gitignore_whitelist():
    gi = open(os.path.join(PROJECT, ".gitignore"), encoding="utf-8").read()
    wl = [l.strip() for l in gi.splitlines() if l.strip().startswith("!data/")]
    missing = []
    for w in wl:
        rel = w.lstrip("!")
        p = os.path.join(PROJECT, rel.replace("/", os.sep))
        if not os.path.exists(p):
            missing.append(w)
    return missing


def main():
    result = {
        "ts": now_iso(),
        "S1_ledger_still_present": s1_ledger_stale(),
        "S2_bak_moved_to_trash": s2_bak_sweep(),
        "S3_report_moved_to_trash": s3_report_sweep(),
        "S4_dead_script_nomination": s4_dead_script_candidates(),
        "S5_gitignore_missing_whitelist": s5_gitignore_whitelist(),
    }
    findings = []
    if result["S1_ledger_still_present"]:
        findings.append("废弃台账未清理 %d 项: %s" % (len(result["S1_ledger_still_present"]), result["S1_ledger_still_present"][:3]))
    if result["S4_dead_script_nomination"]:
        findings.append("死脚本提名 %d 个(需人工确认后清理): %s" % (len(result["S4_dead_script_nomination"]), result["S4_dead_script_nomination"][:5]))
    if result["S5_gitignore_missing_whitelist"]:
        findings.append(".gitignore 白名单指向不存在文件: %s" % result["S5_gitignore_missing_whitelist"])
    if findings:
        # 写待发(不直接推: GC 是 P2 级别, 走队列由 drain 批量投递, 避免刷屏)
        with open(QUEUED_FILE, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now_iso(), "findings": findings}, ensure_ascii=False))
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("[config_gc] S1=%d S2移=%d S3移=%d S4提名=%d S5缺=%d" % (
        len(result["S1_ledger_still_present"]), len(result["S2_bak_moved_to_trash"]),
        len(result["S3_report_moved_to_trash"]), len(result["S4_dead_script_nomination"]),
        len(result["S5_gitignore_missing_whitelist"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
