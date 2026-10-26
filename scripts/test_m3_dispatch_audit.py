#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-F: M-3 派单审计消费断言集成测试"""
import json
import os
import sys
import tempfile
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core.ops.self_audit_checkers as shc


def _mk_tmp_state(violations_count=0, checked=5, consecutive=0):
    """创建临时 state 文件，返回 (path, orig_path)"""
    tmpdir = tempfile.mkdtemp()
    orig = shc._DISPATCH_AUDIT_STATE_PATH
    tmp_state = os.path.join(tmpdir, "dispatch_audit_state.json")
    with open(tmp_state, "w", encoding="utf-8") as f:
        json.dump({
            "last_run": time.time(),
            "violations_count": violations_count,
            "checked": checked,
            "consecutive": consecutive,
        }, f)
    return tmp_state, orig


def test_m3_pass_no_violations():
    """Green: 0 violations → PASS"""
    rep = {"ok": True, "checked": 5, "scope_since": "2026-10-16T20:16:00", "violations": []}
    mock_r = MagicMock()
    mock_r.returncode = 0
    mock_r.stdout = json.dumps(rep, ensure_ascii=False)
    mock_r.stderr = ""
    with patch("subprocess.run", return_value=mock_r):
        r = shc.check_m3_dispatch_audit()
    assert r.status == "PASS", "0 violations 应 PASS: %s" % r.message
    assert r.severity == "P1"
    print("✅ test_m3_pass_no_violations")


def test_m3_fail_p1_single_day():
    """Red→Green: 1个违规第1天 → FAIL P1（未达P0阈值）"""
    rep = {
        "ok": False, "checked": 3, "scope_since": "2026-10-16T20:16:00",
        "violations": [
            {"id": "t_xxx", "rule": "C1-提单人留名", "detail": "created_by='default'"},
        ]
    }
    mock_r = MagicMock()
    mock_r.returncode = 1
    mock_r.stdout = json.dumps(rep, ensure_ascii=False)
    mock_r.stderr = ""
    # 用 tempfile 生成唯一路径，避免 Windows /tmp 被解析为 D:\tmp\ 导致跨测试污染
    _, tmp_path = tempfile.mkstemp(suffix="_dispatch_state.json")
    try:
        with patch("subprocess.run", return_value=mock_r), \
             patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_path):
            r = shc.check_m3_dispatch_audit()
        assert r.status == "FAIL", "有违规应 FAIL: %s" % r.message
        assert r.severity == "P1", "第1天应为 P1: %s" % r.severity
        print("✅ test_m3_fail_p1_single_day")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError as e:
            print(f"🔴 [test_m3_dispatch_audit.py:68] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 OSError → 兜底, 异常={e}", file=sys.stderr)
            pass  # Windows 文件锁延迟释放，跳过无妨
        _restore_queue()


def _restore_queue():
    """清理 M-3 测试写入的派单审计消息，防止污染其他测试的 message_queue.json"""
    import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
    import os
    qpath = os.path.join(shc.DATA_DIR, "message_queue.json")
    try:
        items = atomic_json.atomic_load(qpath, []) or []
        before = len(items)
        items = [m for m in items if not m.get("id", "").startswith("dispatchaudit_")]
        if len(items) < before:
            atomic_json.atomic_dump(items, qpath)
    except Exception as e:
        print(f"🔴 [test_m3_dispatch_audit.py:84] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        pass


def test_m3_fail_p0_consecutive_2():
    """Red→Green: 2天连续违规 → FAIL P0"""
    rep = {
        "ok": False, "checked": 3, "scope_since": "2026-10-16T20:16:00",
        "violations": [
            {"id": "t_yyy", "rule": "C2-复审单", "detail": "没有复审单"},
        ]
    }
    mock_r = MagicMock()
    mock_r.returncode = 1
    mock_r.stdout = json.dumps(rep, ensure_ascii=False)
    mock_r.stderr = ""
    # 上次也有违规 → consecutive=2 → P0
    tmpdir = tempfile.mkdtemp()
    tmp_state = os.path.join(tmpdir, "dispatch_audit_state.json")
    with open(tmp_state, "w", encoding="utf-8") as f:
        json.dump({"last_run": time.time(), "violations_count": 1, "checked": 3, "consecutive": 1}, f)
    try:
        with patch("subprocess.run", return_value=mock_r), \
             patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_state):
            r = shc.check_m3_dispatch_audit()
        assert r.status == "FAIL"
        assert r.severity == "P0", "连续2日应升级为 P0: %s" % r.severity
        assert "P0" in r.message or "连续" in r.message, "消息应含升级提示: %s" % r.message
        print("✅ test_m3_fail_p0_consecutive_2")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
        _restore_queue()


def test_m3_script_missing_skip():
    """Green: 脚本不存在 → SKIPPED（R1-P5 t_45357e19: SKIPPED 也写 state，隔离 state 路径防污染 live）"""
    _, tmp_state = tempfile.mkstemp(suffix="_dispatch_state.json")
    try:
        with patch.object(shc, "ROOT", "/nonexistent_root_xyz"), \
             patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_state):
            r = shc.check_m3_dispatch_audit()
        assert r.status == "SKIPPED", "脚本缺失应 SKIPPED: %s" % r.message
        assert "缺失" in r.message
        print("✅ test_m3_script_missing_skip")
    finally:
        try:
            os.unlink(tmp_state)
        except OSError as e:
            print("🔴 [test_m3_dispatch_audit.py] CR-01 静默吞噬响铃化: 捕获 OSError → 兜底, 异常=%s" % e, file=sys.stderr)


def test_m3_json_parse_fail_skip():
    """Green: 输出非JSON → SKIPPED（R1-P5 t_45357e19: SKIPPED 也写 state，隔离 state 路径防污染 live）"""
    mock_r = MagicMock()
    mock_r.returncode = 0
    mock_r.stdout = "not valid json {{{"
    mock_r.stderr = ""
    _, tmp_state = tempfile.mkstemp(suffix="_dispatch_state.json")
    try:
        with patch("subprocess.run", return_value=mock_r), \
             patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_state):
            r = shc.check_m3_dispatch_audit()
        assert r.status == "SKIPPED", "JSON解析失败应 SKIPPED: %s" % r.message
        print("✅ test_m3_json_parse_fail_skip")
    finally:
        try:
            os.unlink(tmp_state)
        except OSError as e:
            print("🔴 [test_m3_dispatch_audit.py] CR-01 静默吞噬响铃化: 捕获 OSError → 兜底, 异常=%s" % e, file=sys.stderr)


if __name__ == "__main__":
    test_m3_pass_no_violations()
    test_m3_fail_p1_single_day()
    test_m3_fail_p0_consecutive_2()
    test_m3_script_missing_skip()
    test_m3_json_parse_fail_skip()
    print("\n全部通过 ✅")
