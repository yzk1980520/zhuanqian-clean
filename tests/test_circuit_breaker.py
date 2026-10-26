#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_circuit_breaker.py — S7 三级熔断机制测试

TDD 纪律：期望值来自 docs/实盘准入标准_v1.0.md §四（独立文档真源），
禁止从代码反抄（09-25 假绿事故同款防线）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from circuit_breaker import (
    CircuitLevel,
    circuit_level,
    circuit_level_str,
    describe_action,
)


class TestCircuitLevel:
    """三级熔断级别判定测试。"""

    # ── L0：正常 ──────────────────────────────────────────────────
    def test_l0_normal(self):
        """小亏损小回撤 → L0"""
        assert circuit_level(0.01, 0.05, 0) == CircuitLevel.L0
        assert circuit_level(0.0, 0.0, 0.0) == CircuitLevel.L0
        assert circuit_level(0.02, 0.08, 0.1) == CircuitLevel.L0  # 2%盈利，8%回撤，10%IC失效

    # ── L1：黄预警 ────────────────────────────────────────────────
    def test_l1_daily_loss(self):
        """单日亏损 4% > 3% → L1"""
        assert circuit_level(-0.04, 0.05, 0) == CircuitLevel.L1

    def test_l1_cum_dd(self):
        """累计回撤 12% > 10% → L1"""
        assert circuit_level(0.01, 0.12, 0) == CircuitLevel.L1

    def test_l1_either_condition(self):
        """单日亏损或累计回撤任一触发 → L1"""
        assert circuit_level(-0.04, 0.05, 0) == CircuitLevel.L1  # 亏损超 L1
        assert circuit_level(0.01, 0.11, 0) == CircuitLevel.L1

    # ── L2：红停开仓 ──────────────────────────────────────────────
    def test_l2_daily_loss(self):
        """单日亏损 6% > 5% → L2"""
        assert circuit_level(-0.06, 0.05, 0) == CircuitLevel.L2

    def test_l2_cum_dd(self):
        """累计回撤 16% > 15% → L2"""
        assert circuit_level(0.01, 0.16, 0) == CircuitLevel.L2

    def test_l2_overrides_l1(self):
        """L2 条件满足时不应返回 L1"""
        assert circuit_level(-0.06, 0.16, 0) == CircuitLevel.L2

    # ── L3：紧急降阶 ──────────────────────────────────────────────
    def test_l3_cum_dd(self):
        """累计回撤 21% > 20% → L3"""
        assert circuit_level(0.01, 0.21, 0) == CircuitLevel.L3

    def test_l3_ic_fail(self):
        """因子失效 60% > 50% → L3"""
        assert circuit_level(0.0, 0.0, 0.6) == CircuitLevel.L3

    def test_l3_overrides_l2(self):
        """L3 条件满足时不应返回 L2"""
        assert circuit_level(-0.06, 0.21, 0) == CircuitLevel.L3

    # ── 边界值：严格大于（不是 >=） ──────────────────────────────
    def test_boundary_exact_3pct(self):
        """单日亏损恰好 3% → 应为 L0（阈值是 > 非 >=）"""
        assert circuit_level(-0.03, 0.0, 0) == CircuitLevel.L0

    def test_boundary_exact_5pct(self):
        """单日亏损恰好 5% → 应为 L1（阈值是 > 非 >=）"""
        assert circuit_level(-0.05, 0.0, 0) == CircuitLevel.L1

    def test_boundary_exact_10pct(self):
        """累计回撤恰好 10% → 应为 L0"""
        assert circuit_level(0.0, 0.10, 0) == CircuitLevel.L0

    def test_boundary_exact_15pct(self):
        """累计回撤恰好 15% → 应为 L1"""
        assert circuit_level(0.0, 0.15, 0) == CircuitLevel.L1

    def test_boundary_exact_20pct(self):
        """累计回撤恰好 20% → 应为 L2"""
        assert circuit_level(0.0, 0.20, 0) == CircuitLevel.L2

    def test_boundary_exact_ic_fail(self):
        """因子失效恰好 50% → 应为 L0（阈值是 > 非 >=）"""
        assert circuit_level(0.0, 0.0, 0.50) == CircuitLevel.L0

    # ── 字符串接口 ────────────────────────────────────────────────
    def test_circuit_level_str(self):
        assert circuit_level_str(-0.04, 0.05, 0) == "L1"
        assert circuit_level_str(0.01, 0.16, 0) == "L2"
        assert circuit_level_str(0.01, 0.21, 0) == "L3"

    # ── 动作描述 ─────────────────────────────────────────────────
    def test_describe_action(self):
        assert "正常" in describe_action(CircuitLevel.L0)
        assert "预警" in describe_action(CircuitLevel.L1)
        assert "停开仓" in describe_action(CircuitLevel.L2)
        assert "紧急降阶" in describe_action(CircuitLevel.L3)
        assert "不自动下单" not in describe_action(CircuitLevel.L3)  # 描述里不含，但 D6 要求如此


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
