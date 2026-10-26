#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""self_heal_check main() P0 复检路径测试 (2026-10-20 修 r[1]->r[2] bug)

背景: 复检行 dict((r[0], r[1]) for r in rules)[rid]() 误取 r[1](规则名, str)当函数调
用 -> TypeError 被裸 except 吞 -> 复检从未真正跑过(校验存在但静默不生效)。

覆盖:
  1. 复检真的会跑: P-01 首检失败 -> 复检时探针被再次真实调用且返回值落进 state
  2. except 可见性 + 控制流不变: 复检时探针抛异常 -> stderr 带类型与摘要,
     该 rid 仍判 still_bad -> P0 升级, 与修复前控制流一致
全部 monkeypatch + tempfile; schtasks/网络/修复动作/告警发送全部 stub, 零碰生产 data/。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import self_heal_check as shc

# ---------------------------------------------------------------- 环境桩
_PATH_ATTRS = ("DATA", "REPAIR_LOG", "STATE_FILE", "WEBHOOK_PROBE_STATE",
               "DATASRC_PROBE_STATE", "DRAIN_STATE", "GITSYNC_STATE",
               "FRESHNESS_LOG", "FEISHU_CFG", "ALERT_STATE_FILE",
               "REPAIR_STATE_FILE")
_STUB_PROBES = ("probe_p02_task_liveness", "probe_p03_gitsync", "probe_p04_remote",
                "probe_p05_feishu_api", "probe_p06_webhook", "probe_p07_hygiene",
                "probe_p08_config_dead", "probe_p09_datasrc", "probe_p10_dead_deploy",
                "probe_p11_backup_bloat", "probe_p12_gate_block")


def _hermetic_env(monkeypatch, tmp):
    """重定向所有状态文件到 tmp, stub 掉 schtasks/网络探测, 防碰生产 data/"""
    for attr in _PATH_ATTRS:
        monkeypatch.setattr(shc, attr, os.path.join(tmp, os.path.basename(str(getattr(shc, attr)))))
    for attr in _STUB_PROBES:
        monkeypatch.setattr(shc, attr, lambda: (True, "stub-ok"))
    monkeypatch.setattr(shc, "repair_r01_drain", lambda: False)  # repairs=0 -> 无45s等待/无/Run
    monkeypatch.setattr(shc.time, "sleep", lambda *_: None)
    alerts = []
    monkeypatch.setattr(shc, "alert", lambda text, level="P1": alerts.append((level, text)))
    monkeypatch.setattr(sys, "argv", ["self_heal_check.py"])  # 非 dry-run(复检要求 not DRY_RUN)
    return alerts


def _state_results(tmp):
    with open(os.path.join(tmp, "self_heal_state.json"), encoding="utf-8") as f:
        return json.load(f)["results"]


# ---------------------------------------------------------------- 场景 1: 复检真的会跑
def test_recheck_actually_invokes_probe(monkeypatch):
    """P-01 首检失败 -> 复检再次真实调用探针 -> 返回值落进 state; main 返回 0 不升 P0"""
    calls = []

    def fake_p01():
        calls.append(1)
        return (False, "stub-initial-fail") if len(calls) == 1 else (True, "stub-recovered")

    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic_env(monkeypatch, tmp)
        monkeypatch.setattr(shc, "probe_p01_drain", fake_p01)
        rc = shc.main()
        results = _state_results(tmp)

    assert len(calls) == 2, "探针应被调用两次: 首检 + 复检, 实际 %d 次" % len(calls)
    # 复检结果必须是探针真实返回值(ok=True/detail=stub-recovered), 而非异常痕迹
    assert results["P-01"]["recheck"] == {"ok": True, "detail": "stub-recovered"}, \
        "复检未落探针真实返回值: %r" % results["P-01"].get("recheck")
    assert rc == 0 and not alerts, "复检恢复后不应升 P0: rc=%s alerts=%r" % (rc, alerts)


def test_recheck_records_real_failure_value(monkeypatch):
    """复检时探针仍失败 -> 记录真实失败值 -> 升 P0 返回 2(控制流与修复前一致)"""
    calls = []

    def fake_p01():
        calls.append(1)
        return (False, "stub-still-bad-round-%d" % len(calls))

    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic_env(monkeypatch, tmp)
        monkeypatch.setattr(shc, "probe_p01_drain", fake_p01)
        rc = shc.main()
        results = _state_results(tmp)

    assert len(calls) == 2
    assert results["P-01"]["recheck"] == {"ok": False, "detail": "stub-still-bad-round-2"}
    assert rc == 2 and len(alerts) == 1 and alerts[0][0] == "P0"


# ---------------------------------------------------------------- 场景 2: except 可见性
def test_recheck_except_visible_and_flow_unchanged(monkeypatch, capsys):
    """复检时探针抛异常 -> stderr 带类型与摘要(不再静默); rid 仍 still_bad -> P0 返回 2"""
    calls = []

    def fake_p01():
        calls.append(1)
        if len(calls) == 1:
            return False, "stub-initial-fail"
        raise ValueError("stub-recheck-boom")

    with tempfile.TemporaryDirectory() as tmp:
        alerts = _hermetic_env(monkeypatch, tmp)
        monkeypatch.setattr(shc, "probe_p01_drain", fake_p01)
        rc = shc.main()
        results = _state_results(tmp)

    err = capsys.readouterr().err
    assert "CR-01(recheck)" in err and "ValueError" in err and "stub-recheck-boom" in err, \
        "复检 except 必须带类型与摘要: %r" % err
    assert "recheck" not in results["P-01"], "异常 rid 不应有 recheck 记录"
    assert rc == 2 and len(alerts) == 1, "异常应维持 still_bad -> P0: rc=%s" % rc
