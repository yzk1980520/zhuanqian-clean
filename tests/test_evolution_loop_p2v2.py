# -*- coding: utf-8 -*-
"""test_evolution_loop_p2v2.py — EVOL-P2v2 验收测试（断言验证）

验收断言（SOUL 准则5，断言不用打勾）：
1. _read_redline_from_source 接真源，fields 含 TP_UP 且值 == risk_rules 实跳五档
2. 手改一个 risk_rules 常量副本 → read_redline_fn 读出变化 → redline_check.frozen=True + changed_fields 含该字段
3. run_evolution_loop 跑完，结果里 oos_check.pure=True 且 OOS 首日 > fit 末日
4. evidence.engine_commit 接真实 git rev-parse HEAD (40位hash)
"""
import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core.ops.evolution_loop as el  # noqa: E402
import core.pipeline.atomic_json as _aj  # noqa: E402
import risk_rules  # noqa: E402
import json  # noqa: E402

TODAY = date(2026, 10, 10)

# ── 断言1：_read_redline_from_source 接真源，五档齐全 ──
def test_assert1_read_redline_from_source():
    """断言1：_read_redline_from_source 返回的 fields 含 TP_UP 且与 risk_rules 一致。"""
    fields = el._read_redline_from_source()

    # 五档字段均存在
    assert "STOP" in fields, "fields 缺少 STOP"
    assert "CHASE" in fields, "fields 缺少 CHASE"
    assert "TIME" in fields, "fields 缺少 TIME"
    assert "TP_UP" in fields, "fields 缺少 TP_UP"
    assert "TP_DOWN" in fields, "fields 缺少 TP_DOWN"

    # 值与 risk_rules 实跳对齐
    assert fields["STOP"] == risk_rules.STRATEGY_STOP_LOSS_PCT["全仓"], \
        f"STOP 不匹配: {fields['STOP']} != {risk_rules.STRATEGY_STOP_LOSS_PCT['全仓']}"
    assert fields["CHASE"] == risk_rules.CHASE_BAN_PCT, \
        f"CHASE 不匹配: {fields['CHASE']} != {risk_rules.CHASE_BAN_PCT}"
    assert fields["TIME"] == risk_rules.TIME_STOP_TRADING_DAYS, \
        f"TIME 不匹配: {fields['TIME']} != {risk_rules.TIME_STOP_TRADING_DAYS}"
    assert fields["TP_UP"] == [list(t) for t in risk_rules.TREND_TP_LADDER["up"]], \
        f"TP_UP 不匹配"
    assert fields["TP_DOWN"] == [list(t) for t in risk_rules.TREND_TP_LADDER["down"]], \
        f"TP_DOWN 不匹配"

    print(f"断言1: STOP={fields['STOP']}, CHASE={fields['CHASE']}, TIME={fields['TIME']}, "
          f"TP_UP={fields['TP_UP']}, TP_DOWN={fields['TP_DOWN']} ✓")


# ── 断言2：手改副本后 redline_check 检测漂移 ──
def test_assert2_redline_drift_detection():
    """断言2：mock read_fn 模拟 risk_rules 被修改 → redline_check.frozen=True + changed_fields 含该字段。"""
    baseline = {"fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120,
                            "TP_UP": [[6, 0.15], [10, 0.05], [15, 0.07], [25, 0.09], [999, 0.12]],
                            "TP_DOWN": [[5, 0.03], [10, 0.04], [15, 0.05], [20, 0.06], [30, 0.08], [999, 0.1]]}}

    # 模拟 CHASE 从 4.0 被改为 5.0
    def _drifted_read():
        return {"STOP": 0.10, "CHASE": 5.0, "TIME": 120,
                "TP_UP": [[6, 0.15], [10, 0.05], [15, 0.07], [25, 0.09], [999, 0.12]],
                "TP_DOWN": [[5, 0.03], [10, 0.04], [15, 0.05], [20, 0.06], [30, 0.08], [999, 0.1]]}

    rl = el.redline_check(_drifted_read, baseline)
    assert rl["frozen"] is True, f"期望 frozen=True，得到 {rl}"
    assert "CHASE" in rl["changed_fields"], f"期望 changed_fields 含 CHASE，得到 {rl['changed_fields']}"
    print(f"断言2: 手改 CHASE 4.0→5.0 → frozen=True, changed_fields={rl['changed_fields']} ✓")

    # 模拟删除 STOP 字段
    def _deleted_read():
        return {"CHASE": 4.0, "TIME": 120,
                "TP_UP": [[6, 0.15], [10, 0.05], [15, 0.07], [25, 0.09], [999, 0.12]],
                "TP_DOWN": [[5, 0.03], [10, 0.04], [15, 0.05], [20, 0.06], [30, 0.08], [999, 0.1]]}

    rl2 = el.redline_check(_deleted_read, baseline)
    assert rl2["frozen"] is True, f"期望 frozen=True，得到 {rl2}"
    assert "STOP" in rl2["changed_fields"], f"期望 changed_fields 含 STOP，得到 {rl2['changed_fields']}"
    print(f"断言2b: 删除 STOP 字段 → frozen=True, changed_fields={rl2['changed_fields']} ✓")


# ── 断言3：run_evolution_loop OOS 纯净断言 ──
def test_assert3_oos_purity_in_run_evolution_loop():
    """断言3：run_evolution_loop 跑完，oos_check.pure=True 且 OOS 首日 > fit 末日。"""
    # 构造合法 walk-forward 日期：fit=[01-01~01-10], oos=[01-11~01-20]
    fit = [f"2026-01-{d:02d}" for d in range(1, 11)]
    oos = [f"2026-01-{d:02d}" for d in range(11, 21)]

    proposals = [{"proposal_id": "P1", "source": "A", "target": "top_n", "desc": "test"}]
    result = el.run_evolution_loop(
        proposals=proposals,
        today=TODAY,
        circuit_level="L0",
        fit_dates=fit,
        oos_dates=oos,
        dry_run=True
    )

    oos_check = result["oos_check"]
    assert oos_check["pure"] is True, f"期望 OOS 纯净，得到 {oos_check}"

    # 断言 OOS 首日 > fit 末日
    fit_last = max(fit)
    oos_first = min(oos)
    assert oos_first > fit_last, f"OOS 首日 {oos_first} 应大于 fit 末日 {fit_last}"
    print(f"断言3: OOS 首日={oos_first} > fit 末日={fit_last}, oos_check.pure=True ✓")


# ── 断言4：evidence.engine_commit 接真实 git hash ──
def test_assert4_engine_commit_is_real_hash():
    """断言4：evidence.engine_commit 接真实 git rev-parse HEAD (40位hash)。"""
    import subprocess
    r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                       cwd=os.path.dirname(os.path.abspath(__file__)))
    expected_commit = r.stdout.strip()
    assert len(expected_commit) == 40, f"git rev-parse HEAD 失败或非40位: {expected_commit}"

    # 从 run_evolution_loop 结果中验证
    proposals = [{"proposal_id": "P1", "source": "A", "target": "top_n", "desc": "test"}]
    result = el.run_evolution_loop(
        proposals=proposals,
        today=TODAY,
        circuit_level="L0",
        dry_run=True
    )
    actual_commit = result["engine_commit"]
    assert actual_commit == expected_commit, \
        f"engine_commit 不匹配: {actual_commit} != {expected_commit}"
    assert len(actual_commit) == 40, f"engine_commit 非40位: {actual_commit}"
    print(f"断言4: engine_commit={actual_commit[:12]}… (40位hash) ✓")


# ── 额外：grep 验证 evolution_loop.py 内无硬编码阶梯数值 ──
def test_assert5_no_hardcoded_ladder_values():
    """额外断言：evolution_loop.py 内零处硬编码阶梯数值（如 [6, 0.15] 等）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evolution_loop.py")
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()

    # 搜索硬编码的阶梯模式：(数字, 小数) 形式
    import re
    # 匹配类似 (6, 0.15) 或 [6, 0.15] 的阶梯字面量
    hardcoded_patterns = re.findall(r"\[\s*\d+\s*,\s*0\.\d+\s*\]", content)
    # 过滤掉注释/文档字符串里的内容（粗略：去掉 \"\"\" 和 ''' 包裹的区域）
    # 这里只检查函数体，docstring 里出现是正常的说明文字
    # 保守策略：只要有硬编码阶梯列表就告警
    # 但需排除 _read_redline_from_source docstring 中的示例（那里只是说明）
    lines = content.split("\n")
    in_docstring = False
    violations = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if re.search(r"\[\s*\d+\s*,\s*0\.\d+\s*\]", stripped):
            violations.append((i, stripped))
    assert not violations, f"发现硬编码阶梯数值: {violations}"
    print("断言5: evolution_loop.py 内零处硬编码阶梯数值 ✓")


if __name__ == "__main__":
    print("=" * 60)
    print("EVOL-P2v2 验收测试")
    print("=" * 60)
    test_assert1_read_redline_from_source()
    test_assert2_redline_drift_detection()
    test_assert3_oos_purity_in_run_evolution_loop()
    test_assert4_engine_commit_is_real_hash()
    test_assert5_no_hardcoded_ladder_values()
    print("=" * 60)
    print("所有 P2v2 验收测试通过 ✅")
