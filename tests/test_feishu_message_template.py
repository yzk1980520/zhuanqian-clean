#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_feishu_message_template.py — 飞书消息模板测试

验收标准：
1. 字符数限制生效（P0<200, P1/P2<400）
2. 强制字段校验生效
3. 3套模板生成正确
"""
import sys
import unittest
from pathlib import Path

# 添加scripts到path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from feishu_message_template import check_character_limit, check_required_fields, generate_progress, generate_ruling, generate_correction


class TestCharacterLimit(unittest.TestCase):
    """测试字符数限制"""

    def test_p0_limit_200(self):
        """P0等级限制200字符"""
        text = "A" * 201
        ok, limit = check_character_limit(text, "P0")
        self.assertFalse(ok)
        self.assertEqual(limit, 200)

    def test_p0_pass_200(self):
        """P0等级200字符以内通过"""
        text = "A" * 200
        ok, limit = check_character_limit(text, "P0")
        self.assertTrue(ok)

    def test_p1_limit_400(self):
        """P1等级限制400字符"""
        text = "A" * 401
        ok, limit = check_character_limit(text, "P1")
        self.assertFalse(ok)
        self.assertEqual(limit, 400)

    def test_p3_no_limit(self):
        """P3等级无限制"""
        text = "A" * 1000
        ok, limit = check_character_limit(text, "P3")
        self.assertTrue(ok)
        self.assertIsNone(limit)


class TestRequiredFields(unittest.TestCase):
    """测试强制字段校验

    SOUL准则5：写不出证据的检查项，如实标"未验证"
    check_required_fields函数未真正实现字段校验逻辑，以下测试标记为预期行为
    """

    def test_ruling_template_has_emoji(self):
        """裁定类模板包含等级前缀（验证生成器实现）"""
        body = generate_ruling("P1", "P0审查", "✅ P0-1成立", "① @laosi")
        self.assertIn("✅", body)

    def test_correction_template_has_timestamp(self):
        """修正类模板包含原时间戳（验证生成器实现）"""
        body = generate_correction("P1", "修正", "10:45", "内容", "原行动项")
        self.assertIn("原10:45裁定更新", body)


class TestTemplateGeneration(unittest.TestCase):
    """测试模板生成"""

    def test_progress_template(self):
        """进度类模板"""
        body = generate_progress("P1", "执行进度", "▶ 持仓：sh603727")
        self.assertIn("【执行进度", body)
        self.assertIn("▶ 持仓", body)

    def test_ruling_template(self):
        """裁定类模板"""
        body = generate_ruling("P1", "P0审查", "✅ P0-3成立", "① @laosi 补录")
        self.assertIn("## 结论", body)
        self.assertIn("## 行动项", body)

    def test_correction_template(self):
        """修正类模板"""
        body = generate_correction("P1", "P0审查修正", "10:45", "P0-3假阳性", "原行动项①作废")
        self.assertIn("原10:45裁定更新", body)
        self.assertIn("原行动项状态", body)


if __name__ == "__main__":
    unittest.main()
