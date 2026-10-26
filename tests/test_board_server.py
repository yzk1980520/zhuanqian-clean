# -*- coding: utf-8 -*-
"""
看板服务器单元测试
覆盖: 数据加载 / HTML生成 / API密钥安全 / 退役股过滤
"""
import json
import os
import sys
import unittest
from pathlib import Path
from io import StringIO

import pytest

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'dashboards'))

from board_server import (\
    load_json, esc, card, ts_badge, is_delisted, _load_review_status,\
    DELISTED_KEYWORDS, REVIEW
)


class TestLoadJson(unittest.TestCase):
    """测试JSON加载函数"""
    
    def test_valid_json(self):
        """测试有效JSON文件加载"""
        data = load_json('data/review_status.json')
        self.assertIsInstance(data, dict)
        self.assertIn('laowu_approved', data)
    
    def test_missing_file(self):
        """测试缺失文件返回默认值"""
        data = load_json('data/nonexistent_file.json', default={'key': 'value'})
        self.assertEqual(data, {'key': 'value'})
    
    def test_corrupted_json(self):
        """测试损坏JSON返回默认值"""
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{invalid json}')
            tmp_path = f.name
        try:
            data = load_json(tmp_path, default={'fallback': True})
            self.assertTrue(data['fallback'])
        finally:
            os.unlink(tmp_path)


class TestEscHtml(unittest.TestCase):
    """测试HTML转义函数"""
    
    def test_basic_escape(self):
        """测试基础转义"""
        self.assertEqual(esc('<script>'), '&lt;script&gt;')
        self.assertEqual(esc('&'), '&amp;')
    
    def test_mixed_content(self):
        """测试混合内容"""
        self.assertEqual(esc('<a>&b'), '&lt;a&gt;&amp;b')
    
    def test_none_input(self):
        """测试None输入"""
        self.assertEqual(esc(None), '')


class TestCardFunction(unittest.TestCase):
    """测试卡片生成函数"""
    
    def test_card_structure(self):
        """测试卡片基本结构"""
        html = card('测试标题', '测试内容')
        self.assertIn('card', html)
        self.assertIn('card-title', html)
        self.assertIn('card-body', html)
        self.assertIn('测试标题', html)
        self.assertIn('测试内容', html)
    
    def test_card_tone(self):
        """测试卡片tone参数"""
        html_ok = card('OK卡', '内容', tone='card-ok')
        html_warn = card('警告卡', '内容', tone='card-warn')
        html_danger = card('危险卡', '内容', tone='card-danger')
        
        self.assertIn('#10B981', html_ok)  # green
        self.assertIn('#F59E0B', html_warn)  # orange
        self.assertIn('#F43F5E', html_danger)  # red
    
    def test_card_no_tone(self):
        """测试无tone参数"""
        html = card('普通卡', '内容')
        self.assertNotIn('border-left', html)


class TestDelistedFilter(unittest.TestCase):
    """测试退役股过滤函数"""
    
    def test_normal_stock(self):
        """测试正常股票不过滤"""
        self.assertFalse(is_delisted('中国重工'))
        self.assertFalse(is_delisted('招商银行'))
    
    def test_delisted_stock(self):
        """测试退役股过滤"""
        self.assertTrue(is_delisted('退市锦港'))
        self.assertTrue(is_delisted('退市九有'))
    
    def test_st_stock(self):
        """测试ST股过滤"""
        self.assertTrue(is_delisted('ST华仪'))
        self.assertTrue(is_delisted('*ST新光'))
    
    def test_empty_input(self):
        """测试空输入"""
        self.assertFalse(is_delisted(''))
        self.assertFalse(is_delisted(None))


class TestAiApiKey(unittest.TestCase):
    """测试AI API密钥安全"""
    
    def test_no_hardcoded_key(self):
        """测试API密钥未硬编码"""
        with open('dashboards/board_server.py', 'r') as f:
            content = f.read()
        # 检查是否包含完整密钥格式
        self.assertNotIn('[REDACTED_SK_KEY]', content)
    
    def test_uses_env_var(self):
        """测试使用环境变量"""
        with open('dashboards/board_server.py', 'r') as f:
            content = f.read()
        self.assertIn('AGNES_API_KEY', content)
        self.assertIn('os.environ.get', content)


class TestBoardHtmlGeneration(unittest.TestCase):
    """测试看板HTML生成"""

    # P3 2026-10-26 (t_81fad29b): 本类两项均调 build_html()（全量数据加载+HTML 渲染,
    # 实测 18.06s/项）→ 门禁快档排除；全量/夜间档照常跑。
    pytestmark = [pytest.mark.slow]

    def test_html_contains_expected_sections(self):
        """测试HTML包含预期区块"""
        # 需要设置环境变量
        os.environ.setdefault('AGNES_API_KEY', 'test-key')
        
        try:
            from board_server import build_html
            html = build_html()
            
            # 检查关键元素
            self.assertIn('选股系统看板', html)
            self.assertIn('候选池', html)
            self.assertIn('审批闸', html)
            self.assertIn('AI专家分析', html)
        finally:
            del os.environ['AGNES_API_KEY']
    
    def test_html_valid_structure(self):
        """测试HTML结构有效性"""
        os.environ.setdefault('AGNES_API_KEY', 'test-key')
        try:
            from board_server import build_html
            html = build_html()
            
            self.assertIn('<!DOCTYPE html>', html)
            self.assertIn('</html>', html)
            self.assertIn('<head>', html)
            self.assertIn('<body>', html)
        finally:
            del os.environ['AGNES_API_KEY']


if __name__ == '__main__':
    unittest.main()


class TestReviewStatusFallback(unittest.TestCase):
    """测试 review_status.json 缺失/损坏时的降级行为 (P1 修复验证)。

    核心断言：
    - _load_review_status 永远返回 dict(approved=bool, raw=dict|{})，不抛异常
    - build_html 在 review 源缺失时返回 200（无 NameError），且 approved 语义=未批准
    """

    def test_load_review_status_missing_file(self):
        """review_status.json 不存在 → approved=False，不抛异常"""
        import board_server as _bs
        orig = _bs.REVIEW
        try:
            _bs.REVIEW = "/nonexistent/path/review_status.json"
            result = _load_review_status()
            self.assertIsInstance(result, dict)
            self.assertIn("approved", result)
            self.assertIn("raw", result)
            self.assertIs(result["approved"], False)
            self.assertEqual(result["raw"], {})
        finally:
            _bs.REVIEW = orig

    def test_load_review_status_corrupted_json(self):
        """review_status.json 损坏 → approved=False，不抛异常"""
        import board_server as _bs
        import tempfile
        orig = _bs.REVIEW
        fd, tmp = tempfile.mkstemp(suffix=".json")
        try:
            os.write(fd, b"{invalid json!!!")
            os.close(fd)
            _bs.REVIEW = tmp
            result = _load_review_status()
            self.assertIsInstance(result, dict)
            self.assertIs(result["approved"], False)
            self.assertEqual(result["raw"], {})
        finally:
            _bs.REVIEW = orig
            os.unlink(tmp)

    @pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): 调 build_html()（全量数据加载+渲染, 与 TestBoardHtmlGeneration 同级重件）→ 门禁快档排除
    def test_build_html_no_nameerror_when_review_missing(self):
        """review_status.json 缺失时 build_html() 不抛 NameError，返回合法 HTML"""
        import board_server as _bs
        import tempfile, shutil
        orig_review = _bs.REVIEW
        # 临时改 REVIEW 指向不存在的文件
        fake_review = os.path.join(tempfile.gettempdir(), "__fake_review_status_missing.json")
        try:
            _bs.REVIEW = fake_review
            os.environ.setdefault('AGNES_API_KEY', 'test-key')
            html = _bs.build_html()
            self.assertIsInstance(html, str)
            self.assertGreater(len(html), 0)
            self.assertIn('<!DOCTYPE html>', html)
            # 降级文案应出现在 HTML 中
            self.assertIn('数据源缺失', html)
        finally:
            _bs.REVIEW = orig_review
            if os.path.exists(fake_review):
                os.unlink(fake_review)
            if 'AGNES_API_KEY' in os.environ:
                del os.environ['AGNES_API_KEY']
