# -*- coding: utf-8 -*-
import os
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""message_queue.py — 微信消息统一队列 (总管发送)

各脚本完成后写入 data/message_queue.json，总管定时读取并统一发送。
避免重复发送、确保消息去重。
"""
import json, os, time
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from core.pipeline.atomic_json import FileLock, atomic_dump
import core.pipeline.atomic_json as atomic_json  # S4/S6迁移残留修复(2026-10-24 [t_laosan_c1_test_alignment]): 原裸 import 只绑定 core, 下方 atomic_json.atomic_dump 全部 NameError (add_message 被 except 吞掉 → 入队恒失败, 告警唯一出口断链)

QUEUE_FILE = r"D:\open code\zhuanqian\data\message_queue.json"
SENT_LOG = r"D:\open code\zhuanqian\data\message_sent_log.json"


def add_message(sender, content, priority="normal"):
    """写入消息队列 (线程安全: 原子写)"""
    msg = {
        "id": f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}-{os.getpid()}",
        "ts": datetime.now().isoformat(),
        "sender": sender,
        "content": content,
        "priority": priority
    }
    # 原子写 + 跨进程锁: 防 push.add / add_message 并发 append 丢消息
    tmp = QUEUE_FILE + ".tmp"
    try:
        with FileLock(QUEUE_FILE):
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, encoding="utf-8") as f:
                    queue = json.load(f)
            else:
                queue = []
            queue.append(msg)
            atomic_json.atomic_dump(queue, tmp, ensure_ascii=False, indent=2, encoding="utf-8")
            os.replace(tmp, QUEUE_FILE)
        return msg["id"]
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"⚠️ 消息入队失败: {e}")
        return None


def drain_queue(max_msgs=5):
    """读取并清空队列，返回消息列表"""
    if not os.path.exists(QUEUE_FILE):
        return []
    with open(QUEUE_FILE, encoding="utf-8") as f:
        queue = json.load(f)
    if not queue:
        return []
    # 按优先级排序: critical > normal > low
    priority_order = {"critical": 0, "normal": 1, "low": 2}
    queue.sort(key=lambda x: priority_order.get(x.get("priority", "normal"), 1))
    # 取前 max_msgs 条
    msgs = queue[:max_msgs]
    # 清空队列(加锁, 防与 add_message 并发写竞态)
    with FileLock(QUEUE_FILE):
        atomic_json.atomic_dump(queue[max_msgs:], QUEUE_FILE, ensure_ascii=False, indent=2, encoding="utf-8")
    return msgs


def read_all():
    """加锁读取全部队列消息(供消费端在锁内快照, 避免与 add_message 竞态丢消息)"""
    with FileLock(QUEUE_FILE):
        if not os.path.exists(QUEUE_FILE):
            return []
        with open(QUEUE_FILE, encoding="utf-8") as f:
            return json.load(f)


def remove_msgs(ids):
    """加锁移除指定 id(仅移除已成功发送者, 失败/新追加的保留, 杜绝静默丢消息)"""
    if not ids:
        return
    ids = set(ids)
    with FileLock(QUEUE_FILE):
        if not os.path.exists(QUEUE_FILE):
            return
        with open(QUEUE_FILE, encoding="utf-8") as f:
            queue = json.load(f)
        queue = [m for m in queue if m.get("id") not in ids]
        tmp = QUEUE_FILE + ".tmp"
        atomic_json.atomic_dump(queue, tmp, ensure_ascii=False, indent=2, encoding="utf-8")
        os.replace(tmp, QUEUE_FILE)


def mark_sent(msg_id, success=True):
    """记录已发送消息"""
    log = []
    if os.path.exists(SENT_LOG):
        with open(SENT_LOG, encoding="utf-8") as f:
            log = json.load(f)
    log.append({
        "id": msg_id,
        "ts": datetime.now().isoformat(),
        "success": success
    })
    # 只保留最近100条
    log = log[-100:]
    atomic_json.atomic_dump(log, SENT_LOG, ensure_ascii=False, indent=2, encoding="utf-8")


def get_queue_status():
    """返回队列状态"""
    if not os.path.exists(QUEUE_FILE):
        return {"count": 0, "msgs": []}
    with open(QUEUE_FILE, encoding="utf-8") as f:
        queue = json.load(f)
    return {
        "count": len(queue),
        "msgs": [{"id": m.get("id", "?"),
                  "sender": m.get("sender", "unknown"),
                  "ts": m.get("ts", "?")} for m in queue[-10:]]
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python message_queue.py [add|drain|status] [内容]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 3:
        msg_id = add_message("test", sys.argv[2])
        print(f"✅ 消息入队: {msg_id}")
    elif cmd == "drain":
        msgs = drain_queue()
        print(f"📬 队列中有 {len(msgs)} 条消息")
        for m in msgs:
            print(f"  [{m['sender']}] {m['content'][:60]}...")
    elif cmd == "status":
        status = get_queue_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
