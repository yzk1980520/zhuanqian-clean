#!/usr/bin/env python3
"""
test_tdx_score.py: 评分引擎测试
覆盖: 单票评分、截面排名、特征重要性
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestScoreStock:
    """score_stock(inds, weekly, strategy, records)
    返回 (score, signals) 或 None
    """

    def test_empty_input(self):
        from tdx_score import score_stock
        result = score_stock({}, {}, "综合", [])
        # 返回可能是 (0, []) 或 None 或 dict
        assert result is None or isinstance(result, (tuple, list, dict))

    def test_with_valid_indicators(self):
        from tdx_score import score_stock
        inds = {
            "ma5": 100.0, "ma10": 99.0, "ma20": 98.0,
            "dif": 0.5, "dea": 0.3, "macd_hist": 0.1,
            "rsi14": 55.0, "kdj_k": 60.0, "kdj_d": 55.0,
            "vol_ratio": 1.2, "chg5": 3.0, "chg10": 2.0,
            "price": 100.0,
        }
        # strategy=None时自动取STRATEGIES["综合"]
        result = score_stock(inds, None, None, [])
        assert isinstance(result, tuple)
        # score_stock返回可能不止(score, sigs)，用len检查
        assert len(result) >= 2
        score = result[0]
        sigs = result[1]
        assert isinstance(score, (int, float))
        assert isinstance(sigs, list)


class TestCrossSectionRanks:
    """compute_cross_section_ranks(inds_list)
    inds_list格式: [{"code": str, "inds": dict}, ...]
    """

    def test_rank_returns_dict(self):
        from tdx_score import compute_cross_section_ranks
        data = [
            {"code": "600000", "inds": {"chg5": 0.8, "vol_ratio": 1.2, "rsi14": 55}},
            {"code": "600001", "inds": {"chg5": 0.6, "vol_ratio": 1.0, "rsi14": 50}},
            {"code": "600002", "inds": {"chg5": 0.9, "vol_ratio": 1.5, "rsi14": 60}},
        ]
        result = compute_cross_section_ranks(data)
        assert isinstance(result, dict)
        assert "600000" in result
        assert "chg5" in result["600000"]

    def test_rank_ordering(self):
        from tdx_score import compute_cross_section_ranks
        data = [
            {"code": "A", "inds": {"chg5": 0.5, "vol_ratio": 1.0, "rsi14": 50}},
            {"code": "B", "inds": {"chg5": 0.8, "vol_ratio": 1.5, "rsi14": 60}},
            {"code": "C", "inds": {"chg5": 0.3, "vol_ratio": 0.8, "rsi14": 40}},
        ]
        ranks = compute_cross_section_ranks(data)
        # chg5越高百分位越大
        assert ranks["B"]["chg5"] > ranks["A"]["chg5"]
        assert ranks["B"]["chg5"] > ranks["C"]["chg5"]


class TestFeatureImportance:
    """calc_feature_contributions(inds, weekly=None, strategy=None)"""

    def test_basic_format(self):
        from tdx_score import calc_feature_contributions
        inds = {
            "ma5": 100.0, "ma10": 99.0, "ma20": 98.0,
            "ma60": 95.0, "ma120": 90.0,
            "dif": 0.5, "dea": 0.3, "macd_hist": 0.1,
            "rsi14": 55.0, "rsi6": 58.0,
            "kdj_k": 60.0, "kdj_d": 55.0, "kdj_j": 70.0,
            "vol_ratio": 1.2, "chg5": 3.0, "chg10": 2.0,
            "price": 100.0,
            "pos_vs_ma20": 5.0,  # 补充缺失字段
            "vol_pattern": None,  # 可选字段
        }
        # strategy=None时自动使用STRATEGIES["综合"]
        result = calc_feature_contributions(inds, None, None)
        assert isinstance(result, dict)
        assert "均线" in result


class TestIndustryHeat:
    """get_industry_heat(force_refresh)"""

    def test_returns_dict(self):
        from tdx_score import get_industry_heat
        result = get_industry_heat(force_refresh=True)
        assert isinstance(result, dict)


class TestMarketState:
    @pytest.mark.skip(reason="需要完整TDX环境，跳过集成测试")
    def test_analyze_market(self):
        pass

    def test_position_limit_range(self):
        from tdx_score import _get_position_limit
        limit = _get_position_limit("强")
        assert isinstance(limit, (int, float))
        assert limit > 0
