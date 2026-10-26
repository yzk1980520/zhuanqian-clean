# -*- coding: utf-8 -*-
"""
feedback_weight_consumer 单测

覆盖:
1. RED: 预置2条 weight_suggestion → 跑消费者 → 断言产出引用该2条
2. GREEN: 全量回归 pytest 绿
3. read-back 断言验证
4. dry-run 模式验证
5. 空 suggestions 处理
"""
import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

# 注入项目根
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

from core.pipeline.atomic_json import atomic_load, atomic_dump


@pytest.fixture
def suggestions_file(tmp_path):
    """构造测试用 feedback_suggestions.json"""
    p = tmp_path / "feedback_suggestions.json"
    data = {
        "generated_at": "2026-10-16T09:00:00",
        "total_records": 2,
        "weekly_ic": {
            "review_type": "weekly_ic",
            "date": "2026-10-16",
            "observation": "chg5 IC=-0.31死亡",
            "suggested_action": "降权chg5",
            "weight_suggestions": {
                "chg5": {
                    "new_weight": 0,
                    "source": "weekly_ic_monitor",
                    "ts": "2026-10-16T09:00:00",
                    "confidence": "high",
                    "observation": "chg5 IC=-0.31死亡",
                },
                "pos_vs_ma20": {
                    "new_weight": 10,
                    "source": "weekly_ic_monitor",
                    "ts": "2026-10-16T09:00:00",
                    "confidence": "high",
                    "observation": "pos_vs_ma20 IC=-0.23有效",
                },
            },
            "related_factors": ["chg5", "pos_vs_ma20"],
            "confidence": "high",
        },
        "after_close": {
            "review_type": "after_close",
            "date": "2026-10-16",
            "observation": "无交易",
            "suggested_action": "保持空仓",
            "weight_suggestions": None,
        },
    }
    atomic_dump(data, str(p))
    return p


@pytest.fixture
def refs_file(tmp_path):
    return tmp_path / "weight_reestimation_refs.json"


class TestFeedbackWeightConsumer:
    """feedback_weight_consumer 测试"""

    def test_red_two_suggestions_produce_two_refs(self, suggestions_file, refs_file):
        """RED: 预置2条 weight_suggestion → 断言产出引用该2条"""
        from scripts.feedback_weight_consumer import (
            load_suggestions,
            extract_refs,
            build_refs_payload,
            write_refs_atomic,
            SUGGESTIONS_FILE,
            REFS_FILE,
        )

        # 临时替换常量路径
        with patch.object(
            __import__("scripts.feedback_weight_consumer", fromlist=["SUGGESTIONS_FILE"]),
            "SUGGESTIONS_FILE", suggestions_file
        ), patch.object(
            __import__("scripts.feedback_weight_consumer", fromlist=["REFS_FILE"]),
            "REFS_FILE", refs_file
        ):
            data = load_suggestions()
            refs = extract_refs(data)
            payload = build_refs_payload(refs, data.get("generated_at", ""))
            write_refs_atomic(payload)

        # read-back 断言
        result = atomic_load(str(refs_file), default={})
        assert result.get("total_refs") == 2, f"期望2条引用，实际: {result.get('total_refs')}"
        assert len(result.get("refs", [])) == 2
        factors = {r["factor"] for r in result["refs"]}
        assert "chg5" in factors, "应包含 chg5 引用"
        assert "pos_vs_ma20" in factors, "应包含 pos_vs_ma20 引用"
        # after_close 无 weight_suggestions，不应产生引用
        assert all(r["review_type"] != "after_close" for r in result["refs"])

    def test_extract_refs_filters_non_weight_types(self, suggestions_file, refs_file):
        """测试: after_close 无 weight_suggestions → 不产生引用"""
        from scripts.feedback_weight_consumer import extract_refs
        import scripts.feedback_weight_consumer as mod

        with patch.object(mod, "SUGGESTIONS_FILE", suggestions_file):
            data = mod.load_suggestions()
        refs = extract_refs(data)
        # 只有 weekly_ic 的2条
        assert len(refs) == 2
        assert all(r["review_type"] == "weekly_ic" for r in refs)

    def test_extract_refs_empty_suggestions(self, tmp_path, refs_file):
        """测试: 空 suggestions → 0 refs"""
        from scripts.feedback_weight_consumer import extract_refs, build_refs_payload, write_refs_atomic
        import scripts.feedback_weight_consumer as mod

        empty_file = tmp_path / "empty_suggestions.json"
        atomic_dump({"generated_at": "", "total_records": 0, "weekly_ic": {}, "monthly_tune": {}}, str(empty_file))

        with patch.object(mod, "SUGGESTIONS_FILE", empty_file):
            data = mod.load_suggestions()
        refs = extract_refs(data)
        assert len(refs) == 0

    def test_dry_run_no_write(self, suggestions_file, tmp_path):
        """测试: --dry-run 不写 refs 文件"""
        from scripts.feedback_weight_consumer import main
        import scripts.feedback_weight_consumer as mod

        refs_fake = tmp_path / "weight_reestimation_refs.json"
        with patch.object(mod, "SUGGESTIONS_FILE", suggestions_file), \
             patch.object(mod, "REFS_FILE", refs_fake), \
             patch("sys.argv", ["feedback_weight_consumer.py", "--dry-run"]):
            result = main()
        assert result == 0
        assert not refs_fake.exists(), "dry-run 不应写入 refs 文件"

    def test_read_back_assertion(self, suggestions_file, refs_file):
        """测试: write_refs_atomic 的 read-back 断言通过"""
        from scripts.feedback_weight_consumer import load_suggestions, extract_refs, build_refs_payload, write_refs_atomic
        import scripts.feedback_weight_consumer as mod

        with patch.object(mod, "SUGGESTIONS_FILE", suggestions_file), \
             patch.object(mod, "REFS_FILE", refs_file):
            data = mod.load_suggestions()
            refs = mod.extract_refs(data)
            payload = mod.build_refs_payload(refs, data.get("generated_at", ""))
            mod.write_refs_atomic(payload)

        # read-back 再次验证
        rb = atomic_load(str(refs_file), default={})
        assert rb["total_refs"] == 2
        assert rb["refs"] == payload["refs"]

    def test_monthly_tune_also_consumed(self, tmp_path, refs_file):
        """测试: monthly_tune 的 weight_suggestions 也能被消费"""
        from scripts.feedback_weight_consumer import extract_refs
        import scripts.feedback_weight_consumer as mod

        monthly_file = tmp_path / "monthly_suggestions.json"
        data = {
            "generated_at": "2026-10-01T01:00:00",
            "monthly_tune": {
                "review_type": "monthly_tune",
                "weight_suggestions": {
                    "chg5": {"new_weight": 0, "source": "monthly_tune", "ts": "2026-10-01T01:00:00",
                             "confidence": "medium", "observation": "月度复盘"},
                },
            },
        }
        atomic_dump(data, str(monthly_file))

        with patch.object(mod, "SUGGESTIONS_FILE", monthly_file):
            sdata = mod.load_suggestions()
        refs = extract_refs(sdata)
        assert len(refs) == 1
        assert refs[0]["factor"] == "chg5"
        assert refs[0]["review_type"] == "monthly_tune"
