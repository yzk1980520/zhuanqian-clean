#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书API重试机制
添加指数退避和错误处理
"""
import requests
import time
from typing import Dict, Optional

MAX_RETRIES = 3
RETRY_DELAY = 1  # 初始重试延迟（秒）


def post_with_retry(url: str, headers: dict, json_body: dict, timeout: int = 10) -> Optional[Dict]:
    """
    带重试的HTTP POST请求
    
    Args:
        url: 请求URL
        headers: 请求头
        json_body: 请求体
        timeout: 超时时间（秒）
    
    Returns:
        响应JSON或None
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, headers=headers, json=json_body, timeout=timeout)
            
            # 检查HTTP状态码
            if response.status_code == 200:
                data = response.json()
                
                # 检查业务错误码
                if data.get('code') == 0:
                    return data
                
                # 限流错误（99991663）
                elif data.get('code') == 99991663:
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    print(f"⚠️ 触发限流，{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                
                # 其他业务错误
                else:
                    print(f"❌ API返回错误: {data.get('msg')}")
                    return None
            
            # HTTP错误
            else:
                print(f"❌ HTTP错误: {response.status_code}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
                
        except requests.exceptions.Timeout:
            print(f"⚠️ 请求超时，{RETRY_DELAY}秒后重试...")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return None
            
        except requests.exceptions.ConnectionError:
            print(f"⚠️ 连接失败，{RETRY_DELAY}秒后重试...")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
                continue
            return None
            
        except Exception as e:
            print(f"❌ 未知错误: {e}")
            return None
    
    print(f"❌ 重试{MAX_RETRIES}次后仍失败")
    return None


def send_message_with_retry(bot, chat_id: str, content: str, msg_type: str = "text") -> Dict:
    """
    带重试的消息发送
    
    Args:
        bot: FeishuBot实例
        chat_id: 群聊ID
        content: 消息内容
        msg_type: 消息类型
    
    Returns:
        发送结果
    """
    token = bot.get_token()
    if not token:
        return {"success": False, "error": "获取token失败"}
    
    url = f"{bot.base_url}/im/v1/messages"
    headers = {"Authorization": f"Bearer {token}"}
    
    body = {
        "receive_id": chat_id,
        "msg_type": msg_type,
        "content": __import__('json').dumps({"text": content})
    }
    
    result = post_with_retry(url, headers, body)
    
    if result:
        return {
            "success": True,
            "message_id": result.get('data', {}).get('message_id')
        }
    else:
        return {"success": False, "error": "发送失败"}
