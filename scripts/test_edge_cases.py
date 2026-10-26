#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
边界情况测试 - 验证空值、无效输入、异常处理
"""
import sys
import re
from pathlib import Path
from datetime import datetime
import tempfile
from unittest.mock import patch  # 2026-10-15 老六修复: 原文件缺失, L107 NameError

sys.path.insert(0, str(Path(__file__).parent))

def test_empty_message():
    """测试空消息处理"""
    print("\n【测试1】空消息处理")
    
    from feishu_bot import FeishuBot
    bot = FeishuBot(app_id='test', app_secret='test')
    
    # 空字符串
    result = bot.send_message('oc_test1234567890123456789012345678', '')
    if result['success'] == False and '空' in result.get('error', ''):
        print("  ✅ 空字符串被拒绝")
    else:
        print(f"  ❌ 空字符串未被正确拒绝: {result}")
    
    # 空白字符串
    result = bot.send_message('oc_test1234567890123456789012345678', '   ')
    if result['success'] == False:
        print("  ✅ 空白字符串被拒绝")
    else:
        print(f"  ❌ 空白字符串未被拒绝: {result}")
    
    # None
    try:
        result = bot.send_message('oc_test1234567890123456789012345678', None)
        print(f"  ⚠️ None未触发异常: {result}")
    except Exception as e:
        print(f"  ✅ None触发异常: {type(e).__name__}")


def test_invalid_chat_id():
    """测试无效chat_id处理"""
    print("\n【测试2】无效chat_id处理")
    
    from feishu_bot import FeishuBot
    bot = FeishuBot(app_id='test', app_secret='test')
    
    invalid_ids = [
        '',
        'invalid',
        'oc_tooshort',
        'OC_INVALID',
        'oc_123'
    ]
    
    all_rejected = True
    for chat_id in invalid_ids:
        result = bot.send_message(chat_id, 'test')
        if result['success']:
            print(f"  ❌ 无效chat_id未被拒绝: {chat_id}")
            all_rejected = False
    
    if all_rejected:
        print("  ✅ 所有无效chat_id都被拒绝")


def test_long_message():
    """测试超长消息处理"""
    print("\n【测试3】超长消息处理")
    
    from feishu_bot import FeishuBot
    bot = FeishuBot(app_id='test', app_secret='test')
    
    # 超长消息
    long_message = "x" * 25000
    result = bot.send_message('oc_test1234567890123456789012345678', long_message)
    
    # 应该被截断或拒绝
    if result['success'] == False or '截断' in long_message:
        print("  ✅ 超长消息被正确处理")
    else:
        print(f"  ⚠️ 超长消息可能未被截断")


def test_corrupted_json():
    """测试损坏的JSON文件"""
    print("\n【测试4】损坏的JSON文件恢复")
    
    from coordination_system import BlockerDetector
    
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_file = Path(tmpdir) / 'TASK-BOARD.json'
        
        # 测试各种损坏情况
        test_cases = [
            ("{ invalid json }}}", "不完整JSON"),
            ("not json at all", "非JSON文本"),
            ("", "空文件"),
            ("{{{{{{", "纯括号"),
        ]
        
        for content, description in test_cases:
            bad_file.write_text(content)
            
            with patch('coordination_system.TASK_BOARD_FILE', bad_file):
                detector = BlockerDetector()
                try:
                    board = detector._load_board()
                    if board == {'tasks': [], 'stats': {}}:
                        print(f"  ✅ {description}: 正确恢复")
                    else:
                        print(f"  ❌ {description}: 恢复失败")
                except Exception as e:
                    print(f"  ❌ {description}: 崩溃 - {type(e).__name__}")


def test_timezone_comparison():
    """测试时区处理"""
    print("\n【测试5】时区比较")
    
    from datetime import timezone, timedelta
    
    # UTC时间
    utc_time = datetime(2026, 10, 7, 6, 0, 0, tzinfo=timezone.utc)
    # 本地时间（UTC+8）
    local_time = datetime(2026, 10, 7, 14, 0, 0)
    
    # 转换为同一时区比较
    if utc_time == local_time.astimezone(timezone.utc):
        print("  ✅ 时区转换正确")
    else:
        print(f"  ❌ 时区转换失败: {utc_time} != {local_time}")


def main():
    """运行所有边界测试"""
    from unittest.mock import patch
    
    print("=" * 80)
    print("🧪 边界情况测试")
    print("=" * 80)
    
    test_empty_message()
    test_invalid_chat_id()
    test_long_message()
    test_corrupted_json()
    test_timezone_comparison()
    
    print("\n" + "=" * 80)
    print("✅ 边界测试完成")
    print("=" * 80)


if __name__ == '__main__':
    main()
