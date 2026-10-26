#!/usr/bin/env python3
"""
test_layers.py: 过滤层单元测试
覆盖: L1流动性过滤、L2动量筛选、L3评分排序
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestL1Tradability:
    """L1流动性过滤层"""

    def _make_records(self, days=130, close=20.0, amount=2e8):
        """生成足够天数的模拟数据（需>=120天）"""
        return [
            {"close": close, "volume": 1000000, "amount": amount, "date": f"2026-05-{((i-1)%30)+1:02d}"}
            for i in range(1, days+1)
        ]

    def test_st_stock_filtered(self):
        """ST股票应被过滤"""
        from layers.l1_tradability import apply_tradability_filter
        records = self._make_records(close=10.0)
        pass_flag, reason = apply_tradability_filter("000001", "ST测试", records)
        assert pass_flag is False
        assert reason == "st"

    def test_low_price_filtered(self):
        """低价股票应被过滤"""
        from layers.l1_tradability import apply_tradability_filter
        records = self._make_records(close=3.0)
        pass_flag, reason = apply_tradability_filter("600000", "低价股", records)
        assert pass_flag is False
        assert reason == "price"

    def test_low_liq_filtered(self):
        """低流动性股票应被过滤"""
        from layers.l1_tradability import apply_tradability_filter
        records = self._make_records(close=20.0, amount=5e6)
        pass_flag, reason = apply_tradability_filter("600000", "测试", records)
        assert pass_flag is False
        assert reason == "liquidity"

    def test_valid_stock_passed(self):
        """正常股票应通过"""
        from layers.l1_tradability import apply_tradability_filter
        records = self._make_records(close=20.0, amount=2e8)
        pass_flag, reason = apply_tradability_filter("600000", "测试", records)
        assert pass_flag is True
        assert reason is None


class TestApplyMomentumFilter:
    """L2动量筛选"""

    def test_strong_momentum_passed(self):
        """强势股票应通过动量筛选"""
        from layers.l2_momentum import apply_momentum_filter
        top50 = []
        recs_dict = {}
        for i, code in enumerate(["600000", "600001"]):
            records = []
            base_price = 10.0 + i
            for j in range(30):
                records.append({
                    "close": base_price * (1 + j * 0.005),
                    "volume": 500000,
                    "amount": 5e8,
                    "date": f"2026-09-{j+1:02d}"
                })
            recs_dict[code] = records
            top50.append((90.0, 85.0, code, "测试", "银行", [], [], 0, ""))

        result = apply_momentum_filter(top50, recs_dict, min_mom_5d=3.0)
        assert len(result) > 0

    def test_weak_momentum_filtered(self):
        """弱势股票应被过滤"""
        from layers.l2_momentum import apply_momentum_filter
        top50 = []
        recs_dict = {}
        for i, code in enumerate(["600000", "600001"]):
            records = []
            base_price = 10.0 + i
            for j in range(30):
                records.append({
                    "close": base_price * (1 - j * 0.003),
                    "volume": 500000,
                    "amount": 5e8,
                    "date": f"2026-09-{j+1:02d}"
                })
            recs_dict[code] = records
            top50.append((70.0, 65.0, code, "测试", "银行", [], [], 0, ""))

        result = apply_momentum_filter(top50, recs_dict, min_mom_5d=3.0)
        assert len(result) < len(top50)


class TestNormalizeAndSort:
    """L3评分排序"""

    def test_sorting_by_score(self):
        """应按分数降序排序"""
        from layers.l3_ranking import normalize_and_sort
        candidates = [
            (85.0, "A", "600000"),
            (92.0, "B", "600001"),
            (78.0, "C", "600002"),
        ]
        result = normalize_and_sort(candidates, top_n=2)
        assert len(result) == 2
        assert result[0][0] >= result[1][0]

    def test_top_n_limit(self):
        """应限制返回数量"""
        from layers.l3_ranking import normalize_and_sort
        candidates = [(i * 10, f"C{i}", f"60000{i}") for i in range(10)]
        result = normalize_and_sort(candidates, top_n=5)
        assert len(result) <= 5
