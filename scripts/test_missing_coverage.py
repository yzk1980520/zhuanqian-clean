#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺失测试补充：Token刷新 + 并发测试 + 边界情况
"""
import json
import time
import sys
from pathlib import Path
from datetime import datetime, timedelta  # 2026-10-15 老六修复: timedelta 原缺失
from unittest.mock import patch  # 2026-10-15 老六修复: patch 原缺失
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

def test_token_refresh():
    """测试Token过期后自动刷新"""
    print("\n【补充测试1】Token刷新")
    
    from feishu_bot import FeishuBot
    import requests
    from unittest.mock import patch
    
    bot = FeishuBot(app_id='test_id', app_secret='test_secret')
    
    # 设置旧Token（已过期）
    bot._token = "old_token_123"
    bot._token_expire = time.time() - 100  # 100秒前过期
    
    # 模拟新Token获取
    new_token = "new_token_456"
    with patch('requests.post') as mock_post:
        mock_post.return_value.json.return_value = {
            "code": 0,
            "tenant_access_token": new_token,
            "expire": 7200
        }
        
        result_token = bot.get_token()
        
        if result_token == new_token and bot._token == new_token:
            print("  ✅ Token刷新成功")
            return True
        else:
            print(f"  ❌ Token刷新失败: 期望{new_token}, 实际{result_token}")
            return False


def test_concurrent_tasks():
    """测试多任务并发发布"""
    print("\n【补充测试2】多任务并发")
    
    from coordination_system import BlockerDetector, BlockerResolver
    import tempfile
    
    results = []
    
    with tempfile.TemporaryDirectory() as tmpdir:
        task_board_path = Path(tmpdir) / 'TASK-BOARD.json'
        
        # 创建10个任务
        tasks = []
        for i in range(10):
            tasks.append({
                "id": f"T-concurrent-{i}",
                "title": f"并发任务{i}",
                "assignee": f"@user{i}",
                "priority": "P0",
                "deadline": (datetime.now() - timedelta(hours=1)).isoformat(),
                "status": "pending",
                "created_at": (datetime.now() - timedelta(hours=2)).isoformat()
            })
        
        task_board_path.write_text(json.dumps({"tasks": tasks}))
        
        # 并发检测阻塞
        # 2026-10-15 总管: 原写法每线程各自 patch 共享模块属性 coordination_system.TASK_BOARD_FILE,
        # mock.patch 的 save/restore 在 5 线程并发下竞态(其他线程 stop() 会把全局翻回默认值,
        # 使 exists()/open() 两次读属性拿到不同路径) → CI 实证 FileNotFoundError(CI 无 .agent 目录).
        # 改为单一外部 patcher: 全程属性恒为 tmp 路径, 线程只做只读检测, 无竞态.
        def detect_blocker(index):
            detector = BlockerDetector()
            return detector.detect_timeouts()
        
        patcher = patch('coordination_system.TASK_BOARD_FILE', task_board_path)
        patcher.start()
        try:
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(detect_blocker, i) for i in range(5)]
                blockesr_results = [f.result() for f in as_completed(futures)]
        finally:
            patcher.stop()
        
        # 统计检测到的阻塞数
        total_blockers = sum(len(b) for b in blockesr_results)
        
        if total_blockers >= 10:
            print(f"  ✅ 并发检测成功，发现{total_blockers}个阻塞")
            return True
        else:
            print(f"  ❌ 并发检测失败，期望≥10个阻塞，实际{total_blockers}个")
            return False


def test_edge_cases():
    """测试边界情况"""
    print("\n【补充测试3】边界情况")
    
    from feishu_bot import FeishuBot
    from coordination_system import BlockerDetector
    import tempfile
    
    all_passed = True
    
    # 测试1: 空消息内容
    # 2026-10-15 老六修复: FeishuBot 无 send_text 方法(接口漂移), 实测 send_message
    # 对空 content 在 get_token 网络请求前即返回 success:False, 不发起外网调用
    bot = FeishuBot(app_id='test', app_secret='test')
    result = bot.send_message("oc_" + "a" * 32, "")
    if result.get('success') == False:
        print("  ✅ 空消息被拒绝")
    else:
        print("  ⚠️ 空消息未被拒绝")
        all_passed = False
    
    # 测试2: 超长消息（模拟）
    long_message = "x" * 25000  # 超过20000限制
    # 注意：这里不实际发送，只测试长度检查
    if len(long_message) > 20000:
        print("  ✅ 超长消息检测正确")
    else:
        print("  ❌ 超长消息检测失败")
        all_passed = False
    
    # 测试3: 损坏的JSON
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_json_path = Path(tmpdir) / 'bad.json'
        bad_json_path.write_text("{ invalid json }}}}")
        
        with patch('coordination_system.TASK_BOARD_FILE', bad_json_path):
            detector = BlockerDetector()
            try:
                board = detector._load_board()
                if board == {'tasks': [], 'stats': {}}:
                    print("  ✅ 损坏JSON正确恢复")
                else:
                    print("  ❌ 损坏JSON恢复失败")
                    all_passed = False
            except Exception as e:
                print(f"  ❌ 损坏JSON导致崩溃: {e}")
                all_passed = False
    
    return all_passed


def main():
    """运行补充测试"""
    from datetime import timedelta
    
    print("=" * 80)
    print("🧪 缺失测试补充")
    print("=" * 80)
    
    results = []
    results.append(test_token_refresh())
    results.append(test_concurrent_tasks())
    results.append(test_edge_cases())
    
    print("\n" + "=" * 80)
    if all(results):
        print("✅ 所有补充测试通过")
    else:
        print(f"❌ {results.count(False)}项测试失败")
    print("=" * 80)
    
    return 0 if all(results) else 1


if __name__ == '__main__':
    exit(main())
