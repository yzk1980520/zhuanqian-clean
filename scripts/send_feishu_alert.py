# -*- coding: utf-8 -*-
"""
send_feishu_alert.py — 飞书告警推送工具
功能：
  1. 通过 Webhook 发送文本消息到飞书群
  2. 支持 Markdown 格式消息
  3. 支持去重冷却（同一告警短时间内不重复推送）
  4. 支持多种告警级别（CRITICAL/WARNING/INFO）

用法:
  python scripts/send_feishu_alert.py --message "告警内容" --level WARNING
  python scripts/send_feishu_alert.py --message "测试" --level INFO --test
"""
import json
import sys
import urllib.request
import urllib.error
import argparse
import hashlib
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# ==================== 配置 ====================
ROOT = Path(__file__).parent.parent
DEFAULT_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/a6e9e6a7-30a6-4598-8687-5dcfb1e5ed31"
COOLDOWN_FILE = ROOT / "data" / "alert_cooldown.json"
DEFAULT_COOLDOWN_MINUTES = 30

# ==================== 告警级别 ====================
LEVELS = {
    "CRITICAL": {"emoji": "🔴", "color": "danger", "priority": 0},
    "WARNING": {"emoji": "🟡", "color": "warning", "priority": 1},
    "INFO": {"emoji": "🔵", "color": "primary", "priority": 2},
}


def load_cooldown_state():
    """加载冷却状态（D-6 P0-3 loud fail 2026-10-16：损坏态上溢，禁静默 return {}；独立 CLI，raise=调用方可见，经老六 10-16 schtasks 全量核实无活任务注册）"""
    if not COOLDOWN_FILE.exists():
        return {}
    try:
        with open(COOLDOWN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ [send_feishu_alert] load_cooldown_state 读冷却状态失败 {COOLDOWN_FILE}: {e}", file=sys.stderr)
        raise


def save_cooldown_state(state):
    """保存冷却状态"""
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_alert_hash(message: str) -> str:
    """生成告警内容的哈希，用于去重"""
    return hashlib.md5(message.encode("utf-8")).hexdigest()[:12]


def is_in_cooldown(alert_hash: str, cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES) -> bool:
    """检查告警是否在冷却期内"""
    state = load_cooldown_state()
    now = time.time()
    last_sent = state.get(alert_hash, {}).get("last_sent", 0)
    return (now - last_sent) < (cooldown_minutes * 60)


def update_cooldown(alert_hash: str, message: str, level: str):
    """更新冷却状态"""
    state = load_cooldown_state()
    state[alert_hash] = {
        "last_sent": time.time(),
        "message_preview": message[:50],
        "level": level,
    }
    # 清理超过2小时的旧记录
    cutoff = time.time() - (2 * 3600)
    state = {k: v for k, v in state.items() if v["last_sent"] > cutoff}
    save_cooldown_state(state)


def send_feishu_message(
    message: str,
    level: str = "INFO",
    webhook: Optional[str] = None,
    title: Optional[str] = None,
    markdown: bool = False,
) -> Dict[str, Any]:
    """
    发送飞书消息
    
    Args:
        message: 消息正文
        level: 告警级别 CRITICAL/WARNING/INFO
        webhook: 飞书Webhook URL，默认为默认值
        title: 消息标题（可选）
        markdown: 是否使用Markdown格式
    
    Returns:
        dict: {"success": bool, "code": int, "message": str}
    """
    if webhook is None:
        # 尝试从环境变量读取
        webhook = os.environ.get("FEISHU_WEBHOOK", DEFAULT_WEBHOOK)
    
    if level not in LEVELS:
        level = "INFO"
    
    level_info = LEVELS[level]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 构建消息内容
    if markdown:
        # 飞书自定义机器人不支持markdown，转换为纯文本+emoji
        content = f"{level_info['emoji']} [{level}] {message}"
        if title:
            content = f"**{title}**\n\n{content}"
    else:
        content = f"{level_info['emoji']} [{level}] {ts} {message}"
        if title:
            content = f"**{title}**\n\n{content}"
    
    # 构建飞书消息体
    payload = {
        "msg_type": "text",
        "content": {
            "text": content
        }
    }
    
    try:
        req = urllib.request.Request(
            webhook,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode("utf-8"))
        
        if result.get("code") == 0:
            return {"success": True, "code": 0, "message": "发送成功"}
        else:
            return {
                "success": False,
                "code": result.get("code"),
                "message": result.get("msg", "未知错误")
            }
    except urllib.error.HTTPError as e:
        return {"success": False, "code": e.code, "message": f"HTTP错误: {e.reason}"}
    except Exception as e:
        return {"success": False, "code": -1, "message": str(e)}


def send_batch_alerts(alerts: List[Dict], webhook: Optional[str] = None, cooldown_enabled: bool = True) -> Dict[str, Any]:
    """
    批量发送告警，自动去重
    
    Args:
        alerts: 告警列表，每个元素为 {"level": str, "message": str, "title": str}
        webhook: 飞书Webhook URL
        cooldown_enabled: 是否启用冷却去重
    
    Returns:
        dict: {"sent": int, "skipped": int, "failed": int, "results": list}
    """
    results = {"sent": 0, "skipped": 0, "failed": 0, "details": []}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for alert in alerts:
        level = alert.get("level", "INFO")
        message = alert.get("message", "")
        title = alert.get("title", "")
        
        # 生成哈希用于去重
        alert_hash = get_alert_hash(message)
        
        # 检查冷却
        if cooldown_enabled and is_in_cooldown(alert_hash):
            results["skipped"] += 1
            results["details"].append({"level": level, "message": message[:30], "status": "skipped_cooldown"})
            continue
        
        # 发送
        result = send_feishu_message(
            message=message,
            level=level,
            webhook=webhook,
            title=title,
        )
        
        if result["success"]:
            results["sent"] += 1
            if cooldown_enabled:
                update_cooldown(alert_hash, message, level)
            results["details"].append({"level": level, "message": message[:30], "status": "sent"})
        else:
            results["failed"] += 1
            results["details"].append({"level": level, "message": message[:30], "status": f"failed:{result['message']}"})
    
    return results


def main():
    parser = argparse.ArgumentParser(description="飞书告警推送工具")
    parser.add_argument("--message", "-m", required=True, help="告警消息内容")
    parser.add_argument("--level", "-l", choices=["CRITICAL", "WARNING", "INFO"], default="INFO", help="告警级别")
    parser.add_argument("--title", "-t", help="消息标题")
    parser.add_argument("--webhook", "-w", help="飞书Webhook URL（可选，默认使用配置文件中的）")
    parser.add_argument("--test", action="store_true", help="发送测试消息")
    parser.add_argument("--no-cooldown", action="store_true", help="禁用冷却去重")
    parser.add_argument("--batch", "-b", help="批量发送模式，传入JSON文件路径")
    args = parser.parse_args()
    
    if args.test:
        test_msg = (
            "🧪 飞书告警测试消息\n\n"
            "这是一条来自御龙决量化系统的测试告警。\n\n"
            "【系统信息】\n"
            f"- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- 级别: {args.level}\n"
            "- 状态: 正常运行\n\n"
            "*请勿回复此消息*"
        )
        print(f"[TEST] 发送测试消息: {test_msg[:50]}...")
        result = send_feishu_message(
            message=test_msg,
            level=args.level,
            webhook=args.webhook,
        )
    elif args.batch:
        # 批量模式
        batch_file = Path(args.batch)
        if not batch_file.exists():
            print(f"❌ 批量文件不存在: {batch_file}")
            sys.exit(1)
        with open(batch_file, "r", encoding="utf-8") as f:
            alerts = json.load(f)
        print(f"[BATCH] 读取 {len(alerts)} 条告警")
        result = send_batch_alerts(alerts, webhook=args.webhook, cooldown_enabled=not args.no_cooldown)
    else:
        # 单条模式
        result = send_feishu_message(
            message=args.message,
            level=args.level,
            webhook=args.webhook,
            title=args.title,
        )
    
    # 输出结果
    print(f"\n{'='*40}")
    print(f"发送结果: {'✅ 成功' if result['success'] else '❌ 失败'}")
    print(f"状态码: {result.get('code', 'N/A')}")
    if not result['success']:
        print(f"错误: {result.get('message', '未知错误')}")
    print(f"{'='*40}\n")
    
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
