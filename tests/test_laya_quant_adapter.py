#!/usr/bin/env python3
"""
test_laya_quant_adapter.py: Laya 量化适配器测试
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['USE_TF'] = '0'

try:
    from factors.laya_quant_adapter import LayaQuantAdapter, quick_market_analysis
    # 检查 laya 包是否安装
    try:
        import laya
        HAS_LAYA = True
    except ImportError:
        HAS_LAYA = False
    HAS_ADAPTER = True
except ImportError as e:
    HAS_ADAPTER = False
    HAS_LAYA = False
    print(f"Adapter test skipped: {e}")


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 量化适配族(依赖本地模型推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_ADAPTER or not HAS_LAYA, reason="laya_quant_adapter or laya package not available")
class TestLayaQuantAdapter:
    """测试 Laya 量化适配器"""
    
    @pytest.fixture(scope="class")
    def adapter(self):
        return LayaQuantAdapter()
    
    def test_adapter_creation(self):
        """测试适配器创建"""
        adapter = LayaQuantAdapter()
        assert adapter is not None
        assert adapter.model_path.endswith("laya-typed-decisions")
    
    def test_analyze_market_regime(self, adapter):
        """测试市场状态分析"""
        market_data = {
            "sh_index": 3150.5,
            "ma250": 3100.0,
            "volume_ratio": 1.2,
            "change_pct": -0.5
        }
        result = adapter.analyze_market_regime(market_data)
        
        assert "regime" in result
        assert result["regime"] in ["bull", "bear", "volatile", "transition", "unknown"]
        assert "confidence" in result
        assert 0 <= result["confidence"] <= 1
    
    def test_analyze_bear_market(self, adapter):
        """测试熊市分析"""
        result = adapter.analyze_market_regime({
            "sh_index": 2900.0,
            "ma250": 3100.0,
            "volume_ratio": 0.8,
            "change_pct": -2.5
        })
        
        assert result["regime"] in ["bear", "volatile", "transition"]
        assert result.get("position_pct", 50) < 50  # 熊市应建议低仓位
    
    def test_classify_stop_loss_signal(self, adapter):
        """测试止损信号分类"""
        signal = adapter.classify_risk_signal({
            "stock_code": "600000",
            "price_change_5d": -12.0,
            "volume_change": 2.0,
            "rsi_14": 20.0
        })
        
        assert signal.signal_type in ["stop_loss", "reduce_position", "sell", "unknown"]
        assert signal.confidence >= 0
    
    def test_classify_take_profit_signal(self, adapter):
        """测试止盈信号分类"""
        signal = adapter.classify_risk_signal({
            "stock_code": "000001",
            "price_change_5d": 18.0,
            "volume_change": 1.5,
            "rsi_14": 75.0
        })
        
        assert signal.signal_type in ["take_profit", "hold", "unknown"]
    
    def test_evaluate_buy_decision(self, adapter):
        """测试买入决策评估"""
        result = adapter.evaluate_stock_decision({
            "code": "000001",
            "price": 15.8,
            "chg5": 3.2,
            "volume_ratio": 1.8,
            "rsi_6": 65.0
        })
        
        assert "action" in result
        assert result["action"] in ["buy", "hold", "sell", "avoid", "unknown"]
        assert "confidence" in result
    
    def test_stats_tracking(self, adapter):
        """测试统计跟踪"""
        initial_queries = adapter.get_stats()["queries"]
        initial_errors = adapter.get_stats()["errors"]
        
        # 执行几次分析
        adapter.analyze_market_regime({"sh_index": 3100, "ma250": 3050, "volume_ratio": 1.0})
        adapter.classify_risk_signal({"stock_code": "600000", "price_change_5d": -5.0})
        
        stats = adapter.get_stats()
        assert stats["queries"] >= initial_queries + 2
        assert stats["errors"] == initial_errors  # 应该没有错误
    
    def test_error_handling_invalid_data(self, adapter):
        """测试错误处理"""
        # 传入无效数据应返回 safe 结果而非崩溃
        result = adapter.analyze_market_regime({})
        assert result.get("regime", "unknown") in [
            "bull", "bear", "volatile", "transition", "unknown"
        ]


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 量化适配族(依赖本地模型推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_ADAPTER or not HAS_LAYA, reason="laya_quant_adapter or laya package not available")
class TestQuickMarketAnalysis:
    """测试便捷函数"""

    def test_quick_analysis_returns_dict(self):
        result = quick_market_analysis(3150.0, 3100.0, 1.2)
        assert isinstance(result, dict)
        assert "regime" in result


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 量化适配族(依赖本地模型推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_ADAPTER or not HAS_LAYA, reason="laya_quant_adapter or laya package not available")
class TestEdgeCases:
    """测试边界情况"""

    @pytest.fixture
    def adapter(self):
        return LayaQuantAdapter()
    
    def test_very_low_rsi(self, adapter):
        """超卖情况"""
        signal = adapter.classify_risk_signal({
            "stock_code": "600000",
            "price_change_5d": -15.0,
            "rsi_14": 10.0
        })
        # 不应建议买入
        assert signal.signal_type not in ["buy", "hold"] or signal.confidence < 0.5
    
    def test_very_high_rsi(self, adapter):
        """超买情况"""
        signal = adapter.classify_risk_signal({
            "stock_code": "600000",
            "price_change_5d": 20.0,
            "rsi_14": 85.0
        })
        # 验证输出格式，不验证具体预测值（通用模型未针对A股微调）
        assert signal.signal_type in ["take_profit", "sell", "hold", "reduce_position", "unknown"]
        assert 0 <= signal.confidence <= 1
    
    def test_choppy_market(self, adapter):
        """震荡市分析"""
        result = adapter.analyze_market_regime({
            "sh_index": 3100.0,
            "ma250": 3100.0,
            "volume_ratio": 1.0,
            "change_pct": 0.0
        })
        # 验证输出格式
        assert result["regime"] in ["bull", "bear", "volatile", "transition", "unknown"]
        assert "position_pct" in result
        assert 0 <= result.get("position_pct", 50) <= 100
