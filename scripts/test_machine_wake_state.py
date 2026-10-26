#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""machine_wake_state.py 单测 (t_51e04b30 B案, 2026-10-20 老三)

覆盖:
  1. OR 语义守卫(老六会签①): 仅单源命中必须判清醒 — 防改回 AND(漏报真 P0)
  2. 双源均未命中 = 休眠; 双源不可用 = available=False(消费方 fail-safe 照报)
  3. just_woken 窗口判定(第5态输入)
  4. last_wake_time 时间戳解析(GB 文化 ISO 输出) / 查询失败不可用
全部注入/monkeypatch, 不碰真实事件日志与 API(除 guard_semantics 纯函数)。
"""
import datetime as _dt
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import machine_wake_state as mws

BASE = _dt.datetime(2026, 10, 20, 12, 0, 0)


# ---------------------------------------------------------------- OR 语义守卫
def test_guard_semantics_builtin():
    mws.guard_semantics()  # 模块内置断言(防改回 AND), 直接跑


def test_or_single_input_source_hit_is_awake():
    st = mws.get_wake_state(last_input=BASE - _dt.timedelta(minutes=5),
                            last_wake=None, now=BASE)
    assert st["awake"] is True, "仅输入源命中必须判清醒(OR 语义)"
    assert st["just_woken"] is False


def test_or_single_wake_source_hit_is_awake():
    st = mws.get_wake_state(last_input=None,
                            last_wake=BASE - _dt.timedelta(minutes=5), now=BASE)
    assert st["awake"] is True, "仅唤醒源命中必须判清醒(OR 语义)"
    assert st["just_woken"] is True


def test_both_sources_miss_is_asleep():
    st = mws.get_wake_state(last_input=BASE - _dt.timedelta(minutes=120),
                            last_wake=BASE - _dt.timedelta(minutes=120), now=BASE)
    assert st["awake"] is False and st["just_woken"] is False
    assert st["available"] is True


def test_both_sources_unavailable_flags_unavailable():
    st = mws.get_wake_state(last_input=None, last_wake=None, now=BASE)
    assert st["awake"] is False
    assert st["available"] is False, "双源不可用必须显式标记, 消费方按 fail-safe 保守照报"


def test_just_woken_window_boundary():
    assert mws.get_wake_state(last_wake=BASE - _dt.timedelta(minutes=14), now=BASE)["just_woken"] is True
    assert mws.get_wake_state(last_wake=BASE - _dt.timedelta(minutes=16), now=BASE)["just_woken"] is False
    assert mws.get_wake_state(last_wake=BASE - _dt.timedelta(minutes=29), now=BASE)["just_woken"] is False


def test_input_source_not_unavailable_never_counts_as_asleep_evidence():
    """输入源不可用(None)不得当'休眠'证据: 仅唤醒源命中时 available 仍为 True"""
    st = mws.get_wake_state(last_input=None,
                            last_wake=BASE - _dt.timedelta(minutes=60), now=BASE)
    assert st["available"] is True and st["awake"] is False


# ---------------------------------------------------------------- last_wake_time 解析
def test_last_wake_time_parses_iso_output(monkeypatch):
    fake = types.SimpleNamespace(
        stdout="2026-10-19 23:58:01\r\n".encode("gbk"), stderr=b"", returncode=0)
    monkeypatch.setattr(mws.subprocess, "run", lambda *a, **k: fake)
    assert mws.last_wake_time(now=BASE) == _dt.datetime(2026, 10, 19, 23, 58, 1)


def test_last_wake_time_future_event_rolls_back_year(monkeypatch):
    fake = types.SimpleNamespace(
        stdout="2027-01-01 00:00:00\r\n".encode("gbk"), stderr=b"", returncode=0)
    monkeypatch.setattr(mws.subprocess, "run", lambda *a, **k: fake)
    assert mws.last_wake_time(now=BASE) == _dt.datetime(2026, 1, 1, 0, 0, 0)


def test_last_wake_time_query_failure_is_unavailable(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=30)
    monkeypatch.setattr(mws.subprocess, "run", boom)
    assert mws.last_wake_time(now=BASE) is None
