#!/usr/bin/env python3
"""
多Agent心跳检查器 · 总管专用
自动检查老六/老三/老五的kanban任务状态，有变化才通知。

运行方式：
- 手动：python scripts/multi_agent_heartbeat.py
- Cron：每天08:00/20:00自动执行

输出：
- 有变化：挂kanban comment到对应任务
- 无变化：静默
- 异常：写日志 + 飞书告警（P0）
"""

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

# 配置
PROJECT_ROOT = Path(r"D:/open code/zhuanqian")
LOG_FILE = PROJECT_ROOT / "logs" / "multi_agent_heartbeat.log"
STATE_CACHE_FILE = PROJECT_ROOT / "data" / "agent_heartbeat_state.json"

# 时区
CST = timezone(timedelta(hours=8))

# Agent映射（kanban assignee → 中文名）
AGENT_MAP = {
    "workbuddy": "老六",
    "laosan": "老三",
    "atomcode": "老五",
    "default": "总管",
}

# 监控的老六任务（需要关注的）
LAOSIX_WATCH_TASKS = [
    "t_bb7f77a0",  # 总管-老六互审总卡
    "t_939bc3a3",  # D9-2回测过滤
]


def log(msg: str):
    """写日志"""
    ts = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, file=sys.stderr)


def load_state() -> dict:
    """加载上次状态"""
    if STATE_CACHE_FILE.exists():
        try:
            with open(STATE_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"读取状态缓存失败: {e}")
    return {}


def save_state(state: dict):
    """保存当前状态（原子写入）"""
    STATE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_CACHE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp.replace(STATE_CACHE_FILE)
    log("状态缓存已更新")


def run_kanban_list(assignee: str = None, limit: int = 20) -> list:
    """调用kanban_list工具获取任务列表"""
    try:
        cmd = ["hermes", "kanban", "list", "--json"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            # JSON直接是任务数组
            if isinstance(data, list):
                tasks = data
            elif isinstance(data, dict):
                tasks = data.get("tasks", [])
            else:
                tasks = []
            # 按assignee过滤
            if assignee:
                tasks = [t for t in tasks if t.get("assignee") == assignee]
            return tasks[:limit]
        else:
            log(f"kanban list失败: {result.stderr}")
            return []
    except Exception as e:
        log(f"调用kanban list异常: {e}")
        return []


def snapshot_agent_status(assignee: str) -> dict:
    """快照某个Agent的任务状态"""
    tasks = run_kanban_list(assignee=assignee, limit=20)
    
    status_counts = Counter()
    recent_tasks = []
    
    for task in tasks:
        status = task.get("status", "unknown")
        status_counts[status] += 1
        recent_tasks.append({
            "id": task.get("id"),
            "title": task.get("title", "")[:50],
            "status": status,
            "priority": task.get("priority", 0),
        })
    
    return {
        "assignee": assignee,
        "timestamp": datetime.now(CST).isoformat(),
        "total": len(tasks),
        "by_status": dict(status_counts),
        "recent_tasks": recent_tasks[:5],
    }


def diff_state(old: dict, new: dict) -> list:
    """计算状态差异"""
    changes = []
    
    old_by_status = old.get("by_status", {})
    new_by_status = new.get("by_status", {})
    
    # 检查各状态数量变化
    for status in set(list(old_by_status.keys()) + list(new_by_status.keys())):
        old_count = old_by_status.get(status, 0)
        new_count = new_by_status.get(status, 0)
        if old_count != new_count:
            changes.append({
                "type": "status_change",
                "status": status,
                "old": old_count,
                "new": new_count,
            })
    
    # 检查新任务
    old_ids = {t["id"] for t in old.get("recent_tasks", [])}
    new_ids = {t["id"] for t in new.get("recent_tasks", [])}
    
    for task_id in new_ids - old_ids:
        task = next((t for t in new["recent_tasks"] if t["id"] == task_id), {})
        changes.append({
            "type": "new_task",
            "task_id": task_id,
            "title": task.get("title", ""),
            "status": task.get("status", ""),
        })
    
    return changes


def format_comment(agent: str, changes: list) -> str:
    """生成kanban comment"""
    ts = datetime.now(CST).strftime("%H:%M")
    lines = [f"## 【心跳检查】{ts}"]
    
    if not changes:
        lines.append("无变化")
        return "\n".join(lines)
    
    for c in changes:
        if c["type"] == "status_change":
            lines.append(f"- {c['status']}: {c['old']}→{c['new']}")
        elif c["type"] == "new_task":
            lines.append(f"- 新任务 [{c['status']}]: {c['title'][:30]}...")
    
    return "\n".join(lines)


def main():
    """主入口"""
    log("=== 多Agent心跳检查启动 ===")
    
    # 1. 快照所有Agent状态
    agents = ["workbuddy", "laosan", "atomcode"]
    current_state = {}
    
    for agent in agents:
        log(f"检查 {AGENT_MAP.get(agent, agent)}...")
        current_state[agent] = snapshot_agent_status(agent)
    
    # 2. 对比上次状态
    last_state = load_state()
    all_changes = {}
    
    for agent in agents:
        changes = diff_state(last_state.get(agent, {}), current_state[agent])
        if changes:
            all_changes[agent] = changes
            log(f"{AGENT_MAP.get(agent, agent)} 有 {len(changes)} 项变化")
    
    # 3. 保存当前状态
    save_state(current_state)
    
    # 4. 输出报告
    if all_changes:
        log(f"\n发现 {len(all_changes)} 个Agent有状态变化:")
        for agent, changes in all_changes.items():
            comment = format_comment(agent, changes)
            log(f"\n{AGENT_MAP[agent]}:\n{comment}")
            # TODO: 挂kanban comment（需要集成kanban工具）
    else:
        log("\n所有Agent状态无变化，静默。")
    
    log("=== 心跳检查完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
