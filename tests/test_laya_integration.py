#!/usr/bin/env python3
"""
test_laya_integration.py: Laya 集成层测试
"""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['USE_TF'] = '0'

try:
    from factors.laya_integration import (
        LayaDecisionEngine,
        DecisionRequest,
        DecisionResult,
        create_decision_engine,
        quick_classify
    )
    # 检查 laya 包是否安装
    try:
        import laya
        HAS_LAYA = True
    except ImportError:
        HAS_LAYA = False
    HAS_INTEGRATION = True
except ImportError as e:
    HAS_INTEGRATION = False
    HAS_LAYA = False
    print(f"Integration test skipped: {e}")


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 集成族(依赖本地模型, 单次 5-10s 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_INTEGRATION or not HAS_LAYA, reason="laya_integration module or laya package not available")
class TestLayaDecisionEngine:
    """测试 LayaDecisionEngine"""
    
    @pytest.fixture(scope="class")
    def engine(self):
        """创建引擎实例（类级别共享）"""
        return create_decision_engine()
    
    def test_engine_creation(self):
        """测试引擎创建"""
        engine = create_decision_engine()
        assert isinstance(engine, LayaDecisionEngine)
        assert "laya-typed-decisions" in engine.model_path
    
    def test_engine_stats_initial(self, engine):
        """测试初始统计"""
        stats = engine.get_stats()
        assert stats["calls"] == 0
        assert stats["errors"] == 0
        assert stats["error_rate"] == 0.0
    
    def test_classify_task_basic(self, engine):
        """测试基本任务分类"""
        req = DecisionRequest(
            task_type="选股",
            description="对候选池进行多因子评分"
        )
        result = engine.classify_task(req)
        
        assert isinstance(result, DecisionResult)
        assert hasattr(result, "decision")
        assert hasattr(result, "confidence")
        assert hasattr(result, "metadata")
    
    def test_classify_task_returns_valid_category(self, engine):
        """测试分类结果有效性"""
        req = DecisionRequest(
            task_type="选股",
            description="多因子选股"
        )
        result = engine.classify_task(req)
        
        valid_categories = [
            "multi_factor_selection", "pattern_selection", 
            "rotation_selection", "risk_assessment",
            "backtest_analysis", "data_management", "system_maintenance"
        ]
        assert result.decision in valid_categories or result.decision == "unknown"
    
    def test_classify_task_with_high_urgency(self, engine):
        """测试紧急任务分类"""
        req = DecisionRequest(
            task_type="风控",
            description="止损触发检查",
            urgency="critical"
        )
        result = engine.classify_task(req)
        
        assert result.confidence >= 0
        assert result.confidence <= 1
    
    def test_risk_assessment(self, engine):
        """测试市场风险评估"""
        market_conditions = {
            "sh_index": 3150.5,
            "change_pct": -0.8,
            "volume_ratio": 1.2,
            "volatility_20d": 0.25
        }
        result = engine.risk_assessment(market_conditions)
        
        assert isinstance(result, DecisionResult)
        assert hasattr(result, "decision")
    
    def test_error_handling(self):
        """测试错误处理（无模型时）"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # 使用不存在的模型路径
            engine = LayaDecisionEngine(model_path=os.path.join(tmpdir, "nonexistent"))
            
            # 访问 .agent 应触发 FileNotFoundError
            with pytest.raises(FileNotFoundError):
                _ = engine.agent


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 集成族(依赖本地模型, 单次 5-10s 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_INTEGRATION or not HAS_LAYA, reason="laya_integration module or laya package not available")
class TestQuickClassify:
    """测试便捷函数"""

    def test_quick_classify_returns_dict(self):
        """测试 quick_classify 返回格式"""
        result = quick_classify("选股", "多因子评分")

        assert isinstance(result, dict)
        assert "decision" in result
        assert "confidence" in result
        assert "requires_human" in result

    def test_quick_classify_confidence_range(self):
        """测试置信度范围"""
        result = quick_classify("风控", "止损检查")

        assert 0 <= result["confidence"] <= 1


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 集成族(依赖本地模型, 单次 5-10s 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_INTEGRATION, reason="laya_integration module not available")
class TestIntegrationCompatibility:
    """测试与现有系统的兼容性"""
    
    def test_decision_request_serialization(self):
        """测试请求对象序列化"""
        from dataclasses import asdict
        
        req = DecisionRequest(
            task_type="选股",
            description="多因子评分",
            urgency="high"
        )
        
        d = asdict(req)
        assert d["task_type"] == "选股"
        assert d["urgency"] == "high"
        
        # 验证 JSON 序列化（中文会转义为 Unicode）
        json_str = json.dumps(d, ensure_ascii=False)
        assert "选股" in json_str
    
    def test_decision_result_serialization(self):
        """测试结果对象序列化"""
        result = DecisionResult(
            decision="multi_factor_selection",
            confidence=0.75,
            metadata={"test": True}
        )
        
        from dataclasses import asdict
        d = asdict(result)
        
        assert d["decision"] == "multi_factor_selection"
        assert d["confidence"] == 0.75
        assert d["metadata"]["test"] is True
