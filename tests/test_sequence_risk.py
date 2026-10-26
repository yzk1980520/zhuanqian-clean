#!/usr/bin/env python3
"""
test_sequence_risk.py: 轮动序列风控测试
覆盖: 行业避让(R1)/黑天鹅检测(R2)/题材上限(R3)
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ops.sequence_risk import (
    apply_industry_avoidance,
    detect_black_swan_industries,
    apply_topic_cap,
    R1_HEAT_TOP_RATIO,
    R1_DISCOUNT,
    R2_GAP_PCT,
    R2_MIN_TRIGGERS,
    R3_TOPIC_LIMIT,
)


class TestApplyIndustryAvoidance:
    """R1: 行业避让降权测试"""

    def test_no_candidates(self):
        """空候选列表应返回空"""
        candidates = []
        industry_heat_rank = {"白酒": 0.9}
        result, log = apply_industry_avoidance(candidates, industry_heat_rank)
        assert result == []
        assert log["reason"] == "no_candidates_or_no_heat"

    def test_no_heat_data(self):
        """无热度数据应不修改"""
        candidates = [
            {"code": "sh600000", "name": "浦发银行", "final_score": 80, "industry": "银行"}
        ]
        result, log = apply_industry_avoidance(candidates, {})
        assert len(result) == 1
        assert result[0]["final_score"] == 80  # 未修改

    def test_healthy_industry(self):
        """健康行业不应降权"""
        candidates = [
            {"code": "sh600000", "final_score": 80, "industry": "银行"}
        ]
        industry_heat_rank = {
            "银行": {"percentile": 0.3}  # 低热度
        }
        result, log = apply_industry_avoidance(candidates, industry_heat_rank)
        assert result[0]["final_score"] == 80
        assert log["avoided"] == []

    def test_overheated_industry(self):
        """过热行业应降权"""
        candidates = [
            {"code": "sh600000", "final_score": 80, "industry": "白酒"}
        ]
        industry_heat_rank = {
            "白酒": {"percentile": 0.95}  # 高热度，超过0.75阈值
        }
        result, log = apply_industry_avoidance(candidates, industry_heat_rank)
        # 80 * 0.8 = 64
        assert result[0]["final_score"] == 64.0
        assert result[0]["_seq_avoided"] is True
        assert len(log["avoided"]) == 1
        assert log["avoided"][0]["code"] == "sh600000"

    def test_multiple_candidates_mixed(self):
        """混合场景：部分行业过热"""
        candidates = [
            {"code": "sh600000", "final_score": 90, "industry": "白酒"},
            {"code": "sh600001", "final_score": 85, "industry": "银行"},
            {"code": "sh600002", "final_score": 80, "industry": "白酒"},
        ]
        industry_heat_rank = {
            "白酒": {"percentile": 0.95},  # 过热
            "银行": {"percentile": 0.3},   # 健康
        }
        result, log = apply_industry_avoidance(candidates, industry_heat_rank)
        # 白酒降权，银行不变
        assert result[0]["final_score"] == 72.0  # 90 * 0.8
        assert result[1]["final_score"] == 85.0  # 不变
        assert result[2]["final_score"] == 64.0  # 80 * 0.8
        assert len(log["avoided"]) == 2

    def test_missing_score_field(self):
        """缺少score字段时应跳过"""
        candidates = [
            {"code": "sh600000", "name": "测试", "industry": "白酒"}
        ]
        industry_heat_rank = {"白酒": {"percentile": 0.95}}
        result, log = apply_industry_avoidance(candidates, industry_heat_rank)
        assert len(result) == 1
        assert "_seq_avoided" not in result[0]


class TestDetectBlackSwan:
    """R2: 行业黑天鹅检测测试"""

    def test_empty_input(self):
        """空输入应返回空集合"""
        result, log = detect_black_swan_industries([])
        assert result == set()
        assert log["total_triggered"] == 0

    def test_no_trigger(self):
        """无触发条件应返回空"""
        stocks = [
            {"code": "sh600000", "industry": "银行", "gap_pct": -5.0},
            {"code": "sh600001", "industry": "银行", "gap_pct": -3.0},
        ]
        result, log = detect_black_swan_industries(stocks)
        assert result == set()

    def test_single_trigger(self):
        """单只个股触发不应拉黑行业"""
        stocks = [
            {"code": "sh600000", "industry": "白酒", "gap_pct": -20.0},
        ]
        result, log = detect_black_swan_industries(stocks)
        # 需要≥2只才触发
        assert result == set()

    def test_multiple_trigger(self):
        """多只个股触发应拉黑行业"""
        stocks = [
            {"code": "sh600000", "industry": "白酒", "gap_pct": -20.0},
            {"code": "sh600001", "industry": "白酒", "gap_pct": -18.0},
            {"code": "sh600002", "industry": "银行", "gap_pct": -25.0},
        ]
        result, log = detect_black_swan_industries(stocks)
        assert "白酒" in result
        # 银行只有1只触发，不拉黑
        assert "银行" not in result

    def test_custom_threshold(self):
        """自定义阈值应生效"""
        stocks = [
            {"code": "sh600000", "industry": "电子", "gap_pct": -10.0},
            {"code": "sh600001", "industry": "电子", "gap_pct": -10.0},
        ]
        result, log = detect_black_swan_industries(stocks, gap_threshold=-8.0, min_triggers=2)
        assert "电子" in result


class TestApplyTopicCap:
    """R3: 题材上限测试"""

    def test_within_limit(self):
        """候选数未超限应保留所有"""
        candidates = [
            {"code": "sh600000", "topic": "白酒", "final_score": 90},
            {"code": "sh600001", "topic": "白酒", "final_score": 85},
        ]
        result, log = apply_topic_cap(candidates, topic_limit=3)
        assert len(result) == 2

    def test_over_limit(self):
        """候选数超限应按分数截断"""
        candidates = [
            {"code": "sh600000", "topic": "白酒", "final_score": 90},
            {"code": "sh600001", "topic": "白酒", "final_score": 85},
            {"code": "sh600002", "topic": "白酒", "final_score": 80},
            {"code": "sh600003", "topic": "白酒", "final_score": 75},
        ]
        result, log = apply_topic_cap(candidates, topic_limit=3)
        assert len(result) == 3
        # 应按分数排序后截断
        scores = [c["final_score"] for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_multiple_topics(self):
        """多个题材应各自计数"""
        candidates = [
            {"code": "sh600000", "industry": "白酒", "final_score": 90},
            {"code": "sh600001", "industry": "白酒", "final_score": 85},
            {"code": "sh600002", "industry": "白酒", "final_score": 80},
            {"code": "sh600003", "industry": "银行", "final_score": 95},
            {"code": "sh600004", "industry": "银行", "final_score": 90},
        ]
        result, log = apply_topic_cap(candidates, topic_limit=2)
        # 白酒保留2只，银行保留2只
        baijiu = [c for c in result if c.get("industry") == "白酒"]
        bank = [c for c in result if c.get("industry") == "银行"]
        assert len(baijiu) == 2
        assert len(bank) == 2

    def test_missing_topic(self):
        """缺少topic字段应归类为未知"""
        candidates = [
            {"code": "sh600000", "final_score": 90},
            {"code": "sh600001", "final_score": 85},
        ]
        result, log = apply_topic_cap(candidates, topic_limit=1)
        # 应只保留最高分的
        assert len(result) == 1


class TestConfigurationConstants:
    """配置常量验证"""

    def test_r1_constants(self):
        """R1配置应符合预期"""
        assert R1_HEAT_TOP_RATIO == 0.25
        assert R1_DISCOUNT == 0.8

    def test_r2_constants(self):
        """R2配置应符合预期"""
        assert R2_GAP_PCT == -15.0
        assert R2_MIN_TRIGGERS == 2

    def test_r3_constants(self):
        """R3配置应符合预期"""
        assert R3_TOPIC_LIMIT == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
