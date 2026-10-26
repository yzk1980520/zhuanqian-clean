#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书消息发送模块 - 支持Webhook和应用机器人"""
import os
import sys
import json
from pathlib import Path

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

def send_feishu_message(message: str, mention_all: bool = False) -> dict:
    """
    发送飞书消息（优先级：config文件 > 环境变量 > Webhook）

    Args:
        message: 消息内容
        mention_all: 是否@所有人

    Returns:
        发送结果
    """
    # 1. 优先读取config文件（支持webhook配置）
    config_path = Path(__file__).parent.parent / 'config' / 'feishu_config.json'
    config = {}
    if config_path.exists():
        try:
            with open(config_path, encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            print(f"⚠️ 读取feishu_config.json失败: {e}", file=sys.stderr)

    # 2. 如果config启用了webhook，优先使用
    if config.get('enabled') and config.get('webhook_url'):
        from feishu_webhook_bot import FeishuWebhookBot
        bot = FeishuWebhookBot(webhook_url=config['webhook_url'])
        return bot.send_text(message, mention_all)

    # 3. 降级到环境变量（保持向后兼容）
    app_id = os.getenv('FEISHU_APP_ID')
    app_secret = os.getenv('FEISHU_APP_SECRET')
    if app_id and app_secret:
        from feishu_bot import FeishuBot
        bot = FeishuBot()
        chat_id = os.getenv('FEISHU_CHAT_ID', 'oc_100a06a1c71d5f8b1e58f1e420cadd1a')
        return bot.send_message(chat_id, message)

    webhook_url = os.getenv('FEISHU_WEBHOOK_URL')
    if webhook_url:
        from feishu_webhook_bot import FeishuWebhookBot
        bot = FeishuWebhookBot()
        return bot.send_text(message, mention_all)

    # 都没有，返回错误
    return {
        "success": False,
        "error": "未配置飞书通知方式",
        "hint": "请在config/feishu_config.json中配置webhook_url，或设置环境变量FEISHU_APP_ID+FEISHU_APP_SECRET"
    }

def send_task_notification(task_id: str, assignee: str, title: str, 
                          deadline: str, priority: str = 'P0', content: str = '') -> dict:
    """发送任务通知"""
    priority_emoji = {'P0': '🔴', 'P1': '🟡', 'P2': '🟢', 'P3': '⚪'}.get(priority, '🟢')
    
    message = f"""{priority_emoji} 【快速响应任务】

任务ID: {task_id}
负责人: {assignee}
优先级: {priority}
截止时间: {deadline}

任务内容:
{content if content else '请查看任务看板'}

请立即回复"收到+时间"确认！

--
御龙决量化系统 · 全局协调机制v2.0"""
    
    return send_feishu_message(message)

if __name__ == '__main__':
    # 测试发送
    if len(sys.argv) > 1:
        result = send_feishu_message(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result['success'] else 1)
    else:
        print("使用方法: python feishu_sender.py '消息内容'")
        print("       或: python feishu_sender.py --task T-XXX @成员 标题 截止时间 优先级 内容")
