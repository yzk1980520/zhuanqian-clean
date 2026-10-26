#!/usr/bin/env python3
"""
test_gap_filter.py: 断层评分层单元测试
覆盖: batch_score_gaps, 强断层Bonus, gap_pool构建
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestGapFilter:
    """断层评分层测试"""

    def test_import_available(self):
        """验证模块可导入"""
        from integrated_picker.gap_filter import score_earnings_gaps, apply_strong_gap_bonus, build_gap_pool
        assert callable(score_earnings_gaps)
        assert callable(apply_strong_gap_bonus)
        assert callable(build_gap_pool)

    def test_empty_top_codes(self):
        """空股票列表应返回空字典"""
        from integrated_picker.gap_filter import score_earnings_gaps
        result = score_earnings_gaps([], {}, {}, None)
        assert result == {}

    def test_build_gap_pool_disabled(self):
        """断层策略关闭时应返回空字典"""
        from integrated_picker.gap_filter import build_gap_pool
        result = build_gap_pool(False, [], {}, {})
        assert result == {}

    def test_strong_gap_bonus_structure(self):
        """强断层Bonus应保持数据结构"""
        from integrated_picker.gap_filter import apply_strong_gap_bonus
        gap_scores = {
            "600000": (5.0, "断层", ["断层信号"]),
        }
        count = apply_strong_gap_bonus(gap_scores, ["600000"], os.getcwd(), threshold=0.50, bonus=8)
        assert isinstance(count, int)
        # 取决于financial_cache是否存在
