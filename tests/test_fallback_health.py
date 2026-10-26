# -*- coding: utf-8 -*-
"""
tests/test_fallback_health.py — fallback 健康探测单元测试（老四，2026-10-14 P2修复）
================================================================================
覆盖:
  ①probe: 配置不完整 → False
  ②probe: 环境变量缺失 → False
  ③_should_alert: 首次 True / 冷却期内 False（去重）
  ④_should_alert: 冷却过期后 True
  ⑤load_fallback: 从 config.yaml 读到 base_url/model
  ⑥告警写入格式正确（alert_log.jsonl 单行 JSON）
seam: 用 monkeypatch 隔离，不真发网络请求、不碰真实 data/。
"""
import json
import sys
import time
from pathlib import Path

import pytest

PROJ = Path(r"D:\open code\zhuanqian")
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "scripts"))

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "fbh", PROJ / "scripts" / "fallback_health_check.py")
fbh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fbh)


# ── ① probe: 配置不完整 ──
def test_probe_incomplete_config():
    ok, detail = fbh.probe({})
    assert ok is False
    assert "不完整" in detail


# ── ② probe: 环境变量缺失 ──
def test_probe_missing_env(monkeypatch):
    monkeypatch.delenv("__NONEXIST_ENV__", raising=False)
    ok, detail = fbh.probe({"base_url": "https://x.com/v1", "model": "m",
                            "api_key_env": "__NONEXIST_ENV__"})
    assert ok is False
    assert "缺失" in detail


# ── ③ _should_alert: 首次 True / 冷却期内 False ──
def test_should_alert_dedup(tmp_path, monkeypatch):
    cooldown = tmp_path / "cooldown.json"
    monkeypatch.setattr(fbh, "COOLDOWN_FILE", cooldown)
    fp = "fp_test_1"
    assert fbh._should_alert(fp) is True     # 首次应告警
    assert fbh._should_alert(fp) is False    # 冷却期内不重复


# ── ④ _should_alert: 冷却过期后 True ──
def test_should_alert_after_cooldown(tmp_path, monkeypatch):
    cooldown = tmp_path / "cooldown.json"
    monkeypatch.setattr(fbh, "COOLDOWN_FILE", cooldown)
    monkeypatch.setattr(fbh, "ALERT_COOLDOWN_HOURS", 0)  # 冷却=0 立即过期
    fp = "fp_test_2"
    assert fbh._should_alert(fp) is True
    assert fbh._should_alert(fp) is True     # 冷却为0，可再次告警


# ── ⑤ load_fallback: 读到关键字段 ──
def test_load_fallback():
    fb = fbh.load_fallback()
    assert isinstance(fb, dict)
    assert fb.get("base_url"), "fallback base_url 缺失"
    assert fb.get("model"), "fallback model 缺失"


# ── ⑥ 告警写入格式正确 ──
def test_log_alert_format(tmp_path, monkeypatch):
    alert = tmp_path / "alert_log.jsonl"
    monkeypatch.setattr(fbh, "ALERT_LOG", alert)
    fbh._log_alert("P1", "test message", "test_source")
    lines = alert.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["level"] == "P1"
    assert entry["source"] == "test_source"
    assert entry["message"] == "test message"
    assert "timestamp" in entry
