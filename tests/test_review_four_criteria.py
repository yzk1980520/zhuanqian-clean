#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_review_four_criteria.py - 老六复审判据四件套测试
"""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestFourCriteria(unittest.TestCase):
    """四件套核验测试"""
    
    def setUp(self):
        from scripts.review_four_criteria import check_four_criteria, format_review_verdict
        self.check = check_four_criteria
        self.format_verdict = format_review_verdict
    
    def test_all_criteria_met(self):
        """测试全四件满足 → passed=True"""
        import tempfile
        import os
        
        # 创建真实存在的临时文件
        tmp = tempfile.NamedTemporaryFile(suffix='.md', delete=False)
        tmp.write(b"# Test")
        tmp.close()
        evidence_path = tmp.name
        
        result = self.check(
            commit_hash="abc1234",
            evidence_path=evidence_path,
            regression_status="pass",
            commit_declared="abc1234",
            assertions={
                "consumer": "cron_daily_monitor",
                "cycle": "daily",
                "alert_path": "message_queue.json"
            }
        )
        
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["missing"]), 0)
        os.unlink(evidence_path)  # 清理
    
    def test_missing_evidence(self):
        """测试缺一手证据 → passed=False"""
        result = self.check(
            commit_hash="abc1234",
            evidence_path="/tmp/nonexistent.md",  # 不存在
            regression_status="pass",
            commit_declared="abc1234",
            assertions={
                "consumer": "cron",
                "cycle": "daily",
                "alert_path": "queue"
            }
        )
        
        self.assertFalse(result["passed"])
        self.assertIn("C1_未挂一手证据", result["missing"])
    
    def test_regression_not_passed(self):
        """测试回归未跑 → passed=False"""
        result = self.check(
            commit_hash="def5678",
            evidence_path="/tmp/exists.md",
            regression_status="fail",  # 回归失败
            commit_declared="def5678",
            assertions={
                "consumer": "x",
                "cycle": "y",
                "alert_path": "z"
            }
        )
        
        self.assertFalse(result["passed"])
        self.assertIn("C2_回归未跑或未全绿", result["missing"])
    
    def test_commit_mismatch(self):
        """测试引擎commit不一致 → passed=False"""
        result = self.check(
            commit_hash="abc1234",
            evidence_path="/tmp/exists.md",
            regression_status="pass",
            commit_declared="xyz9876",  # 不一致
            assertions={
                "consumer": "a",
                "cycle": "b",
                "alert_path": "c"
            }
        )
        
        self.assertFalse(result["passed"])
        self.assertIn("C3_引擎commit未声明或与实际不一致", result["missing"])
    
    def test_missing_assertion_fields(self):
        """测试读侧断言缺字段 → passed=False"""
        result = self.check(
            commit_hash="abc1234",
            evidence_path="/tmp/exists.md",
            regression_status="pass",
            commit_declared="abc1234",
            assertions={
                "consumer": "x",
                "cycle": "y"
                # 缺 alert_path
            }
        )
        
        self.assertFalse(result["passed"])
        self.assertIn("C4_断言缺alert_path", result["missing"])
    
    def test_format_verdict_pass(self):
        """测试verdict格式化 - 通过"""
        result = {
            "passed": True,
            "missing": [],
            "evidence_ref": "docs/test.md",
            "commit_hash": "abc1234"
        }
        verdict = self.format_verdict(result)
        self.assertIn("✅", verdict)
        self.assertIn("abc1234", verdict)
    
    def test_format_verdict_fail(self):
        """测试verdict格式化 - 打回"""
        result = {
            "passed": False,
            "missing": ["C1_未挂一手证据", "C2_回归未跑或未全绿"],
            "evidence_ref": "无",
            "commit_hash": "def5678"
        }
        verdict = self.format_verdict(result)
        self.assertIn("❌", verdict)
        self.assertIn("C1_未挂一手证据", verdict)
        self.assertIn("C2_回归未跑或未全绿", verdict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
