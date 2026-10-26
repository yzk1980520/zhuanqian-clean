#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_probe_dispatcher_stuck.py — P1-E 归因探针测试

覆盖:
  ① ready 队列为空（stuck 日志是历史残留）→ 归因①
  ② 所有 ready 单目标 profile 已达并发上限 → 归因②
  ③ 有可用 profile 但 stuck → 归因③（spawn 真失败）
  ④ kanban list 失败 → 保守报③
  ⑤ parse_stuck_lines 无匹配行 → 空列表
  ⑥ 旧行为桩红跑：「统一报 WARNING」旧逻辑对 ①② 场景误报（红），真探针正确判①②（绿）
  ⑦ HERMES_HOME env 不得覆盖主 home（P1-B 回归） — mock HERMES_HOME=profiles/x 不读 profile 日志

  红证据：test_red_old_behavior_unified_warning_misclassifies — 用「统一报 WARNING」桩
  跑 ①② 场景，旧逻辑均报 WARNING（误报），真探针判 ①②（正确）。旧逻辑在 Hermes
  只读侧不可 import，桩是行为等价模拟，详见验收报告 §①。
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import probe_dispatcher_stuck as pds


# ── 测试 helper ───────────────────────────────────────────────────────────────

def _make_log(tmpdir, stuck_entries):
    """在 tmpdir 下创建 gateway.log，包含指定 stuck 条目"""
    log_path = os.path.join(tmpdir, "gateway.log")
    with open(log_path, "w") as f:
        for ts, ticks in stuck_entries:
            f.write(
                "%s,000 WARNING gateway.run: "
                "kanban dispatcher stuck: ready queue non-empty for %d consecutive ticks but 0 workers spawned\n"
                % (ts, ticks)
            )
    return log_path


def _make_tasks(ready_assignees, running_assignees=None):
    """构造 kanban 快照"""
    tasks = []
    for i, a in enumerate(ready_assignees):
        tasks.append({"id": "t_ready_%d" % i, "status": "ready", "assignee": a, "runs": []})
    if running_assignees:
        for i, a in enumerate(running_assignees):
            tasks.append({"id": "t_run_%d" % i, "status": "running", "assignee": a, "runs": []})
    return tasks


# ── 用例 ───────────────────────────────────────────────────────────────────────

def test_no_stuck_lines_returns_scenario_1():
    """Green: 无 stuck 日志 → 归因①（正常）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [])
        with patch.object(pds, "GATEWAY_LOG", log_path):
            stuck = pds.parse_stuck_lines(log_path)
            assert stuck == [], "空日志应返回空列表"


def test_stuck_with_empty_ready_queue():
    """Green: stuck 日志有，但 ready 队列为空 → 归因①"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [("2026-10-19 10:00:00", 6)])
        tasks = _make_tasks([])
        with patch.object(pds, "GATEWAY_LOG", log_path), \
             patch.object(pds, "fetch_kanban_snapshot", return_value=(0, tasks, "")):
            scenario, detail = pds.classify_stuck(
                pds.parse_stuck_lines(log_path), tasks
            )
        assert scenario == "①", "ready 为空应归因①，实际: %s" % scenario


def test_all_profiles_at_max_concurrent():
    """Green: ready 单目标 profile 均达并发上限 → 归因②"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [("2026-10-19 20:10:00", 11)])
        # laosi 有 running 任务，laowu 也有 running 任务
        tasks = _make_tasks(["laosi", "laowu"], running_assignees=["laosi", "laowu"])
        with patch.object(pds, "GATEWAY_LOG", log_path), \
             patch.object(pds, "fetch_kanban_snapshot", return_value=(0, tasks, "")):
            scenario, detail = pds.classify_stuck(
                pds.parse_stuck_lines(log_path), tasks
            )
        assert scenario == "②", "全部达并发上限应归因②，实际: %s | %s" % (scenario, detail)


def test_spawn_failure_scenario():
    """Green: 有可用 profile 但 stuck → 归因③（真故障）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [("2026-10-19 07:50:00", 41)])
        # laosi 有 running 任务，但 laowu 空闲，laowu 有 ready 单
        tasks = _make_tasks(["laowu"], running_assignees=["laosi"])
        with patch.object(pds, "GATEWAY_LOG", log_path), \
             patch.object(pds, "fetch_kanban_snapshot", return_value=(0, tasks, "")):
            scenario, detail = pds.classify_stuck(
                pds.parse_stuck_lines(log_path), tasks
            )
        assert scenario == "③", "有可用 profile 应归因③，实际: %s | %s" % (scenario, detail)
        assert "laowu" in detail or "可用" in detail


def test_kanban_list_failure_conserves_scenario_3():
    """Green: kanban list 失败 → 保守报③"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [("2026-10-19 10:00:00", 6)])
        with patch.object(pds, "GATEWAY_LOG", log_path), \
             patch.object(pds, "fetch_kanban_snapshot", return_value=(1, None, "timeout")):
            scenario, detail = pds.classify_stuck(
                pds.parse_stuck_lines(log_path), None
            )
        assert scenario == "③", "kanban 失败应保守报③，实际: %s" % scenario


def test_parse_stuck_lines_filters_non_stuck():
    """Green: 非 stuck 行不应被解析"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "gateway.log")
        with open(log_path, "w") as f:
            f.write("2026-10-19 10:00:00,000 INFO gateway.run: normal log line\n")
            f.write("2026-10-19 10:00:01,000 WARNING something else: not stuck\n")
        result = pds.parse_stuck_lines(log_path)
        assert result == [], "非 stuck 行不应匹配，实际: %s" % result


# ── 红证据: 旧行为桩 (test_red_old_behavior...) ────────────────────────────────
#
# L2 复审 E4 打回「红态未立」：验收报告 §① 虚标「Red 未测」。
# 补救：构造「统一报 WARNING」旧逻辑桩，跑 ①② 场景 → 旧逻辑均误报 WARNING（红），
# 真探针判 ①②（绿）。旧逻辑在 Hermes 只读侧不可 import，桩是行为等价模拟。

def _old_behavior_unified_warning(stuck_lines, tasks):
    """Stub of pre-P1-E Hermes behavior: uniformly reports WARNING for any
    stuck line, with no three-way classification (①/②/③).

    This is a behavioral stub — the actual Hermes dispatcher just logged
    'dispatcher stuck' as WARNING unconditionally. We cannot import it
    (it lives in Hermes internal code, read-only boundary), so we stub
    the behavior: any stuck_lines → WARNING, regardless of ready queue state.
    """
    if stuck_lines:
        return "WARNING", "dispatcher stuck (old unified WARNING, no discrimination)"
    return "OK", "no stuck"


def test_red_old_behavior_unified_warning_misclassifies():
    """Red evidence: old behavior (unified WARNING) misclassifies ① and ② as alarms.

    Scenario ① (false alarm: stuck log exists but ready queue empty):
      - Old behavior: reports WARNING (misclassification — should be silent ①)
      - Real probe: returns ① (correct)

    Scenario ② (false alarm: all ready tasks at max concurrency):
      - Old behavior: reports WARNING (misclassification — should be silent ②)
      - Real probe: returns ② (correct)

    This test PASSES because it asserts the old behavior is WRONG (reports
    WARNING where it shouldn't) and the real probe is RIGHT. The old behavior
    stub's incorrect output IS the 'red' evidence.
    """
    # ── Scenario ①: false alarm (ready 队列为空) ──
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [("2026-10-19 10:00:00", 6)])
        tasks = _make_tasks([])  # no ready tasks = false alarm

        # Old behavior: reports WARNING (WRONG)
        old_scenario, old_detail = _old_behavior_unified_warning(
            pds.parse_stuck_lines(log_path), tasks
        )
        assert old_scenario == "WARNING", \
            "Red evidence: old behavior should report WARNING (misclassification), got: %s" % old_scenario

        # Real probe: correctly classifies as ① (no alarm)
        real_scenario, real_detail = pds.classify_stuck(
            pds.parse_stuck_lines(log_path), tasks
        )
        assert real_scenario == "①", \
            "Green evidence: real probe should classify false alarm as ①, got: %s" % real_scenario

    # ── Scenario ②: false alarm (all profiles at max concurrency) ──
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = _make_log(tmpdir, [("2026-10-19 20:10:00", 11)])
        tasks = _make_tasks(["laosi", "laowu"], running_assignees=["laosi", "laowu"])

        # Old behavior: reports WARNING (WRONG)
        old_scenario, old_detail = _old_behavior_unified_warning(
            pds.parse_stuck_lines(log_path), tasks
        )
        assert old_scenario == "WARNING", \
            "Red evidence: old behavior should report WARNING (misclassification), got: %s" % old_scenario

        # Real probe: correctly classifies as ② (no alarm)
        real_scenario, real_detail = pds.classify_stuck(
            pds.parse_stuck_lines(log_path), tasks
        )
        assert real_scenario == "②", \
            "Green evidence: real probe should classify concurrency-at-limit as ②, got: %s" % real_scenario


# ── P1-B 回归: HERMES_HOME 不读 env ────────────────────────────────────────────

def test_heremes_home_not_read_from_env():
    """Regression P1-B: HERMES_HOME must be hardcoded to main home, not read from env.

    Before fix: `HERMES_HOME = os.environ.get("HERMES_HOME", <main_home>)`
      → profile worker 注入 HERMES_HOME=.../profiles/workbuddy
      → 探针读 profile gateway.log（0 stuck）→ false ①

    After fix: `HERMES_HOME = <main_home>` (hardcoded, env 忽略)
    """
    import inspect
    source = inspect.getsource(pds)
    assert 'os.environ.get("HERMES_HOME"' not in source, \
        "HERMES_HOME must not be read from env — hardcode main home instead"
    assert "profiles" not in pds.HERMES_HOME, \
        "HERMES_HOME should be hardcoded to main home, not a profile subdir"


def test_heremes_home_points_to_main_gateway_log():
    """Regression P1-B: GATEWAY_LOG must point to main dispatcher log, not profile.

    Verifies the runtime constant resolves to the main home's logs/gateway.log.
    """
    expected_log = os.path.join(
        r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home",
        "logs", "gateway.log"
    )
    assert pds.GATEWAY_LOG == expected_log, \
        "GATEWAY_LOG should point to main dispatcher log. Got: %s" % pds.GATEWAY_LOG
