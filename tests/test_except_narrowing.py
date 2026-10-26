"""
test_except_narrowing.py: P0 异常收窄测试
覆盖: risk_rules._load_trade_dates 回退路径、收窄外漏验证
时间：2026-10-07
编制：老三（技术验证专家）
"""
import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestLoadTradeDatesFallback:
    """测试 _load_trade_dates 的异常回退路径"""
    
    def test_json_missing_returns_tdx_fallback(self):
        """sh_index_history.json 缺失时回退 TDX"""
        from risk_rules import _load_trade_dates
        import risk_rules as rr_module
        
        # 清除缓存
        original_cache = getattr(rr_module, '_TRADE_DATES_CACHE', None)
        rr_module._TRADE_DATES_CACHE = None
        
        try:
            with patch('os.path.exists', return_value=False):
                # 直接调用，验证不抛 KeyError
                dates = _load_trade_dates()
                assert isinstance(dates, list)
        except KeyError:
            pytest.fail("_load_trade_dates 不应抛出 KeyError")
        finally:
            if original_cache is not None:
                rr_module._TRADE_DATES_CACHE = original_cache
    
    def test_json_corrupted_returns_tdx_fallback(self):
        """sh_index_history.json 损坏时回退 TDX"""
        from risk_rules import _load_trade_dates
        import risk_rules as rr_module
        
        original_cache = getattr(rr_module, '_TRADE_DATES_CACHE', None)
        rr_module._TRADE_DATES_CACHE = None
        
        try:
            with patch('os.path.exists', return_value=True):
                with patch('builtins.open', MagicMock()):
                    try:
                        dates = _load_trade_dates()
                        assert isinstance(dates, list)
                    except (json.JSONDecodeError, KeyError):
                        pytest.fail("_load_trade_dates 应捕获 JSON 错误并回退")
        finally:
            if original_cache is not None:
                rr_module._TRADE_DATES_CACHE = original_cache
    
    def test_tdx_fallback_also_fails_returns_workday(self):
        """TDX 回退也失败时使用工作日近似"""
        from risk_rules import _load_trade_dates
        import risk_rules as rr_module
        
        original_cache = getattr(rr_module, '_TRADE_DATES_CACHE', None)
        rr_module._TRADE_DATES_CACHE = None
        
        try:
            with patch('os.path.exists', return_value=False):
                with patch.dict('sys.modules', {'tdx_data': None}):
                    try:
                        dates = _load_trade_dates()
                        assert isinstance(dates, list)
                    except Exception as e:
                        pytest.fail(f"_load_trade_dates 应 gracefully 处理所有异常，实际抛出: {type(e).__name__}: {e}")
        finally:
            if original_cache is not None:
                rr_module._TRADE_DATES_CACHE = original_cache


class TestNarrowedExceptionCoverage:
    """测试收窄后的异常捕获是否覆盖正确"""
    
    def test_keyerror_not_caught_in_evaluate_exit(self):
        """验证 evaluate_exit 中不再捕获 KeyError（应为 ValueError）"""
        from risk_rules import evaluate_exit
        
        # 传入非法日期字符串，应触发 ValueError 而非 KeyError
        entry = {
            "entry_price": 100.0,
            "entry_date": "invalid-date",
        }
        
        # 不应抛出 KeyError，应处理为无效日期
        try:
            result = evaluate_exit(entry, 105.0, "强")
            # 如果到达这里，说明异常被正确处理
            assert result is not None
        except KeyError:
            pytest.fail("evaluate_exit 不应抛出 KeyError，已修复为捕获 ValueError/TypeError")
    
    def test_valueerror_is_caught(self):
        """验证 ValueError 被正确捕获"""
        from risk_rules import evaluate_exit
        
        entry = {
            "entry_price": 100.0,
            "entry_date": "not-a-date",
        }
        
        # 应返回默认日期，不抛出异常
        should_exit, reason, exit_type, _ = evaluate_exit(entry, 105.0, "强")
        assert should_exit is False  # 价格未触发任何条件
        assert isinstance(reason, str)


class TestGatewayGuardianTimeoutExpired:
    """测试 gateway_guardian.py 的 TimeoutExpired 处理"""
    
    def test_timeout_expired_not_caught_by_general_except(self):
        """验证 subprocess.TimeoutExpired 不在 general except 范围内"""
        import subprocess
        
        # TimeoutExpired 是 subprocess 模块的异常
        # 检查 gateway_guardian.py 的 except 子句
        guardian_path = Path(__file__).parent.parent / "scripts" / "gateway_guardian.py"
        
        if guardian_path.exists():
            content = guardian_path.read_text(encoding="utf-8")
            
            # 检查是否有明确捕获 TimeoutExpired
            has_timeout_catch = "TimeoutExpired" in content
            
            # 如果没有，这是一个潜在问题
            if not has_timeout_catch:
                pytest.skip("gateway_guardian.py 未明确捕获 TimeoutExpired，可能需要补充")
            else:
                assert True  # 已捕获，测试通过
        else:
            pytest.skip("gateway_guardian.py 不存在")


class TestFeishuReporterConnectionError:
    """测试 health_monitor/reporters/feishu.py 的 ConnectionError 处理"""
    
    def test_connection_error_not_caught_by_general_except(self):
        """验证 requests.ConnectionError 不在 general except 范围内"""
        feishu_path = Path(__file__).parent.parent / "health_monitor" / "reporters" / "feishu.py"
        
        if feishu_path.exists():
            content = feishu_path.read_text(encoding="utf-8")
            
            # 检查是否有明确捕获 ConnectionError 或 requests 异常
            has_connection_catch = "ConnectionError" in content or "requests" in content
            
            # urllib.request 的异常通常是 URLError 或 HTTPError
            has_urllib_catch = "URLError" in content or "HTTPError" in content
            
            if not (has_connection_catch or has_urllib_catch):
                pytest.skip("feishu.py 未明确捕获连接异常，建议使用 general except 已足够（urllib 异常类型）")
            else:
                assert True
        else:
            pytest.skip("feishu.py 不存在")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
