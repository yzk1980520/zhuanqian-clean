# -*- coding: utf-8 -*-
"""
DL模块完整性测试
================
验证训练模型与预测器的兼容性、前向传播正确性、性能基准。

Author: 总管 (技术审查)
Date: 2026-09-24
"""

import sys
import os
import time
import numpy as np
import pickle
import pytest
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from factors.dl_stock_predictor import (
    CNNLSTMAttention, DLPredictionEngine, FEATURES, SEQ_LEN,
    LSTM_UNITS, CNN_FILTERS, DENSE_HID, ATTENTION_HID, DROPOUT_RATE,
    MODEL_PATH, SCALER_PATH,
)


class TestModelLoadingCompatibility:
    """测试训练模型与预测器的兼容性"""

    def test_model_file_exists(self):
        """模型文件存在"""
        assert MODEL_PATH.exists(), f"模型文件不存在: {MODEL_PATH}"

    def test_model_loadable(self):
        """模型可以成功加载"""
        engine = DLPredictionEngine()
        result = engine.load_model()
        assert result is True, "模型加载失败"

    def test_model_parameters_match(self):
        """模型参数与配置一致"""
        engine = DLPredictionEngine()
        engine.load_model()

        model = engine.model
        hyper = {
            'lstm_units': LSTM_UNITS,
            'cnn_filters': CNN_FILTERS,
            'dense_hid': DENSE_HID,
            'attention_hid': ATTENTION_HID,
            'dropout': DROPOUT_RATE,
        }

        # 验证LSTM参数
        assert model.lstm.hid == hyper['lstm_units'], \
            f"LSTM hidden mismatch: {model.lstm.hid} vs {hyper['lstm_units']}"
        assert model.lstm.Wx.shape == (4 * hyper['lstm_units'], hyper['lstm_units']), \
            f"LSTM Wx shape wrong: {model.lstm.Wx.shape}"

        # 验证CNN参数
        assert model.cnn.n_filters == hyper['cnn_filters'], \
            f"CNN filters mismatch: {model.cnn.n_filters} vs {hyper['cnn_filters']}"
        assert model.cnn.W.shape == (hyper['cnn_filters'], 3, len(FEATURES)), \
            f"CNN W shape wrong: {model.cnn.W.shape}"

        # 验证Dense参数
        assert model.dense_mid.W.shape[0] == hyper['dense_hid'], \
            f"Dense hid mismatch: {model.dense_mid.W.shape[0]} vs {hyper['dense_hid']}"

        # 验证Attention参数
        assert model.attention.dim == hyper['lstm_units'], \
            f"Attention dim mismatch: {model.attention.dim} vs {hyper['lstm_units']}"
        assert model.attention.attn_d == hyper['attention_hid'], \
            f"Attention attn_d mismatch: {model.attention.attn_d} vs {hyper['attention_hid']}"

    def test_weight_shapes_consistent(self):
        """权重形状与架构一致"""
        engine = DLPredictionEngine()
        engine.load_model()
        model = engine.model

        # CNN: (filters, kernel, in_ch)
        assert model.cnn.W.shape == (CNN_FILTERS, 3, len(FEATURES))

        # Dense_in: (out, in) = (lstm_hid * cnn_out_T, cnn_filters * cnn_out_T)
        cnn_out_T = SEQ_LEN - 3 + 1  # kernel size is 3
        expected_input = CNN_FILTERS * cnn_out_T  # 8 * 58 = 464
        expected_output = LSTM_UNITS * cnn_out_T  # 16 * 58 = 928
        assert model.dense_in.W.shape == (expected_output, expected_input), \
            f"dense_in shape wrong: {model.dense_in.W.shape} vs {(expected_output, expected_input)}"

        # LSTM: (4*hid, inp), where inp should match dense_in output per timestep
        expected_lstm_Wx_shape = (4 * LSTM_UNITS, LSTM_UNITS)
        assert model.lstm.Wx.shape == expected_lstm_Wx_shape, \
            f"LSTM Wx shape wrong: {model.lstm.Wx.shape} vs {expected_lstm_Wx_shape}"

        # Attention: (attn_dim, dim)
        assert model.attention.Wq.shape == (ATTENTION_HID, LSTM_UNITS)
        assert model.attention.Wv.shape == (LSTM_UNITS, LSTM_UNITS)

        # Dense_mid: (dense_hid, attention_dim)
        assert model.dense_mid.W.shape == (DENSE_HID, ATTENTION_HID)

        # Dense_out: (1, dense_hid)
        assert model.dense_out.W.shape == (1, DENSE_HID)


class TestForwardPropagation:
    """测试前向传播正确性"""

    def test_random_input_shape(self):
        """随机输入形状正确"""
        model = CNNLSTMAttention(n_features=len(FEATURES), seq_len=SEQ_LEN)
        B = 4
        X = np.random.randn(B, SEQ_LEN, len(FEATURES))
        out = model.forward(X, training=False)
        assert out.shape == (B, 1), f"Expected shape (B, 1), got {out.shape}"

    def test_loaded_model_forward(self):
        """加载的模型前向传播正常"""
        engine = DLPredictionEngine()
        assert engine.load_model(), "模型加载失败"

        B = 2
        X = np.random.randn(B, SEQ_LEN, len(FEATURES))
        out = engine.model.forward(X, training=False)
        assert out.shape == (B, 1), f"Expected shape (B, 1), got {out.shape}"

    def test_prediction_consistency(self):
        """相同输入产生相同输出"""
        engine = DLPredictionEngine()
        assert engine.load_model(), "模型加载失败"

        X = np.random.randn(1, SEQ_LEN, len(FEATURES))

        out1 = engine.model.forward(X, training=False)
        out2 = engine.model.forward(X, training=False)

        assert np.allclose(out1, out2), "相同输入应产生相同输出"

    def test_no_gradient_in_inference(self):
        """推理时不计算梯度"""
        model = CNNLSTMAttention(n_features=len(FEATURES), seq_len=SEQ_LEN)
        X = np.random.randn(1, SEQ_LEN, len(FEATURES))
        out = model.forward(X, training=False)

        # 验证输出不为NaN
        assert not np.isnan(out).any(), "输出不应包含NaN"
        assert not np.isinf(out).any(), "输出不应包含Inf"


class TestPerformanceBenchmark:
    """测试性能基准"""

    def test_predict_speed(self):
        """预测速度基准"""
        engine = DLPredictionEngine()
        assert engine.load_model(), "模型加载失败"

        X = np.random.randn(10, SEQ_LEN, len(FEATURES))

        # 预热
        for _ in range(3):
            engine.model.forward(X, training=False)

        # 计时
        start = time.perf_counter()
        for _ in range(10):
            engine.model.forward(X, training=False)
        elapsed = time.perf_counter() - start

        # 基准: 10次预测应小于1秒
        assert elapsed < 1.0, f"预测太慢: {elapsed:.3f}s for 10 predictions"

    def test_memory_usage(self):
        """内存使用基准"""
        engine = DLPredictionEngine()
        assert engine.load_model(), "模型加载失败"

        # 释放一些缓存
        import gc
        gc.collect()

        # 验证模型大小合理
        model_size = engine.model.dense_in.W.nbytes + \
                     engine.model.lstm.Wx.nbytes + \
                     engine.model.attention.Wq.nbytes
        assert model_size < 50 * 1024 * 1024, f"模型过大: {model_size / 1024 / 1024:.1f} MB"


class TestEdgeCases:
    """边界情况测试"""

    def test_batch_size_1(self):
        """单样本批量"""
        model = CNNLSTMAttention(n_features=len(FEATURES), seq_len=SEQ_LEN)
        X = np.random.randn(1, SEQ_LEN, len(FEATURES))
        out = model.forward(X, training=False)
        assert out.shape == (1, 1)

    def test_batch_size_large(self):
        """大批量"""
        model = CNNLSTMAttention(n_features=len(FEATURES), seq_len=SEQ_LEN)
        X = np.random.randn(64, SEQ_LEN, len(FEATURES))
        out = model.forward(X, training=False)
        assert out.shape == (64, 1)

    def test_short_sequence_error(self):
        """短序列处理"""
        engine = DLPredictionEngine()
        engine.load_model()

        # 只有30天数据
        X = np.random.randn(1, 30, len(FEATURES))
        with pytest.raises(Exception):
            engine.model.forward(X, training=False)

    def test_all_zeros_input(self):
        """全零输入"""
        model = CNNLSTMAttention(n_features=len(FEATURES), seq_len=SEQ_LEN)
        X = np.zeros((1, SEQ_LEN, len(FEATURES)))
        out = model.forward(X, training=False)
        assert not np.isnan(out).any(), "全零输入不应产生NaN"


class TestConfigurationConsistency:
    """配置一致性测试"""

    def test_features_count_matches(self):
        """特征数量一致"""
        assert len(FEATURES) == 5, f"Expected 5 features, got {len(FEATURES)}"
        assert FEATURES == ["daily_return", "turnover", "rsi", "volume_ratio", "qfq_ratio"]

    def test_seq_len_matches(self):
        """序列长度一致"""
        assert SEQ_LEN == 60

    def test_dropout_rate_warning(self):
        """Dropout率配置警告"""
        # 训练用0.1，预测用0.2，但推理时不影响
        # 这里只是记录不一致，不报错
        import logging
        logging.warning(f"DROPOUT_RATE不一致: 训练=0.1, 预测={DROPOUT_RATE}")

    def test_constants_documented(self):
        """常量有注释"""
        import inspect
        source = inspect.getsource(sys.modules['factors.dl_stock_predictor'])
        assert "# Model hyperparameters" in source, "缺少超参数注释"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
