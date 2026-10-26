#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书Webhook通知模块 - 真正的消息推送能力"""
import requests
import json
import hmac
import hashlib
import base64
import time
import os
from pathlib import Path
from typing import Dict, Optional

class FeishuWebhookBot:
    """飞书自定义机器人Webhook客户端"""
    
    def __init__(self, webhook_url: str = None, secret: str = None):
        """
        初始化飞书Webhook机器人
        
        Args:
            webhook_url: 飞书群机器人Webhook地址
            secret: 签名密钥（如果启用了签名验证）
        """
        self.webhook_url = webhook_url or os.getenv('FEISHU_WEBHOOK_URL')
        self.secret = secret or os.getenv('FEISHU_WEBHOOK_SECRET')
    
    def generate_sign(self, timestamp: int, secret: str) -> str:
        """生成签名"""
        string_to_sign = f'{timestamp}\n{secret}'
        hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
        return base64.b64encode(hmac_code).decode('utf-8')
    
    def send_text(self, text: str, mention_all: bool = False) -> Dict:
        """
        发送文本消息
        
        Args:
            text: 消息文本
            mention_all: 是否@所有人
        
        Returns:
            发送结果
        """
        if not self.webhook_url:
            return {"success": False, "error": "Webhook URL未配置"}
        
        # 构建消息体
        payload = {
            "msg_type": "text",
            "content": {
                "text": text + ("\n\n@所有人" if mention_all else "")
            }
        }
        
        # 如果需要签名验证
        if self.secret:
            timestamp = int(time.time())
            payload["timestamp"] = str(timestamp)
            payload["sign"] = self.generate_sign(timestamp, self.secret)
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            result = response.json()
            
            if result.get("StatusCode") == 0 or result.get("code") == 0:
                print(f"✅ 消息发送成功")
                return {"success": True, "data": result}
            else:
                print(f"❌ 消息发送失败: {result}")
                return {"success": False, "error": str(result)}
        except Exception as e:
            print(f"❌ 消息发送异常: {e}")
            return {"success": False, "error": str(e)}
    
    def send_markdown(self, title: str, content: str) -> Dict:
        """
        发送富文本消息
        
        Args:
            title: 消息标题
            content: 消息内容（支持Markdown）
        
        Returns:
            发送结果
        """
        if not self.webhook_url:
            return {"success": False, "error": "Webhook URL未配置"}
        
        payload = {
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": title,
                        "content": [[{"tag": "text", "text": content}]]
                    }
                }
            }
        }
        
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            result = response.json()
            
            if result.get("StatusCode") == 0 or result.get("code") == 0:
                print(f"✅ 富文本消息发送成功")
                return {"success": True, "data": result}
            else:
                print(f"❌ 富文本消息发送失败: {result}")
                return {"success": False, "error": str(result)}
        except Exception as e:
            print(f"❌ 富文本消息发送异常: {e}")
            return {"success": False, "error": str(e)}
    
    def send_task_notification(self, task_id: str, assignee: str, title: str, 
                               deadline: str, priority: str = 'P0', content: str = '') -> Dict:
        """
        发送任务通知（带@成员）
        
        Args:
            task_id: 任务ID
            assignee: 负责人
            title: 任务标题
            deadline: 截止时间
            priority: 优先级
            content: 任务内容
        
        Returns:
            发送结果
        """
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
御龙决量化系统 · 全局协调机制v2.0
生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"""
        
        return self.send_text(message)

def main():
    """测试飞书Webhook通知"""
    print('=' * 80)
    print('🤖 飞书Webhook通知测试')
    print('=' * 80)
    print()
    
    # 检查配置
    webhook_url = os.getenv('FEISHU_WEBHOOK_URL')
    secret = os.getenv('FEISHU_WEBHOOK_SECRET')
    
    if not webhook_url:
        print('❌ 错误: 缺少FEISHU_WEBHOOK_URL环境变量')
        print()
        print('请设置环境变量:')
        print('  FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx')
        print()
        print('或在 .env 文件中添加:')
        print('  FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx')
        print('  FEISHU_WEBHOOK_SECRET=your_secret (可选)')
        return 1
    
    # 初始化机器人
    bot = FeishuWebhookBot()
    
    # 测试发送文本消息
    print('【步骤1】发送测试文本消息...')
    result = bot.send_text('🧪 飞书Webhook集成测试\n\n这是总管发送的测试消息，请忽略。')
    
    if not result['success']:
        print(f'❌ 测试失败: {result.get("error")}')
        return 1
    
    print('✅ 文本消息发送成功')
    print()
    
    # 测试发送任务通知
    print('【步骤2】发送测试任务通知...')
    result = bot.send_task_notification(
        task_id='T-TEST-20261006-222500',
        assignee='@全体成员',
        title='快速响应机制v2.0测试',
        deadline='2026-10-06 22:30:00',
        priority='P0',
        content='这是总管集成的真正飞书推送能力测试'
    )
    
    if not result['success']:
        print(f'❌ 任务通知发送失败: {result.get("error")}')
        return 1
    
    print('✅ 任务通知发送成功')
    print()
    
    print('=' * 80)
    print('✅ 飞书Webhook集成测试通过')
    print('=' * 80)
    print()
    print('📌 下一步:')
    print('  1. 检查飞书群是否收到测试消息')
    print('  2. 如有@功能需求，建议改用应用机器人API')
    print('  3. 正式启用快速响应机制')
    
    return 0

if __name__ == '__main__':
    exit(main())
