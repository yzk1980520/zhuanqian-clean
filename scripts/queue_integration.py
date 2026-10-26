#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S3消息队列集成器
功能：
1. 将监控告警写入message_queue
2. 支持优先级标记
3. 触发notification_sender推送
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print("⚠ [queue_integration] stdout reconfigure 失败，回退默认编码", file=sys.stderr)

PROJECT = Path(__file__).parent.resolve()
DATA_DIR = PROJECT.parent / "data"
QUEUE_FILE = DATA_DIR / "message_queue.json"
ALERT_HISTORY = DATA_DIR / "alert_history.json"

# OPS-2 2026-10-17 写口收敛: 仓库根 atomic_json (跨进程 FileLock + fsync + os.replace) 为
# 首选写回通道 — 根治 drain 与写者并发时 W3 型静默覆盖; 缺失时降级 tmp+os.replace(仍原子, 无锁)。
_ROOT = str(PROJECT.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
try:
    from core.pipeline.atomic_json import update_json as _atomic_update_json
except Exception:
    _atomic_update_json = None

def log(msg: str = ""):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def load_queue():
    """加载消息队列（D-6 P0-3 loud fail 2026-10-16：损坏态上溢，禁静默 return []；独立 CLI/被 monitor_alert_v2 import，raise=调用方可见，经老六 10-16 schtasks 全量核实无活任务注册）"""
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ [queue_integration] load_queue 读队列失败 {QUEUE_FILE}: {e}", file=sys.stderr)
        raise

def save_queue(queue):
    """写回队列: 优先 atomic_json.update_json (跨进程 FileLock+原子替换+fsync, 防并发覆盖);
    缺失时降级 tmp+os.replace (仍原子)。文件缺失以 [] 初始化; 文件损坏 → update_json R4 loud raise。"""
    qpath = str(QUEUE_FILE)
    if _atomic_update_json is not None:
        _atomic_update_json(qpath, lambda _old, q=queue: q, default=[])
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = qpath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    os.replace(tmp, qpath)

def add_alert(alert_type: str, priority: str, content: str, data: dict = None):
    """添加告警到队列 — message_queue.json 生产端唯一规范写口 (OPS-2 2026-10-17 收敛后)。
    契约 shape: {id, type, priority, content, data, ts, sent}。
    消费侧 cron_message_sender: 层2 按 content 渲染; 层4 解析 content 内 [Pn] 段做脏值过滤/抑制。
    非本函数写口 → 见 docs/OPS2-写口收敛-20261017.md 豁免清单。"""
    queue = load_queue()
    
    alert = {
        "id": f"{alert_type}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "type": alert_type,
        "priority": priority,
        "content": content,
        "data": data or {},
        "ts": datetime.now().timestamp(),
        "sent": False
    }
    
    queue.append(alert)
    save_queue(queue)
    
    log(f"📨 已添加告警 [{priority}] {alert_type}: {content[:50]}...")
    
    # 更新历史
    history = []
    if ALERT_HISTORY.exists():
        try:
            with open(ALERT_HISTORY, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (FileNotFoundError, IOError, PermissionError, json.JSONDecodeError) as e:
            print(f"❌ [queue_integration] ALERT_HISTORY 加载失败 {ALERT_HISTORY}: {e}", file=sys.stderr)
    
    history.append({
        "ts": alert["ts"],
        "type": alert_type,
        "priority": priority,
        "content": content
    })
    
    # 保留最近100条
    history = history[-100:]
    with open(ALERT_HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    
    return alert

def check_and_notify(monitor_status: dict):
    """检查监控状态并触发告警"""
    alerts = monitor_status.get("alerts", [])
    
    for alert in alerts:
        priority = "P0" if alert.get("level") == "critical" else "P1"
        add_alert(
            alert_type=alert.get("type", "unknown"),
            priority=priority,
            content=alert.get("message", ""),
            data=alert
        )
    
    # 检查持仓状态
    holdings = monitor_status.get("holdings_count", 0)
    if holdings > 0:
        # 持仓中，定期巡检
        pass
    else:
        pass
        # 空仓，检查是否需要开仓
        pass

def main():
    log("=" * 60)
    log("S3消息队列集成器启动")
    log("=" * 60)
    
    # 读取监控状态
    monitor_file = DATA_DIR / "s3_monitor_status.json"
    if not monitor_file.exists():
        log("⚠️ 监控状态文件不存在")
        return
    
    with open(monitor_file, "r", encoding="utf-8") as f:
        monitor_status = json.load(f)
    
    # 检查并触发告警
    check_and_notify(monitor_status)
    
    # 显示当前队列
    queue = load_queue()
    log(f"\n📊 当前队列: {len(queue)}条消息")
    
    if queue:
        log("\n待推送消息:")
        for msg in queue[:5]:
            log(f"  [{msg.get('priority', 'P2')}] {msg.get('content', '')[:50]}...")
    
    log("\n✅ 消息队列集成器执行完毕")

if __name__ == "__main__":
    main()
