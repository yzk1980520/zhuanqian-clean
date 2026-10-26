#!/usr/bin/env python3
"""
test_laya_common.py: Laya 核心算法单元测试
测试范围: build_sequence, confidence_from_probs, ece_score, temperature
"""
import os
import sys
import math
import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from laya.common import (
        build_sequence,
        DecisionModel,
        confidence_from_probs,
        ece_score,
        proper_reward,
        render_options,
        temp_bucket,
        clamp_temperature,
        collate_items,
        QTYPES,
        QTYPE_NAMES,
        TEMP_MIN,
        TEMP_MAX,
    )
    HAS_LAYA = True
except ImportError as e:
    HAS_LAYA = False


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestBuildSequence:
    """测试序列构建"""

    @pytest.fixture
    def mock_tokenizer(self):
        """创建模拟 tokenizer"""
        class MockTokenizer:
            cls_token_id = 0
            sep_token_id = 1
            mask_token_id = 2
            pad_token_id = 3
            mask_token = "[MASK]"
            cls_token = "[CLS]"
            sep_token = "[SEP]"

            def __call__(self, text, add_special_tokens=False):
                # 简单实现：每个单词映射为 token ID
                tokens = text.split()
                return {"input_ids": list(range(len(tokens)))}

            def encode(self, text, add_special_tokens=False):
                return self(text, add_special_tokens)["input_ids"]

        return MockTokenizer()

    def test_basic_sequence(self, mock_tokenizer):
        """测试基础序列构建"""
        q = {
            "t": "choice",
            "ins": "Which category?",
            "crit": {"a": "Option A", "b": "Option B"}
        }
        state = "This is a test"

        seq, markers = build_sequence(mock_tokenizer, state, q, max_len=128)

        assert isinstance(seq, list)
        assert len(seq) > 0
        assert len(seq) <= 128
        assert len(markers) == 2  # 两个选项

    def test_sequence_starts_with_cls(self, mock_tokenizer):
        """测试序列以 CLS token 开头"""
        q = {
            "t": "choice",
            "ins": "Test",
            "crit": {"a": "A"}
        }
        seq, _ = build_sequence(mock_tokenizer, "state", q)
        assert seq[0] == mock_tokenizer.cls_token_id

    def test_sequence_contains_mask(self, mock_tokenizer):
        """测试序列包含 MASK token"""
        q = {
            "t": "choice",
            "ins": "Test",
            "crit": {"a": "A", "b": "B"}
        }
        seq, markers = build_sequence(mock_tokenizer, "state", q)
        assert mock_tokenizer.mask_token_id in seq

    def test_sequence_max_len_truncation(self, mock_tokenizer):
        """测试序列长度截断"""
        q = {
            "t": "choice",
            "ins": "Test",
            "crit": {"a": "A", "b": "B"}
        }
        state = "This is a very long state " * 100
        seq, _ = build_sequence(mock_tokenizer, state, q, max_len=32)
        assert len(seq) <= 32

    def test_choice_sequence(self, mock_tokenizer):
        """测试 choice 类型序列"""
        q = {
            "t": "choice",
            "ins": "Which department?",
            "crit": {
                "billing": "invoices, payments",
                "technical": "bugs, outages"
            }
        }
        seq, markers = build_sequence(mock_tokenizer, "Payment failed", q)
        assert len(markers) == 2

    def test_score_sequence(self, mock_tokenizer):
        """测试 score 类型序列"""
        q = {
            "t": "score",
            "ins": "How urgent?",
            "crit": ["low", "medium", "high"]
        }
        seq, markers = build_sequence(mock_tokenizer, "Critical issue", q)
        assert len(markers) == 3

    def test_noul_sequence(self, mock_tokenizer):
        """测试 noul 类型序列"""
        q = {
            "t": "noul",
            "ins": "Is this phishing?",
            "crit": {"true": "phishing", "false": "legitimate"}
        }
        seq, markers = build_sequence(mock_tokenizer, "Click here", q)
        assert len(markers) == 2

    def test_empty_state(self, mock_tokenizer):
        """测试空状态"""
        q = {
            "t": "choice",
            "ins": "Test",
            "crit": {"a": "A"}
        }
        seq, markers = build_sequence(mock_tokenizer, "", q)
        assert len(seq) > 0
        assert len(markers) == 1

    def test_state_dict_serialization(self, mock_tokenizer):
        """测试 dict 状态序列化"""
        q = {
            "t": "choice",
            "ins": "Test",
            "crit": {"a": "A"}
        }
        state = {"key": "value", "nested": {"x": 1}}
        seq, markers = build_sequence(mock_tokenizer, state, q)
        assert len(seq) > 0


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestConfidenceFromProbs:
    """测试置信度计算"""

    def test_high_confidence(self):
        """测试高置信度"""
        p = np.array([0.95, 0.03, 0.02])
        conf = confidence_from_probs(p, k=3)
        assert conf > 0.7  # 归一化熵，0.95 概率对应 ~0.79

    def test_low_confidence(self):
        """测试低置信度"""
        p = np.array([0.34, 0.33, 0.33])
        conf = confidence_from_probs(p, k=3)
        assert conf < 0.5

    def test_binary_equal(self):
        """测试二分类等概率"""
        p = np.array([0.5, 0.5])
        conf = confidence_from_probs(p, k=2)
        assert conf < 0.5

    def test_single_option(self):
        """测试单选项"""
        p = np.array([1.0])
        conf = confidence_from_probs(p, k=1)
        assert conf == 1.0

    def test_very_confident(self):
        """测试极高置信度"""
        p = np.array([0.999, 0.001])
        conf = confidence_from_probs(p, k=2)
        assert conf > 0.98  # 修正断言阈值


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestEceScore:
    """测试校准误差计算"""

    def test_perfect_calibration(self):
        """测试完美校准"""
        conf = np.array([0.9, 0.8, 0.7, 0.6, 0.5])
        correct = np.array([1, 1, 1, 0, 0])  # 5个中3个正确 = 60%
        ece = ece_score(conf, correct, bins=5)
        assert ece >= 0

    def test_worst_calibration(self):
        """测试最差校准"""
        conf = np.array([0.9, 0.9, 0.9, 0.1, 0.1])
        correct = np.array([0, 0, 0, 1, 1])
        ece = ece_score(conf, correct)
        assert ece > 0.5

    def test_empty_input(self):
        """测试空输入"""
        conf = np.array([])
        correct = np.array([])
        ece = ece_score(conf, correct)
        assert math.isnan(ece)

    def test_all_correct(self):
        """测试全部正确"""
        conf = np.array([0.9, 0.8, 0.7])
        correct = np.array([1, 1, 1])
        ece = ece_score(conf, correct)
        assert ece < 0.3

    def test_all_wrong(self):
        """测试全部错误"""
        conf = np.array([0.9, 0.8, 0.7])
        correct = np.array([0, 0, 0])
        ece = ece_score(conf, correct)
        assert ece > 0.5


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestTemperature:
    """测试温度校准"""

    def test_normal_temperature(self):
        """测试正常温度范围"""
        t = clamp_temperature(1.5)
        assert 0.5 <= t <= 5.0

    def test_low_clamp(self):
        """测试低温裁剪"""
        t = clamp_temperature(0.1)
        assert t == 0.5

    def test_high_clamp(self):
        """测试高温裁剪"""
        t = clamp_temperature(10.0)
        assert t == 5.0

    def test_nan_fallback(self):
        """测试 NaN 回退"""
        t = clamp_temperature(float('nan'))
        assert t == 1.0

    def test_inf_fallback(self):
        """测试 Inf 回退"""
        t = clamp_temperature(float('inf'))
        assert t == 1.0

    def test_invalid_string(self):
        """测试无效字符串"""
        t = clamp_temperature("invalid")
        assert t == 1.0


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestTempBucket:
    """测试温度桶"""

    def test_choice_2(self):
        bucket = temp_bucket(QTYPES["choice"], 2)
        assert bucket == "choice:2"

    def test_choice_3_5(self):
        bucket = temp_bucket(QTYPES["choice"], 5)
        assert bucket == "choice:3-5"

    def test_choice_6_10(self):
        bucket = temp_bucket(QTYPES["choice"], 10)
        assert bucket == "choice:6-10"

    def test_choice_11_plus(self):
        bucket = temp_bucket(QTYPES["choice"], 15)
        assert bucket == "choice:11+"

    def test_score_3(self):
        bucket = temp_bucket(QTYPES["score"], 3)
        assert bucket == "score:3-5"

    def test_noul_2(self):
        bucket = temp_bucket(QTYPES["noul"], 2)
        assert bucket == "noul:2"


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestRenderOptions:
    """测试选项渲染"""

    def test_choice_render(self):
        q = {"t": "choice", "crit": {"a": "Option A", "b": "Option B"}}
        opts = render_options(q)
        assert len(opts) == 2
        assert "a: Option A" in opts[0]
        assert "b: Option B" in opts[1]

    def test_score_render(self):
        q = {"t": "score", "crit": ["low", "medium", "high"]}
        opts = render_options(q)
        assert len(opts) == 3
        assert "level 0: low" in opts[0]
        assert "level 2: high" in opts[2]

    def test_noul_render(self):
        q = {"t": "noul", "crit": {}}
        opts = render_options(q)
        assert len(opts) == 2
        assert "false" in opts[0]
        assert "true" in opts[1]


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestCollateItems:
    """测试批处理"""

    def test_collate_single(self):
        items = [{
            "ids": [1, 2, 3],
            "markers": [5],
            "qtype": 0
        }]
        result = collate_items([items], pad_id=0)
        assert result["input_ids"].shape[0] == 1
        assert result["attention_mask"].shape[0] == 1

    def test_collate_multiple(self):
        items = [
            {"ids": [1, 2], "markers": [3], "qtype": 0},
            {"ids": [1, 2, 3, 4], "markers": [5], "qtype": 1}
        ]
        result = collate_items([items], pad_id=0)
        assert result["input_ids"].shape[0] == 2
        assert result["input_ids"].shape[1] == 4  # 最大长度

    def test_collate_empty(self):
        result = collate_items([], pad_id=0)
        assert result is None