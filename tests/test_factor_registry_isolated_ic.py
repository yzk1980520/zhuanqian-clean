# -*- coding: utf-8 -*-
"""test_factor_registry_isolated_ic.py — 审查题1/题2: Q1 ic_mean=None(隔离) 消费方 None 安全

Kimi-41 Q1 B-prime 把 5 因子 ic_mean/icir 隔离为 None(旧 IC 移 ic_history)。
回归实锤(总管 2026-10-08 审查): 4 个消费方方法假设 ic_mean 是 float, 遇 None 直接崩:
  - check_gate      factor_registry.py:248/251/258  -> '<'/'>' None vs float -> TypeError
  - generate_report factor_registry.py:338/340       -> abs(None)/f"{None:.4f}" -> TypeError
  - list_factors    factor_registry.py:192/194/196  -> None < min_ic -> TypeError
语义: ic_mean=None 表示"IC 已隔离, 不可用于门禁", 应返回 (False, 原因) 而非 crash;
报告/过滤应把 None 因子标注 isolated / 排除, 而非崩。
RED: 当前实现崩; GREEN: 修复后语义正确且正常 float 路径不变。
"""
import sys
from pathlib import Path

import pytest

# 基地化S3 (2026-10-22): 原硬编码主仓路径 (P2-1 self_audit 嵌套worktree断言同型环境敏感) —
# worktree 隔离下误指主仓(主仓未合入S3时无 core/ → 测试在worktree导入落空) → 改为被测仓库根(worktree安全)。
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def _reg(monkeypatch):
    import core.scoring.factor_registry as factor_registry
    monkeypatch.setattr(factor_registry, "root_fr", None, raising=False)  # no-op
    # 直接建真实 registry(带 pos_vs_ma20 loud-skip), 但把 _save 全禁, 保证测试零写盘
    reg = factor_registry.FactorRegistry()
    # 禁写: 任何路径触发 _save/_save_ic_history 都不落盘
    reg._save = lambda: None
    reg._save_ic_history = lambda: None
    return reg


class TestCheckGateNoneSafe:
    def test_isolated_ic_returns_fail_not_crash(self, monkeypatch):
        reg = _reg(monkeypatch)
        m = reg.get("VMR5")  # ic_mean=None (Q1 隔离), direction=positive
        assert m.ic_mean is None, "测试前提: VMR5 应为隔离态 ic_mean=None"
        ok, reason = reg.check_gate("VMR5")   # 修复前: TypeError '<' None<float
        assert ok is False, "隔离因子必须 fail, 不得 crash 也不得 pass"
        assert ("隔离" in reason) or ("None" in reason), "reason 须说明 IC 已隔离"

    def test_isolated_negative_factor_fail_not_crash(self, monkeypatch):
        reg = _reg(monkeypatch)
        m = reg.get("vol_ratio")  # ic_mean=None, direction=negative (R2 脏态 is_valid=True)
        assert m.ic_mean is None
        ok, reason = reg.check_gate("vol_ratio")   # 修复前: '>' None<float 崩
        assert ok is False
        assert ("隔离" in reason) or ("None" in reason)

    def test_numeric_ic_path_unchanged(self, monkeypatch):
        reg = _reg(monkeypatch)
        # chg20: ic_mean=0.0(float), direction=negative -> 走正常分支不崩
        ok, reason = reg.check_gate("chg20")
        assert ok is False and ("IC" in reason)   # 0.0 > -0.03 fail, 但非 crash
        assert "隔离" not in reason


class TestGenerateReportNoneSafe:
    def test_report_with_isolated_valid_factor_not_crash(self, monkeypatch):
        reg = _reg(monkeypatch)
        # vol_ratio: is_valid=True 且 ic_mean=None -> valid 列表里, abs(None) 曾崩
        valid = reg.get_valid_factors()
        assert any(f.ic_mean is None for f in valid), "测试前提: valid 里存在 ic_mean=None"
        rpt = reg.generate_report()   # 修复前: TypeError abs(None)
        assert isinstance(rpt, str)
        assert "isolated" in rpt or "IC已隔离" in rpt or "n/a" in rpt, "报告须把 None IC 标注, 不得静默当 0"


class TestListFactorsNoneSafe:
    def test_filter_min_ic_with_none_factors_not_crash(self, monkeypatch):
        reg = _reg(monkeypatch)
        # 修复前: None < 0.03 崩; 修复后 None 因子被排除(无法对阈值排序), 其余正常过滤
        res = reg.list_factors(min_ic=0.03)
        assert isinstance(res, list)
        assert all(f.ic_mean is not None for f in res), "min_ic 过滤结果不得含 None IC 因子"

    def test_filter_min_icir_with_none_not_crash(self, monkeypatch):
        reg = _reg(monkeypatch)
        res = reg.list_factors(min_icir=0.3)
        assert isinstance(res, list)
        assert all(f.icir is not None for f in res), "min_icir 过滤结果不得含 None ICIR"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
