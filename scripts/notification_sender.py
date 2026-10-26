#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S3消息队列推送服务
功能：
1. 读取data/message_queue.json
2. 通过飞书Webhook推送消息
3. 支持优先级过滤（P0/P1/P2）
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\notification_sender.py] CR-01: except Exception:", file=sys.stderr)
PROJECT = Path(__file__).parent.resolve()
DATA_DIR = PROJECT.parent / "data"
QUEUE_FILE = DATA_DIR / "message_queue.json"
LOG_FILE = DATA_DIR / "notification_log.jsonl"

# 飞书Webhook配置（需替换为实际webhook URL）
FEISHU_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/YOUR_WEBHOOK_ID"

def log(msg: str):
    ts = datetime.now().isoformat()
    print(f"[{ts}] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "msg": msg}, ensure_ascii=False) + "\n")

def load_queue():
    """加载消息队列（D-6 P0-3 loud fail 2026-10-16：损坏态上溢，禁静默 return []；独立 CLI/被 monitor_alert_v2 import，raise=调用方可见，经老六 10-16 schtasks 全量核实无活任务注册）"""
    if not QUEUE_FILE.exists():
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception as e:
            print(f"❌ [notification_sender] load_queue 读队列失败 {QUEUE_FILE}: {e}", file=sys.stderr)
            raise

def save_queue(queue):
    """保存消息队列"""
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

def send_feishu(message: str, priority: str = "P2"):
    """发送飞书消息"""
    import urllib.request
    
    # 构建消息体
    payload = {
        "msg_type": "text",
        "content": {
            "text": f"[{priority}] {message}"
        }
    }
    
    # 发送请求
    try:
        req = urllib.request.Request(
            FEISHU_WEBHOOK,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("code") == 0
    except Exception as e:
        log(f"❌ 飞书推送失败: {e}")
        return False

def process_queue():
    """处理消息队列"""
    queue = load_queue()
    if not queue:
        return
    
    log(f"📨 队列中有 {len(queue)} 条消息待处理")
    
    # 按优先级排序（P0 > P1 > P2）
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    sorted_queue = sorted(queue, key=lambda x: priority_order.get(x.get("priority", "P2"), 2))
    
    # 发送消息
    sent_count = 0
    for msg in sorted_queue:
        priority = msg.get("priority", "P2")
        content = msg.get("content", "")
        
        if send_feishu(content, priority):
            log(f"✅ 已推送 [{priority}]: {content[:50]}...")
            sent_count += 1
        else:
            log(f"❌ 推送失败 [{priority}]: {content[:50]}...")
    
    # 清空已发送消息
    if sent_count > 0:
        remaining = [m for m in queue if m.get("priority") != "P0" or not m.get("sent")]
        save_queue(remaining)
        log(f"📤 已发送 {sent_count} 条消息，剩余 {len(remaining)} 条")

def main():
    """主函数"""
    log("=" * 50)
    log("S3消息队列推送服务启动")
    log("=" * 50)
    
    process_queue()
    
    log("✅ 推送服务执行完毕")

if __name__ == "__main__":
    main()
