#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-B: probe_p04_remote 数值阈值化测试

覆盖:
  - ahead > THRESHOLD(50) → 应报异常(Red)
  - ahead <= THRESHOLD 且 ok=True → 应通过(Green)
  - ok=False → 应报异常
  - 日志陈旧(>70min) → 应报异常
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import self_heal_check as shc

THRESHOLD = getattr(shc, "P04_AHEAD_THRESHOLD", 50)


def _write_fixture(state_results, log_age_min=5):
    """在临时目录写入 state + freshness log，返回 (tmpdir, old_DATA, old_LOG)"""
    tmpdir = tempfile.mkdtemp(prefix="p04_test_")
    state = {"last_run": datetime.now().isoformat(), "results": state_results}
    state_path = os.path.join(tmpdir, "remote_freshness_state.json")
    with open(state_path, "w") as f:
        json.dump(state, f)
    log_path = os.path.join(tmpdir, "remote_freshness.log")
    with open(log_path, "w") as f:
        f.write("ahead=1 age=5.0\n")
    t = time.time() - log_age_min * 60
    os.utime(log_path, (t, t))
    return tmpdir, shc.DATA, shc.FRESHNESS_LOG


def _cleanup(tmpdir, old_data, old_log):
    shc.DATA = old_data
    shc.FRESHNESS_LOG = old_log
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


def test_ahead_exceeds_threshold_returns_false():
    """Red: ahead=60 > 50 → 应报异常"""
    tmpdir, old_data, old_log = _write_fixture([
        {"remote": "origin", "ok": True, "local_ahead": 60, "alerts": []},
        {"remote": "gitcode", "ok": True, "local_ahead": 60, "alerts": []},
    ])
    shc.DATA = tmpdir
    try:
        ok, detail = shc.probe_p04_remote()
        assert not ok, "ahead=60 应报异常，实际: %s" % detail
        assert "50" in detail or "阈" in detail or "ahead" in detail.lower(), \
            "异常信息应含阈值说明: %s" % detail
    finally:
        _cleanup(tmpdir, old_data, old_log)


def test_ahead_within_threshold_returns_true():
    """Green: ahead=1 <= 50 → 应通过"""
    tmpdir, old_data, old_log = _write_fixture([
        {"remote": "origin", "ok": True, "local_ahead": 1, "alerts": []},
        {"remote": "gitcode", "ok": True, "local_ahead": 1, "alerts": []},
    ])
    shc.DATA = tmpdir
    try:
        ok, detail = shc.probe_p04_remote()
        assert ok, "ahead=1 应通过，实际: %s" % detail
    finally:
        _cleanup(tmpdir, old_data, old_log)


def test_remote_not_ok_returns_false():
    """Green: ok=False → 应报异常（保留原有语义）"""
    tmpdir, old_data, old_log = _write_fixture([
        {"remote": "origin", "ok": False, "local_ahead": 0, "alerts": ["network error"]},
        {"remote": "gitcode", "ok": True, "local_ahead": 1, "alerts": []},
    ])
    shc.DATA = tmpdir
    try:
        ok, detail = shc.probe_p04_remote()
        assert not ok, "ok=False 应报异常，实际: %s" % detail
        assert "origin" in detail
    finally:
        _cleanup(tmpdir, old_data, old_log)


def test_freshness_log_stale_returns_false():
    """Green: 日志陈旧 >70min → 应报异常"""
    tmpdir, old_data, old_log = _write_fixture(
        [{"remote": "origin", "ok": True, "local_ahead": 1, "alerts": []}],
        log_age_min=80
    )
    shc.DATA = tmpdir
    shc.FRESHNESS_LOG = os.path.join(tmpdir, "remote_freshness.log")
    try:
        ok, detail = shc.probe_p04_remote()
        assert not ok, "日志陈旧应报异常，实际: %s" % detail
    finally:
        _cleanup(tmpdir, old_data, old_log)


def test_missing_state_fallback_pass():
    """Green: state 文件不存在 → 回退到日志新鲜度判定(通过)"""
    tmpdir, old_data, old_log = _write_fixture([], log_age_min=5)
    # 删掉 state 文件，只留 log
    state_path = os.path.join(tmpdir, "remote_freshness_state.json")
    if os.path.exists(state_path):
        os.unlink(state_path)
    shc.DATA = tmpdir
    shc.FRESHNESS_LOG = os.path.join(tmpdir, "remote_freshness.log")
    try:
        ok, detail = shc.probe_p04_remote()
        assert ok, "无 state 文件时应回退通过，实际: %s" % detail
    finally:
        _cleanup(tmpdir, old_data, old_log)
