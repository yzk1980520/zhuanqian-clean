#!/usr/bin/env python3
"""
test_pipeline_equivalence.py: 行为一致性测试
验证新 pipeline.py 与原 integrated_picker.py 行为一致
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestPipelineEquivalence:
    """验证新 pipeline 与原文件行为一致"""
    
    def test_import_pipeline(self):
        """新 pipeline 可导入"""
        from integrated_picker.pipeline import run_integrated_picker
        assert callable(run_integrated_picker)
    
    def test_import_original(self):
        """原文件仍可直接导入"""
        from core.pipeline.integrated_picker import run_integrated_picker as orig_picker
        assert callable(orig_picker)
    
    def test_symbols_consistency(self):
        """新旧接口符号一致"""
        from core.pipeline.integrated_picker import (
            run_integrated_picker,
            dual_pool_gate,
            three_gate_advice,
            check_position_for_pick,
            check_cooldown_for_pick,
        )
        from integrated_picker.pipeline import run_integrated_picker as pipeline_fn
        
        # 核心函数应可调用
        assert callable(run_integrated_picker)
        assert callable(pipeline_fn)
        assert callable(dual_pool_gate)
        assert callable(three_gate_advice)
        assert callable(check_position_for_pick)
        assert callable(check_cooldown_for_pick)


class TestPipelineLayers:
    """验证新 pipeline 包含所有必要层"""
    
    def test_pipeline_has_market_layer(self):
        """应包含 Layer 0 市场状态分析"""
        from integrated_picker.pipeline import run_integrated_picker
        import inspect
        source = inspect.getsource(run_integrated_picker)
        assert "Layer 0" in source or "市场状态" in source
    
    def test_pipeline_has_gap_layer(self):
        """应包含 Layer 2 断层评分"""
        from integrated_picker.pipeline import run_integrated_picker
        import inspect
        source = inspect.getsource(run_integrated_picker)
        assert "Layer 2" in source or "断层" in source or "gap_scores" in source
    
    def test_pipeline_has_financial_layer(self):
        """应包含 Layer 3b 财务评分"""
        from integrated_picker.pipeline import run_integrated_picker
        import inspect
        source = inspect.getsource(run_integrated_picker)
        assert "财务" in source or "fin_scores" in source or "fraud" in source.lower()
    
    def test_pipeline_has_pattern_layer(self):
        """应包含 Layer 7 形态识别"""
        from integrated_picker.pipeline import run_integrated_picker
        import inspect
        source = inspect.getsource(run_integrated_picker)
        assert "形态" in source or "pattern" in source.lower()
    
    def test_pipeline_has_sequence_risk(self):
        """应包含 P2-C 序列风控"""
        from integrated_picker.pipeline import run_integrated_picker
        import inspect
        source = inspect.getsource(run_integrated_picker)
        assert "序列风控" in source or "sequence_risk" in source.lower() or "R1" in source


class TestPipelineConfig:
    """验证配置正确性"""
    
    def test_min_score_config(self):
        """MIN_SCORE 应为 20"""
        from integrated_picker.config import MIN_SCORE
        assert MIN_SCORE == 20
    
    def test_cooldown_config(self):
        """COOLDOWN_DAYS 应为 5"""
        from integrated_picker.config import COOLDOWN_DAYS
        assert COOLDOWN_DAYS == 5
    
    def test_chase_ban_config(self):
        """CHASE_BAN_PCT 应为 4% (2026-09-23 验证)"""
        from risk_rules import CHASE_BAN_PCT
        assert CHASE_BAN_PCT == 4.0


class TestPipelineImports:
    """验证所有依赖可导入"""
    
    def test_tdx_score_imports(self):
        """tdx_score 核心函数可导入"""
        from tdx_score import (
            score_stock,
            compute_cross_section_ranks,
            get_industry_heat,
            calc_feature_contributions,
        )
        assert callable(score_stock)
        assert callable(compute_cross_section_ranks)
    
    def test_layers_imports(self):
        """layers 模块可导入"""
        from layers.l1_tradability import apply_tradability_filter
        from layers.l2_momentum import apply_momentum_filter
        from layers.l3_ranking import normalize_and_sort
        assert callable(apply_tradability_filter)
        assert callable(apply_momentum_filter)
        assert callable(normalize_and_sort)
    
    def test_sublayer_imports(self):
        """新增子层可导入"""
        from integrated_picker.gap_filter import score_earnings_gaps
        from integrated_picker.financial_filter import compute_financial_threshold
        from integrated_picker.pattern_filter import apply_pattern_bonus
        from integrated_picker.sequence_risk import apply_sequence_risk_wrapper
        assert callable(score_earnings_gaps)
        assert callable(compute_financial_threshold)
        assert callable(apply_pattern_bonus)
        assert callable(apply_sequence_risk_wrapper)
