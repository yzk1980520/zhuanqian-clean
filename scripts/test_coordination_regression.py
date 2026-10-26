#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局协调系统回归测试
覆盖：飞书API集成、阻塞检测、自动修复、边界情况
"""
import json
import os
import sys
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

class TestResults:
    """测试结果收集器"""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def record(self, test_name, success, error=None):
        if success:
            self.passed += 1
            print(f"  ✅ {test_name}")
        else:
            self.failed += 1
            self.errors.append((test_name, error))
            print(f"  ❌ {test_name}: {error}")
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*80}")
        print(f"测试结果: {self.passed}/{total} 通过")
        if self.errors:
            print(f"失败项: {len(self.errors)}")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        print(f"{'='*80}")
        return self.failed == 0


def test_feishu_token_cache():
    """测试Token缓存逻辑"""
    print("\n【测试组1】飞书Token缓存")
    results = TestResults()
    
    # 模拟Token获取
    mock_response = {
        "code": 0,
        "tenant_access_token": "test_token_123",
        "expire": 7200
    }
    
    # 测试1: 首次获取
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = mock_response
        from feishu_bot import FeishuBot
        bot = FeishuBot(app_id='test_id', app_secret='test_secret')
        token = bot.get_token()
        results.record("首次获取Token", token == "test_token_123")
    
    # 测试2: 缓存命中（未过期）
    bot._token_expire = time.time() + 3600  # 1小时后过期
    token = bot.get_token()
    results.record("缓存命中（未过期）", token == "test_token_123")
    
    # 测试3: 缓存失效（已过期）
    bot._token_expire = time.time() - 100  # 100秒前过期
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = mock_response
        token = bot.get_token()
        results.record("缓存失效后重新获取", token == "test_token_123")
    
    return results


def test_feishu_error_handling():
    """测试飞书API错误处理"""
    print("\n【测试组2】飞书API错误处理")
    results = TestResults()
    
    from feishu_bot import FeishuBot
    
    # 测试1: Token获取失败
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {
            "code": 19007,
            "msg": "Bot Not Enabled"
        }
        bot = FeishuBot(app_id='test_id', app_secret='test_secret')
        token = bot.get_token()
        results.record("Token获取失败返回None", token is None)
    
    # 测试2: 网络超时
    with patch('requests.post') as mock_post:
        mock_post.side_effect = Exception("Timeout")
        bot = FeishuBot(app_id='test_id', app_secret='test_secret')
        token = bot.get_token()
        results.record("网络超时返回None", token is None)
    
    # 测试3: 消息发送失败
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {
            "code": 230053,
            "msg": "The user has stopped the bot"
        }
        bot = FeishuBot(app_id='test_id', app_secret='test_secret')
        result = bot.send_message('chat_id', 'test')
        results.record("消息发送失败返回错误", not result['success'])
    
    return results


def test_blocker_detection():
    """测试阻塞点检测"""
    print("\n【测试组3】阻塞点检测")
    results = TestResults()
    
    from coordination_system import BlockerDetector
    
    # 创建临时任务看板
    with tempfile.TemporaryDirectory() as tmpdir:
        task_board_path = Path(tmpdir) / 'TASK-BOARD.json'
        
        # 测试1: 超时任务检测
        tasks = [
            {
                "id": "T-001",
                "title": "测试任务",
                "assignee": "@老五",
                "priority": "P0",
                "deadline": (datetime.now() - timedelta(hours=1)).isoformat(),
                "status": "pending",
                "created_at": (datetime.now() - timedelta(hours=2)).isoformat()
            }
        ]
        task_board_path.write_text(json.dumps({"tasks": tasks}))
        
        # 临时替换TASK_BOARD_FILE
        original_file = BlockerDetector.__module__
        with patch('coordination_system.TASK_BOARD_FILE', task_board_path):
            detector = BlockerDetector()
            blockers = detector.detect_timeouts()
            results.record("检测到超时任务", len(blockers) == 1)
            results.record("超时任务优先级正确", blockers[0]['severity'] == 'P0')
        
        # 测试2: 停滞任务检测
        tasks = [
            {
                "id": "T-002",
                "title": "停滞任务",
                "assignee": "@老六",
                "priority": "P1",
                "deadline": (datetime.now() + timedelta(hours=1)).isoformat(),
                "status": "pending",
                "created_at": (datetime.now() - timedelta(hours=5)).isoformat()
            }
        ]
        task_board_path.write_text(json.dumps({"tasks": tasks}))
        
        with patch('coordination_system.TASK_BOARD_FILE', task_board_path):
            detector = BlockerDetector()
            blockers = detector.detect_stalled_tasks()
            results.record("检测到停滞任务", len(blockers) == 1)

        # 测试3: 空任务列表 (2026-10-15 老六修复: 原代码在 with tmpdir 块外写文件,
        # TemporaryDirectory 已清理导致 FileNotFoundError, 现缩进移入块内)
        task_board_path.write_text(json.dumps({"tasks": []}))
        with patch('coordination_system.TASK_BOARD_FILE', task_board_path):
            detector = BlockerDetector()
            blockers = detector.detect_timeouts()
            results.record("空任务列表无阻塞", len(blockers) == 0)

    return results


def test_blocker_resolution():
    """测试阻塞点修复"""
    print("\n【测试组4】阻塞点修复")
    results = TestResults()
    
    from coordination_system import BlockerResolver
    
    resolver = BlockerResolver()
    
    # 测试1: 重新分配任务
    blocker = {
        "type": "TIMEOUT",
        "task_id": "T-001",
        "title": "测试任务",
        "assignee": "@老五",
        "priority": "P0",
        "overdue_seconds": 3600
    }
    
    with tempfile.TemporaryDirectory() as tmpdir:
        task_board_path = Path(tmpdir) / 'TASK-BOARD.json'
        task_board_path.write_text(json.dumps({
            "tasks": [{
                "id": "T-001",
                "title": "测试任务",
                "assignee": "@老五",
                "priority": "P0",
                "deadline": datetime.now().isoformat(),
                "status": "pending"
            }]
        }))
        
        # 模拟飞书发送失败
        with patch('coordination_system.BlockerResolver._send_reminder', return_value={'success': False}):
            with patch('coordination_system.TASK_BOARD_FILE', task_board_path):
                result = resolver.resolve_timeout(blocker)
                results.record("超时任务重新分配成功", result['success'])
                results.record("重新分配后负责人为总管", '@总管' in str(result))
    
    # 测试2: 未知阻塞类型
    unknown_blocker = {"type": "UNKNOWN", "task_id": "T-999"}
    result = resolver.resolve_blocker(unknown_blocker)
    results.record("未知阻塞类型返回失败", not result['success'])
    
    return results


def test_edge_cases():
    """测试边界情况"""
    print("\n【测试组5】边界情况")
    results = TestResults()
    
    # 测试1: 任务看板文件损坏
    with tempfile.TemporaryDirectory() as tmpdir:
        task_board_path = Path(tmpdir) / 'TASK-BOARD.json'
        task_board_path.write_text("invalid json {{{")
        
        from coordination_system import BlockerDetector
        with patch('coordination_system.TASK_BOARD_FILE', task_board_path):
            detector = BlockerDetector()
            try:
                blockers = detector.run_detection()
                results.record("损坏的任务看板不崩溃", True)
            except Exception as e:
                results.record("损坏的任务看板不崩溃", False, str(e))
    
    # 测试2: 飞书API限流
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {
            "code": 99991663,
            "msg": "rate limit exceeded"
        }
        from feishu_bot import FeishuBot
        bot = FeishuBot(app_id='test_id', app_secret='test_secret')
        result = bot.send_message('chat_id', 'test')
        results.record("API限流正确返回错误", not result['success'])
    
    # 测试3: 缺少环境变量
    with patch.dict(os.environ, {}, clear=True):
        from feishu_sender import send_feishu_message
        result = send_feishu_message("test")
        results.record("缺少环境变量返回错误", not result['success'])
    
    return results


def main():
    """运行所有测试"""
    print("=" * 80)
    print("🧪 全局协调系统回归测试")
    print("=" * 80)
    
    all_passed = True
    
    # 运行各测试组
    all_passed &= test_feishu_token_cache()
    all_passed &= test_feishu_error_handling()
    all_passed &= test_blocker_detection()
    all_passed &= test_blocker_resolution()
    all_passed &= test_edge_cases()
    
    # 总结
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ 所有测试通过！")
    else:
        print("❌ 存在失败项，请检查上方详情")
    print("=" * 80)
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    exit(main())
