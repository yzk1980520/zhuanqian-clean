#!/usr/bin/env python3
"""
test_tdx_indicators.py: TDX技术指标计算模块测试
覆盖: SMA/EMA/RSI/ATR/MACD/成交量模式等基础指标计算
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.scoring.tdx_indicators import (
    calc_sma,
    calc_ema_list,
    calc_rsi,
    calc_atr,
    calc_atr_stop,
    calc_macd,
    aggregate_weekly,
    compute_weekly_indicators,
    analyze_volume_pattern,
    compute_indicators,
)


class TestCalcSMA:
    """SMA简单移动平均测试"""

    def test_basic(self):
        """测试基本计算"""
        data = [1, 2, 3, 4, 5]
        result = calc_sma(data, 3)
        assert result == 4.0  # (2+3+4)/3 或 (3+4+5)/3 取决于实现

    def test_insufficient_data(self):
        """数据不足返回None"""
        data = [1, 2]
        result = calc_sma(data, 3)
        assert result is None

    def test_empty_data(self):
        """空数据返回None"""
        result = calc_sma([], 3)
        assert result is None

    def test_exact_period(self):
        """数据刚好等于周期"""
        data = [10, 20, 30]
        result = calc_sma(data, 3)
        assert result == 20.0


class TestCalcEMA:
    """EMA指数移动平均测试"""

    def test_basic(self):
        """测试基本计算"""
        data = [1, 2, 3, 4, 5]
        result = calc_ema_list(data, 3)
        assert len(result) == 5
        assert result[0] is None
        assert result[1] is None
        assert result[2] is not None  # 第一个有效值

    def test_insufficient_data(self):
        """数据不足返回None列表"""
        data = [1, 2]
        result = calc_ema_list(data, 3)
        assert len(result) == 2
        assert all(r is None for r in result)

    def test_ema_values_monotonic(self):
        """单调递增数据的EMA应递增"""
        data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        result = calc_ema_list(data, 3)
        # 跳过None值
        valid = [r for r in result if r is not None]
        assert len(valid) >= 2
        assert valid[-1] > valid[-2]  # EMA应反映上升趋势


class TestCalcRSI:
    """RSI相对强弱指标测试"""

    def test_basic(self):
        """测试基本计算"""
        closes = [10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 17, 19, 20]
        result = calc_rsi(closes, 14)
        assert 0 <= result <= 100

    def test_insufficient_data(self):
        """数据不足返回50"""
        closes = [10, 11, 12]
        result = calc_rsi(closes, 14)
        assert result == 50.0

    def test_all_gains(self):
        """全涨行情RSI应接近100"""
        closes = [10 + i for i in range(15)]
        result = calc_rsi(closes, 14)
        assert result > 90

    def test_all_losses(self):
        """全跌行情RSI应接近0"""
        closes = [10 - i for i in range(15)]
        result = calc_rsi(closes, 14)
        assert result < 10

    def test_neutral_market(self):
        """震荡行情RSI应在50附近"""
        closes = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10]
        result = calc_rsi(closes, 14)
        assert 40 <= result <= 60


class TestCalcATR:
    """ATR平均真实波幅测试"""

    def test_basic(self):
        """测试基本计算"""
        records = [
            {"high": 110, "low": 100, "close": 105},
            {"high": 115, "low": 105, "close": 110},
            {"high": 120, "low": 110, "close": 115},
        ] * 15  # 至少15条记录
        result = calc_atr(records, 14)
        assert result is not None
        assert result > 0

    def test_insufficient_data(self):
        """数据不足返回None"""
        records = [
            {"high": 110, "low": 100, "close": 105},
            {"high": 115, "low": 105, "close": 110},
        ]
        result = calc_atr(records, 14)
        assert result is None

    def test_empty_records(self):
        """空记录返回None"""
        result = calc_atr([], 14)
        assert result is None


class TestCalcATRStop:
    """ATR止损计算测试"""

    def test_basic(self):
        """测试止损计算"""
        records = [
            {"high": 110, "low": 100, "close": 105}
        ] * 15
        stop_price, atr = calc_atr_stop(records, multiplier=2.0)
        assert stop_price is not None
        assert atr is not None
        assert stop_price < 105  # 止损价应低于当前价

    def test_insufficient_data(self):
        """数据不足返回None"""
        records = [{"high": 110, "low": 100, "close": 105}]
        stop_price, atr = calc_atr_stop(records, multiplier=2.0)
        assert stop_price is None
        assert atr is None


class TestCalcMACD:
    """MACD指标测试"""

    def test_basic(self):
        """测试基本计算"""
        closes = list(range(10, 40))  # 30天数据
        dif, dea, hist = calc_macd(closes)
        assert dif is not None
        assert dea is not None
        assert hist is not None

    def test_insufficient_data(self):
        """数据不足返回None"""
        closes = [10, 11, 12]
        dif, dea, hist = calc_macd(closes)
        assert dif is None
        assert dea is None
        assert hist is None

    def test_macd_dif_dea_relationship(self):
        """验证DIF和DEA的关系"""
        # 上升趋势
        closes = [10 + i * 0.5 for i in range(30)]
        dif, dea, hist = calc_macd(closes)
        # 初期DIF和DEA可能相等（都基于前26个数据计算）
        # 应确保hist >= 0（上升趋势）
        assert hist >= 0


class TestAggregateWeekly:
    """周线聚合测试"""

    def test_basic(self):
        """测试基本聚合"""
        records = [
            {"date": "20240101", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"date": "20240102", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 150},
            {"date": "20240103", "open": 11, "high": 13, "low": 11, "close": 12, "volume": 200},
        ]
        result = aggregate_weekly(records)
        assert len(result) >= 1
        # 周线应包含所有数据
        assert result[0]["high"] == 13
        assert result[0]["low"] == 9

    def test_empty_records(self):
        """空记录返回空列表"""
        result = aggregate_weekly([])
        assert result == []

    def test_date_string_format(self):
        """支持字符串日期格式"""
        records = [
            {"date": "20240101", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        ]
        result = aggregate_weekly(records)
        assert len(result) == 1


class TestComputeWeeklyIndicators:
    """周线指标计算测试"""

    def test_basic(self):
        """测试基本计算"""
        records = [
            {"date": f"20240{i//5}{i%5+1:02d}", "open": 10+i, "high": 12+i, 
             "low": 9+i, "close": 11+i, "volume": 100+i}
            for i in range(50)
        ]
        result = compute_weekly_indicators(records)
        assert result is not None
        assert "w_ma5" in result
        assert "w_ma10" in result
        assert "w_bullish" in result

    def test_insufficient_data(self):
        """数据不足返回None"""
        records = [
            {"date": "20240101", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
        ]
        result = compute_weekly_indicators(records)
        assert result is None


class TestAnalyzeVolumePattern:
    """成交量模式分析测试"""

    def test_basic(self):
        """测试基本分析"""
        records = [
            {"close": 10 + i * 0.1, "volume": 100 + i * 10,
             "high": 11 + i * 0.1, "low": 9 + i * 0.1}
            for i in range(25)
        ]
        pattern, description = analyze_volume_pattern(records)
        # 应返回模式或None
        assert pattern is None or isinstance(pattern, str)

    def test_insufficient_data(self):
        """数据不足返回None"""
        records = [
            {"close": 10, "volume": 100, "high": 11, "low": 9}
        ]
        pattern, description = analyze_volume_pattern(records)
        assert pattern is None
        assert description is None

    def test_empty_records(self):
        """空记录返回None"""
        pattern, description = analyze_volume_pattern([])
        assert pattern is None
        assert description is None


class TestComputeIndicators:
    """主指标集合计算测试"""

    def test_basic(self):
        """测试基本计算"""
        records = [
            {"date": f"202401{i:02d}", "close": 10 + i * 0.1, "high": 11 + i * 0.1,
             "low": 9 + i * 0.1, "volume": 100 + i * 10,
             "open": 10 + i * 0.05, "amount": 1000 + i * 100}
            for i in range(1, 31)
        ]
        result = compute_indicators(records)
        assert result is not None
        assert isinstance(result, dict)
        # 应包含关键指标
        assert "ma5" in result or any("ma" in k for k in result.keys())

    def test_insufficient_data(self):
        """数据不足返回None"""
        records = [
            {"close": 10, "high": 11, "low": 9, "volume": 100,
             "open": 10, "amount": 1000}
        ]
        result = compute_indicators(records)
        assert result is None

    def test_empty_records(self):
        """空记录返回None"""
        result = compute_indicators([])
        assert result is None

    def test_returns_dict(self):
        """验证返回值类型"""
        records = [
            {"date": f"202401{i:02d}", "close": 10 + i, "high": 11 + i, "low": 9 + i,
             "volume": 100 + i * 10, "open": 10 + i * 0.5,
             "amount": 1000 + i * 100}
            for i in range(1, 41)
        ]
        result = compute_indicators(records)
        assert isinstance(result, dict)
        # 检查包含关键指标
        key_list = list(result.keys())
        assert len(key_list) > 5  # 应有多个指标


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
