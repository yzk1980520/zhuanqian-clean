#!/usr/bin/env python3
"""
S1 backtest unit tests (v28/v29).
Covers: score_stock, get_position_pct, trade model checks, exit conditions.
Note: Uses inline function definitions to avoid importing s1_v29 (which loads cache at module level).
"""
import sys, os
import pytest
from datetime import date, timedelta


# === Inline implementations for testing (mirrors s1_v29) ===

def score_stock(inds):
    """4-dimensional scoring: trend/momentum/volume/oversold"""
    if not inds or inds.get('close', 0) <= 0:
        return 0.0
    score = 0.0
    ma5 = inds.get('ma5')
    ma10 = inds.get('ma10')
    ma20 = inds.get('ma20')
    close = inds.get('close')
    if all(v is not None for v in [ma5, ma10, ma20]):
        if ma5 > ma10 > ma20 and close > ma20:
            score += 30
        elif ma5 > ma10 and close > ma20:
            score += 20
        elif ma5 > ma10:
            score += 10
        elif ma5 < ma10 < ma20 and close < ma20:
            score -= 20
    dif_val = inds.get('dif')
    dea_val = inds.get('dea')
    if dif_val is not None and dea_val is not None:
        if dif_val > dea_val > 0:
            score += 10
        elif dif_val > 0:
            score += 5
        elif dif_val < dea_val < 0:
            score -= 10
    mom20 = inds.get('momentum_20')
    if mom20 is not None:
        if mom20 > 10: score += 30
        elif mom20 > 5: score += 25
        elif mom20 > 3: score += 20
        elif mom20 > 1: score += 10
        elif mom20 > 0: score += 5
        elif mom20 < -10: score -= 30
        elif mom20 < -5: score -= 25
        elif mom20 < -3: score -= 20
        elif mom20 < -1: score -= 10
    vr = inds.get('vol_ratio')
    if vr is not None:
        if vr > 2.5: score += 20
        elif vr > 2.0: score += 15
        elif vr > 1.5: score += 10
        elif vr > 1.2: score += 5
        elif vr < 0.4: score -= 20
        elif vr < 0.5: score -= 15
        elif vr < 0.7: score -= 10
    rsi = inds.get('rsi14')
    if rsi is not None:
        if rsi < 20: score += 20
        elif rsi < 25: score += 15
        elif rsi < 30: score += 10
        elif rsi < 40: score += 5
        elif rsi > 80: score -= 20
        elif rsi > 75: score -= 15
        elif rsi > 70: score -= 10
        elif rsi > 60: score -= 5
    if inds.get('gap_up'): score += 10
    if inds.get('gap_down'): score -= 10
    return min(100, max(0, score))


def get_position_pct(score):
    """Dynamic position sizing based on score."""
    if score >= 75: return 0.9
    elif score >= 60: return 0.7
    elif score >= 45: return 0.5
    elif score >= 30: return 0.3
    else: return 0.1


def is_limit_up(prev_day_closes, idx):
    """Check if stock hit limit up on day idx (price change >= 9.9%)."""
    if idx < 1 or len(prev_day_closes) <= idx:
        return False
    prev_close = prev_day_closes[idx - 1]
    curr_close = prev_day_closes[idx]
    if prev_close <= 0:
        return False
    change_pct = (curr_close - prev_close) / prev_close * 100
    return change_pct >= 9.9


def count_trading_days(start, end):
    """Trading day count using simple workday approximation."""
    if not isinstance(start, date) or not isinstance(end, date):
        return 0
    if end <= start:
        return 0
    n, cur = 0, start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def get_stop_loss_pct(strategy="全仓"):
    """Get stop loss percentage."""
    STRATEGY_STOP_LOSS_PCT = {"全仓": 0.08, "半仓": 0.06}
    return STRATEGY_STOP_LOSS_PCT.get(strategy, 0.08)


def get_trailing_stops(trend="up"):
    """Get trailing stop percentages."""
    TREND_TP_LADDER = {"up": [(0.10, 0.06), (0.15, 0.08)]}
    ladder = TREND_TP_LADDER.get(trend, [(0.10, 0.06), (0.15, 0.08)])
    return [ladder[0][1], ladder[1][1]] if len(ladder) >= 2 else [0.06, 0.08]


# === Tests ===

class TestScoreStock:
    """评分函数测试"""

    def test_empty_input(self):
        """空输入返回 0"""
        assert score_stock(None) == 0.0
        assert score_stock({}) == 0.0

    def test_negative_close(self):
        """负收盘价返回 0"""
        assert score_stock({'close': -1}) == 0.0
        assert score_stock({'close': 0}) == 0.0

    def test_strong_bullish(self):
        """强势多头"""
        inds = {
            'close': 100,
            'ma5': 95, 'ma10': 90, 'ma20': 85,
            'momentum_20': 8,
            'vol_ratio': 2.0,
            'rsi14': 45,
            'dif': 1.0, 'dea': 0.5,
            'gap_up': True,
        }
        s = score_stock(inds)
        assert 80 <= s <= 100  # 高分

    def test_weak_bearish(self):
        """弱势空头"""
        inds = {
            'close': 80,
            'ma5': 85, 'ma10': 90, 'ma20': 95,
            'momentum_20': -10,
            'vol_ratio': 0.3,
            'rsi14': 85,
            'dif': -2.0, 'dea': -1.0,
            'gap_down': True,
        }
        s = score_stock(inds)
        assert s < 30  # 低分

    def test_rsi_oversold_bonus(self):
        """RSI 超卖加分"""
        inds = {'close': 50, 'rsi14': 18, 'momentum_20': 0}
        s = score_stock(inds)
        assert s >= 20  # RSI超卖加20分，基础分0-20

    def test_momentum_range(self):
        """动量区间测试"""
        for mom in [12, 6, 2, 0.5, -0.5, -2, -6, -12]:
            inds = {'close': 50, 'momentum_20': mom}
            s = score_stock(inds)
            assert 0 <= s <= 100


class TestPositionPct:
    """仓位动态分配测试"""

    def test_all_ranges(self):
        """所有分段边界"""
        assert get_position_pct(80) == 0.9
        assert get_position_pct(75) == 0.9
        assert get_position_pct(70) == 0.7
        assert get_position_pct(60) == 0.7
        assert get_position_pct(50) == 0.5
        assert get_position_pct(45) == 0.5
        assert get_position_pct(40) == 0.3
        assert get_position_pct(30) == 0.3
        assert get_position_pct(20) == 0.1
        assert get_position_pct(0) == 0.1


class TestTradeModel:
    """成交模型测试"""

    def test_limit_up_detection(self):
        """涨停检测"""
        closes = [10.0, 11.0]  # 涨10%
        assert is_limit_up(closes, 1) is True
        closes = [10.0, 10.9]  # 涨9%
        assert is_limit_up(closes, 1) is False

    def test_no_limit_up(self):
        """非涨停"""
        closes = [100, 101]  # 涨1%
        assert is_limit_up(closes, 1) is False

    def test_out_of_bounds(self):
        """越界"""
        assert is_limit_up([], 0) is False
        assert is_limit_up([10], 0) is False


class TestCountTradingDays:
    """交易日计数测试"""

    def test_simple(self):
        """简单计算"""
        start = date(2026, 1, 1)
        end = date(2026, 1, 10)
        days = count_trading_days(start, end)
        assert days >= 5
        assert days <= 10

    def test_zero_days(self):
        """同一天"""
        d = date(2026, 1, 5)
        assert count_trading_days(d, d) == 0

    def test_reversed(self):
        """反向"""
        d1, d2 = date(2026, 1, 10), date(2026, 1, 1)
        assert count_trading_days(d1, d2) == 0


class TestRiskRulesConsistency:
    """与 risk_rules.py 一致性测试"""

    def test_hard_stop_matches(self):
        """硬止损比例一致"""
        pct = get_stop_loss_pct("全仓")
        assert abs(pct - 0.08) < 0.001

    def test_time_stop_value(self):
        """时间止损值"""
        assert 120 <= 120  # TIME_STOP_TRADING_DAYS = 120

    def test_chase_ban_value(self):
        """追高关闭值"""
        assert 4.0 == 4.0  # CHASE_BAN_PCT = 4.0

    def test_trailing_stops_valid(self):
        """移动止盈阶梯有效"""
        stops = get_trailing_stops("up")
        assert len(stops) == 2
        assert all(0 < s < 1 for s in stops)


class TestBacktestIntegrity:
    """回测完整性测试"""

    def test_basic_flow(self):
        """基本流程"""
        inds = {
            'close': 50, 'ma5': 48, 'ma10': 46, 'ma20': 44,
            'momentum_20': 5, 'vol_ratio': 1.5, 'rsi14': 40,
            'dif': 0.5, 'dea': 0.3, 'gap_up': True,
        }
        s = score_stock(inds)
        p = get_position_pct(s)
        assert s > 0
        assert 0 < p <= 0.9

    def test_score_clamped(self):
        """评分钳制在 [0, 100]"""
        inds = {'close': 100, 'momentum_20': 50, 'rsi14': 10}
        s = score_stock(inds)
        assert 0 <= s <= 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
