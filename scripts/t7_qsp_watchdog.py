#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t7_qsp_watchdog.py — T7运维外环看门狗(总管侧)

定位: 盯老六QSP自愈引擎的状态出口(self_heal_state.json), 
      探测层死亡最长≤6h必有另一层告警, 双看门狗互为备份。

契约(2026-10-16 老六L2会签JF-5):
  - 只读: data/self_heal_state.json / data/repair_log.jsonl
  - 告警出口: data/message_queue.json (唯一) + data/t7_watchdog_log.jsonl (本地台账)
  - 不写业务文件, 不自执行修复动作

节律: 每6h (01/07/13/19:05, 错峰老六侧 03/09/15/21:05)
cron: job_id=e268ea73500a「T7选股运维外环看门狗」
"""
import json
import os
import sys
from datetime import datetime, timedelta

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
STATE_FILE = os.path.join(DATA, "self_heal_state.json")
REPAIR_LOG = os.path.join(DATA, "repair_log.jsonl")
WATCHDOG_LOG = os.path.join(DATA, "t7_watchdog_log.jsonl")
QUEUE = os.path.join(DATA, "message_queue.json")

# 阈值
MAX_RUN_AGE_MIN = 30  # last_run 龄>30min = P0
CONSEC_P0_WARN = 2    # consec_p0≥2 = P0
EXEMPT_PROBES = {"P-07", "P-10", "P-11"}  # 待老大拍板项, 不刷屏

def log_event(level, check, detail):
    """写本地台账"""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "level": level,
        "check": check,
        "detail": detail
    }
    with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry

def load_state():
    """加载自愈状态"""
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"🔴 [t7_qsp_watchdog.py:52] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (json.JSONDecodeError, IOError) → 兜底, 异常={e}", file=sys.stderr)
        return None

def load_queue():
    """加载告警队列"""
    if not os.path.exists(QUEUE):
        return []
    try:
        with open(QUEUE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"🔴 [t7_qsp_watchdog.py:62] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (json.JSONDecodeError, IOError) → 兜底, 异常={e}", file=sys.stderr)
        return []

def save_queue(q):
    """保存告警队列"""
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)

def add_alert(priority, check, content):
    """入队告警(T2唯一出口)"""
    q = load_queue()
    q.append({
        "id": f"t7_{check}_{datetime.now().strftime('%Y%m%d%H%M')}",
        "type": "t7_qsp_watchdog",
        "priority": priority,
        "content": content,
        "data": {},
        "ts": datetime.now().isoformat(timespec="seconds"),
        "sent": False
    })
    save_queue(q)
    return q[-1]["id"]

def check_last_run_age(state):
    """检查last_run新鲜度"""
    check = "last_run_age"
    last_run = state.get("last_run")
    if not last_run:
        msg = "last_run 缺失 — 自愈引擎从未运行"
        log_event("P0", check, msg)
        return add_alert("P0", check, msg)
    
    try:
        lr = datetime.fromisoformat(last_run)
        age_min = (datetime.now() - lr).total_seconds() / 60.0
        log_event("INFO", check, f"last_run 龄 {age_min:.1f}min")
        
        if age_min > MAX_RUN_AGE_MIN:
            msg = f"自愈引擎停滞 {age_min:.0f}min (>30min阈值)"
            log_event("P0", check, msg)
            return add_alert("P0", check, msg)
    except (ValueError, TypeError) as e:
        msg = f"last_run 格式错误: {last_run} ({e})"
        log_event("P0", check, msg)
        return add_alert("P0", check, msg)
    
    return None

def check_consec_p0(state):
    """检查连续P0计数"""
    check = "consec_p0"
    consec = state.get("consec_p0", 0)
    log_event("INFO", check, f"consec_p0={consec}")
    
    if consec >= CONSEC_P0_WARN:
        msg = f"连续{consec}轮P0未解除 — 自愈引擎持续失能"
        log_event("P0", check, msg)
        return add_alert("P0", check, msg)
    
    return None

def check_probe_failures(state):
    """检查探针失败(排除豁免项)"""
    check = "probe_failures"
    results = state.get("results", {})
    failures = []
    
    for pid, info in results.items():
        if pid in EXEMPT_PROBES:
            continue
        if not info.get("ok", True):
            failures.append(f"{pid}({info.get('name', '')}): {info.get('detail', '')}")
    
    if failures:
        msg = "探针异常: " + "; ".join(failures[:3])
        log_event("P1", check, msg)
        return add_alert("P1", check, msg)
    
    return None

def main():
    """主入口"""
    print(f"[T7外环看门狗] {datetime.now().isoformat()}")
    
    state = load_state()
    if not state:
        msg = "状态文件缺失: " + STATE_FILE
        log_event("P0", "state_file", msg)
        add_alert("P0", "state_file", msg)
        print(f"❌ {msg}")
        return 1
    
    print(f"  last_run: {state.get('last_run')}")
    print(f"  consec_p0: {state.get('consec_p0', 0)}")
    print(f"  results: {len(state.get('results', {}))} 项")
    
    alerts = []
    alerts.append(check_last_run_age(state))
    alerts.append(check_consec_p0(state))
    alerts.append(check_probe_failures(state))
    
    fired = [a for a in alerts if a]
    if fired:
        print(f"⚠️  发出 {len(fired)} 条告警")
        for aid in fired:
            print(f"  alert_id={aid}")
    else:
        print("✅ 外环健康")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
