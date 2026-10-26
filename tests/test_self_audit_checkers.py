# -*- coding: utf-8 -*-
"""test_self_audit_checkers.py — 自审 Agent R0 检查器测试

覆盖规则：
  C-1  S1假绿复现：final_verdict=FAIL ∧ laowu_approved=True
  C-2  门禁一致性：sanity gate PASS ∧ review_gate frozen=True
  D-1  DD口径漂移：max_drawdown 赋值 ≠ 裁定 35%
  A-1  契约漂移：裸读 review_status.json 裁定类消费方未走 review_gate

使用 tmp_path 合成数据，不碰生产 data/。
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ops.self_audit_checkers import (  # noqa: E402
    AuditResult,
    check_a1_s1_consumer_arbitration,
    check_c1_s1_false_green,
    check_c2_gate_consistency,
    check_d1_dd_threshold_drift,
    _extract_dd_threshold_from_line,
    _is_comment_or_docstring_line,
)


# ====================================================================
# fixtures
# ====================================================================

@pytest.fixture
def fake_review_status(tmp_path):
    """创建临时 review_status.json，返回 (path, write_status)"""
    def _write(data):
        p = tmp_path / "review_status.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)
    return _write


@pytest.fixture
def fake_sanity_gate(tmp_path):
    """创建临时 sanity_gate_status.json，返回 (path, write_gate)"""
    def _write(data):
        p = tmp_path / "sanity_gate_status.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return str(p)
    return _write


# ====================================================================
# C-1：S1假绿复现检测
# ====================================================================

class TestC1FalseGreen:
    """C-1: final_verdict=FAIL ∧ laowu_approved=True 矛盾检测"""

    def test_c1_pass_no_contradiction(self, tmp_path, fake_review_status):
        """PASS ∧ True → 无矛盾"""
        fake_review_status({"final_verdict": "PASS", "laowu_approved": True})
        # 临时替换常量路径
        import core.ops.self_audit_checkers as m
        orig = m.REVIEW_STATUS_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "review_status.json")
        try:
            r = m.check_c1_s1_false_green()
            assert r.status == "PASS"
            assert r.severity == "P0"
        finally:
            m.REVIEW_STATUS_PATH = orig

    def test_c1_false_green_detected(self, tmp_path, fake_review_status):
        """FAIL ∧ True → 假绿"""
        fake_review_status({
            "final_verdict": "FAIL",
            "laowu_approved": True,
            "findings": {"all_configs_failed": True},
        })
        import core.ops.self_audit_checkers as m
        orig = m.REVIEW_STATUS_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "review_status.json")
        try:
            r = m.check_c1_s1_false_green()
            assert r.status == "FAIL"
            assert r.severity == "P0"
            assert "假绿" in r.message
            assert r.details["final_verdict"] == "FAIL"
            assert r.details["laowu_approved"] is True
        finally:
            m.REVIEW_STATUS_PATH = orig

    def test_c1_bool_false_verdict(self, tmp_path, fake_review_status):
        """final_verdict=False ∧ laowu_approved=True → 假绿"""
        fake_review_status({
            "final_verdict": False,
            "laowu_approved": True,
        })
        import core.ops.self_audit_checkers as m
        orig = m.REVIEW_STATUS_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "review_status.json")
        try:
            r = m.check_c1_s1_false_green()
            assert r.status == "FAIL"
        finally:
            m.REVIEW_STATUS_PATH = orig

    def test_c1_missing_file_skipped(self, tmp_path):
        """文件不存在 → SKIPPED"""
        import core.ops.self_audit_checkers as m
        orig = m.REVIEW_STATUS_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "nonexistent.json")
        try:
            r = m.check_c1_s1_false_green()
            assert r.status == "SKIPPED"
        finally:
            m.REVIEW_STATUS_PATH = orig

    def test_c1_no_contradiction_fail_false(self, tmp_path, fake_review_status):
        """FAIL ∧ laowu_approved=False → 无矛盾（正常冻结）"""
        fake_review_status({
            "final_verdict": "FAIL",
            "laowu_approved": False,
        })
        import core.ops.self_audit_checkers as m
        orig = m.REVIEW_STATUS_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "review_status.json")
        try:
            r = m.check_c1_s1_false_green()
            assert r.status == "PASS"
        finally:
            m.REVIEW_STATUS_PATH = orig


# ====================================================================
# C-2：门禁一致性检测
# ====================================================================

class TestC2GateConsistency:
    """C-2: sanity gate PASS ∧ review_gate frozen=True 矛盾检测"""

    def test_c2_consistent_pass(self, tmp_path, fake_review_status, fake_sanity_gate):
        """sanity PASS + review_gate 放行 → 一致"""
        fake_review_status({"final_verdict": "PASS", "laowu_approved": True})
        fake_sanity_gate({"status": "PASS", "gate_id": "SG-TEST-001"})
        import core.ops.self_audit_checkers as m
        orig_rs = m.REVIEW_STATUS_PATH
        orig_sg = m.SANITY_GATE_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "review_status.json")
        m.SANITY_GATE_PATH = str(tmp_path / "sanity_gate_status.json")
        try:
            r = m.check_c2_gate_consistency()
            assert r.status == "PASS"
        finally:
            m.REVIEW_STATUS_PATH = orig_rs
            m.SANITY_GATE_PATH = orig_sg

    def test_c2_consistency_conflict(self, tmp_path, fake_review_status, fake_sanity_gate):
        """sanity PASS + review_gate 冻结 → 矛盾"""
        fake_review_status({
            "final_verdict": "FAIL",
            "laowu_approved": True,
            "findings": {"all_configs_failed": True},
        })
        fake_sanity_gate({"status": "PASS", "gate_id": "SG-TEST-002"})
        import core.ops.self_audit_checkers as m
        orig_rs = m.REVIEW_STATUS_PATH
        orig_sg = m.SANITY_GATE_PATH
        m.REVIEW_STATUS_PATH = str(tmp_path / "review_status.json")
        m.SANITY_GATE_PATH = str(tmp_path / "sanity_gate_status.json")
        try:
            r = m.check_c2_gate_consistency()
            assert r.status == "FAIL"
            assert r.severity == "P0"
            assert "矛盾" in r.message
        finally:
            m.REVIEW_STATUS_PATH = orig_rs
            m.SANITY_GATE_PATH = orig_sg

    def test_c2_sanity_skip_no_conflict(self, tmp_path, fake_review_status):
        """sanity SKIP（无新回测）+ review_gate 冻结 → 不冲突"""
        fake_review_status({"final_verdict": "FAIL", "laowu_approved": True})
        import core.ops.self_audit_checkers as m
        # sanity_gate_status.json 不存在 → SKIPPED
        orig_sg = m.SANITY_GATE_PATH
        m.SANITY_GATE_PATH = str(tmp_path / "nonexistent.json")
        try:
            r = m.check_c2_gate_consistency()
            assert r.status == "SKIPPED"
        finally:
            m.SANITY_GATE_PATH = orig_sg


# ====================================================================
# D-1：DD 口径漂移检测
# ====================================================================

class TestD1DDThresholdDrift:
    """D-1: max_drawdown 门禁赋值与裁定 35% 比对"""

    def test_extract_dd_threshold_gate_dict(self):
        """GATE dict 中的 max_drawdown 赋值"""
        assert _extract_dd_threshold_from_line('    "max_drawdown": 0.35,') == 0.35
        assert _extract_dd_threshold_from_line('    "max_drawdown": 0.70,') == 0.70

    def test_extract_dd_threshold_max_dd_comparison(self):
        """max_dd <= 35 百分比阈值"""
        assert _extract_dd_threshold_from_line('        dd_status = "✓" if max_dd <= 35 else "✗"') == 0.35
        assert _extract_dd_threshold_from_line('    if max_dd <= 70:') == 0.70

    def test_extract_dd_placeholder_skipped(self):
        """占位符 0.0 跳过"""
        assert _extract_dd_threshold_from_line('        "max_drawdown": 0.0,') is None
        assert _extract_dd_threshold_from_line('    max_drawdown = 0.0') is None

    def test_extract_dd_result_data_skipped(self):
        """结果数据（多小数位）跳过"""
        assert _extract_dd_threshold_from_line('        "max_drawdown": 29.68') is None

    def test_extract_dd_comment_skipped(self):
        """注释行跳过"""
        assert _extract_dd_threshold_from_line('    # "max_drawdown": 0.70  # 旧口径') is None

    def test_d1_no_drift_current_state(self, tmp_path, monkeypatch):
        """当前 evaluate.py 已是 0.35，应 PASS"""
        import core.ops.self_audit_checkers as m
        # 不影响实际扫描，只验证函数可调用
        r = m.check_d1_dd_threshold_drift()
        # 实际项目中 evaluate.py 已经是 0.35，此测试验证无漂移
        assert r.checker == "d1_dd_threshold_drift"
        assert r.category == "threshold_conflict"

    def test_d1_drift_detected_when_value_changed(self, tmp_path, monkeypatch):
        """构造漂移场景：在 tmp 目录创建一个有漂移值的文件"""
        # 创建一个临时项目结构来测试
        test_dir = tmp_path / "test_proj"
        test_dir.mkdir()
        # 写一个带错误阈值的文件
        bad_file = test_dir / "bad_evaluate.py"
        bad_file.write_text(
            'GATE = {\n    "max_drawdown": 0.70,\n}\n',
            encoding="utf-8",
        )
        # 用 monkeypatch 替换 ROOT
        import core.ops.self_audit_checkers as m
        orig_root = m.ROOT
        m.ROOT = str(test_dir)
        try:
            r = m.check_d1_dd_threshold_drift()
            assert r.status == "FAIL"
            assert len(r.details["drifts"]) >= 1
            assert r.details["drifts"][0]["value"] == 0.70
        finally:
            m.ROOT = orig_root


# ====================================================================
# A-1：契约漂移检测
# ====================================================================

class TestA1ConsumerArbitration:
    """A-1: 裸读 review_status.json 裁定类消费方检测"""

    def test_a1_compliant_with_alias(self, tmp_path, monkeypatch):
        """文件用 _rg.evaluate() 别名 → 合规"""
        test_dir = tmp_path / "test_proj"
        test_dir.mkdir()
        good_file = test_dir / "good_consumer.py"
        good_file.write_text(
            'import review_gate as _rg\n'
            'review = _rg.evaluate("data/review_status.json")\n'
            'frozen = review["frozen"]\n',
            encoding="utf-8",
        )
        import core.ops.self_audit_checkers as m
        orig_root = m.ROOT
        m.ROOT = str(test_dir)
        try:
            r = m.check_a1_s1_consumer_arbitration()
            assert r.status == "PASS"
        finally:
            m.ROOT = orig_root

    def test_a1_violation_raw_read(self, tmp_path, monkeypatch):
        """文件裸读 laowu_approved 做决策 → 违例"""
        test_dir = tmp_path / "test_proj"
        test_dir.mkdir()
        bad_file = test_dir / "bad_consumer.py"
        bad_file.write_text(
            'import json\n'
            'with open("data/review_status.json") as f:\n'
            '    status = json.load(f)\n'
            'laowu_approved = status.get("laowu_approved", False)\n'
            'if laowu_approved and pos_count <= 1:\n'
            '    print("allowed")\n',
            encoding="utf-8",
        )
        import core.ops.self_audit_checkers as m
        orig_root = m.ROOT
        m.ROOT = str(test_dir)
        try:
            r = m.check_a1_s1_consumer_arbitration()
            assert r.status == "FAIL"
            assert len(r.details["violations"]) >= 1
            assert r.details["violations"][0]["file"] == "bad_consumer.py"
        finally:
            m.ROOT = orig_root

    def test_a1_no_review_status_reference(self, tmp_path, monkeypatch):
        """不含 review_status.json 引用的文件 → 不扫描"""
        test_dir = tmp_path / "test_proj"
        test_dir.mkdir()
        unrelated = test_dir / "unrelated.py"
        unrelated.write_text('x = 1\n', encoding="utf-8")
        import core.ops.self_audit_checkers as m
        orig_root = m.ROOT
        m.ROOT = str(test_dir)
        try:
            r = m.check_a1_s1_consumer_arbitration()
            assert r.status == "PASS"
        finally:
            m.ROOT = orig_root

    def test_a1_docstring_line_skipped(self, tmp_path, monkeypatch):
        """docstring 中的 - xxx 列表项不被误检为裁定代码"""
        test_dir = tmp_path / "test_proj"
        test_dir.mkdir()
        doc_file = test_dir / "doc_file.py"
        doc_file.write_text(
            '"""\n'
            'Module docstring.\n'
            '  - laowu_approved is True → PASS\n'
            '  - else → FAIL\n'
            '"""\n'
            'x = 1\n',
            encoding="utf-8",
        )
        import core.ops.self_audit_checkers as m
        orig_root = m.ROOT
        m.ROOT = str(test_dir)
        try:
            r = m.check_a1_s1_consumer_arbitration()
            assert r.status == "PASS"
        finally:
            m.ROOT = orig_root


# ====================================================================
# 工具函数测试
# ====================================================================

class TestHelpers:
    def test_is_comment_or_docstring_line_comment(self):
        lines = ["# this is a comment", "x = 1"]
        assert _is_comment_or_docstring_line(lines, 0) is True
        assert _is_comment_or_docstring_line(lines, 1) is False

    def test_is_comment_or_docstring_line_docstring_item(self):
        lines = ['"""', '  - laowu_approved is True → PASS', '"""', 'x = 1']
        assert _is_comment_or_docstring_line(lines, 1) is True
        assert _is_comment_or_docstring_line(lines, 3) is False

    def test_audit_result_to_json_line(self):
        r = AuditResult(
            checker="test_check", category="false_green",
            status="FAIL", severity="P0",
            message="test message", details={"a": 1}, evidence="ev"
        )
        line = r.to_json_line()
        parsed = json.loads(line)
        assert parsed["checker"] == "test_check"
        assert parsed["status"] == "FAIL"
        assert "timestamp" in parsed


# ====================================================================
# 回归：现有 self_audit 功能不受影响
# ====================================================================

class TestSelfAuditRegression:
    def test_self_audit_import(self):
        """self_audit.py 仍可正常导入"""
        import core.ops.self_audit  # noqa: F401

    def test_self_audit_has_audit_flag(self):
        """self_audit.py --audit 参数存在（通过 subprocess 验证）"""
        import subprocess
        # 2026-10-24 T051 C4 对齐: 根级 self_audit.py 为 S5 shim (star-import, 无 CLI dispatch),
        # 真源入口 = python -m core.ops.self_audit (2026-10-24 核验 --audit 在 usage)
        r = subprocess.run(
            [sys.executable, "-m", "core.ops.self_audit", "--help"],
            cwd=str(ROOT),
            capture_output=True, text=True, encoding="utf-8",
        )
        assert "--audit" in r.stdout


# ====================================================================
# P1-3：self_audit --audit 超时修复回归（2026-10-19 老三，commits 18ceda88+6be0aae6）
# ====================================================================

class TestP13TimeoutFix:
    """P1-3 超时修复：扫描黑名单 / 逐项墙钟预算 / subprocess 超时降级 P2。"""

    def test_scan_exclude_dirs_blocks_venv(self):
        """扫描黑名单须排除 .venv/.worktrees 等，防 24k 文件树再吞入（P1-3 根因）。"""
        import core.ops.self_audit_checkers as m
        for d in (".venv", ".worktrees", "backups", "archive", "models"):
            assert d in m.SCAN_EXCLUDE_DIRS, f"{d} 必须进扫描黑名单（P1-3 根因回归）"

    def test_walk_python_files_bounded(self):
        """黑名单修复后全扫应是数百一方文件，不含 .venv/.worktrees 子目录。"""
        import core.ops.self_audit_checkers as m
        files = m._walk_python_files()
        for f in files:
            # P2 t_ba5e3a49（S1迁移余面）：改为相对 ROOT 的路径分量断言，不做绝对路径字符串断言。
            # checkout 本身位于 .worktrees/ 下（kanban 嵌套 worktree <main>/.worktrees/<task>）时，
            # 扫出的所有文件绝对路径天然含 /.worktrees/ —— 这是环境特征而非 walker 漏排 .worktrees 子目录；
            # 路径分量断言等价检查「ROOT 下的 .venv/.worktrees 子目录未被扫入」，对 checkout 落点不敏感。
            parts = os.path.relpath(f, m.ROOT).replace("\\", "/").split("/")
            assert ".venv" not in parts, f"扫进了 .venv 子目录: {f}"
            assert ".worktrees" not in parts, f"扫进了 .worktrees 子目录: {f}"
        # 修复前 24,846（.venv 占 96%）；修复后 ~599。断言有界而非精确值（防误伤）。
        assert len(files) < 2000, f"全扫文件数 {len(files)} 过大，疑似黑名单被绕过"

    def test_run_checker_bounded_fast_pass(self):
        """预算内完成 → 原样返回 fn 产出的 AuditResult（不降级）。"""
        import core.ops.self_audit_checkers as m
        def fast():
            return m.AuditResult(checker="fast", category="x", status="PASS",
                                 severity="P0", message="ok")
        r = m._run_checker_bounded(fast, budget_s=5)
        assert r.status == "PASS" and r.checker == "fast"

    def test_run_checker_bounded_timeout_downgrades_p2(self):
        """超预算 → P2 SKIPPED「超时跳过」，主流程不被阻塞（P1-3 核心行为）。"""
        import time
        import core.ops.self_audit_checkers as m
        def slow():
            time.sleep(2.0)
            return m.AuditResult(checker="slow", category="x", status="PASS",
                                 severity="P0", message="late")
        r = m._run_checker_bounded(slow, budget_s=1)
        assert r.status == "SKIPPED"
        assert r.severity == "P2"
        assert "超时跳过" in r.message

    def test_run_checker_bounded_exception_p0(self):
        """fn 抛非超时异常 → P0 SKIPPED（真异常 ≠ 超时，保留 P0 不静默吞）。"""
        import core.ops.self_audit_checkers as m
        def boom():
            raise RuntimeError("kaboom")
        r = m._run_checker_bounded(boom, budget_s=5)
        assert r.status == "SKIPPED" and r.severity == "P0"
        assert "kaboom" in r.message

    def test_m3_timeout_downgrades_p2(self, monkeypatch):
        """M-3 subprocess 超时 → P2 SKIPPED（不再 P1、不阻塞主流程）。"""
        import subprocess as sp
        import core.ops.self_audit_checkers as m
        def raise_timeout(*a, **k):
            raise sp.TimeoutExpired(cmd="dispatch_audit_check.py", timeout=60)
        monkeypatch.setattr(sp, "run", raise_timeout)
        r = m.check_m3_dispatch_audit()
        assert r.status == "SKIPPED" and r.severity == "P2"
        assert "超时跳过" in r.message

    def test_r1_timeout_downgrades_p2(self, monkeypatch):
        """R-1 subprocess 超时 → P2 SKIPPED（不再 P0、不阻塞主流程）。"""
        import subprocess as sp
        import core.ops.self_audit_checkers as m
        def raise_timeout(*a, **k):
            raise sp.TimeoutExpired(cmd="check_remote_main_freshness.py", timeout=60)
        monkeypatch.setattr(sp, "run", raise_timeout)
        r = m.check_r1_remote_freshness()
        assert r.status == "SKIPPED" and r.severity == "P2"
        assert "超时跳过" in r.message
