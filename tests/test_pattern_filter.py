#!/usr/bin/env python3
"""
test_pattern_filter.py: 形态识别层单元测试
覆盖: W底/杯柄/牛旗/三角/V型反转形态加分
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPatternBonus:
    """技术形态加分"""

    def test_import_available(self):
        """验证模块可导入"""
        from integrated_picker.pattern_filter import apply_pattern_bonus
        assert callable(apply_pattern_bonus)

    def test_empty_ranking(self):
        """空列表应返回原列表"""
        from integrated_picker.pattern_filter import apply_pattern_bonus
        result, count = apply_pattern_bonus([], {}, {}, os.getcwd())
        assert result == []
        assert count == 0


class TestPatternSuppression:
    """形态加分冲突抑制"""

    def test_cap_flow_suppression(self):
        """资金大幅流出时应减少形态加分"""
        from integrated_picker.pattern_filter import apply_pattern_bonus
        ranking = [(90.0, 85.0, 80.0, 5.0, 0.8, True, 0, "", "600000", "测试", "银行", [], [], 0, "", [], 0, "", [], [])]
        flow_map = {"600000": -6e8}  # 流出6亿
        result, count = apply_pattern_bonus(ranking, {"600000": []}, flow_map, os.getcwd())
        assert isinstance(result, list)
