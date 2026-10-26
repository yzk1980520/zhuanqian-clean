#!/usr/bin/env python3
"""
common.py 单元测试
测试公共工具模块
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest


# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from common import (
    find_atomcode,
    validate_api_key,
    ensure_directory,
    safe_write_text,
    parse_jsonl_line
)


class TestFindAtomcode:
    """测试跨平台路径查找"""
    
    def test_find_in_path(self):
        """测试从PATH中找到atomcode"""
        with patch('shutil.which') as mock_which:
            mock_which.return_value = "/usr/local/bin/atomcode"
            result = find_atomcode()
            assert result == "/usr/local/bin/atomcode"
    
    @pytest.mark.skipif(os.name != 'nt',
                        reason="Windows路径语义测试: 非Windows下模拟nt分支会实例化WindowsPath抛NotImplementedError(CI ubuntu 3.11实证)")
    def test_find_in_windows_paths(self):
        """测试Windows常见路径查找"""
        with patch('os.name', 'nt'):
            with patch('shutil.which', return_value=None):
                with patch.object(Path, 'exists') as mock_exists:
                    mock_exists.side_effect = [False, False, True]
                    result = find_atomcode()
                    assert result is not None
                    assert "atomcode" in result.lower()
    
    def test_find_not_found(self):
        """测试未找到atomcode"""
        with patch('shutil.which', return_value=None):
            with patch.object(Path, 'exists', return_value=False):
                result = find_atomcode()
                assert result is None


class TestValidateApiKey:
    """测试API Key验证"""
    
    def test_valid_key(self):
        """测试有效API Key"""
        valid_key = "ht_" + "a" * 41
        assert validate_api_key(valid_key) is True
    
    def test_invalid_prefix(self):
        """测试无效前缀"""
        invalid_key = "abc_" + "a" * 40
        assert validate_api_key(invalid_key) is False
    
    def test_invalid_length(self):
        """测试无效长度"""
        assert validate_api_key("ht_" + "a" * 10) is False
        assert validate_api_key("ht_" + "a" * 50) is False
    
    def test_empty_key(self):
        """测试空字符串"""
        assert validate_api_key("") is False


class TestEnsureDirectory:
    """测试目录创建"""
    
    def test_create_new_directory(self):
        """测试创建新目录"""
        with tempfile.TemporaryDirectory() as tmp:
            new_dir = Path(tmp) / "new_dir"
            ensure_directory(new_dir)
            assert new_dir.exists()
            assert new_dir.is_dir()
    
    def test_create_existing_directory(self):
        """测试创建已存在目录"""
        with tempfile.TemporaryDirectory() as tmp:
            existing_dir = Path(tmp) / "existing_dir"
            existing_dir.mkdir()
            ensure_directory(existing_dir)
            assert existing_dir.exists()


class TestSafeWriteText:
    """测试安全写入"""
    
    def test_write_file(self):
        """测试写入文件"""
        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "test.txt"
            content = "测试内容"
            
            safe_write_text(test_file, content)
            
            assert test_file.exists()
            assert test_file.read_text() == content
    
    def test_write_overwrites(self):
        """测试覆盖写入"""
        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "test.txt"
            test_file.write_text("旧内容")
            
            safe_write_text(test_file, "新内容")
            
            assert test_file.read_text() == "新内容"


class TestParseJsonlLine:
    """测试JSONL解析"""
    
    def test_valid_json(self):
        """测试有效JSON"""
        line = '{"type": "run.started", "provider": "test"}'
        result = parse_jsonl_line(line)
        assert result is not None
        assert result['type'] == 'run.started'
        assert result['provider'] == 'test'
    
    def test_invalid_json(self):
        """测试无效JSON"""
        line = 'this is not json'
        result = parse_jsonl_line(line)
        assert result is None
    
    def test_empty_line(self):
        """测试空行"""
        result = parse_jsonl_line('')
        assert result is None
    
    def test_whitespace_only(self):
        """测试空白行"""
        result = parse_jsonl_line('   ')
        assert result is None


def run_tests():
    """运行所有测试"""
    import traceback
    
    test_classes = [
        TestFindAtomcode,
        TestValidateApiKey,
        TestEnsureDirectory,
        TestSafeWriteText,
        TestParseJsonlLine,
    ]
    
    passed = 0
    failed = 0
    failures = []
    
    
    for test_class in test_classes:
        test_instance = test_class()
        test_name = test_class.__name__
        
        print(f"\n📦 {test_name}")
        
        for method_name in dir(test_instance):
            if method_name.startswith('test_'):
                try:
                    method = getattr(test_instance, method_name)
                    method()
                    passed += 1
                except Exception as e:
                    print(f"  ❌ {method_name}: {e}")
                    failures.append((test_name, method_name, str(e)))
                    failed += 1
                    if os.environ.get('DEBUG'):
                        traceback.print_exc()
    
    print(f"📊 测试结果: {passed} 通过, {failed} 失败")
    
    if failures:
        for test_name, method_name, error in failures:
            print(f"   {test_name}.{method_name}: {error}")
    
    
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
