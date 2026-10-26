# -*- coding: utf-8 -*-
"""
test_exception_swallowing_fix.py — D-6 P0-2/P0-3 异常吞噬修复 RED 证据

验证目标（修复后 GREEN）：
  sys_watchdog.load_json      损坏JSON → 抛异常（非 return None 假阴性）
  loop_watch.schtasks_run     异常 → 抛异常（非 return False 假阴性）
  loop_watch.schtasks_enable  异常 → 抛异常（非 return False 假阴性）
  queue_integration.load_queue 损坏JSON → 抛异常（非 return [] 假阴性）
  notification_sender.load_queue 损坏JSON → 抛异常（非 return [] 假阴性）
  send_feishu_alert.load_cooldown_state 损坏JSON → 抛异常（非 return {} 假阴性）
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class TestSysWatchdogLoadJson(unittest.TestCase):
    """P0-2: sys_watchdog.py:59 修复 — load_json 不再吞异常"""

    def test_corrupted_json_raises_not_none(self):
        """损坏的 JSON 文件 → 必须抛异常，不能静默返回 None"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sw", ROOT / "scripts" / "sys_watchdog.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("NOT VALID JSON{{{")
            path = f.name
        try:
            with self.assertRaises(json.JSONDecodeError):
                mod.load_json(path)
        finally:
            os.unlink(path)

    def test_missing_file_returns_none(self):
        """文件不存在 → 返回 None（正常路径，保持不变）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sw", ROOT / "scripts" / "sys_watchdog.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIsNone(mod.load_json("/nonexistent/path.json"))

    def test_check_drain_with_corrupted_state(self):
        """P0-2 核心断言: drain_state 损坏 → load_json 抛异常上溢，check_drain 不假绿"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sw", ROOT / "scripts" / "sys_watchdog.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{bad json")
            bad_path = f.name
        orig = mod.DRAIN_STATE
        try:
            mod.DRAIN_STATE = bad_path
            # 修复后：load_json 抛 JSONDecodeError，check_drain 不调用方吞掉
            with self.assertRaises(json.JSONDecodeError):
                mod.check_drain()
        finally:
            mod.DRAIN_STATE = orig
            os.unlink(bad_path)


class TestLoopWatchSchtasksFunctions(unittest.TestCase):
    """P0-2: loop_watch.py:90,99 修复 — schtasks_run/enable 不再吞异常"""

    def test_schtasks_run_raises_on_exception(self):
        """schtasks_run 执行异常时应该抛异常，不能 return False"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lw", ROOT / "scripts" / "loop_watch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with mock.patch.object(mod.subprocess, "run", side_effect=OSError("no schtasks")):
            with self.assertRaises(OSError):
                mod.schtasks_run("QSP_SelfHeal")

    def test_schtasks_enable_raises_on_exception(self):
        """schtasks_enable 执行异常时应该抛异常，不能 return False"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "lw", ROOT / "scripts" / "loop_watch.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with mock.patch.object(mod.subprocess, "run", side_effect=OSError("permission denied")):
            with self.assertRaises(OSError):
                mod.schtasks_enable("QSP_SelfHeal")


class TestQueueIntegrationLoadQueue(unittest.TestCase):
    """P0-3: queue_integration.py:35 修复 — load_queue 不再吞异常"""

    def test_corrupted_queue_raises_not_empty_list(self):
        """损坏的队列文件 → 必须抛异常，不能静默返回 []"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "qi", ROOT / "scripts" / "queue_integration.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[broken json")
            bad_path = str(Path(f.name))
        orig = mod.QUEUE_FILE
        try:
            mod.QUEUE_FILE = Path(bad_path)
            with self.assertRaises(json.JSONDecodeError):
                mod.load_queue()
        finally:
            mod.QUEUE_FILE = orig
            os.unlink(bad_path)

    def test_missing_queue_returns_empty_list(self):
        """队列文件不存在 → 返回 []（正常路径）；重定向到必不存在路径，不碰真实队列文件（2026-10-21 t_bae6c7d6 隔离修复：全量套件顺序依赖假红）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "qi", ROOT / "scripts" / "queue_integration.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        orig = mod.QUEUE_FILE
        try:
            mod.QUEUE_FILE = Path(tempfile.gettempdir()) / f"p14b_missing_queue_{os.getpid()}.json"
            self.assertEqual(mod.load_queue(), [])
        finally:
            mod.QUEUE_FILE = orig


class TestNotificationSenderLoadQueue(unittest.TestCase):
    """P0-3: notification_sender.py:42 修复 — load_queue 不再吞异常"""

    def test_corrupted_queue_raises_not_empty_list(self):
        """损坏队列 → 抛异常，不能 return [] 假阴性"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ns", ROOT / "scripts" / "notification_sender.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("corrupt")
            bad_path = str(Path(f.name))
        orig = mod.QUEUE_FILE
        try:
            mod.QUEUE_FILE = Path(bad_path)
            with self.assertRaises(json.JSONDecodeError):
                mod.load_queue()
        finally:
            mod.QUEUE_FILE = orig
            os.unlink(bad_path)

    def test_missing_queue_returns_empty_list(self):
        """队列文件不存在 → 返回 []；重定向到必不存在路径，不碰真实队列文件（2026-10-21 t_bae6c7d6 隔离修复）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "ns", ROOT / "scripts" / "notification_sender.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        orig = mod.QUEUE_FILE
        try:
            mod.QUEUE_FILE = Path(tempfile.gettempdir()) / f"p14b_missing_queue_{os.getpid()}.json"
            self.assertEqual(mod.load_queue(), [])
        finally:
            mod.QUEUE_FILE = orig


class TestSendFeishuAlertLoadCooldownState(unittest.TestCase):
    """P0-3: send_feishu_alert.py:47 修复 — load_cooldown_state 不再吞异常"""

    def test_corrupted_cooldown_raises_not_empty_dict(self):
        """损坏的冷却状态文件 → 抛异常，不能 return {} 假阴性"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sf", ROOT / "scripts" / "send_feishu_alert.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid")
            bad_path = str(Path(f.name))
        orig = mod.COOLDOWN_FILE
        try:
            mod.COOLDOWN_FILE = Path(bad_path)
            with self.assertRaises(json.JSONDecodeError):
                mod.load_cooldown_state()
        finally:
            mod.COOLDOWN_FILE = orig
            os.unlink(bad_path)

    def test_missing_cooldown_returns_empty_dict(self):
        """冷却状态文件不存在 → 返回 {}（正常路径）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sf", ROOT / "scripts" / "send_feishu_alert.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.load_cooldown_state(), {})


if __name__ == "__main__":
    unittest.main()
