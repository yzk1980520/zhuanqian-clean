#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_weight_adjustment_task.py - 权重调整消费闭环测试
"""
import sys
import unittest
import json
import tempfile
from typing import List, Dict
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestWeightAdjustmentTask(unittest.TestCase):
    """权重调整任务单生成测试"""
    
    def setUp(self):
        """准备测试数据"""
        from scripts.weight_adjustment_task import (
            load_refs,
            generate_task_from_refs,
            write_tasks,
            check_daily
        )
        self.load_refs = load_refs
        self.generate_task = generate_task_from_refs
        self.write_tasks = write_tasks
        self.check_daily = check_daily
    
    def _make_refs(self, refs_list: List, total: int) -> Dict:
        """构造refs文件内容"""
        return {
            "total_refs": total,
            "refs": refs_list,
            "generated_at": datetime.now().isoformat()
        }
    
    def test_load_refs_from_file(self):
        """测试load_refs读取文件"""
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
        data = {
            "total_refs": 3,
            "refs": {
                "weekly_ic": [
                    {"factor": "price_reversal_5d", "source": "ic", "adjust_direction": "up"}
                ],
                "monthly_tune": [
                    {"factor": "value_proxy", "source": "monthly", "adjust_direction": "down"}
                ]
            }
        }
        json.dump(data, tmp)
        tmp.close()
        
        with patch('scripts.weight_adjustment_task.REFS_PATH', Path(tmp.name)):
            result = self.load_refs()
            self.assertEqual(result.get("total_refs"), 3)
        
        import os
        os.unlink(tmp.name)
    
    def test_generate_task_creates_correct_structure(self):
        """测试任务单生成结构"""
        refs = {
            "total_refs": 2,
            "refs": {
                "weekly_ic": [
                    {"factor": "price_reversal_5d", "source": "ic", "adjust_direction": "up", "window_days": 20},
                    {"factor": "rsi_oversold", "source": "ic", "adjust_direction": "down", "window_days": 20}
                ]
            }
        }
        
        tasks = self.generate_task(refs)
        
        # 断言任务单生成
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        
        # 验证必要字段
        self.assertIn("task_id", task)
        self.assertIn("source", task)
        self.assertIn("candidate_weights", task)
        self.assertIn("review_request", task)
        self.assertIn("created_at", task)
        
        # 验证权重提取
        self.assertEqual(task["candidate_weights"]["factors_adjusted"], 2)
        self.assertEqual(task["candidate_weights"]["direction_distribution"]["up"], 1)
        self.assertEqual(task["candidate_weights"]["direction_distribution"]["down"], 1)
    
    def test_write_tasks_append_only(self):
        """测试任务单append写入"""
        tasks = [
            {
                "task_id": "wt-001",
                "source": "weekly_ic",
                "status": "pending"
            },
            {
                "task_id": "wt-002",
                "source": "monthly_tune",
                "status": "pending"
            }
        ]
        
        # 创建临时tasks文件
        tmp = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False)
        tmp.close()
        
        with patch('scripts.weight_adjustment_task.TASKS_PATH', Path(tmp.name)):
            written = self.write_tasks(tasks)
            
            self.assertEqual(written, 2)
            
            # 验证文件内容
            with open(tmp.name) as f:
                lines = f.readlines()
                self.assertEqual(len(lines), 2)
                
                # 验证每行JSON有效
                for line in lines:
                    task = json.loads(line)
                    self.assertIn("task_id", task)
        
        import os
        os.unlink(tmp.name)
    
    def test_check_daily_alert_when_refs_without_tasks(self):
        """测试refs存在但无任务单 → 告警"""
        tmp_refs = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
        json.dump({"total_refs": 3, "refs": {"weekly_ic": [1, 2, 3]}}, tmp_refs)
        tmp_refs.close()
        
        with patch('scripts.weight_adjustment_task.REFS_PATH', Path(tmp_refs.name)), \
             patch('scripts.weight_adjustment_task.TASKS_PATH', Path('/nonexistent/tasks.jsonl')):
            result = self.check_daily()
            
            self.assertEqual(result["status"], "alert")
            self.assertIsNotNone(result["alert"])
            self.assertIn("C1", result["alert"])
        
        import os
        os.unlink(tmp_refs.name)
    
    def test_check_daily_info_when_no_refs(self):
        """测试无refs → info状态"""
        with patch('scripts.weight_adjustment_task.REFS_PATH', Path('/nonexistent/refs.json')), \
             patch('scripts.weight_adjustment_task.TASKS_PATH', Path('/nonexistent/tasks.jsonl')):
            result = self.check_daily()
            
            self.assertEqual(result["status"], "info")
            self.assertIn("C2", result["alert"])


if __name__ == '__main__':
    unittest.main(verbosity=2)
