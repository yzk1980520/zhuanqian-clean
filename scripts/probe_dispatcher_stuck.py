#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_dispatcher_stuck.py — P1-E 归因探针（zhuanqian 侧降噪，不动 Hermes 内部）

读 gateway.log 尾部 + kanban list 快照，把 dispatcher stuck 归因为三值之一：
  ① 无单可派（ready 队列为空）→ 不告警，仅 stdout 输出
  ② 并发上限（ready 单的目标 profile 已达成 max_in_progress）→ INFO，不告警
  ③ spawn 真失败（ready 单有可用 profile，但最近有 spawn_failed/crashed）→ P1 入队

只读：不调度、不写 kanban、不修改任何生产文件。
告警出口：data/message_queue.json（规则 11 唯一投递器）。

用法:
  python scripts/probe_dispatcher_stuck.py           # 人读
  python scripts/probe_dispatcher_stuck.py --json    # 机器读
  python scripts/probe_dispatcher_stuck.py --alert   # 发现③时写 message_queue(P1)

示例:
  2026-10-16 20:09 同一句 WARNING，今早是②(配额墙=真)，晚上是①(队列流动=假)。
  本探针通过 kanban 快照区分三者。
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = str(Path(__file__).parent.parent)
sys.path.insert(0, PROJECT)

# ── 路径配置 ──────────────────────────────────────────────────────────────────
# P1-B fix: 硬编码主 Hermes home，不读 HERMES_HOME env。
# 原因：profile worker 注入 HERMES_HOME=.../profiles/x 会导致探针读 profile
# gateway.log（0 stuck 行）→ 假报①。主 dispatcher gateway.log 唯一真源，必须固定。
HERMES_HOME = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
GATEWAY_LOG = os.path.join(HERMES_HOME, "logs", "gateway.log")
HERMES_BIN = os.path.join(HERMES_HOME, "bin", "hermes.exe")
DATA_DIR = os.path.join(PROJECT, "data")
MESSAGE_QUEUE = os.path.join(DATA_DIR, "message_queue.json")
STATE_FILE = os.path.join(DATA_DIR, "dispatcher_stuck_state.json")

# 每次最多读尾部行数（覆盖最近 ~1h 的日志，假设 tick=30s）
TAIL_LINES = 500
# 判断"最近 spawn 失败"的时间窗（分钟）
SPAWN_FAIL_WINDOW_MIN = 30

# ── 环境变量剥离（同 dispatch_audit_check.py 同款 fix）───────────────────────
_KANBAN_FENCE_ENV = ("HERMES_DELEGATED_CHILD_CONTEXT",)


def _clean_env():
    env = dict(os.environ)
    for k in _KANBAN_FENCE_ENV:
        env.pop(k, None)
    return env


def _run_hermes(*args, timeout=15):
    """调用 hermes CLI，剥离委托 marker 防止 recompute_ready 写事务 PermissionError"""
    try:
        r = subprocess.run(
            [HERMES_BIN, *args],
            capture_output=True, text=True, timeout=timeout,
            env=_clean_env(), creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", "hermes.exe not found: %s" % HERMES_BIN
    except subprocess.TimeoutExpired:
        return 124, "", "timeout %ds" % timeout


# ── 核心逻辑 ──────────────────────────────────────────────────────────────────

def parse_stuck_lines(log_path, tail_lines=TAIL_LINES):
    """从 gateway.log 尾部解析所有 dispatcher stuck 行

    Returns:
        list[dict]: [{ts, ticks}, ...] 按时间倒序（最新在前）
    """
    if not os.path.exists(log_path):
        return []
    pattern = re.compile(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ "
        r"WARNING gateway\.run: kanban dispatcher stuck: "
        r"ready queue non-empty for (\d+) consecutive ticks but 0 workers spawned"
    )
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        print(f"🔴 [probe_dispatcher_stuck.py:95] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 OSError → 兜底, 异常={e}", file=sys.stderr)
        return []
    tail = lines[-tail_lines:]
    results = []
    for line in tail:
        m = pattern.search(line)
        if m:
            results.append({"ts": m.group(1), "ticks": int(m.group(2))})
    return list(reversed(results))  # 最新在前


def fetch_kanban_snapshot():
    """获取 kanban list --json 快照，返回 (rc, tasks_list_or_None, err)"""
    rc, stdout, stderr = _run_hermes("kanban", "list", "--json")
    if rc != 0:
        return rc, None, stderr[:200]
    try:
        tasks = json.loads(stdout)
        return 0, tasks, ""
    except json.JSONDecodeError as e:
        return 1, None, "JSONDecodeError: %s" % e


def classify_stuck(stuck_lines, tasks):
    """归因分类

    参数:
        stuck_lines: parse_stuck_lines() 返回的列表（最新在前，取第一个）
        tasks: fetch_kanban_snapshot() 返回的 tasks 列表

    返回:
        (scenario, detail)
          scenario: ①|②|③|UNKNOWN
          detail: 说明文字
    """
    if not stuck_lines:
        return "①", "未发现 dispatcher stuck 日志行（探针正常）"

    latest = stuck_lines[0]
    ticks = latest["ticks"]
    ts = latest["ts"]

    if tasks is None:
        return "③", "无 kanban 快照，保守报③（stuck %d ticks，无法确认是否假故障）" % ticks

    # ① ready 队列为空 → 不是 stuck，可能是历史残留
    ready_tasks = [t for t in tasks if t.get("status") == "ready"]
    if not ready_tasks:
        return "①", "ready 队列为空（%s 前 %d ticks 时报告 stuck，当前无 ready 单）" % (ts, ticks)

    # 统计各 profile 的 running 任务数
    profile_running = {}
    for t in tasks:
        if t.get("status") == "running":
            a = t.get("assignee", "unknown")
            profile_running[a] = profile_running.get(a, 0) + 1

    # max_in_progress_per_profile = 1（硬编码，见 config.yaml）
    MAX_PER_PROFILE = 1

    # 检查 ready 任务的目标 profile 是否都达并发上限
    blocked_profiles = set()
    for t in ready_tasks:
        assignee = t.get("assignee", "")
        if profile_running.get(assignee, 0) >= MAX_PER_PROFILE:
            blocked_profiles.add(assignee)

    if blocked_profiles and len(blocked_profiles) == len(set(
        t.get("assignee", "") for t in ready_tasks
    )):
        # ② 所有 ready 单的目标 profile 均已达并发上限
        return "②", (
            "ready %d 单全部 profile 已达并发上限(%d)。"
            "profile 活跃中: %s。队列在流动，非故障。"
        ) % (len(ready_tasks), MAX_PER_PROFILE, json.dumps(sorted(blocked_profiles), ensure_ascii=False))

    # ③ 有 ready 单目标 profile 可用，但仍 stuck → spawn 真失败
    #    检查最近是否有 spawn_failed / crashed 事件
    recent_failures = _count_recent_spawn_failures(tasks, limit=5)
    free_profiles = [
        t.get("assignee", "") for t in ready_tasks
        if profile_running.get(t.get("assignee", ""), 0) < MAX_PER_PROFILE
    ]
    return "③", (
        "ready %d 单中有可用 profile: %s，但仍 stuck %d ticks。"
        "近期 spawn 失败数: %d。疑似真故障。"
    ) % (len(ready_tasks), json.dumps(free_profiles[:3], ensure_ascii=False),
        ticks, recent_failures)


def _count_recent_spawn_failures(tasks, limit=5):
    """统计近期 spawn_failed / crashed 事件数"""
    count = 0
    for t in tasks:
        for run in t.get("runs", []):
            outcome = run.get("outcome", "")
            if outcome in ("gave_up", "crashed", "spawn_failed"):
                count += 1
                if count >= limit:
                    break
        if count >= limit:
            break
    return count


def enqueue_p1(detail):
    """写 data/message_queue.json（P1，走 QSP_MsgDrain）"""
    try:
        from core.pipeline.atomic_json import atomic_load, atomic_dump
        items = atomic_load(MESSAGE_QUEUE, []) or []
        items.append({
            "id": "dispatcher_stuck_p1_%d" % int(datetime.now().timestamp()),
            "content": "⚠️ [dispatcher-stuck-P1] 归因③ 真故障: %s" % detail[:200],
            "platform": "feishu",
            "ts": datetime.now().timestamp(),
        })
        atomic_dump(items, MESSAGE_QUEUE)
        return True
    except Exception as e:
        print("写 message_queue 失败: %s" % e, file=sys.stderr)
        return False


def save_state(scenario, detail, stuck_lines):
    """保存探针状态到 data/dispatcher_stuck_state.json"""
    state = {
        "last_run": datetime.now().isoformat(),
        "scenario": scenario,
        "detail": detail,
        "stuck_lines_count": len(stuck_lines),
        "latest_ticks": stuck_lines[0]["ticks"] if stuck_lines else 0,
    }
    try:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(state, STATE_FILE)
    except Exception:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="P1-E dispatcher stuck 归因探针")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--alert", action="store_true",
                        help="发现③时写 message_queue(P1)")
    args = parser.parse_args()

    # 1. 读 gateway.log 尾部
    stuck_lines = parse_stuck_lines(GATEWAY_LOG)

    # 2. 取 kanban 快照
    rc, tasks, err = fetch_kanban_snapshot()
    if rc != 0:
        tasks = None

    # 3. 归因
    scenario, detail = classify_stuck(stuck_lines, tasks)

    # 4. 输出
    result = {
        "scenario": scenario,
        "detail": detail,
        "stuck_lines": stuck_lines[:3],
        "kanban_rc": rc,
        "ready_count": len([t for t in (tasks or []) if t.get("status") == "ready"])
        if tasks is not None else None,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        icon = {"①": "✅", "②": "ℹ️", "③": "🔴", "UNKNOWN": "❓"}[scenario]
        print("%s 归因①/②/③: %s" % (icon, detail))
        if stuck_lines:
            print("   最新 stuck: %s ticks=%s" % (
                stuck_lines[0]["ts"], stuck_lines[0]["ticks"]))

    # 5. 告警逻辑
    if scenario == "③" and args.alert:
        enqueue_p1(detail)
        print("   → 已写 message_queue(P1)")
    elif scenario in ("①", "②"):
        print("   → 降噪标注: %s（Hermes 内部仍会打 WARNING，本探针仅在外侧降阶）" % scenario)

    # 6. 写状态
    save_state(scenario, detail, stuck_lines)

    # 7. 退出码
    return 0 if scenario in ("①", "②") else 2


if __name__ == "__main__":
    sys.exit(main())
