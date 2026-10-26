#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_t7_qsp_watchdog.py — T7外环看门狗测试

验收标准：
1. last_run 龄检测正确（<30min ok, >30min P0）
2. consec_p0 计数检测正确（≥2 P0）
3. 探针失败检测正确（排除豁免项）
4. 告警入队正确
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

# 添加scripts到path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from t7_qsp_watchdog import (
    check_last_run_age,
    check_consec_p0,
    check_probe_failures,
    load_state,
    add_alert,
    load_queue,
    WATCHDOG_LOG,
    QUEUE
)


class TestLastRunAge(unittest.TestCase):
    """测试last_run新鲜度检测"""

    def test_fresh_run_ok(self):
        """last_run 5分钟前 → ok"""
        state = {
            "last_run": (datetime.now() - timedelta(minutes=5)).isoformat(),
            "consec_p0": 0,
            "results": {}
        }
        alert = check_last_run_age(state)
        self.assertIsNone(alert, "fresh run should not alert")

    def test_stale_run_p0(self):
        """last_run 1小时前 → P0"""
        state = {
            "last_run": (datetime.now() - timedelta(hours=1)).isoformat(),
            "consec_p0": 0,
            "results": {}
        }
        alert = check_last_run_age(state)
        self.assertIsNotNone(alert, "stale run should alert P0")

    def test_missing_last_run_p0(self):
        """last_run 缺失 → P0"""
        state = {
            "consec_p0": 0,
            "results": {}
        }
        alert = check_last_run_age(state)
        self.assertIsNotNone(alert, "missing last_run should alert P0")

    def test_invalid_format_p0(self):
        """last_run 格式错误 → P0"""
        state = {
            "last_run": "not-a-datetime",
            "consec_p0": 0,
            "results": {}
        }
        alert = check_last_run_age(state)
        self.assertIsNotNone(alert, "invalid format should alert P0")


class TestConsecP0(unittest.TestCase):
    """测试连续P0计数检测"""

    def test_zero_consec_ok(self):
        """consec_p0=0 → ok"""
        state = {
            "last_run": datetime.now().isoformat(),
            "consec_p0": 0,
            "results": {}
        }
        alert = check_consec_p0(state)
        self.assertIsNone(alert)

    def test_low_consec_ok(self):
        """consec_p0=1 → ok"""
        state = {
            "last_run": datetime.now().isoformat(),
            "consec_p0": 1,
            "results": {}
        }
        alert = check_consec_p0(state)
        self.assertIsNone(alert)

    def test_high_consec_p0(self):
        """consec_p0=2 → P0"""
        state = {
            "last_run": datetime.now().isoformat(),
            "consec_p0": 2,
            "results": {}
        }
        alert = check_consec_p0(state)
        self.assertIsNotNone(alert)


class TestProbeFailures(unittest.TestCase):
    """测试探针失败检测"""

    def test_all_ok_no_alert(self):
        """所有探针ok → 无告警"""
        state = {
            "last_run": datetime.now().isoformat(),
            "consec_p0": 0,
            "results": {
                "P-01": {"name": "告警投递链活性", "ok": True},
                "P-02": {"name": "任务级活性", "ok": True}
            }
        }
        alert = check_probe_failures(state)
        self.assertIsNone(alert)

    def test_failure_alert(self):
        """探针失败 → P1告警"""
        state = {
            "last_run": datetime.now().isoformat(),
            "consec_p0": 0,
            "results": {
                "P-01": {"name": "告警投递链活性", "ok": False, "detail": "last_run 龄 45min"},
                "P-02": {"name": "任务级活性", "ok": True}
            }
        }
        alert = check_probe_failures(state)
        self.assertIsNotNone(alert)

    def test_exempt_probes_ignored(self):
        """豁免项失败 → 不告警"""
        state = {
            "last_run": datetime.now().isoformat(),
            "consec_p0": 0,
            "results": {
                "P-07": {"name": "卫生", "ok": False, "detail": "垃圾堆积"},
                "P-10": {"name": "死部署副本", "ok": False},
                "P-11": {"name": "备份堆积", "ok": False}
            }
        }
        alert = check_probe_failures(state)
        self.assertIsNone(alert, "exempt probes should not trigger alert")


class TestAlertQueue(unittest.TestCase):
    """测试告警入队"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        # 直接修改模块变量
        import t7_qsp_watchdog as mod
        mod.QUEUE = os.path.join(self.tmp_dir, "message_queue.json")
        self.mod = mod

    def tearDown(self):
        q_path = self.mod.QUEUE
        if os.path.exists(q_path):
            os.unlink(q_path)

    def test_add_alert_creates_queue(self):
        """首次告警创建队列文件"""
        alert_id = self.mod.add_alert("P1", "test", "test content")
        self.assertTrue(os.path.exists(self.mod.QUEUE))
        q = json.loads(Path(self.mod.QUEUE).read_text(encoding="utf-8"))
        self.assertEqual(len(q), 1)
        self.assertEqual(q[0]["content"], "test content")
        self.assertEqual(alert_id, q[0]["id"])

    def test_add_alert_appends(self):
        """追加告警到现有队列"""
        self.mod.add_alert("P1", "test1", "content1")
        alert_id = self.mod.add_alert("P2", "test2", "content2")
        q = json.loads(Path(self.mod.QUEUE).read_text(encoding="utf-8"))
        self.assertEqual(len(q), 2)
        self.assertEqual(q[1]["content"], "content2")
        self.assertEqual(alert_id, q[1]["id"])


if __name__ == "__main__":
    unittest.main()
