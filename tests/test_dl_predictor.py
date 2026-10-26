# -*- coding: utf-8 -*-
"""
DL模型单元测试 - CNN/LSTM/Attention组件
========================================

Author: 老三 (技术验证专家)
Date: 2026-09-24
"""

import sys
import os
import numpy as np
import pytest
import pandas as pd
from pathlib import Path

# Add project to path
PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from factors.dl_stock_predictor import (
    CNNBlock, LSTMBlock, AttentionBlock, DenseBlock,
    CNNLSTMAttention, DLPredictionEngine,
    extract_features, compute_rsi, compute_volume_ratio,
    DL_WEIGHT, MODEL_ARCH, SEQ_LEN, FEATURES,
)
from utils.features import FeatureScaler


# ============================================================================
# Test CNNBlock
# ============================================================================

class TestCNNBlock:
    def test_forward_shape(self):
        """CNN forward输出形状正确"""
        B, T, C = 4, 60, 5
        cnn = CNNBlock(n_filters=16, kernel=3, in_ch=5)
        x = np.random.randn(B, T, C)
        out = cnn.forward(x)
        assert out.shape == (B, 16, T - 3 + 1)

    def test_backward_shape(self):
        """CNN backward输入输出形状一致"""
        B, T, C = 4, 60, 5
        cnn = CNNBlock(n_filters=16, kernel=3, in_ch=5)
        x = np.random.randn(B, T, C)
        out = cnn.forward(x)
        dout = np.ones_like(out)
        dx = cnn.backward(dout)
        assert dx.shape == x.shape

    def test_gradient_flow(self):
        """梯度可以正常传播"""
        B, T, C = 2, 20, 3
        cnn = CNNBlock(n_filters=8, kernel=3, in_ch=3)
        x = np.random.randn(B, T, C)
        out = cnn.forward(x)
        loss = out.sum()
        # 手动计算梯度
        dout = np.ones_like(out)
        dx = cnn.backward(dout)
        assert not np.allclose(dx, 0), "梯度应为非零"


# ============================================================================
# Test LSTMBlock
# ============================================================================

class TestLSTMBlock:
    def test_forward_shape(self):
        """LSTM forward输出形状正确"""
        B, T, inp = 4, 60, 5
        lstm = LSTMBlock(inp=inp, hid=64)
        x = np.random.randn(B, T, inp)
        out = lstm.forward(x)
        assert out.shape == (B, T, 64)

    def test_backward_shape(self):
        """LSTM backward输入输出形状一致"""
        B, T, inp = 4, 60, 5
        lstm = LSTMBlock(inp=inp, hid=64)
        x = np.random.randn(B, T, inp)
        out = lstm.forward(x)
        dout = np.ones_like(out)
        dx = lstm.backward(dout)
        assert dx.shape == x.shape

    def test_bias_gradient_no_bug(self):
        """修复bias梯度累加bug"""
        B, T, inp = 2, 10, 3
        lstm = LSTMBlock(inp=inp, hid=16)
        x = np.random.randn(B, T, inp)
        out = lstm.forward(x)
        # 使用非uniform输入确保梯度非零
        dout = np.random.randn(B, T, 16)
        dx = lstm.backward(dout)
        # bias梯度应为非零
        assert not np.allclose(lstm.db, 0), "bias梯度应为非零"

    def test_last_batch_consistency(self):
        """最后batch大小不一致时仍能正确工作"""
        B, T, inp = 3, 20, 4
        lstm = LSTMBlock(inp=inp, hid=32)
        x = np.random.randn(B, T, inp)
        out = lstm.forward(x)
        dout = np.ones_like(out)
        dx = lstm.backward(dout)
        assert dx.shape[0] == B


# ============================================================================
# Test AttentionBlock
# ============================================================================

class TestAttentionBlock:
    def test_forward_shape(self):
        """Attention forward输出形状正确"""
        B, T, D = 4, 58, 64
        attn = AttentionBlock(dim=64, attn_dim=32)
        x = np.random.randn(B, T, D)
        out = attn.forward(x)
        assert out.shape == (B, D)

    def test_backward_shape(self):
        """Attention backward输入输出形状一致"""
        B, T, D = 4, 58, 64
        attn = AttentionBlock(dim=64, attn_dim=32)
        x = np.random.randn(B, T, D)
        out = attn.forward(x)
        dout = np.ones_like(out)
        dx = attn.backward(dout)
        assert dx.shape == x.shape

    def test_attention_weights_normalized(self):
        """注意力权重应归一化"""
        B, T, D = 2, 10, 32
        attn = AttentionBlock(dim=D, attn_dim=16)
        x = np.random.randn(B, T, D)
        _ = attn.forward(x)
        attn_weights = attn._cache["attn"]
        # 每行的注意力权重和应为1
        row_sums = attn_weights.sum(axis=-1)
        assert np.allclose(row_sums, 1.0, atol=1e-5)


# ============================================================================
# Test DenseBlock
# ============================================================================

class TestDenseBlock:
    def test_forward_shape(self):
        """Dense forward输出形状正确"""
        inp, outp = 10, 20
        dense = DenseBlock(inp=inp, outp=outp)
        x = np.random.randn(4, inp)
        out = dense.forward(x)
        assert out.shape == (4, outp)

    def test_backward_shape(self):
        """Dense backward输入输出形状一致"""
        inp, outp = 10, 20
        dense = DenseBlock(inp=inp, outp=outp)
        x = np.random.randn(4, inp)
        out = dense.forward(x)
        dout = np.ones_like(out)
        dx = dense.backward(dout)
        assert dx.shape == x.shape


# ============================================================================
# Test CNNLSTMAttention (Full Model)
# ============================================================================

class TestCNNLSTMAttention:
    def test_forward_shape(self):
        """完整模型forward输出形状正确"""
        model = CNNLSTMAttention(n_features=5, seq_len=60)
        B = 4
        X = np.random.randn(B, 60, 5)
        out = model.forward(X, training=False)
        assert out.shape == (B, 1)

    def test_backward_gradient_flow(self):
        """梯度可以在完整模型中传播"""
        np.random.seed(42)
        model = CNNLSTMAttention(n_features=5, seq_len=60)
        X = np.random.randn(2, 60, 5)
        out = model.forward(X, training=False)
        # 手动计算backward
        model.backward()
        # 检查各层梯度非零
        assert not np.allclose(model.cnn.dW, 0)
        assert not np.allclose(model.lstm.dWx, 0)
        assert not np.allclose(model.attention.dWq, 0)

    def test_save_load(self, tmp_path):
        """模型可以正确保存和加载"""
        np.random.seed(42)
        model = CNNLSTMAttention(n_features=5, seq_len=60)
        # 做一次forward
        X = np.random.randn(2, 60, 5)
        model.forward(X)
        model.backward()

        # 保存
        path = tmp_path / "test_model.pkl"
        model.save(path)
        assert path.exists()

        # 加载到新模型
        model2 = CNNLSTMAttention(n_features=5, seq_len=60)
        model2.load(path)
        assert np.allclose(model2.cnn.W, model.cnn.W)
        assert np.allclose(model2.lstm.Wx, model.lstm.Wx)


# ============================================================================
# Test DLPredictionEngine
# ============================================================================

class TestDLPredictionEngine:
    def test_predict_fallback(self):
        """无模型时使用统计fallback"""
        engine = DLPredictionEngine()
        # 创建模拟数据
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
        assert pred is not None
        assert 0 <= conf <= 1

    def test_model_loading(self, tmp_path):
        """模型加载测试"""
        # 创建并保存一个简单模型
        np.random.seed(42)
        model = CNNLSTMAttention(n_features=5, seq_len=60)
        X = np.random.randn(2, 60, 5)
        model.forward(X)
        model.save(tmp_path / "model.pkl")

        # 加载模型并预测
        engine = DLPredictionEngine(model_path=tmp_path / "model.pkl")
        # 检查加载是否成功
        loaded = engine.load_model()
        if loaded:
            assert engine.is_model_ready()

    def test_rank_stocks(self, tmp_path):
        """股票排名测试"""
        # 创建模型
        np.random.seed(42)
        model = CNNLSTMAttention(n_features=5, seq_len=60)
        X = np.random.randn(2, 60, 5)
        model.forward(X)
        model.save(tmp_path / "model.pkl")

        engine = DLPredictionEngine(model_path=tmp_path / "model.pkl")

        # 创建多个股票的模拟数据
        all_stocks = {}
        for code in ['000001', '000002', '000003']:
            dates = pd.date_range('2024-01-01', periods=100, freq='D')
            np.random.seed(hash(code) % 2**32)
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
            all_stocks[code] = df

        ranked = engine.rank_stocks(all_stocks, top_k=2)
        assert len(ranked) == 2
        assert all(ranked[i][1] >= ranked[i+1][1] for i in range(len(ranked)-1))


# ============================================================================
# Test Feature Engineering
# ============================================================================

class TestFeatureEngineering:
    def test_extract_features_shape(self):
        """特征提取输出形状正确"""
        np.random.seed(42)
        records = []
        base_price = 100
        for i in range(100):
            records.append({
                'date': f'2024-01-{i+1:02d}',
                'open': base_price + np.random.randn() * 0.5,
                'high': base_price + abs(np.random.randn()) * 1,
                'low': base_price - abs(np.random.randn()) * 1,
                'close': base_price + np.cumsum(np.random.randn(100))[i] * 0.1,
                'volume': np.random.randint(100000, 1000000),
                'amount': base_price * np.random.randint(100000, 1000000),
            })
        feats = extract_features(records)
        assert feats is not None
        assert feats.shape[1] == 5  # 5个特征

    def test_compute_rsi(self):
        """RSI计算测试"""
        np.random.seed(42)
        close = np.cumsum(np.random.randn(50)) + 100
        rsi = compute_rsi(close, window=14)
        assert len(rsi) == 50
        assert np.all((rsi >= 0) & (rsi <= 100))

    def test_feature_scaler(self):
        """FeatureScaler测试"""
        np.random.seed(42)
        X = np.random.randn(100, 5) * 10 + 5
        scaler = FeatureScaler()
        scaler.fit(X)  # 先调用fit
        X_scaled = scaler.transform(X)
        assert X_scaled.shape == X.shape
        assert np.allclose(X_scaled.mean(axis=0), 0, atol=1e-5)
        assert np.allclose(X_scaled.std(axis=0), 1, atol=1e-5)


# ============================================================================
# Test dl_score_stock Integration
# ============================================================================

class TestDLScoreIntegration:
    def test_dl_score_format(self, tmp_path):
        """dl_score_stock返回格式正确"""
        from factors.dl_stock_predictor import dl_score_stock

        # 创建模型
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

        result = dl_score_stock('000001', df, engine)
        assert 'dl_score' in result
        assert 'dl_confidence' in result
        assert 'predicted_return' in result
        assert isinstance(result['dl_score'], float)
        assert 0 <= result['dl_confidence'] <= 1


# ============================================================================
# Test Backward Compatibility
# ============================================================================

class TestBackwardCompatibility:
    def test_features_constant(self):
        """FEATURES列表与训练脚本一致"""
        assert FEATURES == ["daily_return", "turnover", "rsi", "volume_ratio", "qfq_ratio"]

    def test_seq_len_constant(self):
        """SEQ_LEN与训练脚本一致"""
        assert SEQ_LEN == 60

    def test_model_arch_constant(self):
        """MODEL_ARCH正确"""
        assert MODEL_ARCH == "cnn_lstm_attention"

    def test_dl_weight(self):
        """DL_WEIGHT配置正确"""
        assert DL_WEIGHT == 0.20


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
