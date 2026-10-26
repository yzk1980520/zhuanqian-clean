# -*- coding: utf-8 -*-
"""
DL模型门禁测试 - IC/IR/单调性检验
==================================

Author: 老三 (技术验证专家)
Date: 2026-09-24

门禁标准:
- IC_mean > 0.03
- ICIR > 0.3
- 单调性检验通过
- 滚动正IC窗口 >= 3
"""

import sys
import os
import numpy as np
import pytest
from pathlib import Path

# Add project to path
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from scripts.train_dl_model import (
    rank_ic, compute_ic_ir, check_monotonicity, rolling_positive_windows,
    IC_THRESHOLD, IR_THRESHOLD, MIN_ROLLING_POS, ROLLING_WIN,
)


# ============================================================================
# Test IC/IR Computation
# ============================================================================

class TestICIR:
    def test_rank_ic_perfect_correlation(self):
        """完美正相关IC=1"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([1, 2, 3, 4, 5])
        ic = rank_ic(x, y)
        assert abs(ic - 1.0) < 1e-6

    def test_rank_ic_perfect_negative(self):
        """完美负相关IC=-1"""
        x = np.array([1, 2, 3, 4, 5])
        y = np.array([5, 4, 3, 2, 1])
        ic = rank_ic(x, y)
        assert abs(ic - (-1.0)) < 1e-6

    def test_rank_ic_no_correlation(self):
        """无相关性IC≈0"""
        np.random.seed(42)
        x = np.random.randn(100)
        y = np.random.randn(100)
        ic = rank_ic(x, y)
        assert abs(ic) < 0.2  # 小样本可能不完全为0

    def test_compute_ic_ir_empty(self):
        """空数据返回0"""
        ic_mean, ic_std, ic_vals = compute_ic_ir([], [], window=10)
        assert ic_mean == 0.0
        assert ic_std == 0.0

    def test_compute_ic_ir_short_series(self):
        """短序列正确处理"""
        np.random.seed(42)
        preds = np.random.randn(20)
        targets = np.random.randn(20)
        ic_mean, ic_std, ic_vals = compute_ic_ir(preds, targets, window=10)
        assert isinstance(ic_mean, float)
        assert isinstance(ic_std, float)

    def test_icir_formula(self):
        """ICIR = IC_mean / IC_std"""
        np.random.seed(42)
        preds = np.random.randn(1000)
        targets = np.random.randn(1000)
        ic_mean, ic_std, _ = compute_ic_ir(preds, targets, window=50)
        if ic_std > 0:
            expected_icir = ic_mean / ic_std
            # 通过rolling方式验证
            ic_vals = []
            for i in range(50, 1000):
                ic = rank_ic(preds[i-50:i], targets[i-50:i])
                ic_vals.append(ic)
            arr = np.array(ic_vals)
            assert abs(ic_mean - arr.mean()) < 1e-6
            assert abs(ic_std - arr.std()) < 1e-6


# ============================================================================
# Test Monotonicity Check
# ============================================================================

class TestMonotonicity:
    def test_perfect_monotonic_increase(self):
        """完美单调递增"""
        preds = np.arange(100)
        targets = np.arange(100) * 0.1
        assert check_monotonicity(preds, targets) is True

    def test_perfect_monotonic_decrease(self):
        """完美单调递减"""
        preds = np.arange(100)
        targets = -np.arange(100) * 0.1
        assert check_monotonicity(preds, targets) is True

    def test_random_no_strict_monotonic(self):
        """随机数据不一定通过严格单调性检验"""
        np.random.seed(42)
        preds = np.random.randn(200)
        targets = np.random.randn(200)
        # 可能通过也可能不通过，但不应报错
        result = check_monotonicity(preds, targets)
        assert isinstance(result, bool)

    def test_group_size_consistency(self):
        """分组大小一致"""
        preds = np.arange(100)
        targets = np.arange(100) * 0.01
        # 应该单调递增
        assert check_monotonicity(preds, targets, n_groups=5) is True


# ============================================================================
# Test Rolling Positive Windows
# ============================================================================

class TestRollingWindows:
    def test_all_positive(self):
        """所有窗口IC都为正"""
        np.random.seed(42)
        # 创建高度相关的预测和真实值
        base = np.random.randn(500)
        preds = base + np.random.randn(500) * 0.1
        targets = base + np.random.randn(500) * 0.1
        pos, total = rolling_positive_windows(preds, targets, win=50, step=50)
        assert pos >= total * 0.8  # 至少80%窗口为正

    def test_all_negative(self):
        """所有窗口IC都为负"""
        np.random.seed(42)
        base = np.random.randn(500)
        preds = -base + np.random.randn(500) * 0.1
        targets = base + np.random.randn(500) * 0.1
        pos, total = rolling_positive_windows(preds, targets, win=50, step=50)
        assert pos <= total * 0.2  # 至多20%窗口为正

    def test_threshold_check(self):
        """阈值检查逻辑正确"""
        np.random.seed(42)
        preds = np.random.randn(300)
        targets = np.random.randn(300)
        pos, total = rolling_positive_windows(preds, targets, win=50, step=50)
        assert pos <= total
        assert pos >= 0


# ============================================================================
# Test Gate Pass Logic
# ============================================================================

class TestGateLogic:
    def test_all_pass(self):
        """所有门禁都通过"""
        ic_mean = 0.05  # > 0.03
        icir = 0.5      # > 0.3
        mono = True
        pos_windows = 5  # >= 3
        total_windows = 10

        ic_pass = abs(ic_mean) > IC_THRESHOLD
        ir_pass = abs(icir) > IR_THRESHOLD
        mono_pass = mono
        roll_pass = pos_windows >= MIN_ROLLING_POS

        assert ic_pass is True
        assert ir_pass is True
        assert mono_pass is True
        assert roll_pass is True

    def test_one_fail(self):
        """一个门禁失败则整体失败"""
        ic_mean = 0.02  # < 0.03 (失败)
        icir = 0.5
        mono = True
        pos_windows = 5

        ic_pass = abs(ic_mean) > IC_THRESHOLD
        ir_pass = abs(icir) > IR_THRESHOLD
        mono_pass = mono
        roll_pass = pos_windows >= MIN_ROLLING_POS

        gate_pass = ic_pass and ir_pass and mono_pass and roll_pass
        assert gate_pass is False

    def test_threshold_values(self):
        """阈值常量正确"""
        assert IC_THRESHOLD == 0.03
        assert IR_THRESHOLD == 0.3
        assert MIN_ROLLING_POS == 3
        assert ROLLING_WIN == 60


# ============================================================================
# Test End-to-End with Sample Data
# ============================================================================

class TestEndToEnd:
    def test_full_pipeline(self):
        """完整评估流程"""
        np.random.seed(42)
        # 模拟真实数据
        n = 1000
        preds = np.random.randn(n)
        targets = preds + np.random.randn(n) * 0.5  # 有一定相关性

        ic_mean, ic_std, ic_series = compute_ic_ir(preds, targets, window=ROLLING_WIN)
        mono = check_monotonicity(preds, targets)
        pos_wins, tot_wins = rolling_positive_windows(preds, targets)

        # 输出结果应为合理值
        assert isinstance(ic_mean, float)
        assert isinstance(ic_std, float)
        assert 0 <= mono <= 1  # 实际上应该是bool
        assert pos_wins <= tot_wins


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
