#!/usr/bin/env python3
"""
test_signal_day_chg.py: 信号日涨幅计算函数测试
覆盖: 正常情况、边界条件、异常输入
"""
import sys, os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from risk_rules import signal_day_chg


class TestSignalDayChg:
    """signal_day_chg 函数测试"""

    def setup_method(self):
        """准备测试数据"""
        self.records = [
            {'date': date(2024, 1, i), 'close': 10.0 + i * 0.5}
            for i in range(1, 11)
        ]

    def test_normal_case(self):
        """测试1: 正常涨幅计算"""
        result = signal_day_chg(self.records, date(2024, 1, 5))
        assert result is not None
        assert result[0] == 12.5  # 第5天收盘价
        expected_chg = (12.5 / 12.0 - 1) * 100  # 相对第4天
        assert abs(result[1] - expected_chg) < 0.01

    def test_first_day(self):
        """测试2: 第一天无前一交易日"""
        result = signal_day_chg(self.records, date(2024, 1, 1))
        assert result[0] == 10.5
        assert result[1] is None  # 无前一交易日，涨幅为None

    def test_date_not_found(self):
        """测试3: 日期不存在"""
        # 使用有效但不存在的日期（1月15日不在测试数据中）
        result = signal_day_chg(self.records, date(2024, 1, 15))
        assert result is None

    def test_string_date(self):
        """测试4: 字符串日期输入"""
        result = signal_day_chg(self.records, '2024-01-05')
        assert result is not None
        assert result[0] == 12.5

    def test_empty_records(self):
        """测试5: 空记录列表"""
        result = signal_day_chg([], date(2024, 1, 1))
        assert result is None

    def test_single_record(self):
        """测试6: 单条记录"""
        single = [{'date': date(2024, 1, 1), 'close': 10.0}]
        result = signal_day_chg(single, date(2024, 1, 1))
        assert result[0] == 10.0
        assert result[1] is None

    def test_boundary_index(self):
        """测试7: 边界索引检查"""
        # 最后一个日期
        result = signal_day_chg(self.records, date(2024, 1, 10))
        assert result is not None
        assert result[0] == 15.0

    def test_negative_change(self):
        """测试8: 跌幅计算"""
        records_down = [
            {'date': date(2024, 1, i), 'close': 10.0 - i * 0.3}
            for i in range(1, 6)
        ]
        result = signal_day_chg(records_down, date(2024, 1, 4))
        assert result[1] < 0, "应返回负涨幅"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
