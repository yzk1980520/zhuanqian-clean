#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书API集成模块 - 真正的消息推送能力"""
import requests
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

class FeishuBot:
    """飞书机器人客户端"""
    
    def __init__(self, app_id: str = None, app_secret: str = None):
        """
        初始化飞书机器人
        
        Args:
            app_id: 飞书应用App ID（从.env读取）
            app_secret: 飞书应用App Secret（从.env读取）
        """
        self.app_id = app_id or os.getenv('FEISHU_APP_ID')
        self.app_secret = app_secret or os.getenv('FEISHU_APP_SECRET')
        self.base_url = "https://open.feishu.cn/open-apis"
        self.token = None
    
    def get_token(self) -> str:
        """获取tenant_access_token"""
        # 安全检查：确保_token_expire已初始化
        expire_time = getattr(self, '_token_expire', 0)
        if self.token and datetime.now().timestamp() < expire_time - 300:
            return self.token
        
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                self.token = data["tenant_access_token"]
                self._token_expire = datetime.now().timestamp() + data.get("expire", 7200)
                return self.token
            else:
                raise RuntimeError(f"获取token失败: {data.get('msg')}")
        except Exception as e:
            print(f"❌ 获取飞书token失败: {e}")
            return None
    
    def send_message(self, chat_id: str, content: str, msg_type: str = "text",
                     receive_id_type: str = "chat_id") -> Dict:
        """
        发送消息到群聊

        Args:
            chat_id: 群聊ID
            content: 消息内容
            msg_type: 消息类型（text/interactive）
            receive_id_type: 接收方ID类型. 本实例Feishu open-apis枚举=chat_id/open_id/user_id/
                email/union_id (2026-10-15 总管T5验收: 缺此query参数恒400 99992402)

        Returns:
            发送结果
        """
        # 边界检查：chat_id格式验证
        import re
        if not chat_id or not re.match(r'^oc_[a-f0-9]{32}$', chat_id):
            return {"success": False, "error": f"无效的chat_id格式: {chat_id}"}

        # 边界检查：消息内容验证
        if not content or not content.strip():
            return {"success": False, "error": "消息内容不能为空"}

        # 边界检查：消息长度限制
        MAX_LENGTH = 20000
        if len(content) > MAX_LENGTH:
            content = content[:MAX_LENGTH-100] + "\n\n...（内容过长已截断）"

        token = self.get_token()
        if not token:
            return {"success": False, "error": "获取token失败"}
        
        url = f"{self.base_url}/im/v1/messages?receive_id_type={receive_id_type}"
        headers = {"Authorization": f"Bearer {token}"}
        
        # 构建消息体
        if msg_type == "text":
            body = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": content})
            }
        else:
            body = {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps({
                    "header": {
                        "title": {"content": content, "tag": "plain_text"}
                    }
                })
            }
        
        try:
            response = requests.post(url, headers=headers, json=body, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                print(f"✅ 消息发送成功: {data.get('data', {}).get('message_id')}")
                return {"success": True, "message_id": data.get("data", {}).get("message_id")}
            else:
                print(f"❌ 消息发送失败: {data.get('msg')}")
                return {"success": False, "error": data.get("msg")}
        except Exception as e:
            print(f"❌ 消息发送异常: {e}")
            return {"success": False, "error": str(e)}
    
    def at_member(self, open_id: str) -> str:
        """
        生成@成员标签
        
        Args:
            open_id: 成员open_id
        
        Returns:
            @标签字符串
        """
        return f"<at user_id='{open_id}'>@{open_id}</at>"
    
    def send_task_notification(self, chat_id: str, task_id: str, assignee_open_id: str, 
                               title: str, deadline: str, priority: str = 'P0') -> Dict:
        """
        发送任务通知（带@成员）
        
        Args:
            chat_id: 群聊ID
            task_id: 任务ID
            assignee_open_id: 负责人open_id
            title: 任务标题
            deadline: 截止时间
            priority: 优先级
        
        Returns:
            发送结果
        """
        # 构建消息内容
        priority_emoji = {'P0': '🔴', 'P1': '🟡', 'P2': '🟢', 'P3': '⚪'}.get(priority, '🟢')
        
        content = f"""{priority_emoji} 【快速响应任务】

任务ID: {task_id}
负责人: {self.at_member(assignee_open_id)}
优先级: {priority}
截止时间: {deadline}

请立即回复"收到+时间"确认！

--
御龙决量化系统 · 全局协调机制v2.0"""
        
        return self.send_message(chat_id, content, "text")

def main():
    """测试飞书API集成"""
    print('=' * 80)
    print('🤖 飞书API集成测试')
    print('=' * 80)
    print()
    
    # 检查环境变量
    app_id = os.getenv('FEISHU_APP_ID')
    app_secret = os.getenv('FEISHU_APP_SECRET')
    
    if not app_id or not app_secret:
        print('❌ 错误: 缺少飞书API凭证')
        print('请设置环境变量:')
        print('  FEISHU_APP_ID=your_app_id')
        print('  FEISHU_APP_SECRET=your_app_secret')
        print()
        print('或在 .env 文件中添加:')
        print('  FEISHU_APP_ID=your_app_id')
        print('  FEISHU_APP_SECRET=your_app_secret')
        return 1
    
    # 初始化客户端
    bot = FeishuBot()
    
    # 测试获取token
    print('【步骤1】获取tenant_access_token...')
    token = bot.get_token()
    if not token:
        print('❌ Token获取失败')
        return 1
    print('✅ Token获取成功')
    print()
    
    # 测试发送消息
    print('【步骤2】发送测试消息...')
    result = bot.send_message(
        chat_id=os.getenv('FEISHU_CHAT_ID', 'oc_100a06a1c71d5f8b1e58f1e420cadd1a'),
        content='🧪 飞书API集成测试消息\n\n这是总管发送的测试消息，请忽略。',
        msg_type='text'
    )
    
    if result['success']:
        print('✅ 消息发送成功')
        print(f"   message_id: {result.get('message_id')}")
    else:
        print(f'❌ 消息发送失败: {result.get("error")}')
        return 1
    
    print()
    print('=' * 80)
    print('✅ 飞书API集成测试通过')
    print('=' * 80)
    
    return 0

if __name__ == '__main__':
    exit(main())
