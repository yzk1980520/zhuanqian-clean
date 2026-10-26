"""
tests/test_factor_gate_blocking.py — P0: 因子门禁未贯穿出票链路修复

Seam 定义（经 2026-10-20 老大确认）：
  S1: check_gates() 读 factor_gate.json gate_passed 字段
  S2: main() 在 check_gates()=False 时 exit(3) 而非继续选股
  S3: factor_layer_enabled=False 时因子门禁豁免（不因 gate 失败而阻塞）

验收断言（来自 factor_gate.json 真实结构 + daily_pick.py exit code 3 约定）：
  - gate_passed=False 且 factor_layer_enabled=True → check_gates()=False
  - check_gates()=False → main() sys.exit(3)
  - factor_layer_enabled=False → check_gates()=True（豁免）
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _write_gate_json(tmpdir: Path, gate_passed: bool, factor_layer_enabled: bool = True):
    """构造最小合法 factor_gate.json 快照。"""
    gate_data = {
        "date": "2026-10-20",
        "gate_passed": gate_passed,
        "effective_factors": 1 if gate_passed else 1,
        "threshold": 8,
        "gap": 7,
        "factor_layer_enabled": factor_layer_enabled,
        "factor_layer_source": "config.json",
        "factor_layer_note": "" if factor_layer_enabled else "因子层显式关闭",
    }
    gate_path = tmpdir / "data" / "factor_ic" / "factor_gate.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(json.dumps(gate_data, ensure_ascii=False), encoding="utf-8")
    return gate_path


def _write_ic_latest(tmpdir: Path):
    """构造最小合法 factor_ic_latest.json（R6 门禁需要）。"""
    ic_data = {
        "last_date": "2026-10-16",
        "freshness_days": 2,
        "total_samples": 28,
        "source": "pure_python_v10_exact_132d@test",
        "computed_at": "2026-10-18 03:06:14",
        "factors": [{"name": "AMIHUD", "ic": 0.0335, "status": "valid"}],
    }
    ic_path = tmpdir / "data" / "factor_ic" / "factor_ic_latest.json"
    ic_path.parent.mkdir(parents=True, exist_ok=True)
    ic_path.write_text(json.dumps(ic_data, ensure_ascii=False), encoding="utf-8")
    return ic_path


def _write_review_status(tmpdir: Path, frozen: bool = False):
    """构造最小合法 review_status.json（老五闸门需要）。"""
    rs = {
        "laowu_approved": not frozen,
        "pending_review": False,
        "review_completed": True,
        "verdict": "APPROVED" if not frozen else "FROZEN",
        "last_updated": "2026-10-20",
    }
    rs_path = tmpdir / "data" / "review_status.json"
    rs_path.write_text(json.dumps(rs, ensure_ascii=False), encoding="utf-8")
    return rs_path


def _write_anchor_report(tmpdir: Path):
    """构造合法 engine_anchor_report.json（R2 门禁通过：success==total>0）。"""
    anchor = {"success": 1, "total_files": 1}
    anchor_path = tmpdir / "data" / "engine_anchor_report.json"
    anchor_path.write_text(json.dumps(anchor, ensure_ascii=False), encoding="utf-8")
    return anchor_path


@pytest.fixture()
def tmp_project(tmp_path: Path):
    """临时项目根目录，含最小必需 data/ 文件（R2/R6/老五闸门全绿）。"""
    data_dir = tmp_path / "data" / "factor_ic"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_ic_latest(tmp_path)
    _write_review_status(tmp_path, frozen=False)
    _write_anchor_report(tmp_path)
    return tmp_path


# ─── S1: check_gates() 读 factor_gate.json ────────────────────────────────────

class TestCheckGatesFactorGate:
    """S1: check_gates() 必须读 factor_gate.json 的 gate_passed 字段。"""

    def test_s1_gate_fail_with_factor_layer_on_returns_false(self, tmp_project: Path):
        """
        RED (待实现): factor_gate.json gate_passed=False 且 factor_layer_enabled=True
        → check_gates() 应返回 False（门禁阻断）。

        验收断言来源：
          - factor_gate.json gate_passed=false（今日 18:04 实测）
          - AGENTS.md §四.1 规则2：因子门禁未通过时应阻塞出票
          - daily_pick.py exit code 3 约定：门禁暂停=非成功
        """
        _write_gate_json(tmp_project, gate_passed=False, factor_layer_enabled=True)

        # 临时注入 PROJECT_ROOT（让模块用 tmp_project 而非真实 D:/open code/zhuanqian）
        import auto_live_pipeline as alp

        with mock.patch.object(alp, "PROJECT_ROOT", tmp_project):
            result = alp.check_gates()

        # RED: 当前实现不读 factor_gate.json，返回 True → 本断言失败即 red
        assert result is False, (
            f"check_gates() 应返回 False 当 factor_gate.json gate_passed=False, "
            f"但得到 {result}；因子门禁未贯穿出票链路（P0 根因）"
        )

    def test_s1_gate_pass_with_factor_layer_on_returns_true(self, tmp_project: Path):
        """
        gate_passed=True 且 factor_layer_enabled=True → check_gates()=True。
        验收断言：factor_gate.json 里 gate_passed=true 表示有效因子 ≥ 阈值。
        """
        _write_gate_json(tmp_project, gate_passed=True, factor_layer_enabled=True)

        import auto_live_pipeline as alp

        with mock.patch.object(alp, "PROJECT_ROOT", tmp_project):
            result = alp.check_gates()

        assert result is True


# ─── S3: factor_layer_enabled=False 豁免 ──────────────────────────────────────

class TestCheckGatesFactorLayerExempt:
    """S3: factor_layer_enabled=False 时因子门禁豁免，不因 gate 失败而阻塞。"""

    def test_s3_gate_fail_but_factor_layer_off_returns_true(self, tmp_project: Path):
        """
        RED (待实现): factor_gate.json gate_passed=False 但 factor_layer_enabled=False
        → check_gates() 应返回 True（豁免，因子层不参与打分）。

        验收断言来源：
          - factor_gate.json factor_layer_enabled=false（今日 18:04 实测）
          - gate_check.py L19: "关闭因子层不会让门禁变绿" ← 注意：这句话说的是
            gate_check.py 自身的判定口径，但 auto_live_pipeline.check_gates()
            应该尊重 factor_layer_enabled 开关（否则逻辑层关闭等于形同虚设）
        """
        _write_gate_json(tmp_project, gate_passed=False, factor_layer_enabled=False)

        import auto_live_pipeline as alp

        with mock.patch.object(alp, "PROJECT_ROOT", tmp_project):
            result = alp.check_gates()

        # RED: 当前实现未读 factor_layer_enabled，会因 gate_passed=False 返回 False
        assert result is True, (
            f"check_gates() 应豁免 factor_layer_enabled=False 场景返回 True, "
            f"但得到 {result}"
        )


# ─── S2: main() exit code 3 ───────────────────────────────────────────────────

class TestMainExitCodeOnGateFail:
    """S2: main() 在 check_gates()=False 时应 sys.exit(3)，不继续选股。"""

    def test_s2_main_exits_3_when_factor_gate_fails(self, tmp_project: Path, monkeypatch):
        """
        RED (待实现): check_gates()=False → main() return 3（门禁暂停语义）。

        验收断言来源：
          - daily_pick.py L100-106：门禁未通过 exit code 3（已验证）
          - AGENTS.md §七.1：exit code 语义 0=成功 1=失败 3=门禁暂停
        """
        _write_gate_json(tmp_project, gate_passed=False, factor_layer_enabled=True)

        import auto_live_pipeline as alp

        monkeypatch.setattr(alp, "PROJECT_ROOT", tmp_project)
        monkeypatch.setattr(alp.sys, "argv", ["auto_live_pipeline.py", "--mode", "daily"])

        # check_data_health 返回 True，使 main() 走到门禁检查
        monkeypatch.setattr(alp, "check_data_health", lambda: True)

        # 正常路径：main() 在 check_gates()=False 后 return 3（门禁暂停），
        # 不继续 run_stock_selection()。
        rc = alp.main()

        # RED: 当前 main() 忽略 check_gates() 返回值（只打印警告），
        # 继续 run_stock_selection() → 大概率 return 0/1，而非 3
        assert rc == 3, (
            f"main() 在因子门禁未通过时应 return 3（门禁暂停语义），"
            f"但得到 {rc}；门禁未贯穿出票链路（P0 根因）"
        )
