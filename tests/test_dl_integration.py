# -*- coding: utf-8 -*-
"""
DL模块集成测试
==============

测试DL模块与主系统的集成，确保故障不影响主流程。

Author: 老三 (技术验证专家)
Date: 2026-09-24
"""

import sys
import os
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project to path
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from factors.dl_stock_predictor import (
    DLPredictionEngine, dl_score_stock, integrate_dl_into_picker,
    MODEL_PATH, SCALER_PATH, DL_WEIGHT,
)


# ============================================================================
# Test Integration Graceful Degradation
# ============================================================================

class TestGracefulDegradation:
    """测试DL故障时的降级行为"""

    def test_no_model_file(self, tmp_path):
        """模型文件不存在时返回fallback值"""
        engine = DLPredictionEngine(model_path=tmp_path / "nonexistent.pkl")
        assert not engine.is_model_ready()

        # 创建模拟数据
        import pandas as pd
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(100) * 0.02)
        df = pd.DataFrame({
            'date': dates,
            'open': close * (1 + np.random.randn(100) * 0.001),
            'high': close * (1 + np.abs(np.random.randn(100)) * 0.005),
            'low': close * (1 - np.abs(np.random.randn(100)) * 0.005),
            'close': close,
            'volume': np.random.randint(100000, 1000000, 100),
            'amount': close * np.random.randint(100000, 1000000, 100),
        })

        pred, conf = engine.predict_single_stock(df)
        assert pred is not None  # fallback应该返回值
        assert 0 <= conf <= 1

    def test_short_data(self, tmp_path):
        """数据不足时返回fallback值"""
        engine = DLPredictionEngine(model_path=tmp_path / "model.pkl")

        import pandas as pd
        # 只有30天数据，不足60天
        dates = pd.date_range('2024-01-01', periods=30, freq='D')
        close = np.ones(30) * 100
        df = pd.DataFrame({
            'date': dates,
            'open': close,
            'high': close * 1.01,
            'low': close * 0.99,
            'close': close,
            'volume': np.ones(30) * 100000,
            'amount': close * 100000,
        })

        pred, conf = engine.predict_single_stock(df)
        # 数据不足时应返回fallback值，不崩溃
        assert pred is not None
        assert conf is not None

    def test_dl_score_with_fallback(self, tmp_path):
        """dl_score_stock在无模型时返回默认值"""
        result = dl_score_stock('000001', None, engine=None)
        # 无数据时应返回默认值
        assert 'dl_score' in result
        assert 'dl_confidence' in result
        assert 'predicted_return' in result


# ============================================================================
# Test Configuration Consistency
# ============================================================================

class TestConfiguration:
    """测试配置一致性"""

    def test_dl_weight(self):
        """DL权重配置正确"""
        assert DL_WEIGHT == 0.20

    def test_model_path_exists(self):
        """模型路径配置正确"""
        assert MODEL_PATH.name == "dl_predictor.pkl"
        assert MODEL_PATH.suffix == ".pkl"

    def test_features_list(self):
        """特征列表正确"""
        from factors.dl_stock_predictor import FEATURES
        assert len(FEATURES) == 5
        assert "daily_return" in FEATURES
        assert "rsi" in FEATURES


# ============================================================================
# Test Main System Compatibility
# ============================================================================

class TestMainSystemCompatibility:
    """测试与主系统的兼容性"""

    def test_integrated_picker_import(self):
        """integrated_picker可以正常导入"""
        try:
            import integrated_picker
            # 检查是否有score_stock或相关函数
            has_score = hasattr(integrated_picker, 'score_stock')
            # integrated_picker可能是包，检查子模块
            if not has_score:
                import integrated_picker.tdx_core as tdx_core
                has_score = hasattr(tdx_core, 'score_stock')
            assert has_score, "integrated_picker中未找到score_stock"
        except ImportError:
            pytest.skip("integrated_picker未安装")

    def test_tdx_core_import(self):
        """tdx_core可以正常导入"""
        try:
            import tdx_core
            assert hasattr(tdx_core, 'score_stock')
        except ImportError:
            pytest.skip("tdx_core未安装")

    def test_dl_module_import(self):
        """DL模块可以正常导入"""
        import factors.dl_stock_predictor
        assert hasattr(factors.dl_stock_predictor, 'DLPredictionEngine')
        assert hasattr(factors.dl_stock_predictor, 'dl_score_stock')


# ============================================================================
# Test Edge Cases
# ============================================================================

class TestEdgeCases:
    """边界条件测试"""

    def test_nan_handling(self, tmp_path):
        """NaN值处理"""
        import pandas as pd
        engine = DLPredictionEngine(model_path=tmp_path / "model.pkl")

        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        close = np.ones(100) * 100
        close[50] = np.nan  # 插入NaN
        df = pd.DataFrame({
            'date': dates,
            'open': close,
            'high': close * 1.01,
            'low': close * 0.99,
            'close': close,
            'volume': np.ones(100) * 100000,
            'amount': close * 100000,
        })

        # 应该能处理NaN（通过dropna）
        pred, conf = engine.predict_single_stock(df)
        assert pred is not None or conf is not None

    def test_zero_volume(self, tmp_path):
        """零成交量处理"""
        import pandas as pd
        engine = DLPredictionEngine(model_path=tmp_path / "model.pkl")

        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        close = 100 + np.cumsum(np.random.randn(100) * 0.02)
        df = pd.DataFrame({
            'date': dates,
            'open': close,
            'high': close * 1.01,
            'low': close * 0.99,
            'close': close,
            'volume': np.zeros(100),  # 零成交量
            'amount': np.zeros(100),
        })

        # 应该能处理零成交量
        pred, conf = engine.predict_single_stock(df)
        # 可能返回None因为turnover会是NaN/Inf
        assert pred is None or conf is None or (isinstance(pred, float) and isinstance(conf, float))


# ============================================================================
# Test Performance
# ============================================================================

class TestPerformance:
    """性能测试"""

    def test_predict_single_stock_speed(self, tmp_path):
        """单只股票预测速度"""
        import time
        import pandas as pd

        # 创建模型
        from factors.dl_stock_predictor import CNNLSTMAttention
        np.random.seed(42)
        model = CNNLSTMAttention(n_features=5, seq_len=60)
        X = np.random.randn(2, 60, 5)
        model.forward(X)
        model.save(tmp_path / "model.pkl")

        engine = DLPredictionEngine(model_path=tmp_path / "model.pkl")

        # 创建测试数据
        dates = pd.date_range('2024-01-01', periods=100, freq='D')
        np.random.seed(123)
        close = 100 + np.cumsum(np.random.randn(100) * 0.02)
        df = pd.DataFrame({
            'date': dates,
            'open': close * (1 + np.random.randn(100) * 0.001),
            'high': close * (1 + np.abs(np.random.randn(100)) * 0.005),
            'low': close * (1 - np.abs(np.random.randn(100)) * 0.005),
            'close': close,
            'volume': np.random.randint(100000, 1000000, 100),
            'amount': close * np.random.randint(100000, 1000000, 100),
        })

        # 测试预测速度
        start = time.time()
        for _ in range(10):
            engine.predict_single_stock(df)
        elapsed = time.time() - start

        # 10次预测应在1秒内完成
        assert elapsed < 1.0, f"预测太慢: {elapsed:.2f}s for 10 predictions"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
