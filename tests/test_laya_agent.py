#!/usr/bin/env python3
"""
test_laya_agent.py: Laya Agent 单元测试
测试范围: 模型加载、推理、错误处理、边界情况
"""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

# 设置环境变量避免 TensorFlow 冲突
os.environ['USE_TF'] = '0'

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import laya
    from laya.agent import Agent, load
    from laya.common import build_sequence, DecisionModel, confidence_from_probs
    HAS_LAYA = True
except ImportError as e:
    HAS_LAYA = False
    laya = None


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 本地模型推理族(模型一次性加载 ~49s setup + 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestAgentLoad:
    """测试 Agent 模型加载"""

    def test_load_local_model(self, agent):
        """测试加载本地模型 (通过 fixture)"""
        assert agent is not None
        assert hasattr(agent, 'model')
        assert hasattr(agent, 'tok')
        assert hasattr(agent, 'cfg')

    def test_load_with_device_cpu(self, model_path):
        """测试指定 CPU 设备加载"""
        if not os.path.exists(model_path):
            pytest.skip("Local model not found")
        from laya.agent import Agent
        agent = Agent(model_path, device='cpu')
        assert str(agent.device) == 'cpu'

    def test_load_invalid_path(self):
        """测试加载无效路径"""
        with pytest.raises(FileNotFoundError):
            Agent("/nonexistent/path/to/model")

    def test_load_missing_weights(self, tmp_path):
        """测试缺失权重文件"""
        # 创建一个只有 config 的临时目录
        config = {"encoder": "answerdotai/ModernBERT-large", "head_layers": 2}
        (tmp_path / "rl_agent_config.json").write_text(json.dumps(config))
        (tmp_path / "encoder").mkdir()
        (tmp_path / "encoder" / "config.json").write_text("{}")

        with pytest.raises(FileNotFoundError, match="model.safetensors"):
            Agent(str(tmp_path))


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 本地模型推理族(模型一次性加载 ~49s setup + 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestAgentPredict:
    """测试 Agent 推理功能"""

    @pytest.fixture
    def agent(self, model_path):
        """加载测试用的 Agent"""
        if not os.path.exists(model_path):
            pytest.skip("Local model not found")
        return Agent(model_path)

    def test_predict_choice_question(self, agent):
        """测试 choice 类型问题"""
        questions = {
            "department": {
                "type": "choice",
                "instructions": "Which department?",
                "criteria": {
                    "billing": "invoices, payments",
                    "technical": "bugs, outages",
                    "sales": "pricing"
                }
            }
        }
        state = "My payment failed"

        result = agent.predict(state, questions)
        assert "answers" in result
        assert "department" in result["answers"]
        assert result["answers"]["department"]["type"] == "choice"
        assert "choice" in result["answers"]["department"]
        assert "confidence" in result["answers"]["department"]
        assert "probabilities" in result["answers"]["department"]

    def test_predict_score_question(self, agent):
        """测试 score 类型问题"""
        questions = {
            "urgency": {
                "type": "score",
                "instructions": "How urgent?",
                "criteria": ["low", "medium", "high"]
            }
        }
        state = "This is critical"

        result = agent.predict(state, questions)
        assert "urgency" in result["answers"]
        assert result["answers"]["urgency"]["type"] == "score"
        assert "score" in result["answers"]["urgency"]
        assert "legend" in result["answers"]["urgency"]

    def test_predict_noul_question(self, agent):
        """测试 noul 类型问题"""
        questions = {
            "is_phishing": {
                "type": "noul",
                "instructions": "Is this phishing?"
            }
        }
        state = "Click here to verify your account"

        result = agent.predict(state, questions)
        assert "is_phishing" in result["answers"]
        assert result["answers"]["is_phishing"]["type"] == "noul"
        assert "noul" in result["answers"]["is_phishing"]
        assert "confidence" in result["answers"]["is_phishing"]

    def test_predict_mixed_questions(self, agent):
        """测试混合类型问题"""
        questions = {
            "dept": {
                "type": "choice",
                "instructions": "Which department?",
                "criteria": {"billing": "payments", "technical": "bugs"}
            },
            "urgency": {
                "type": "score",
                "instructions": "How urgent?",
                "criteria": ["low", "high"]
            },
            "is_risky": {
                "type": "noul",
                "instructions": "Is this risky?"
            }
        }
        state = {"message": "Payment failed urgently"}

        result = agent.predict(state, questions)
        assert len(result["answers"]) == 3
        assert "dept" in result["answers"]
        assert "urgency" in result["answers"]
        assert "is_risky" in result["answers"]

    def test_predict_empty_questions(self, agent):
        """测试空问题列表"""
        result = agent.predict("test", {})
        assert result["answers"] == {}
        assert result["usage"]["input_tokens"] == 0

    def test_predict_single_option_choice(self, agent):
        """测试单选项 choice"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Test",
                "criteria": {"only": "one option"}
            }
        }
        state = "test"
        result = agent.predict(state, questions)
        assert result["answers"]["test"]["choice"] == "only"

    def test_usage_tracking(self, agent):
        """测试 token 使用统计"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Test",
                "criteria": {"a": "option A", "b": "option B"}
            }
        }
        state = "This is a test message"
        result = agent.predict(state, questions)
        assert "usage" in result
        assert result["usage"]["input_tokens"] > 0
        assert result["usage"]["output_tokens"] == 0  # Non-autoregressive


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 本地模型推理族(模型一次性加载 ~49s setup + 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestAgentValidation:
    """测试 Agent 输入验证"""

    @pytest.fixture
    def agent(self, model_path):
        if not os.path.exists(model_path):
            pytest.skip("Local model not found")
        return Agent(model_path)

    def test_invalid_question_type(self, agent):
        """测试无效问题类型"""
        questions = {
            "test": {
                "type": "invalid",
                "instructions": "Test"
            }
        }
        with pytest.raises(ValueError, match="unknown type"):
            agent.predict("test", questions)

    def test_missing_instructions(self, agent):
        """测试缺少 instructions"""
        questions = {
            "test": {
                "type": "choice",
                "criteria": {"a": "A"}
            }
        }
        with pytest.raises(ValueError, match="no 'instructions'"):
            agent.predict("test", questions)

    def test_empty_criteria_choice(self, agent):
        """测试空 criteria (choice)"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Test",
                "criteria": {}
            }
        }
        with pytest.raises(ValueError, match="at least one criterion"):
            agent.predict("test", questions)

    def test_list_criteria_choice(self, agent):
        """测试 list 格式的 criteria"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Test",
                "criteria": ["a", "b", "c"]
            }
        }
        state = "test"
        result = agent.predict(state, questions)
        assert result["answers"]["test"]["choice"] in ["a", "b", "c"]

    def test_score_without_criteria(self, agent):
        """测试 score 类型缺少 criteria"""
        questions = {
            "test": {
                "type": "score",
                "instructions": "Test"
            }
        }
        with pytest.raises(ValueError, match="a score question takes 'criteria'"):
            agent.predict("test", questions)

    def test_state_dict_conversion(self, agent):
        """测试 dict 状态转换"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Classify",
                "criteria": {"a": "A", "b": "B"}
            }
        }
        state = {"key": "value", "nested": {"x": 1}}
        result = agent.predict(state, questions)
        assert "test" in result["answers"]


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 本地模型推理族(模型一次性加载 ~49s setup + 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestAgentContext:
    """测试 Agent 上下文处理"""

    @pytest.fixture
    def agent(self, model_path):
        if not os.path.exists(model_path):
            pytest.skip("Local model not found")
        return Agent(model_path)

    def test_long_state_truncation(self, agent):
        """测试长文本截断"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Classify",
                "criteria": {"a": "A", "b": "B"}
            }
        }
        # 生成一个很长的文本（超过 max_len）
        long_text = "test " * 1000
        result = agent.predict(long_text, questions)
        assert "test" in result["answers"]

    def test_special_characters(self, agent):
        """测试特殊字符处理"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Test",
                "criteria": {"a": "A", "b": "B"}
            }
        }
        state = "Test <script>alert('xss')</script> & \"quotes\" 'apostrophes'"
        result = agent.predict(state, questions)
        assert "test" in result["answers"]

    def test_multiline_state(self, agent):
        """测试多行状态"""
        questions = {
            "test": {
                "type": "choice",
                "instructions": "Test",
                "criteria": {"a": "A", "b": "B"}
            }
        }
        state = "Line 1\nLine 2\nLine 3"
        result = agent.predict(state, questions)
        assert "test" in result["answers"]


@pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): laya 本地模型推理族(模型一次性加载 ~49s setup + 推理) → 门禁快档排除
@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestAgentExit:
    """测试 Agent 上下文管理"""

    @pytest.fixture
    def agent(self, model_path):
        if not os.path.exists(model_path):
            pytest.skip("Local model not found")
        return Agent(model_path)

    def test_context_manager(self, agent):
        """测试 with 语句清理"""
        with agent:
            result = agent.predict("test", {
                "test": {
                    "type": "choice",
                    "instructions": "Test",
                    "criteria": {"a": "A"}
                }
            })
            assert "test" in result["answers"]
        # Context manager should not raise