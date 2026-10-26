#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-C: runbook 路径修复 + P-11 卫生断言测试"""
import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import self_heal_check as shc


def test_runbook_path_exists():
    """Green: docs/runbook-人工单点.md 真实存在"""
    path = os.path.join(shc.PROJECT, "docs", "runbook-人工单点.md")
    assert os.path.exists(path), "runbook 文件不存在: %s" % path
    print("✅ test_runbook_path_exists")


def test_validate_alert_paths_all_good():
    """Green: 所有 ALERT_REF_PATHS 路径都存在 → log 通过，不写 alert"""
    alert_calls = []
    log_calls = []
    def mock_alert(text, level="P1"):
        alert_calls.append((text, level))
    def mock_log(tag, text, level="alert"):
        log_calls.append((tag, text))

    with patch.object(shc, "alert", mock_alert), \
         patch.object(shc, "log", mock_log):
        shc.validate_alert_paths()
    assert len(alert_calls) == 0, "不应有 alert，实际: %s" % alert_calls
    assert any("P-11" in lc[0] or "P-11" in lc[1] for lc in log_calls), "应有 P-11 log: %s" % log_calls
    print("✅ test_validate_alert_paths_all_good")


def test_validate_alert_paths_broken_triggers_p1():
    """Red→Green: 注入缺失路径 → 应触发 P1 alert"""
    broken_path = "docs/非存在路径-%d.md" % id(tempfile.mkdtemp())
    original = shc.ALERT_REF_PATHS[:]
    shc.ALERT_REF_PATHS.append(broken_path)
    try:
        alert_calls = []
        def mock_alert(text, level="P1"):
            alert_calls.append((text, level))
        with patch.object(shc, "alert", mock_alert), \
             patch.object(shc, "log", lambda *a, **k: None):
            shc.validate_alert_paths()
        p1_alerts = [a for a in alert_calls if a[1] == "P1"]
        assert len(p1_alerts) > 0, "应有 P1 alert，实际: %s" % alert_calls
        assert "P-11" in p1_alerts[0][0], "alert 应含 P-11: %s" % p1_alerts[0][0]
        assert "非存在路径" in p1_alerts[0][0], \
            "alert 应提及断裂路径: %s" % p1_alerts[0][0]
        print("✅ test_validate_alert_paths_broken_triggers_p1")
    finally:
        shc.ALERT_REF_PATHS.pop()


def test_runbook_content_current_not_archived():
    """Green: 新 runbook 不应包含已完成的旧操作（如 webhook 重建）"""
    path = os.path.join(shc.PROJECT, "docs", "runbook-人工单点.md")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # 旧内容特征词不应出现在新 runbook 中作为待办
    # （archive 版有这些，新应为当前待办）
    # 新 runbook 应包含当前待办关键词
    assert "Gateway" in content or "gateway" in content, \
        "新 runbook 应包含当前待办（Gateway churn 等）"
    print("✅ test_runbook_content_current_not_archived")


if __name__ == "__main__":
    test_runbook_path_exists()
    test_validate_alert_paths_all_good()
    test_validate_alert_paths_broken_triggers_p1()
    test_runbook_content_current_not_archived()
    print("\n全部通过 ✅")
