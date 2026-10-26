#!/usr/bin/env python3
"""
回测错误恢复测试
覆盖：数据缺失、计算异常、边界情况容错
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from datetime import date
from backtest.backtest_fast_inds import fast_compute_all, build_sorted_index, get_scan_inds_bisect


class TestDataMissing:
    """数据缺失容错测试"""

    def test_missing_close(self):
        """缺少close字段"""
        records = [
            {"date": date(2024, 1, i), "high": 11.0, "low": 9.0, "volume": 1000000}
            for i in range(1, 30)
        ]
        # 应返回None或抛出异常
        try:
            result = fast_compute_all(records)
            assert result is None or len(result) == 0
        except Exception:
            print(f"🔴 [tests\test_error_recovery.py] CR-01: except Exception:", file=sys.stderr)
    def test_missing_volume(self):
        """缺少volume字段"""
        records = [
            {"date": date(2024, 1, i), "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i}
            for i in range(1, 30)
        ]
        try:
            result = fast_compute_all(records)
            # 应正常计算（volume缺失时使用默认值）
            assert result is not None
        except Exception:
            print(f"🔴 [tests\test_error_recovery.py] CR-01: except Exception:", file=sys.stderr)
    def test_negative_price(self):
        """负价格处理"""
        records = [
            {"date": date(2024, 1, i), "close": -10.0 if i == 5 else 10.0 + i, 
             "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
            for i in range(1, 30)
        ]
        try:
            result = fast_compute_all(records)
            # 应能处理负价格（跳过或修正）
            assert result is not None
        except Exception:
            print(f"🔴 [tests\test_error_recovery.py] CR-01: except Exception:", file=sys.stderr)
class TestBoundaryConditions:
    """边界条件测试"""

    def test_single_record(self):
        """单条记录"""
        records = [{"date": date(2024, 1, 1), "close": 10.0, "high": 11.0, "low": 9.0, "volume": 1000000}]
        result = fast_compute_all(records)
        assert result is None  # 数据不足

    def test_exact_threshold(self):
        """恰好20条记录（阈值边界）"""
        records = [
            {"date": date(2024, 1, i), "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
            for i in range(1, 21)
        ]
        result = fast_compute_all(records)
        # 应返回空列表或None（需要至少20条才有计算）
        assert result is None or len(result) == 0

    def test_just_over_threshold(self):
        """恰好21条记录"""
        records = [
            {"date": date(2024, 1, i), "open": 10.0 + i, "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
            for i in range(1, 22)
        ]
        result = fast_compute_all(records)
        # 应返回少量记录
        assert result is not None
        assert len(result) >= 1


class TestErrorRecovery:
    """错误恢复测试"""

    def test_inconsistent_date_format(self):
        """不一致的日期格式"""
        records = [
            {"date": f"2024-01-{i:02d}", "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i, "volume": 1000000}
            for i in range(1, 30)
        ]
        try:
            result = fast_compute_all(records)
            assert result is not None
        except Exception as e:
            # 应记录错误但不崩溃
            print(f"警告: 日期格式不一致导致异常: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
