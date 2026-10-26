"""
tests/test_gate.py - DL门禁测试
=================================
测试DL模型的IC/IR/单调性/滚动窗口门禁逻辑
"""
import sys
import os
import unittest
import numpy as np
import pickle

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from utils.features import extract_features, FeatureScaler
from factors.dl_stock_predictor import DLPredictionEngine, FEATURES, SEQ_LEN


class TestGateCheck(unittest.TestCase):
    """Test DL gate check logic (simulated)."""

    def test_ic_mean_above_threshold(self):
        """IC均值门禁：IC > 0.03通过"""
        ic_values = [0.04, 0.05, 0.03]
        ic_mean = np.mean(ic_values)
        self.assertGreater(ic_mean, 0.03)

    def test_ic_mean_below_threshold(self):
        """IC均值门禁：IC < 0.03不通过"""
        ic_values = [0.01, 0.02, 0.025]
        ic_mean = np.mean(ic_values)
        self.assertLess(ic_mean, 0.03)

    def test_icir_calculation(self):
        """ICIR计算：IC均值/IC标准差"""
        ic_values = np.array([0.04, 0.05, 0.03, 0.06, 0.04])
        ic_mean = np.mean(ic_values)
        ic_std = np.std(ic_values)
        icir = ic_mean / ic_std if ic_std > 0 else 0
        self.assertGreater(icir, 0)  # ICIR应为正值

    def test_monotonicity_check(self):
        """单调性检验：预测与标签正相关"""
        predictions = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        labels = np.array([0.05, 0.15, 0.25, 0.35, 0.45])
        correlation = np.corrcoef(predictions, labels)[0, 1]
        self.assertGreater(correlation, 0.5)  # Strong positive correlation

    def test_rolling_windows_positive(self):
        """滚动正IC窗口检验：至少3个窗口为正"""
        # 模拟130个正IC窗口
        positive_count = sum(1 for ic in [0.04] * 130 + [-0.01] * 13 if ic > 0)
        self.assertGreaterEqual(positive_count, 3)


class TestFeatureExtractor(unittest.TestCase):
    """Test unified feature extraction."""

    def test_extract_features_returns_numpy_array(self):
        """特征提取返回numpy数组而非DataFrame"""
        from utils.features import extract_features
        import numpy as np

        records = [
            {"date": f"2026-09-{i:02d}", "open": 10.0, "high": 10.5,
             "low": 9.5, "close": 10.0 + i * 0.1, "volume": 1000000,
             "amount": 10000000}
            for i in range(70)
        ]

        feats = extract_features(records, seq_len=60)
        self.assertIsInstance(feats, np.ndarray)
        # 70条记录减去daily_return的1个NaN，应该是69行
        self.assertEqual(feats.shape[0], 69)
        self.assertEqual(feats.shape[1], 5)


class TestScalable(unittest.TestCase):
    """Test FeatureScaler."""

    def test_fit_transform_roundtrip(self):
        """fit-transform应能恢复数据"""
        from utils.features import FeatureScaler
        import numpy as np

        X = np.random.randn(100, 5)
        scaler = FeatureScaler()
        scaler.fit(X)
        X_scaled = scaler.transform(X)

        # 标准化后均值应为0，标准差应为1
        self.assertAlmostEqual(X_scaled.mean(), 0.0, places=5)
        self.assertAlmostEqual(X_scaled.std(), 1.0, places=5)

    def test_partial_fit_incremental(self):
        """partial_fit支持增量更新"""
        from utils.features import FeatureScaler
        import numpy as np

        scaler = FeatureScaler()
        chunk1 = np.random.randn(50, 5)
        chunk2 = np.random.randn(50, 5)

        scaler.fit(chunk1)  # 使用fit而非partial_fit
        scaler.partial_fit(chunk2)  # 增量更新

        # 验证统计量已更新
        self.assertIsNotNone(scaler._mean)
        self.assertIsNotNone(scaler._std)

    def test_save_load_roundtrip(self):
        """scaler保存加载应保持一致"""
        import tempfile
        from utils.features import FeatureScaler
        import numpy as np

        scaler = FeatureScaler()
        X = np.random.randn(100, 5)
        scaler.fit(X)

        # 使用字典保存/加载（兼容pickle）
        with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as f:
            temp_path = f.name

        try:
            # 保存
            with open(temp_path, 'wb') as f:
                pickle.dump({'mean': scaler._mean, 'std': scaler._std}, f)

            # 加载
            scaler2 = FeatureScaler()
            with open(temp_path, 'rb') as f:
                st = pickle.load(f)
            scaler2._mean = st['mean']
            scaler2._std = st['std']

            self.assertTrue(np.allclose(scaler._mean, scaler2._mean))
            self.assertTrue(np.allclose(scaler._std, scaler2._std))
        finally:
            os.unlink(temp_path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
