#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_heal_check P-12 门禁阻断持续监控测试 (2026-10-20 补看门狗盲区)

三档判定自证(项目铁律: 新增断言必须自证 FAIL/PASS/边界):
  PASS : gate blocked 但 mtime <2天 / 无 frozen / 冻结恰好 2 天( strict > 边界) -> True
  FAIL : gate blocked 且 mtime >2天 / frozen 且冻结 >2天 / frozen 但冻结键不可解析 -> False
  边界 : mtime 年龄 2天±2min 跨阈翻转; 冻结天数 2->3 跨阈翻转
全部用 tempfile 造临时文件 + 显式路径注入, 不碰生产 data/。
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import self_heal_check as shc

DAY = 86400.0


def _write(path, obj, age_sec=0.0):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    if age_sec:
        t = time.time() - age_sec
        os.utime(path, (t, t))


def _freeze_key(days_ago):
    return "_freeze_" + (datetime.now().date() - timedelta(days=days_ago)).strftime("%Y%m%d")


# ---------------------------------------------------------------- PASS 档
def test_pass_gate_blocked_but_fresh():
    """blocked=true 但 mtime <2天(门禁在被持续重评) 且无 frozen -> 通过"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": True, "block_reason": "衰减超阈值"}, age_sec=3600)
        ok, detail = shc.probe_p12_gate_block(
            gate, os.path.join(tmp, "automation_daily.json"),
            os.path.join(tmp, "review_status.json"))
    assert ok, "mtime 1天前的 blocked 不应报异常: " + detail
    assert "blocked=True" in detail and "frozen=False" in detail


def test_pass_no_block_no_freeze():
    """gate 未阻断且未冻结 -> 通过"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": False})
        daily = os.path.join(tmp, "automation_daily.json")
        _write(daily, {"gate_flag": {"frozen": False}})
        ok, detail = shc.probe_p12_gate_block(
            gate, daily, os.path.join(tmp, "review_status.json"))
    assert ok, detail


def test_pass_all_files_missing():
    """状态文件全缺失 -> 不误报(阻断未发生)"""
    with tempfile.TemporaryDirectory() as tmp:
        ok, detail = shc.probe_p12_gate_block(
            os.path.join(tmp, "no_gate.json"), os.path.join(tmp, "no_daily.json"),
            os.path.join(tmp, "no_review.json"))
    assert ok, "文件缺失不应误报: " + detail


# ---------------------------------------------------------------- FAIL 档
def test_fail_gate_blocked_stale():
    """blocked=true 且 mtime 年龄 >2天 -> 异常, detail 含天数与原因"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": True, "block_reason": "衰减超阈值：OOS 衰减 0.7858"},
               age_sec=3 * DAY)
        ok, detail = shc.probe_p12_gate_block(
            gate, os.path.join(tmp, "automation_daily.json"),
            os.path.join(tmp, "review_status.json"))
    assert not ok, "blocked 3天无人重评应报异常"
    assert "walk_forward_gate" in detail and "3.0 天" in detail
    assert "衰减超阈值" in detail
    assert "人工处置" in detail and "review_status.json" in detail


def test_fail_frozen_over_threshold():
    """frozen=true 且冻结起始 3 天前 -> 异常, detail 含连续天数与原因"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": False})
        daily = os.path.join(tmp, "automation_daily.json")
        _write(daily, {"gate_flag": {"frozen": True, "reason": "final_verdict=False"}})
        review = os.path.join(tmp, "review_status.json")
        _write(review, {_freeze_key(3): {"frozen_at": "x", "reason": "P0 amount 字段损坏, 暂停出票"}})
        ok, detail = shc.probe_p12_gate_block(gate, daily, review)
    assert not ok, "冻结连续3天应报异常"
    assert "选股冻结已连续 3 天" in detail and "amount" in detail


def test_fail_frozen_but_key_unparseable():
    """frozen=true 但无 _freeze_* 键 -> fail-loud 命中(禁留静默盲区)"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": False})
        daily = os.path.join(tmp, "automation_daily.json")
        _write(daily, {"gate_flag": {"frozen": True}})
        review = os.path.join(tmp, "review_status.json")
        _write(review, {"final_verdict": False})
        ok, detail = shc.probe_p12_gate_block(gate, daily, review)
    assert not ok, "冻结态但起始日不可解析应按命中处置: " + detail
    assert "不可解析" in detail


def test_fail_both_conditions_hit():
    """两道红线同时命中 -> detail 同时含两项"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": True, "block_reason": "衰减超阈值"}, age_sec=5 * DAY)
        daily = os.path.join(tmp, "automation_daily.json")
        _write(daily, {"gate_flag": {"frozen": True}})
        review = os.path.join(tmp, "review_status.json")
        _write(review, {_freeze_key(4): {"reason": "停票"}})
        ok, detail = shc.probe_p12_gate_block(gate, daily, review)
    assert not ok
    assert "walk_forward_gate" in detail and "连续 4 天" in detail


# ---------------------------------------------------------------- 边界档
def test_boundary_gate_mtime_just_under_2d():
    """mtime 年龄 2天-2min(<阈) -> 不命中"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": True, "block_reason": "x"}, age_sec=2 * DAY - 120)
        ok, detail = shc.probe_p12_gate_block(
            gate, os.path.join(tmp, "automation_daily.json"),
            os.path.join(tmp, "review_status.json"))
    assert ok, "2天-2min 应判未超期: " + detail


def test_boundary_gate_mtime_just_over_2d():
    """mtime 年龄 2天+2min(>阈) -> 命中"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": True, "block_reason": "x"}, age_sec=2 * DAY + 120)
        ok, detail = shc.probe_p12_gate_block(
            gate, os.path.join(tmp, "automation_daily.json"),
            os.path.join(tmp, "review_status.json"))
    assert not ok, "2天+2min 应判超期: " + detail
    assert "2.0 天" in detail


def test_boundary_freeze_exactly_2_days():
    """冻结起始=2天前(恰好在阈上, 严格 > 不命中) -> 不命中"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": False})
        daily = os.path.join(tmp, "automation_daily.json")
        _write(daily, {"gate_flag": {"frozen": True}})
        review = os.path.join(tmp, "review_status.json")
        _write(review, {_freeze_key(2): {"reason": "停票"}})
        ok, detail = shc.probe_p12_gate_block(gate, daily, review)
    assert ok, "冻结恰2天(非 >2)不应命中: " + detail


def test_boundary_freeze_uses_latest_key():
    """存在历史遗留 _freeze_ 旧键时取最新起始日, 不被旧键拖成假阳性"""
    with tempfile.TemporaryDirectory() as tmp:
        gate = os.path.join(tmp, "walk_forward_gate.json")
        _write(gate, {"blocked": False})
        daily = os.path.join(tmp, "automation_daily.json")
        _write(daily, {"gate_flag": {"frozen": True}})
        review = os.path.join(tmp, "review_status.json")
        _write(review, {_freeze_key(9): {"reason": "旧冻结遗留"},
                        _freeze_key(1): {"reason": "新冻结"}})
        ok, detail = shc.probe_p12_gate_block(gate, daily, review)
    assert ok, "最新冻结仅1天, 不应被 9 天前的旧键拖成命中: " + detail
