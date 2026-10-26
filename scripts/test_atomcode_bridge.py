#!/usr/bin/env python3
"""
AtomCode Bridge 单元测试
测试跨平台路径查找、异常处理、JSON解析等功能
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess
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
from atomcode_bridge import run_atomcode, analyze_code


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
                    # 模拟第一个候选路径存在
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
        valid_key = "ht_" + "a" * 41  # ht_开头，总长度44
        assert validate_api_key(valid_key) is True
    
    def test_invalid_prefix(self):
        """测试无效前缀"""
        invalid_key = "abc_" + "a" * 40
        assert validate_api_key(invalid_key) is False
    
    def test_invalid_length(self):
        """测试无效长度"""
        short_key = "ht_" + "a" * 10
        assert validate_api_key(short_key) is False
        
        long_key = "ht_" + "a" * 50
        assert validate_api_key(long_key) is False
    
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


@pytest.fixture(scope='class', autouse=True)
def _pin_atomcode_path_for_ci():
    # 2026-10-15 总管 CI兼容: 无 AtomCode CLI 的环境(CI ubuntu)中,
    # run_atomcode 调用期守卫会先于 mocked subprocess.run 抛 RuntimeError.
    # 钉住 ATOMCODE_PATH 占位路径让调用走到被 mock 的 subprocess 层;
    # 本地(有CLI)直接 no-op.
    # 注: 原 setUpClass/tearDownClass 写法在 pytest9 非 TestCase 类上不触发, 改用 fixture.
    import atomcode_bridge
    if atomcode_bridge.ATOMCODE_PATH:
        yield
        return
    p = patch('atomcode_bridge.ATOMCODE_PATH', 'atomcode')
    p.start()
    yield
    p.stop()

class TestRunAtomcode:
    """测试AtomCode调用"""
    
    @patch('subprocess.run')
    def test_timeout_handling(self, mock_run):
        """测试超时处理"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=['atomcode'], timeout=180)
        
        result = run_atomcode("test prompt", timeout=1)
        
        assert result['success'] is False
        assert 'Timeout' in result['error']
    
    @patch('subprocess.run')
    def test_file_not_found(self, mock_run):
        """测试文件不存在"""
        mock_run.side_effect = FileNotFoundError("atomcode.exe")
        
        result = run_atomcode("test prompt")
        
        assert result['success'] is False
        assert 'not found' in result['error'].lower()
    
    @patch('subprocess.run')
    def test_successful_call(self, mock_run):
        """测试成功调用"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({
            "type": "run.started",
            "provider": "custom",
            "model": "agnes-2.5-flash"
        }) + '\n' + json.dumps({
            "type": "assistant.message",
            "message": {
                "content": [{"type": "text", "text": "分析完成"}]
            }
        })
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        result = run_atomcode("test prompt")
        
        assert result['success'] is True
        assert result['provider'] == 'custom'
        assert result['model'] == 'agnes-2.5-flash'
        assert '分析完成' in result.get('content', '')


class TestAnalyzeCode:
    """测试代码分析功能"""
    
    @patch('atomcode_bridge.run_atomcode')
    def test_empty_project_dir(self, mock_run):
        """测试空项目目录"""
        try:
            analyze_code("", "test query")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "project_dir不能为空" in str(e)
    
    @patch('atomcode_bridge.run_atomcode')
    def test_empty_query(self, mock_run):
        """测试空查询"""
        try:
            analyze_code("/tmp", "")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "query不能为空" in str(e)


def run_tests():
    """运行所有测试"""
    import traceback
    
    tests = [
        TestFindAtomcode(),
        TestValidateApiKey(),
        TestEnsureDirectory(),
        TestSafeWriteText(),
        TestParseJsonlLine(),
        TestRunAtomcode(),
        TestAnalyzeCode(),
    ]
    
    passed = 0
    failed = 0
    
    
    for test_class in tests:
        test_name = test_class.__class__.__name__
        print(f"\n📦 {test_name}")
        
        for method_name in dir(test_class):
            if method_name.startswith('test_'):
                method = getattr(test_class, method_name)
                try:
                    pass
                    # 检查是否需要tmp_path参数
                    import inspect
                    sig = inspect.signature(method)
                    params = list(sig.parameters.values())
                    
                    if len(params) > 1:  # 有tmp_path参数
                        with tempfile.TemporaryDirectory() as tmp:
                            method(tmp)
                    else:
                        method()
                    
                    print(f"  ✅ {method_name}")
                    passed += 1
                except Exception as e:
                    print(f"  ❌ {method_name}: {e}")
                    failed += 1
                    if os.environ.get('DEBUG'):
                        traceback.print_exc()
    
    print(f"📊 测试结果: {passed} 通过, {failed} 失败")
    
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
