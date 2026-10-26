# -*- coding: utf-8 -*-
"""
refresh_task_board.py — 任务板刷新器（老三 2026-09-30，总管流水线建议）
=====================================================================
作用: 读 .agent/TASK-BOARD.json, 检测各任务证据文件的新鲜度/存在性,
      产出 .agent/TASK-BOARD.flags.json (打标, 供总管/老六拍板参考)。

安全边界(铁律):
  - 本脚本只"检测+打标", 绝不自动翻转任务状态(完成/取消/进行中)。
  - 状态机翻转必须总管/老六拍板。cron 只是给拍板人提供"哪些任务该看一眼"的信号。
  - 检测口径: evidence 路径存在性 + mtime(是否 >48h 未更新) → 给 flag。

cron 挂法(Windows 计划任务, 复用项目 cron 机制):
  每日 08:00 跑一次:  python scripts/refresh_task_board.py
"""
import json, os, time
from datetime import datetime

ROOT = r"D:/open code/zhuanqian"
BOARD = os.path.join(ROOT, ".agent", "TASK-BOARD.json")
FLAGS = os.path.join(ROOT, ".agent", "TASK-BOARD.flags.json")
STALE_HOURS = 48        # evidence 超过 48h 未更新 → 标 stale
LOG = os.path.join(ROOT, ".agent", "refresh_task_board.log")


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        print(f"🔴 [scripts\refresh_task_board.py] CR-01: except Exception:", file=sys.stderr)
def evidence_state(paths, now):
    """返回 (missing, stale): 缺失的证据 / 超过 STALE_HOURS 未刷新的证据。"""
    missing, stale = [], []
    for p in paths:
        full = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if not os.path.exists(full):
            missing.append(p)
            continue
        mtime = os.path.getmtime(full)
        if (now - mtime) / 3600.0 > STALE_HOURS:
            stale.append("%s (%.0fh前)" % (p, (now - mtime) / 3600.0))
    return missing, stale


def main():
    if not os.path.exists(BOARD):
        log("FATAL: 任务板缺失 %s" % BOARD)
        return 1
    board = json.load(open(BOARD, encoding="utf-8"))
    now = time.time()
    out = {"generated": datetime.now().isoformat(), "rules": board.get("rules"),
           "signals": [], "summary": {}}
    active, done, cancelled, blocked = [], [], [], []
    for t in board.get("tasks", []):
        tid, st, name = t.get("id"), t.get("state"), t.get("name")
        row = {"id": tid, "name": name, "state": st, "owner": t.get("owner")}
        if t.get("blocking"):
            row["blocking"] = True
        if "取消" in st:
            cancelled.append(tid); out["signals"].append(row); continue
        if "完成" in st:
            done.append(tid); out["signals"].append(row); continue
        if "进行中" in st or "待" in st or "阻塞" in st or "待裁定" in st or "待启动" in st or "待总管" in st or "待确认" in st:
            active.append(tid)
        else:
            active.append(tid)
        # 证据检测(仅对有 evidence 的非取消任务)
        ev = t.get("evidence") or []
        if ev and "取消" not in st:
            miss, stale = evidence_state(ev, now)
            row["evidence_missing"] = miss
            row["evidence_stale"] = stale
            if "进行中" in st or "待" in st or "阻塞" in st:
                if miss:
                    row["flag"] = "EVIDENCE_MISSING"
                    out["signals"].append(row)
                elif stale:
                    row["flag"] = "EVIDENCE_STALE"
                    out["signals"].append(row)
                elif "进行中" in st:
                    row["flag"] = "OK_IN_PROGRESS"
                else:
                    row["flag"] = "WAITING_APPROVAL"
    out["summary"] = {
        "active": active, "done": done, "cancelled": cancelled,
        "blocked": [t.get("id") for t in board.get("tasks", []) if t.get("blocking") and "取消" not in t.get("state","") and "完成" not in t.get("state","")],
        "note": "cron 仅检测打标, 状态翻转须总管/老六拍板"
    }
    with open(FLAGS, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log("刷新完成: active=%s done=%s cancelled=%s blocked=%s" % (
        active, done, cancelled, out["summary"]["blocked"]))
    print("📋 任务板刷新 → flags 已写 %s" % FLAGS)
    print("   active=%s | done=%s | 取消=%s | 阻塞中=%s" % (
        active, done, cancelled, out["summary"]["blocked"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
