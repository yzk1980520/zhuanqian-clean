#!/usr/bin/env python3
"""
setup_financial_analysis.py 单元测试
测试配置检测、API Key验证等功能
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from setup_financial_analysis import (
    detect_current_config,
    show_status,
    create_default_config,
    set_api_key
)
import common  # 直接导入common模块以访问validate_api_key


class TestDetectCurrentConfig:
    """测试配置检测"""
    
    def test_detect_existing_config(self):
        """测试检测已有配置"""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".htsc-skills"
            config_file = config_dir / "config"
            config_file.parent.mkdir(parents=True)
            
            # 创建配置文件
            config_file.write_text("HT_APIKEY=ht_test123\n")
            
            with patch('pathlib.Path.home', return_value=home):
                results = detect_current_config()
                
                # 找到配置文件
                found = [r for r in results if r['path'] == str(config_file)]
                assert len(found) == 1
                assert found[0]['exists'] is True
                assert found[0]['has_ht_apikey'] is True
    
    def test_detect_missing_config(self):
        """测试检测缺失配置"""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)

            # 2026-10-15 老六修复: detect_current_config 第三个探测路径是
            # Path.cwd()/".env", 原测试只 patch 了 home 没隔离 cwd,
            # 项目根 .env 真实存在导致 exists=True 断言失败
            with patch('pathlib.Path.home', return_value=home), \
                 patch('pathlib.Path.cwd', return_value=home):
                results = detect_current_config()

                # 所有配置都应不存在
                for result in results:
                    assert result['exists'] is False


class TestSetApiKey:
    """测试API Key设置"""
    
    def test_set_valid_key(self):
        """测试设置有效API Key"""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_dir = home / ".htsc-skills"
            
            with patch('pathlib.Path.home', return_value=home):
                with patch('common.ensure_directory'):
                    set_api_key("ht_" + "a" * 41)
                    
                    config_file = config_dir / "config"
                    assert config_file.exists()
                    content = config_file.read_text()
                    assert "HT_APIKEY=ht_" in content
    
    def test_set_invalid_key(self):
        """测试设置无效API Key"""
        try:
            set_api_key("invalid_key")
            assert False, "Should raise ValueError"
        except ValueError as e:
            assert "格式错误" in str(e)


def run_tests():
    """运行所有测试"""
    import traceback
    
    test_classes = [
        TestDetectCurrentConfig,
        TestSetApiKey,
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
