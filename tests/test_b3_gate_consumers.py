# -*- coding: utf-8 -*-
"""B3 TDD: review_status.json gate 裁定类消费方统一走 review_gate (K44 遗留, /tdd 执行)

等价性报告: docs/B3_equivalence_20261009.md (4 漂移场景 + 真数据, S1 一致, S2/S3 fail-open→fail-safe,
S5 消除 fv=FAIL 假绿放行)。本测试 = 接线静态断言 (S3, 同 R0b/R4c 约定) + 死读修复断言。
真实裁定行为已委托 review_gate.evaluate (test_review_gate.py 13 项覆盖), 本测试不重复, 不碰 data/。

seam (4 处, 静态/源码级):
  1. integrated_picker.py  gate 段 → 委托 review_gate.evaluate (原内联裸读 laowu_approved 裁定)
  2. positioner.py          gate2 段 → 委托 review_gate.evaluate (原缺文件 fail-open 跳过)
  3. s3_auto_pipeline.py    gate 段 → 委托 review_gate.evaluate (原缺文件 fail-open 未设)
  4. system_audit_checker.py 矛盾检测 → 修嵌套死读 laowu.approved (laowu 非 dict→永 None) 改读真字段
"""
import os
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel: str) -> str:
    # S4: 优先查 core/pipeline/, 回退根级
    pipeline = Path(ROOT) / 'core' / 'pipeline' / rel
    root = Path(ROOT) / rel
    return pipeline.read_text(encoding='utf-8') if pipeline.exists() else root.read_text(encoding='utf-8')


# ── 1. integrated_picker: gate 委托 review_gate ───────────────────
def test_integrated_picker_delegates_review_gate():
    src = _src("integrated_picker.py")
    # 改后: 引用 review_gate + 走 evaluate 裁定 (含 final_verdict/B1 否决/fail-safe)
    assert "import review_gate" in src, "integrated_picker 未委托 review_gate"
    assert "review_gate.evaluate" in src, "integrated_picker gate 段未走 review_gate.evaluate"
    # 改前裸读裁定行必须消失 (不再自己读 laowu_approved 做 exit 裁定)
    assert '_laowu_approved = _rv.get("laowu_approved")' not in src, (
        "integrated_picker 仍在内联裸读 laowu_approved 裁定 (未委托 review_gate)"
    )
    assert "if not _laowu_approved:" not in src, (
        "integrated_picker 仍是旧 `if not _laowu_approved` 裁定 (漏 final_verdict/fail-safe)"
    )


# ── 2. positioner: gate2 委托 review_gate (fail-open→fail-safe) ────
def test_positioner_delegates_review_gate():
    src = _src("positioner.py")
    assert "import review_gate" in src, "positioner 未委托 review_gate"
    assert "review_gate.evaluate" in src, "positioner gate2 未走 review_gate.evaluate"
    # 改前: 缺文件 fail-open 跳过 + 裸读 laowu_approved 裁定行消失
    assert "approved = d.get('laowu_approved', False)" not in src, (
        "positioner gate2 仍裸读 laowu_approved 裁定 (漏 final_verdict/fail-safe)"
    )


# ── 3. s3_auto_pipeline: gate 委托 review_gate ────────────────────
def test_s3_auto_pipeline_delegates_review_gate():
    src = _src("scripts/s3_auto_pipeline.py")
    assert "import review_gate" in src, "s3_auto_pipeline 未委托 review_gate"
    assert "review_gate.evaluate" in src, "s3_auto_pipeline gate 未走 review_gate.evaluate"
    assert "gates[\"laowu_approved\"] = review.get('laowu_approved', False)" not in src, (
        "s3_auto_pipeline 仍裸读 laowu_approved 裁定 (漏 final_verdict/fail-safe)"
    )


# ── 4. system_audit_checker: 嵌套死读修复 → 真矛盾检测 ────────────
def test_system_audit_checker_fixes_dead_nested_read():
    src = _src("scripts/system_audit_checker.py")
    # 改前死读: 嵌套 laowu.approved (laowu 非 dict → 永 None → 矛盾检测形同虚设, 假绿)
    assert "review_data.get('laowu', {}).get('approved'" not in src, (
        "system_audit_checker 仍嵌套读 laowu.approved (死读, laowu 非 dict → 永 None)"
    )
    assert "nested_approved = review_data.get('laowu'" not in src, (
        "system_audit_checker nested_approved 死读仍在"
    )
    # 改后: 真矛盾检测 = 顶层 laowu_approved vs final_verdict (B3 假绿场景 S5 同源)
    assert "final_verdict" in src, (
        "system_audit_checker 未读真字段 final_verdict 做矛盾检测"
    )


# ── 行为回归: 4 个 gate 裁定消费方 全部委托后, 裁定逻辑统一在 review_gate ─
def test_all_gate_consumers_converge_on_review_gate():
    """B3 收敛断言: 3 gate 裁定类 委托 review_gate.evaluate + 诊断类矛盾检测改读真字段。"""
    for rel in ("integrated_picker.py", "positioner.py", "scripts/s3_auto_pipeline.py"):
        assert "review_gate.evaluate" in _src(rel), f"{rel} 未收敛到 review_gate.evaluate"
    audit = _src("scripts/system_audit_checker.py")
    # 诊断类: 死读串残留 = 假"一致" (必须无残留)
    assert ".get('approved'" not in audit, "system_audit_checker 仍有嵌套 .get('approved') 死读"
    # 矛盾检测改读真字段 final_verdict
    assert "final_verdict" in audit, "system_audit_checker 矛盾检测未读真字段 final_verdict"
