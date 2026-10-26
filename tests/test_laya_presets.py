#!/usr/bin/env python3
"""
test_laya_presets.py: Laya 预置问题模板测试
测试范围: triage, email, guard, moderation, router 预置模板
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from laya.presets import (
        triage_questions,
        email_questions,
        guard_questions,
        moderation_questions,
        router_questions,
    )
    HAS_LAYA = True
except ImportError as e:
    HAS_LAYA = False


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestTriageQuestions:
    """测试客服工单分类模板"""

    def test_returns_dict(self):
        questions = triage_questions()
        assert isinstance(questions, dict)

    def test_has_intent(self):
        questions = triage_questions()
        assert "intent" in questions
        assert questions["intent"]["type"] == "choice"
        assert "criteria" in questions["intent"]
        # triage 使用的是 refund 而不是 billing
        assert "refund" in questions["intent"]["criteria"]
        assert "technical_help" in questions["intent"]["criteria"]

    def test_has_is_urgent(self):
        questions = triage_questions()
        assert "is_urgent" in questions
        assert questions["is_urgent"]["type"] == "noul"

    def test_has_frustration(self):
        questions = triage_questions()
        assert "frustration" in questions
        assert questions["frustration"]["type"] == "score"
        assert len(questions["frustration"]["criteria"]) == 4

    def test_has_refund_requested(self):
        questions = triage_questions()
        assert "refund_requested" in questions
        assert questions["refund_requested"]["type"] == "noul"

    def test_has_churn_risk(self):
        questions = triage_questions()
        assert "churn_risk" in questions
        assert questions["churn_risk"]["type"] == "noul"


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestEmailQuestions:
    """测试邮件分类模板"""

    def test_returns_dict(self):
        questions = email_questions()
        assert isinstance(questions, dict)

    def test_has_category(self):
        questions = email_questions()
        assert "category" in questions
        assert questions["category"]["type"] == "choice"
        assert "billing" in questions["category"]["criteria"]
        assert "technical" in questions["category"]["criteria"]
        assert "sales" in questions["category"]["criteria"]
        assert "security" in questions["category"]["criteria"]

    def test_has_is_spam(self):
        questions = email_questions()
        assert "is_spam" in questions
        assert questions["is_spam"]["type"] == "noul"

    def test_has_is_phishing(self):
        questions = email_questions()
        assert "is_phishing" in questions
        assert questions["is_phishing"]["type"] == "noul"

    def test_has_urgency(self):
        questions = email_questions()
        assert "urgency" in questions
        assert questions["urgency"]["type"] == "score"

    def test_has_needs_reply(self):
        questions = email_questions()
        assert "needs_reply" in questions
        assert questions["needs_reply"]["type"] == "noul"

    def test_custom_categories(self):
        """测试自定义分类"""
        custom = {"finance": "money matters", "legal": "legal issues"}
        questions = email_questions(categories=custom)
        assert "finance" in questions["category"]["criteria"]
        assert "legal" in questions["category"]["criteria"]


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestGuardQuestions:
    """测试 Prompt 防护模板"""

    def test_returns_dict(self):
        questions = guard_questions()
        assert isinstance(questions, dict)

    def test_has_jailbreak(self):
        questions = guard_questions()
        assert "jailbreak" in questions
        assert questions["jailbreak"]["type"] == "noul"

    def test_has_prompt_injection(self):
        questions = guard_questions()
        assert "prompt_injection" in questions
        assert questions["prompt_injection"]["type"] == "noul"

    def test_has_sensitive_data(self):
        questions = guard_questions()
        assert "sensitive_data" in questions
        assert questions["sensitive_data"]["type"] == "noul"

    def test_has_harm_severity(self):
        questions = guard_questions()
        assert "harm_severity" in questions
        assert questions["harm_severity"]["type"] == "score"
        assert len(questions["harm_severity"]["criteria"]) == 4

    def test_has_topic(self):
        questions = guard_questions()
        assert "topic" in questions
        assert questions["topic"]["type"] == "choice"
        assert "product_support" in questions["topic"]["criteria"]
        assert "coding" in questions["topic"]["criteria"]


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestModerationQuestions:
    """测试内容审核模板"""

    def test_returns_dict(self):
        questions = moderation_questions()
        assert isinstance(questions, dict)

    def test_has_toxic(self):
        questions = moderation_questions()
        assert "toxic" in questions
        assert questions["toxic"]["type"] == "noul"

    def test_has_harassment(self):
        questions = moderation_questions()
        assert "harassment" in questions
        assert questions["harassment"]["type"] == "noul"

    def test_has_threat(self):
        questions = moderation_questions()
        assert "threat" in questions
        assert questions["threat"]["type"] == "noul"

    def test_has_spam(self):
        questions = moderation_questions()
        assert "spam" in questions
        assert questions["spam"]["type"] == "noul"

    def test_has_severity(self):
        questions = moderation_questions()
        assert "severity" in questions
        assert questions["severity"]["type"] == "score"
        assert len(questions["severity"]["criteria"]) == 4


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestRouterQuestions:
    """测试模型路由模板"""

    def test_returns_dict(self):
        questions = router_questions()
        assert isinstance(questions, dict)

    def test_has_difficulty(self):
        questions = router_questions()
        assert "difficulty" in questions
        assert questions["difficulty"]["type"] == "score"
        assert len(questions["difficulty"]["criteria"]) == 4

    def test_has_domain(self):
        questions = router_questions()
        assert "domain" in questions
        assert questions["domain"]["type"] == "choice"
        assert "code" in questions["domain"]["criteria"]
        assert "math_or_logic" in questions["domain"]["criteria"]
        assert "writing" in questions["domain"]["criteria"]

    def test_has_needs_tools(self):
        questions = router_questions()
        assert "needs_tools" in questions
        assert questions["needs_tools"]["type"] == "noul"

    def test_has_is_sensitive(self):
        questions = router_questions()
        assert "is_sensitive" in questions
        assert questions["is_sensitive"]["type"] == "noul"


@pytest.mark.skipif(not HAS_LAYA, reason="laya not installed")
class TestQuestionValidation:
    """测试预置模板的有效性"""

    def test_all_presets_have_instructions(self):
        """所有预置问题都有 instructions"""
        for preset_fn in [triage_questions, email_questions, guard_questions,
                          moderation_questions, router_questions]:
            questions = preset_fn()
            for qid, qdef in questions.items():
                assert "instructions" in qdef, f"{preset_fn.__name__}.{qid} missing instructions"

    def test_all_presets_have_valid_types(self):
        """所有预置问题类型有效"""
        valid_types = {"choice", "score", "noul"}
        for preset_fn in [triage_questions, email_questions, guard_questions,
                          moderation_questions, router_questions]:
            questions = preset_fn()
            for qid, qdef in questions.items():
                assert qdef["type"] in valid_types, f"{preset_fn.__name__}.{qid} invalid type"

    def test_triage_has_5_questions(self):
        questions = triage_questions()
        assert len(questions) == 5

    def test_email_has_5_questions(self):
        questions = email_questions()
        assert len(questions) == 5

    def test_guard_has_5_questions(self):
        questions = guard_questions()
        assert len(questions) == 5

    def test_moderation_has_5_questions(self):
        questions = moderation_questions()
        assert len(questions) == 5

    def test_router_has_4_questions(self):
        questions = router_questions()
        assert len(questions) == 4