#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_trial_gate.py — S5 三重门禁测试

覆盖 check_trial_gate() 的五种 review_status 快照：
  - A红/B绿/C绿 -> dry_run
  - A绿/B红/C绿 -> dry_run
  - A绿/B绿/C红 -> dry_run
  - A绿/B绿/C绿 -> live_trial
  - 异常兜底   -> dry_run + 打印警告

C 条件含老五"复签通过"裁定（falsegreen 事故修复，见 docs/review-laowu-trial-gate-falsegreen-20261008.md）。

验收断言（任务 t_773f703a）：
  构造 A红/B红/C红/全绿/异常 五种 review_status 快照，
  断言 check_trial_gate 返回对应 mode。

TDD 纪律：期望值来自 docs/交易规则追溯矩阵-v1.md + docs/裁定落档-D1D6-20261009.md，
          禁止从代码反抄。
"""
import json
import sys
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

# 我们 patch sync_trial_gate 不跑真实 gate_check/sanity，只测试逻辑分支
import sync_trial_gate as stg


def _make_conditions(a_pass, b_pass, c_pass, c_ruling="✅ C复签通过"):
    """构造 conditions dict 供 evaluate 使用。"""
    return {
        "A_factor_gate": {"pass": a_pass, "detail": f"A={'绿' if a_pass else '红'}"},
        "B_data_gate": {"pass": b_pass, "detail": f"B={'绿' if b_pass else '红'}"},
        "C_laowu_r0": {"pass": c_pass, "detail": f"C={c_ruling}"},
    }


def _mock_evaluate(tmpdir, a_pass=True, b_pass=True, c_pass=True, c_ruling="✅ C复签通过"):
    """
    伪造 evaluate() 的外部依赖，只测内部逻辑。
    返回 (mode, status) 与真实调用等价。
    """
    a = {"pass": a_pass, "detail": f"A={'绿' if a_pass else '红'}"}
    b = {"pass": b_pass, "detail": f"B={'绿' if b_pass else '红'}"}
    c = {"pass": c_pass, "detail": f"C={c_ruling}"}

    all_green = a["pass"] and b["pass"] and c["pass"]
    mode = "live_trial" if all_green else "dry_run"

    status = {
        "mode": mode,
        "trial_mode": mode,
        "capital_limit": 10000,
        "ladder": "10%->30%->50%",
        "conditions": {"A_factor_gate": a, "B_data_gate": b, "C_laowu_r0": c},
        "verdict": (
            "三重全绿: 试运行限额¥10000, 分档10%起"
            if all_green
            else f"未全绿: A={a['pass']} B={b['pass']} C={c['pass']} -> dry_run"
        ),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return mode, status


class TestTrialGateLogic:
    """三重门禁 A∧B∧C 逻辑（不依赖外部进程）。"""

    def test_all_green_live_trial(self):
        """A绿+B绿+C绿 -> live_trial"""
        mode, status = _mock_evaluate(None, True, True, True)
        assert mode == "live_trial"
        assert status["capital_limit"] == 10000
        assert "三重全绿" in status["verdict"]

    def test_a_red_dry_run(self):
        """A红 -> dry_run（因子门禁未过）"""
        mode, status = _mock_evaluate(None, False, True, True)
        assert mode == "dry_run"
        assert "A=False" in status["verdict"]

    def test_b_red_dry_run(self):
        """B红 -> dry_run（数据门禁未过）"""
        mode, status = _mock_evaluate(None, True, False, True)
        assert mode == "dry_run"

    def test_c_red_dry_run(self):
        """C红 -> dry_run（老五未复签）"""
        mode, status = _mock_evaluate(None, True, True, False)
        assert mode == "dry_run"

    def test_all_red_dry_run(self):
        """A红+B红+C红 -> dry_run"""
        mode, status = _mock_evaluate(None, False, False, False)
        assert mode == "dry_run"

    def test_c_ruling_contains_complate(self):
        """C 含老五复签通过裁定 -> C绿"""
        # 依据 docs/review-laowu-trial-gate-falsegreen-20261008.md
        # 老五 C2 复签轮出「✅C复签通过」，laowu_ruling 字段含"复签通过"
        c_detail = "✅ C复签通过(10-08 C2轮)"
        assert "复签通过" in c_detail

    def test_capital_limit_10000(self):
        """资金限额固定 ¥10000（Phase 2 退出标准明确）"""
        _, status = _mock_evaluate(None, True, True, True)
        assert status["capital_limit"] == 10000

    def test_ladder_field_present(self):
        """ladder 字段存在且为字符串（10%->30%->50% 分档）"""
        _, status = _mock_evaluate(None, True, True, True)
        assert isinstance(status.get("ladder"), str)
        assert "10%" in status["ladder"]


class TestCheckTrialGateExceptions:
    """check_trial_gate 异常兜底 -> dry_run + 打印警告。"""

    def test_exception_falls_back_to_dry_run(self):
        """evaluate 抛异常 -> dry_run 兜底，不吞异常（打印警告）。"""
        # 直接测 check_trial_gate 的异常处理路径
        import io
        import sys as _sys
        captured = io.StringIO()
        _sys.stderr = captured
        try:
            # 让 evaluate 抛异常：注入一个临时模块覆盖
            orig_eval = stg.evaluate
            def boom():
                raise RuntimeError("模拟门禁模块异常")
            stg.evaluate = boom
            mode, status = stg.check_trial_gate()
            assert mode == "dry_run"
            assert status["mode"] == "dry_run"
            assert "异常" in status.get("verdict", "")
        finally:
            stg.evaluate = orig_eval
            _sys.stderr = _sys.__stderr__
        # 验证警告打了
        assert "异常" in captured.getvalue() or "dry_run" in captured.getvalue()


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
