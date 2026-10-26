#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
群播消息推送脚本 - 飞书群发功能
用于将系统消息批量推送到指定群聊
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 配置
PROJECT_ROOT = Path(__file__).parent.parent
FEISHU_CONFIG = PROJECT_ROOT / "config" / "feishu_config.json"

def load_feishu_config():
    """加载飞书配置"""
    if not FEISHU_CONFIG.exists():
        return None
    with open(FEISHU_CONFIG, 'r', encoding='utf-8') as f:
        return json.load(f)

def send_to_groups(message: str, mention_all: bool = False):
    """
    群播消息 - 发送到所有相关群聊
    
    Args:
        message: 消息内容
        mention_all: 是否@所有人
    
    Returns:
        发送结果列表
    """
    config = load_feishu_config()
    if not config or not config.get('enabled'):
        return [{"chat": "all", "success": False, "error": "飞书配置未启用"}]
    
    # 定义目标群聊
    groups = [
        {"name": "hermes主群", "chat_id": "oc_100a06a1c71d5f8b1e58f1e420cadd1a"},
        # 可扩展：其他群聊
    ]
    
    results = []
    for group in groups:
        result = send_to_group(group["name"], group["chat_id"], message, mention_all)
        results.append(result)
    
    return results

def send_to_group(chat_name: str, chat_id: str, message: str, mention_all: bool = False) -> dict:
    """
    发送消息到指定群聊
    
    Args:
        chat_name: 群聊名称（用于日志）
        chat_id: 群聊ID
        message: 消息内容
        mention_all: 是否@所有人
    
    Returns:
        发送结果
    """
    try:
        # 使用lark-cli发送（Windows需要完整路径）
        import subprocess
        lark_cli = os.environ.get('LARK_CLI', r"D:\npm-global\lark-cli.cmd")
        cmd = [
            lark_cli, "im", "+messages-send",
            "--chat-id", chat_id,
            "--text", message
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            response = json.loads(result.stdout)
            if response.get('ok'):
                return {
                    "chat": chat_name,
                    "chat_id": chat_id,
                    "success": True,
                    "message_id": response['data']['message_id']
                }
            else:
                return {
                    "chat": chat_name,
                    "chat_id": chat_id,
                    "success": False,
                    "error": response.get('error', {}).get('message', '未知错误')
                }
        else:
            return {
                "chat": chat_name,
                "chat_id": chat_id,
                "success": False,
                "error": result.stderr
            }
    except Exception as e:
        return {
            "chat": chat_name,
            "chat_id": chat_id,
            "success": False,
            "error": str(e)
        }

def format_message(title: str, content: str, priority: str = "P2") -> str:
    """
    格式化消息
    
    Args:
        title: 消息标题
        content: 消息内容
        priority: 优先级 (P0/P1/P2/P3)
    
    Returns:
        格式化后的消息
    """
    priority_emoji = {"P0": "🔴", "P1": "🟡", "P2": "🟢", "P3": "⚪"}.get(priority, "🟢")
    
    message = f"""{priority_emoji} 【{title}】

{content}

--
御龙决量化系统 · 群播推送"""
    
    return message

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='群播消息推送')
    parser.add_argument('--title', '-t', required=True, help='消息标题')
    parser.add_argument('--content', '-c', required=True, help='消息内容')
    parser.add_argument('--priority', '-p', default='P2', choices=['P0', 'P1', 'P2', 'P3'], help='优先级')
    parser.add_argument('--mention-all', '-m', action='store_true', help='@所有人')
    
    args = parser.parse_args()
    
    print(f"=== 群播推送 ===")
    print(f"标题: {args.title}")
    print(f"优先级: {args.priority}")
    print()
    
    message = format_message(args.title, args.content, args.priority)
    results = send_to_groups(message, args.mention_all)
    
    print("发送结果:")
    all_success = True
    for r in results:
        status = "✅" if r['success'] else "❌"
        print(f"  {status} {r['chat']}: {r['chat_id'][:20]}...")
        if not r['success']:
            print(f"      错误: {r.get('error', '未知')}")
            all_success = False
    
    print()
    if all_success:
        print("✅ 群播推送完成")
        sys.exit(0)
    else:
        print("❌ 部分群播失败")
        sys.exit(1)
