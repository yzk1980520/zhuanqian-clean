#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_closedloop_daily_report.py - 闭环健康度日报测试
"""
import sys
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestClosedloopDailyReport(unittest.TestCase):
    """闭环日报测试"""
    
    def setUp(self):
        """准备测试数据"""
        from scripts.closedloop_daily_report import (
            generate_daily_report,
            verify_read_side,
            write_alerts_to_queue
        )
        self.generate_report = generate_daily_report
        self.verify = verify_read_side
        self.write_alerts = write_alerts_to_queue
    
    def test_generate_daily_report_structure(self):
        """测试日报生成结构

        P2#5(a) @opencode: mock 必须按 clh.check_aX() 的**真实**权威契约
        返回 {"status","detail"} (旧 mock 误用 {"id","pass","description"} 幻影契约,
        使消费键错位缺陷从未被测试捕获)。"""
        # mock closedloop_health的函数 (按实际权威契约: status/detail)
        tmpdir = tempfile.mkdtemp()
        
        with patch('scripts.closedloop_health.check_a1_contract') as mock_a1, \
             patch('scripts.closedloop_health.check_a2_single_source') as mock_a2, \
             patch('scripts.closedloop_health.check_a3_feedback_write') as mock_a3, \
             patch('scripts.closedloop_health.check_a4_feedback_read') as mock_a4, \
             patch('scripts.closedloop_health.check_a5_false_green') as mock_a5, \
             patch('scripts.closedloop_daily_report.REPORTS_DIR', Path(tmpdir)):
            
            mock_a1.return_value = {"status": "PASS", "detail": "contract"}
            mock_a2.return_value = {"status": "FAIL", "detail": "single_source"}
            mock_a3.return_value = {"status": "PASS", "detail": "feedback_write"}
            mock_a4.return_value = {"status": "PASS", "detail": "feedback_read"}
            mock_a5.return_value = {"status": "PASS", "detail": "false_green"}
            
            report = self.generate_report()
            
            # 验证结构
            self.assertIn("report_date", report)
            self.assertIn("assertions", report)
            self.assertIn("health_metrics", report)
            
            # 验证健康度计算
            self.assertEqual(report["health_metrics"]["total_assertions"], 5)
            self.assertEqual(report["health_metrics"]["passed"], 4)
            self.assertAlmostEqual(
                report["health_metrics"]["health_ratio"],
                4/5,
                places=2
            )
            
            # 验证告警触发
            self.assertTrue(report["alert_triggered"])
            self.assertEqual(len(report["alerts"]), 1)
            self.assertEqual(report["alerts"][0]["id"], "A2")
            # detail 权威文本必须流入 alert.description (消费键对齐核心断言)
            self.assertEqual(report["alerts"][0]["description"], "single_source")
            self.assertEqual(report["alerts"][0]["status"], "FAIL")

    def test_generate_daily_report_all_pass_no_alert(self):
        """全 PASS → alert_triggered=False, 零告警 (修复前此路径恒为 true, 5 条空告警)。"""
        tmpdir = tempfile.mkdtemp()
        spec = {"status": "PASS", "detail": "ok"}
        with patch('scripts.closedloop_health.check_a1_contract', return_value=dict(spec)), \
             patch('scripts.closedloop_health.check_a2_single_source', return_value=dict(spec)), \
             patch('scripts.closedloop_health.check_a3_feedback_write', return_value=dict(spec)), \
             patch('scripts.closedloop_health.check_a4_feedback_read', return_value=dict(spec)), \
             patch('scripts.closedloop_health.check_a5_false_green', return_value=dict(spec)), \
             patch('scripts.closedloop_daily_report.REPORTS_DIR', Path(tmpdir)):
            report = self.generate_report()
            self.assertFalse(report["alert_triggered"])
            self.assertEqual(report["alerts"], [])
            self.assertEqual(report["health_metrics"]["passed"], 5)
            self.assertAlmostEqual(report["health_metrics"]["health_ratio"], 1.0)

    def test_generate_daily_report_partial_triggers_alert(self):
        """PARTIAL (非 PASS) 也触发告警并携带 detail 文本 (降级面可见, 非静默)。"""
        tmpdir = tempfile.mkdtemp()
        spec_pass = {"status": "PASS", "detail": "ok"}
        spec_part = {"status": "PARTIAL", "detail": "超期 3h, 疑似漏跑"}
        with patch('scripts.closedloop_health.check_a1_contract', return_value=dict(spec_pass)), \
             patch('scripts.closedloop_health.check_a2_single_source', return_value=dict(spec_part)), \
             patch('scripts.closedloop_health.check_a3_feedback_write', return_value=dict(spec_pass)), \
             patch('scripts.closedloop_health.check_a4_feedback_read', return_value=dict(spec_pass)), \
             patch('scripts.closedloop_health.check_a5_false_green', return_value=dict(spec_pass)), \
             patch('scripts.closedloop_daily_report.REPORTS_DIR', Path(tmpdir)):
            report = self.generate_report()
            self.assertTrue(report["alert_triggered"])
            self.assertEqual(len(report["alerts"]), 1)
            self.assertEqual(report["alerts"][0]["id"], "A2")
            self.assertEqual(report["alerts"][0]["status"], "PARTIAL")
            self.assertEqual(report["alerts"][0]["description"], "超期 3h, 疑似漏跑")
    
    def test_verify_read_side_ok(self):
        """测试读侧验证 - 正常状态"""
        tmpdir = tempfile.mkdtemp()
        today = datetime.now().strftime("%Y-%m-%d")
        report_file = Path(tmpdir) / f"closedloop_daily_{today}.json"
        
        # 创建有效的日报
        report = {
            "report_date": today,
            "generated_at": datetime.now().isoformat(),
            "assertions": [],
            "health_metrics": {"total": 4, "passed": 4, "health_ratio": 1.0},
            "alert_triggered": False,
            "alerts": []
        }
        with open(report_file, 'w') as f:
            json.dump(report, f)
        
        with patch('scripts.closedloop_daily_report.REPORTS_DIR', Path(tmpdir)):
            result = self.verify()
            
            self.assertEqual(result["status"], "ok")
            self.assertIn("report", result)
            self.assertEqual(result["health_ratio"], 1.0)
    
    def test_verify_read_side_alert(self):
        """测试读侧验证 - 告警状态"""
        with patch('scripts.closedloop_daily_report.REPORTS_DIR', Path('/nonexistent')):
            result = self.verify()
            
            self.assertEqual(result["status"], "alert")
            self.assertIn("无今日日报", result["message"])
    
    def test_write_alerts_to_queue(self):
        """测试告警写入队列"""
        tmpdir = tempfile.mkdtemp()
        
        with patch('scripts.closedloop_daily_report.PROJECT_ROOT', Path(tmpdir)):
            report = {
                "report_date": datetime.now().strftime("%Y-%m-%d"),
                "alerts": [
                    {"id": "A1", "description": "refs未生成", "severity": "P2"},
                    {"id": "A3", "description": "cron未注册", "severity": "P2"}
                ],
                "alert_triggered": True
            }
            
            self.write_alerts(report)
            
            # 验证队列文件创建
            queue_file = Path(tmpdir) / "data" / "message_queue.json"
            self.assertTrue(queue_file.exists())
            
            with open(queue_file) as f:
                queue = json.load(f)
                
                self.assertEqual(len(queue), 2)
                self.assertEqual(queue[0]["type"], "closedloop_alert")
                self.assertEqual(queue[0]["alert_id"], "A1")


if __name__ == '__main__':
    unittest.main(verbosity=2)
