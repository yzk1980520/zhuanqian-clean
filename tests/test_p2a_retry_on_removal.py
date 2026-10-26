# -*- coding: utf-8 -*-
"""P2-a TDD: cron_config.json sanity_gate retry_on 配置脱节删除验证。

老五 exit(2) 裁决坐实:
  - scheduler_script.py:527 对所有非零 exit 统一走失败路径, 无 exit(2) 专属分支
  - cron_config.json `retry_on=[2]` 仅配置声明, 代码无消费方
  - factor_ic_daily_monitor.py 实际只 sys.exit(0/1), 从不 exit(2)
  - run_sanity_gate_cron.py:188 `return 2` 真实可达, 但调度器**不做重试**
  → retry_on=[2] 是"配置声明行为, 实现从不触发"的假绿同类, 删。

seam: cron_config.json sanity_gate block → 全库 Python 无代码读 retry_on/gate_semantics
方向: 删 retry_on key + 修正 gate_semantics 中"可重试"假断言 (同源假绿)
影响面: 3 消费方(next_steps_executor/sched_reconcile) 均不读 retry_on (0 命中坐实)
"""
import json
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
CRON_CONFIG = PROJECT / "cron_config.json"


def test_p2a_retry_on_key_removed():
    """retry_on 已从 cron_config.json 中删除 (无消费方, 纯配置声明)。"""
    d = json.loads(CRON_CONFIG.read_text(encoding="utf-8-sig"))
    # sanity_gate block 不应再有 retry_on
    sg = _find_block(d, "sanity_gate")
    assert sg is not None, "sanity_gate block 缺失"
    assert "retry_on" not in sg, (
        f"P2-a 未落地: sanity_gate.retry_on={sg.get('retry_on')} 仍存在 "
        "(全库 0 消费方, 配置声明无实现, 假绿同类)"
    )


def test_p2a_gate_semantics_no_false_retry_claim():
    """gate_semantics 不再暗示 exit 2 会被重试 (假绿语义清除)。"""
    d = json.loads(CRON_CONFIG.read_text(encoding="utf-8-sig"))
    sg = _find_block(d, "sanity_gate")
    semantics = sg.get("gate_semantics", "")
    # 原: "exit 2=内部错误(可重试)" → 修正: "exit 2=内部错误(调度器统一走失败路径,无重试)"
    assert "可重试" not in semantics, (
        f"gate_semantics 仍暗示 retry 语义: {semantics!r} (假绿)"
    )
    # 实际调度器行为描述应正确 (无 retry)
    # 不硬断言具体文字, 只断言"无假绿"


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): 全库 grep 子进程(实测 19.20s) → 门禁快档排除
def test_p2a_consume_side_zero():
    """全库 Python 生产代码无 retry_on 读取 (回归保护, 证明删除安全)。

    排除: .venv (第三方同名) + 本测试文件自身 (自带 'retry_on' 字面量, 防自指)。
    """
    import subprocess
    r = subprocess.run(
        ["grep", "-rln", "retry_on", "--include=*.py", str(PROJECT)],
        capture_output=True, text=True
    )
    hits = [f for f in r.stdout.strip().split("\n")
            if f and ".venv" not in f and "test_p2a_retry_on_removal" not in f]
    assert not hits, (
        f"P2-a 删除后仍有生产代码读 retry_on: {hits} "
        "(若新增消费方, 需重新评估是否该补实现)"
    )


def _find_block(o, key):
    """递归找 key 在 dict 里 (sanity_gate 在 events 下或根下)。"""
    if isinstance(o, dict):
        if key in o:
            return o[key]
        for v in o.values():
            r = _find_block(v, key)
            if r is not None:
                return r
    return None
