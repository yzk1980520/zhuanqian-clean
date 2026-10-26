#!/usr/bin/env python3
"""
沪深主板单票全仓策略回测测试
覆盖：load_stock, get_all_codes, compute_scores, run_backtest
"""
import sys, os, json
import pytest
from unittest.mock import patch
from pathlib import Path

import importlib.util

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(PROJECT, "scripts", "hs300_single_stock_backtest.py")
spec = importlib.util.spec_from_file_location("hs300_module", SCRIPT_PATH)
hs300 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hs300)

load_stock = hs300.load_stock
get_all_codes = hs300.get_all_codes
compute_scores = hs300.compute_scores
ma = hs300.ma
STOP_LOSS = hs300.STOP_LOSS
MAX_HOLD = hs300.MAX_HOLD
COST = hs300.COST
TP_LADDER = hs300.TP_LADDER
WEIGHTS = hs300.WEIGHTS


class TestLoadStock:
    """测试数据加载"""

    def test_valid_code(self):
        """有效代码加载"""
        data = load_stock("sh601118")
        assert data is not None
        assert len(data) > 0
        assert "close" in data[0]

    def test_invalid_code(self):
        """无效代码"""
        data = load_stock("invalid_code")
        assert data is None

    def test_empty_code(self):
        """空代码"""
        data = load_stock("")
        assert data is None


class TestGetAllCodes:
    """测试代码列表"""

    def test_returns_list(self):
        """返回列表"""
        codes = get_all_codes()
        assert isinstance(codes, list)
        assert len(codes) > 0

    def test_only_main_board(self):
        """仅沪深主板"""
        codes = get_all_codes()
        for code in codes[:10]:
            assert (code.startswith("sh60") or code.startswith("sh61") or
                    code.startswith("sz000") or code.startswith("sz001") or code.startswith("sz002"))


class TestComputeScores:
    """测试评分计算"""

    def test_insufficient_data(self):
        """数据不足"""
        score = compute_scores([{"close": 10}] * 50)
        assert score["total"] == 0

    def test_basic_flow(self):
        """基本流程"""
        # 生成60条模拟数据
        bars = []
        price = 10.0
        for i in range(60):
            price += 0.1
            bars.append({"close": price, "volume": 1000000 + i * 10000})
        
        score = compute_scores(bars)
        assert 0 <= score["total"] <= 100

    def test_constants(self):
        """常量验证"""
        assert STOP_LOSS == -0.08
        assert MAX_HOLD == 20
        assert COST == 0.001

    def test_tp_ladder(self):
        """止盈阶梯验证"""
        assert len(TP_LADDER) == 4
        # 阶梯递增（回撤越大）
        thresholds = [dd for _, dd in TP_LADDER]
        for i in range(len(thresholds) - 1):
            assert thresholds[i] <= thresholds[i + 1]

    def test_weights_sum(self):
        """权重和=1"""
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 0.01


class TestMA:
    """测试MA计算"""

    def test_normal(self):
        """正常"""
        result = ma([1, 2, 3, 4, 5], 5)
        assert result == 3.0

    def test_partial(self):
        """不足n"""
        result = ma([1, 2], 5)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
