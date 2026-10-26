# -*- coding: utf-8 -*-
"""R0b TDD: 根目录 review_gate.py — 统一仲裁读法 (K47 §二 / B3 / B1)

单一真源读法, 4 消费方(auto_trading/cron_daily/auto_live/automation_scheduler)统一 import,
消除"各写各的" + auto_live 嵌套坏键 laowu.approved + scheduler fail-open。

读法优先级 (evaluate):
  1. final_verdict 显式字段 (B3 唯一仲裁): 'FAIL'/'PASS' 或 False/True
  2. B1 现算: findings 硬失败 (all_configs_failed / diversity_collapse / recommendation 含"禁止新买入") 拥否决权 → FAIL
  3. 回落 laowu_approved: 仅显式 True 才放行, 缺失/False/None → 冻结 (fail-safe)
  文件缺失 / 解析失败 / 非 dict → fail-safe 冻结 (WARN, 不静默吞)

seam = review_gate.evaluate(path) / is_frozen(path) (纯读, 用 tmp_path 合成 review_status, 不碰 data/)。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import review_gate  # noqa: E402


def _write(tmp_path, obj, name="review_status.json"):
    import json
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_t1_final_verdict_fail_explicit(tmp_path):
    p = _write(tmp_path, {"final_verdict": "FAIL", "laowu_approved": True,
                          "findings": {"all_configs_failed": True}})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "final_verdict"


def test_t2_final_verdict_pass_explicit(tmp_path):
    p = _write(tmp_path, {"final_verdict": "PASS", "laowu_approved": True})
    r = review_gate.evaluate(p)
    assert r["frozen"] is False
    assert r["source"] == "final_verdict"


def test_t3_final_verdict_bool_false(tmp_path):
    p = _write(tmp_path, {"final_verdict": False})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "final_verdict"


def test_t4_b1_all_configs_failed_veto(tmp_path):
    """无 final_verdict, findings.all_configs_failed=True → B1 否决 (即使 laowu_approved=True)"""
    p = _write(tmp_path, {"laowu_approved": True,
                          "findings": {"all_configs_failed": True}})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "b1_findings"


def test_t5_b1_diversity_collapse_veto(tmp_path):
    p = _write(tmp_path, {"laowu_approved": True,
                          "findings": {"diversity_collapse": True}})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "b1_findings"


def test_t6_b1_recommendation_ban(tmp_path):
    p = _write(tmp_path, {"laowu_approved": True,
                          "recommendation": "🔴 紧急：... 等待因子重构完成前禁止新买入"})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "b1_findings"


def test_t7_no_hard_fail_fallthrough_true(tmp_path):
    """无 final_verdict + 无硬失败 + laowu_approved=True → 放行"""
    p = _write(tmp_path, {"laowu_approved": True,
                          "findings": {"max_win_rate": "40%"}})
    r = review_gate.evaluate(p)
    assert r["frozen"] is False
    assert r["source"] == "laowu_approved"


def test_t8_no_hard_fail_fallthrough_false(tmp_path):
    p = _write(tmp_path, {"laowu_approved": False})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "laowu_approved"


def test_t9_missing_lawu_field_failsafe(tmp_path):
    """laowu_approved 缺失 + 无硬失败 + 无 final_verdict → fail-safe 冻结"""
    p = _write(tmp_path, {"findings": {}})
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "laowu_approved"


def test_t10_file_missing_failsafe(tmp_path):
    r = review_gate.evaluate(str(tmp_path / "does_not_exist.json"))
    assert r["frozen"] is True
    assert r["source"] == "fail_safe"


def test_t11_corrupt_json_failsafe(tmp_path):
    p = tmp_path / "review_status.json"
    p.write_text("{broken json ...", encoding="utf-8")
    r = review_gate.evaluate(str(p))
    assert r["frozen"] is True
    assert r["source"] == "fail_safe"


def test_t12_not_dict_failsafe(tmp_path):
    p = _write(tmp_path, ["not", "a", "dict"])
    r = review_gate.evaluate(p)
    assert r["frozen"] is True
    assert r["source"] == "fail_safe"


def test_t13_is_frozen_thin_api(tmp_path):
    p = _write(tmp_path, {"final_verdict": "FAIL"})
    assert review_gate.is_frozen(p) is True
    p2 = _write(tmp_path, {"final_verdict": "PASS"}, name="r2.json")
    assert review_gate.is_frozen(p2) is False
