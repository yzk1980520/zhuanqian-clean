#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_heal_check P-10/P-11 新探针测试 (2026-10-15 T7 下一版)

覆盖:
  P-10 死部署副本: 无启用态任务引用 -> 报告; 有活引用 -> 通过;
       注册表不可用(非 Windows) -> 跳过; 目录不存在 -> 通过
  P-11 备份/垃圾堆积: .bak* 计数/.trash 体积超阈 -> 报告;
       .git/__pycache__/.trash 内的 bak 不计数; 未超阈 -> 通过
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import self_heal_check as shc


# ---------------------------------------------------------------- P-10
def test_p10_flags_dead_deploy():
    """无启用态任务引用 health_monitor -> 死部署报告"""
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "health_monitor"), exist_ok=True)
        with patch.object(shc, "PROJECT", tmp), \
             patch.object(shc, "_task_registry",
                          return_value=[("\\HealthCheck_L1_5min", False,
                                         r"C:\...\python.exe health_monitor_cli.py --mode full"),
                                        ("\\QSP_SelfHeal", True,
                                         r"C:\...\python.exe self_heal_check.py")]):
            ok, detail = shc.probe_p10_dead_deploy()
    assert not ok, "无活引用应报死部署: " + detail
    assert "health_monitor" in detail and "死部署副本" in detail


def test_p10_clean_when_live_ref():
    """有启用态任务引用 -> 通过"""
    with patch.object(shc, "_task_registry",
                      return_value=[("\\SomeJob", True,
                                     r"C:\...\python.exe health_monitor\monitor.py")]):
        ok, detail = shc.probe_p10_dead_deploy()
    assert ok, "有活引用不应报死部署: " + detail


def test_p10_skips_when_registry_unavailable():
    """非 Windows / schtasks 缺失 -> 跳过(不能误报)"""
    with patch.object(shc, "_task_registry", return_value=[]):
        ok, detail = shc.probe_p10_dead_deploy()
    assert ok, "注册表不可用应当跳过而非误报: " + detail
    assert "跳过" in detail


def test_p10_ignores_absent_dir():
    """注册目录不存在 -> 通过"""
    with patch.object(shc, "DEPLOY_DIRS", ("no_such_deploy_dir_xyz",)):
        ok, detail = shc.probe_p10_dead_deploy()
    assert ok, detail


# ---------------------------------------------------------------- P-11
def _make_tree(root, n_bak=0, with_git_bak=False, with_pycache_bak=False,
               trash_file_mb=0):
    for i in range(n_bak):
        (Path(root) / ("mod%d.py.bak_20261015" % i)).write_text("x", encoding="utf-8")
    if with_git_bak:
        g = Path(root) / ".git"
        g.mkdir(exist_ok=True)
        (g / "old.py.bak").write_text("x", encoding="utf-8")
    if with_pycache_bak:
        p = Path(root) / "__pycache__"
        p.mkdir(exist_ok=True)
        (p / "old.py.bak").write_text("x", encoding="utf-8")
    if trash_file_mb:
        t = Path(root) / ".trash"
        t.mkdir(exist_ok=True)
        (t / "big.bin").write_bytes(b"\0" * (trash_file_mb * 1024 * 1024))


def test_p11_under_threshold():
    with tempfile.TemporaryDirectory() as tmp:
        _make_tree(tmp, n_bak=2)
        with patch.object(shc, "PROJECT", tmp):
            ok, detail = shc.probe_p11_backup_bloat()
    assert ok, "少量 bak 应通过: " + detail


def test_p11_bak_over_threshold():
    with tempfile.TemporaryDirectory() as tmp:
        _make_tree(tmp, n_bak=3)
        with patch.object(shc, "PROJECT", tmp), \
             patch.object(shc, "BAK_MAX_COUNT", 3), \
             patch.object(shc, "TRASH_MAX_MB", 9999):
            ok, detail = shc.probe_p11_backup_bloat()
    assert not ok, "bak 超阈应报告: " + detail
    assert ".bak* x3" in detail


def test_p11_trash_over_threshold():
    with tempfile.TemporaryDirectory() as tmp:
        _make_tree(tmp, n_bak=0, trash_file_mb=2)
        with patch.object(shc, "PROJECT", tmp), \
             patch.object(shc, "BAK_MAX_COUNT", 9999), \
             patch.object(shc, "TRASH_MAX_MB", 1):
            ok, detail = shc.probe_p11_backup_bloat()
    assert not ok, ".trash 超体积极应报告: " + detail
    assert ".trash/" in detail


def test_p11_excludes_git_and_pycache():
    """.git/__pycache__ 内的 bak 不计数(否则 CI checkout 会假阳性)"""
    with tempfile.TemporaryDirectory() as tmp:
        _make_tree(tmp, n_bak=0, with_git_bak=True, with_pycache_bak=True)
        with patch.object(shc, "PROJECT", tmp), \
             patch.object(shc, "BAK_MAX_COUNT", 1), \
             patch.object(shc, "TRASH_MAX_MB", 9999):
            ok, detail = shc.probe_p11_backup_bloat()
    assert ok, ".git/pycache 内 bak 不应计数: " + detail
