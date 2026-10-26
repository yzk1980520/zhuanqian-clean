#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_heal P-01/P-02 机器清醒判定矩阵单测 (t_51e04b30 B案, 2026-10-20 老三)

验收矩阵(四态 + 老六会签②第5态, 先红后绿):
  S1 清醒 × stale   -> P0 照报 (rc=2, P0 告警)
  S2 休眠 × stale   -> 降级 INFO + 台账 GAP-003 (rc!=2, 无 P0 告警, 台账登记)
  S3 刚醒 × stale整体在休眠窗内 -> 复检不升 P0 (第5态, 防每次唤醒误报风暴)
  S4 刚醒 × stale在唤醒后发生   -> P0 照报 (stale 与休眠无关, 漏报防线)
  S5 双源全不可用            -> fail-safe P0 照报
  S6 P-02 任务级活性同矩阵(休眠降级)
  S7 卫生项 __pycache__/ 白名单 (gitignored 构建产物不算红项)
全 monkeypatch + tempfile, schtasks/网络/双源 API 全 stub, 零碰生产 data/。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import self_heal_check as shc


# ---------------------------------------------------------------- 环境桩(同 test_self_heal_recheck.py 口径)
_PATH_ATTRS = ("DATA", "REPAIR_LOG", "STATE_FILE", "WEBHOOK_PROBE_STATE",
               "DATASRC_PROBE_STATE", "DRAIN_STATE", "GITSYNC_STATE",
               "FRESHNESS_LOG", "FEISHU_CFG", "ALERT_STATE_FILE",
               "REPAIR_STATE_FILE", "KNOWN_GAPS")
_STUB_PROBES = ("probe_p03_gitsync", "probe_p04_remote",
                "probe_p05_feishu_api", "probe_p06_webhook", "probe_p07_hygiene",
                "probe_p08_config_dead", "probe_p09_datasrc", "probe_p10_dead_deploy",
                "probe_p11_backup_bloat", "probe_p12_gate_block")


def _hermetic(monkeypatch, tmp, drain_last_run=None, p02_fail=False):
    for attr in _PATH_ATTRS:
        if hasattr(shc, attr):  # KNOWN_GAPS 等新字段旧版模块无, 红态对照时跳过
            monkeypatch.setattr(shc, attr, os.path.join(tmp, os.path.basename(str(getattr(shc, attr)))))
    for attr in _STUB_PROBES:
        monkeypatch.setattr(shc, attr, lambda: (True, "stub-ok"))
    if drain_last_run is not None:
        with open(os.path.join(tmp, "drain_state.json"), "w", encoding="utf-8") as f:
            json.dump({"last_run": drain_last_run, "consec_fail": 0, "last_remaining": 0}, f)
    monkeypatch.setattr(shc, "probe_p01_drain",
                       lambda: (True, "stub-fresh") if drain_last_run == "FRESH"
                       else (False, "drain last_run 龄 90min ≥15min"))
    monkeypatch.setattr(shc, "probe_p02_task_liveness",
                       lambda: (False, "stub-p02-stale") if p02_fail else (True, "stub-ok"))
    monkeypatch.setattr(shc, "repair_r01_drain", lambda: False)
    monkeypatch.setattr(shc, "repair_r02_tasks", lambda d: False)
    monkeypatch.setattr(shc.time, "sleep", lambda *_: None)
    alerts = []
    monkeypatch.setattr(shc, "alert", lambda text, level="P1": alerts.append((level, text)))
    monkeypatch.setattr(sys, "argv", ["self_heal_check.py"])
    return alerts


def _wake(**kw):
    d = {"available": True, "awake": False, "just_woken": False,
         "last_input": None, "last_wake": None,
         "input_age_min": None, "wake_age_min": None, "reasons": []}
    d.update(kw)
    return d


def _patch_probe(monkeypatch, wake_or_exc):
    if not hasattr(shc, "machine_wake_state"):  # 旧版无矩阵: 不 patch, 让行为差异自己红
        return
    if isinstance(wake_or_exc, Exception):
        def boom():
            raise wake_or_exc
        monkeypatch.setattr(shc.machine_wake_state, "probe_wake_state", boom)
    else:
        monkeypatch.setattr(shc.machine_wake_state, "probe_wake_state", lambda: wake_or_exc)


def _rc_and_state(tmp):
    with open(os.path.join(tmp, "self_heal_state.json"), encoding="utf-8") as f:
        return json.load(f)["results"]


# ---------------------------------------------------------------- S1 清醒 × stale -> P0
def test_s1_awake_stale_still_p0(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="2026-10-20T01:00:00")
        _patch_probe(monkeypatch, _wake(awake=True, just_woken=False,
                                       last_input="2026-10-20T04:10:00",
                                       input_age_min=5.0, reasons=["input<30min"]))
        rc = shc.main()
        results = _rc_and_state(tmp)
    assert rc == 2, "机器清醒且 drain stale 必须照报 P0 (rc=2), 实际 rc=%s" % rc
    assert any(lvl == "P0" for lvl, _ in alerts)
    assert "downgraded" not in results.get("P-01", {}), "清醒态不得降级"


# ---------------------------------------------------------------- S2 休眠 × stale -> 降级 INFO + 台账
def test_s2_asleep_stale_downgraded_info(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="2026-10-20T01:00:00")
        _patch_probe(monkeypatch, _wake(awake=False, just_woken=False,
                                        input_age_min=180.0, wake_age_min=180.0,
                                        reasons=["no-recent-input", "no-recent-wake"]))
        rc = shc.main()
        results = _rc_and_state(tmp)
        led = json.load(open(os.path.join(tmp, "known_gaps.json"), encoding="utf-8"))
        assert rc != 2, "机器休眠窗 drain stale 属按设计静默, 不得升 P0, 实际 rc=%s" % rc
        assert not any(lvl == "P0" for lvl, _ in alerts), "休眠窗不得发 P0 告警"
        assert results["P-01"].get("downgraded", {}).get("gap") == "GAP-003"
        # 台账 GAP-003 登记(铁律#12 写侧, tmp 内读取)
        g3 = next(g for g in led["gaps"] if g["gap_id"] == "GAP-003")
    assert g3["downgrade_count"] == 1 and g3["last_downgrade_rule"] == "P-01"
    assert g3["recovery_assertion"]["consumer"].startswith("self_audit")


# ---------------------------------------------------------------- S3 刚醒 × stale整体在休眠窗内 -> 不升 P0 (第5态)
def test_s3_just_woken_stale_in_sleep_window_no_p0(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="2026-10-19T22:30:00")
        _patch_probe(monkeypatch, _wake(awake=True, just_woken=True,
                                        last_wake="2026-10-20T01:14:00", wake_age_min=2.0,
                                        reasons=["wake<15min"]))
        rc = shc.main()
        results = _rc_and_state(tmp)
    assert rc != 2, "第5态: stale 整体在休眠窗内+刚醒, 复检不得报 P0, 实际 rc=%s" % rc
    assert not any(lvl == "P0" for lvl, _ in alerts)
    assert "第5态" in results["P-01"]["downgraded"]["reason"]


# ---------------------------------------------------------------- S4 刚醒 × stale发生在唤醒后 -> P0
def test_s4_just_woken_stale_after_wake_still_p0(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="2026-10-20T01:10:00")
        _patch_probe(monkeypatch, _wake(awake=True, just_woken=False,
                                        last_input="2026-10-20T04:12:00", input_age_min=2.0,
                                        last_wake="2026-10-20T00:30:00", wake_age_min=44.0,
                                        reasons=["input<30min"]))
        rc = shc.main()
        results = _rc_and_state(tmp)
    assert rc == 2, "stale 发生在唤醒之后(与休眠无关)必须照报 P0, 实际 rc=%s" % rc
    assert "downgraded" not in results.get("P-01", {})


# ---------------------------------------------------------------- S5 双源全不可用 -> fail-safe P0
def test_s5_sources_unavailable_failsafe_p0(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="2026-10-20T01:00:00")
        _patch_probe(monkeypatch, _wake(available=False, awake=False))
        rc = shc.main()
    assert rc == 2, "双源不可用=不可证明休眠, 必须 fail-safe 照报 P0, 实际 rc=%s" % rc
    assert any(lvl == "P0" for lvl, _ in alerts)


def test_s5b_probe_exception_failsafe_p0(monkeypatch):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="2026-10-20T01:00:00")
        _patch_probe(monkeypatch, RuntimeError("stub-dual-source-boom"))
        rc = shc.main()
    assert rc == 2, "双源探测异常不得静默降级(异常吞噬=P0 缺陷), 实际 rc=%s" % rc


# ---------------------------------------------------------------- S6 P-02 同矩阵
def test_s6_p02_asleep_downgraded(monkeypatch):
    import tempfile
    stale_ts = "2026-10-19T22:45:00"
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="FRESH", p02_fail=True)
        if hasattr(shc, "p02_stale_ts_list"):  # 旧版无该函数: 跳过, 让 P0 行为差异自己红
            monkeypatch.setattr(shc, "p02_stale_ts_list", lambda: [stale_ts, stale_ts])
        _patch_probe(monkeypatch, _wake(awake=False, just_woken=False,
                                        input_age_min=200.0, wake_age_min=200.0))
        rc = shc.main()
        results = _rc_and_state(tmp)
    assert rc != 2, "P-02 休眠窗降级同矩阵, 实际 rc=%s" % rc
    assert results["P-02"].get("downgraded", {}).get("gap") == "GAP-003"


def test_s6b_p02_just_woken_in_sleep_window_downgraded(monkeypatch):
    import tempfile
    stale_ts = "2026-10-19T22:45:00"
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="FRESH", p02_fail=True)
        if hasattr(shc, "p02_stale_ts_list"):  # 旧版无该函数: 跳过, 让 P0 行为差异自己红
            monkeypatch.setattr(shc, "p02_stale_ts_list", lambda: [stale_ts, stale_ts])
        _patch_probe(monkeypatch, _wake(awake=True, just_woken=True,
                                        last_wake="2026-10-20T01:14:00", wake_age_min=2.0))
        rc = shc.main()
        results = _rc_and_state(tmp)
    assert rc != 2, "P-02 第5态: 全部 stale ts 早于最近唤醒, 不得升 P0, 实际 rc=%s" % rc
    assert "P-02" in results["P-02"]["downgraded"]["reason"] or \
        "休眠窗" in results["P-02"]["downgraded"]["reason"]


def test_s6c_p02_none_ts_cannot_prove_sleep_window(monkeypatch):
    """P-02 任一任务无 last_run 记录(None) 无法证明在休眠窗内 -> 第5态不命中, 走①/④"""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic(monkeypatch, tmp, drain_last_run="FRESH", p02_fail=True)
        if hasattr(shc, "p02_stale_ts_list"):
            monkeypatch.setattr(shc, "p02_stale_ts_list", lambda: [None, "2026-10-19T22:45:00"])
        _patch_probe(monkeypatch, _wake(awake=False, just_woken=False,
                                        last_wake="2026-10-20T01:14:00",
                                        input_age_min=200.0, wake_age_min=200.0))
        # just_woken=False(wake_age 200min) -> 第5态不命中; 双源未命中 -> ④ 休眠降级
        rc = shc.main()
        results = _rc_and_state(tmp)
    # ④ 休眠判定 -> 仍降级(INFO), 但 reason 不得是"第5态"
    assert "downgraded" in results["P-02"]
    assert "第5态" not in results["P-02"]["downgraded"]["reason"]


# ---------------------------------------------------------------- S7 卫生项 __pycache__ 白名单
def test_p07_pycache_whitelisted(monkeypatch):
    """验收矩阵第5条: P-07 卫生检查白名单 __pycache__/ (gitignored 构建产物不算红项)"""
    import tempfile
    with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as data:
        monkeypatch.setattr(shc, "PROJECT", proj)
        monkeypatch.setattr(shc, "DATA", data)
        os.makedirs(os.path.join(proj, "__pycache__"))
        with open(os.path.join(proj, ".coverage"), "w") as f:
            f.write("x")
        ok, detail = shc.probe_p07_hygiene()
        assert ok is False and ".coverage" in detail, "真红项 .coverage 必须报红"
        assert "__pycache__" not in detail, "__pycache__ 是 gitignored 构建产物, 不得算卫生红项"
    with tempfile.TemporaryDirectory() as proj, tempfile.TemporaryDirectory() as data:
        monkeypatch.setattr(shc, "PROJECT", proj)
        monkeypatch.setattr(shc, "DATA", data)
        os.makedirs(os.path.join(proj, "__pycache__"))
        ok, detail = shc.probe_p07_hygiene()
        assert ok is True, "仅 __pycache__ 存在时必须判卫生良好"
        assert "卫生良好" in detail
