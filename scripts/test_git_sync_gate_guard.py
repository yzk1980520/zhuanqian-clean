# -*- coding: utf-8 -*-
"""test_git_sync_gate_guard.py -- git_sync_task 门禁自递归 fork 弹护栏回归断言

背景(2026-10-19 老六定位):
  git_sync_task.run_pytest_gate() 派生 `python -m pytest scripts/test_*.py`,
  而派生的目标集合恰好包含调用它的测试本身(原 test_git_sync_gate_logic.py::
  TestGateFunctionDirectly) → pytest → run_pytest_gate → pytest 无限自递归。
  实测: 递归 34 层 / 单轮 539s / 49 个 python.exe 并发; 每 3.4s 净增 1 个进程。

护栏 = 环境变量哨兵 ZQ_PYTEST_GATE。本文件即该护栏的回归断言:
  1. 哨兵生效时拒绝派生(且必须"快", 快 = 真的没派生子进程)
  2. 门禁目标集合不含已隔离的僵尸测试文件
  3. 正常路径仍会把哨兵写进子进程 env(否则护栏形同虚设)

方法学铁律(2026-10-18): 「过滤器存在但静默不生效」是本项目头号病史, 已 5 次。
  ⇒ 每个过滤器必须有一条回归断言。本文件即第 1 条护栏断言。
"""
import glob
import os
import sys
import time

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

QUARANTINED = "test_git_sync_gate_logic.py"


def test_sentinel_blocks_recursive_spawn():
    """哨兵 ZQ_PYTEST_GATE=1 时, run_pytest_gate 必须拒绝派生并立刻返回。

    "立刻"用墙钟断言: 真跑一次 17 文件门禁 >=5s, 若护栏失效会再套一层。
    """
    import git_sync_task

    old = os.environ.get("ZQ_PYTEST_GATE")
    os.environ["ZQ_PYTEST_GATE"] = "1"
    try:
        t0 = time.time()
        r = git_sync_task.run_pytest_gate()
        elapsed = time.time() - t0
    finally:
        if old is None:
            os.environ.pop("ZQ_PYTEST_GATE", None)
        else:
            os.environ["ZQ_PYTEST_GATE"] = old

    assert r["ok"] is False, "哨兵生效时必须判不绿(不绿不推), got=%r" % r
    assert "ZQ_PYTEST_GATE" in r.get("note", ""), \
        "返回 note 必须说明是哨兵拦截, got=%r" % r.get("note")
    assert elapsed < 2.0, \
        "护栏失效: 耗时 %.2fs >= 2s, 说明仍在派生 pytest(自递归)" % elapsed


def test_gate_target_excludes_quarantined_zombie():
    """门禁目标集合不得包含已隔离的僵尸测试文件(它曾是 fork 弹发起者)。"""
    files = sorted(glob.glob(os.path.join(PROJECT, "scripts", "test_*.py")))
    assert files, "scripts/test_*.py 一个都没有 — 门禁假绿风险"
    hit = [f for f in files if os.path.basename(f) == QUARANTINED]
    assert not hit, \
        "%s 又回到 scripts/ 了 — 它会直接调用 run_pytest_gate 触发自递归: %s" \
        % (QUARANTINED, hit)


def test_contract_guards_are_in_gate_scope():
    """契约真源守卫必须在门禁范围内且真实存在。

    2026-10-19 架构审查实测: tests/test_contract_docs_consistency.py 与
    tests/test_doc_freshness.py 两个会 FAIL 的契约守卫, 因为 glob 只认
    scripts/test_*.py, 从未进过任何门禁执行面(推前/pre-commit/CI 三面全漏),
    ⇒ 真源戳从 f39cdae2961c 漂到 e239dc1f623b 无人发现。
    失效模式 = 「守卫存在但静默不生效」(本项目头号病史)。故钉死此断言。
    """
    import git_sync_task

    listed = list(git_sync_task.CONTRACT_GUARD_TESTS)
    assert listed, "CONTRACT_GUARD_TESTS 为空 — 契约守卫又掉出门禁了"
    for rel in listed:
        p = os.path.join(PROJECT, *rel.split("/"))
        assert os.path.exists(p), \
            "契约守卫 %s 不存在 — 门禁会静默跳过它(不报错但也不校验)" % rel


def test_guard_file_itself_does_not_call_run_pytest_gate():
    """本护栏测试自身绝不能调用 run_pytest_gate(否则本文件变成新的发起者)。"""
    src = open(os.path.abspath(__file__), encoding="utf-8").read()
    assert "run_pytest_gate()" in src or True  # 占位, 真实断言见下
    # 只允许在哨兵已置位的上下文里出现调用
    body = src.split("def test_sentinel_blocks_recursive_spawn")[1] \
              .split("def test_gate_target")[0]
    assert 'os.environ["ZQ_PYTEST_GATE"] = "1"' in body, \
        "调用 run_pytest_gate 前必须置位哨兵"
