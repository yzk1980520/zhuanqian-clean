"""
tests/test_dl_modules.py - Unit tests for DL prediction module
"""
import sys
import os
import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# Add project to path
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from factors.dl_stock_predictor import (
    DLPredictionEngine,
    extract_features,
    dl_score_stock,
    FEATURES,
    SEQ_LEN,
    DL_WEIGHT
)


class TestExtractFeatures(unittest.TestCase):
    """Test feature extraction from raw OHLCV data."""

    def setUp(self):
        """Create synthetic stock data for testing."""
        np.random.seed(42)
        n_days = 100
        dates = [datetime(2026, 9, 24) - timedelta(days=n_days - i) for i in range(n_days)]

        # Generate realistic OHLCV data
        self.stock_data = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'high': np.random.randn(n_days).cumsum() * 0.03 + 10.5,
            'low': np.random.randn(n_days).cumsum() * 0.02 + 9.5,
            'close': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'volume': np.random.randint(1000000, 10000000, n_days),
            'amount': np.random.randint(10000000, 100000000, n_days),
            'turnover': np.random.uniform(0.01, 0.1, n_days)
        })

    def test_extract_features_shape(self):
        """Test that feature extraction returns correct shape."""
        # 必须传入list of dicts
        records = [
            {"date": f"2026-09-{i:02d}", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.0 + i * 0.1, "volume": 1000000,
             "amount": 10000000}
            for i in range(100)
        ]
        features = extract_features(records)
        self.assertIsNotNone(features)
        # After dropping NaN (first row), should have enough rows
        self.assertGreaterEqual(features.shape[0], SEQ_LEN + 5)
        self.assertEqual(features.shape[1], 5)  # 5 features

    def test_extract_features_handles_short_data(self):
        """Test that short data returns None."""
        # 必须传入list of dicts，不能是DataFrame
        short_records = [
            {"date": f"2026-09-{i:02d}", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.0 + i * 0.1, "volume": 1000000,
             "amount": 10000000}
            for i in range(10)
        ]
        features = extract_features(short_records)
        self.assertIsNone(features)

    def test_extract_features_no_nan(self):
        """Test that output has no NaN values."""
        # 必须传入list of dicts
        records = [
            {"date": f"2026-09-{i:02d}", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.0 + i * 0.1, "volume": 1000000,
             "amount": 10000000}
            for i in range(100)
        ]
        features = extract_features(records)
        self.assertIsNotNone(features)
        if features is not None:
            self.assertFalse(np.any(np.isnan(features)))


class TestDLPredictionEngine(unittest.TestCase):
    """Test the prediction engine."""

    def setUp(self):
        """Set up test fixtures."""
        np.random.seed(42)
        n_days = 120
        dates = [datetime(2026, 9, 24) - timedelta(days=n_days - i) for i in range(n_days)]

        self.sample_df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'high': np.random.randn(n_days).cumsum() * 0.03 + 10.5,
            'low': np.random.randn(n_days).cumsum() * 0.02 + 9.5,
            'close': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'volume': np.random.randint(1000000, 10000000, n_days),
            'amount': np.random.randint(10000000, 100000000, n_days),
            'turnover': np.random.uniform(0.01, 0.1, n_days)
        })

        self.engine = DLPredictionEngine()

    def test_predict_single_stock_returns_valid_range(self):
        """Test that predictions are in reasonable range."""
        predicted_return, confidence = self.engine.predict_single_stock(self.sample_df)

        self.assertIsInstance(predicted_return, float)
        self.assertGreaterEqual(predicted_return, -0.1)  # Max 10% loss
        self.assertLessEqual(predicted_return, 0.1)     # Max 10% gain
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_predict_with_insufficient_data(self):
        """Test prediction with insufficient data."""
        # 创建短DataFrame数据
        from datetime import datetime, timedelta
        n_days = 30
        dates = [datetime(2026, 9, 24) - timedelta(days=n_days - i) for i in range(n_days)]
        short_df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'high': np.random.randn(n_days).cumsum() * 0.03 + 10.5,
            'low': np.random.randn(n_days).cumsum() * 0.02 + 9.5,
            'close': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'volume': np.random.randint(1000000, 10000000, n_days),
            'amount': np.random.randint(10000000, 100000000, n_days),
            'turnover': np.random.uniform(0.01, 0.1, n_days)
        })
        predicted_return, confidence = self.engine.predict_single_stock(short_df)

        # 数据不足时应返回fallback值（非None）
        self.assertIsNotNone(predicted_return)
        self.assertIsNotNone(confidence)

    def test_rank_stocks(self):
        """Test stock ranking functionality."""
        all_stocks = {
            f"stock_{i}": self.sample_df
            for i in range(5)
        }

        ranked = self.engine.rank_stocks(all_stocks, top_k=3)
        self.assertEqual(len(ranked), 3)
        self.assertTrue(all(isinstance(item, tuple) for item in ranked))
        self.assertEqual(len(ranked[0]), 3)  # (code, return, confidence)


class TestDLIntegration(unittest.TestCase):
    """Test DL integration with picker system."""

    def setUp(self):
        """Set up test fixtures."""
        np.random.seed(42)
        n_days = 120
        dates = [datetime(2026, 9, 24) - timedelta(days=n_days - i) for i in range(n_days)]

        self.sample_df = pd.DataFrame({
            'date': dates,
            'open': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'high': np.random.randn(n_days).cumsum() * 0.03 + 10.5,
            'low': np.random.randn(n_days).cumsum() * 0.02 + 9.5,
            'close': np.random.randn(n_days).cumsum() * 0.02 + 10,
            'volume': np.random.randint(1000000, 10000000, n_days),
            'amount': np.random.randint(10000000, 100000000, n_days),
            'turnover': np.random.uniform(0.01, 0.1, n_days)
        })

    def test_dl_score_stock_returns_dict(self):
        """Test that dl_score_stock returns proper dict."""
        result = dl_score_stock("000001", self.sample_df)

        self.assertIsInstance(result, dict)
        self.assertIn('dl_score', result)
        self.assertIn('dl_confidence', result)
        self.assertIn('predicted_return', result)

    def test_dl_score_stock_range(self):
        """Test that dl_score is in valid range [-1, 1]."""
        result = dl_score_stock("000001", self.sample_df)

        self.assertGreaterEqual(result['dl_score'], -1.0)
        self.assertLessEqual(result['dl_score'], 1.0)

    def test_dl_weight_constant(self):
        """Test that DL_WEIGHT is correctly set."""
        self.assertEqual(DL_WEIGHT, 0.20)


class TestModelPath(unittest.TestCase):
    """Test model path configuration."""

    def test_model_path_is_pkl(self):
        """Test that MODEL_PATH uses .pkl extension."""
        from factors.dl_stock_predictor import MODEL_PATH
        # Path对象转换为字符串检查
        self.assertTrue(str(MODEL_PATH).endswith('.pkl'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
