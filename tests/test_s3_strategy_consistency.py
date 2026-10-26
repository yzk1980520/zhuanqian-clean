#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_s3_strategy_consistency.py — S3策略路径一致性测试
老五评审 P1-1 要求: 补充测试覆盖
- TestTpLadderExecution: tp_ladder 触发卖出实际路径
- TestChaseBanBoundary: prev_close=0, tp_ladder=[] 边界条件
- TestPathConsistency: pipeline vs rotation 的 chase_ban_pct 拦截一致性
"""
import sys
import os
import unittest
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple

os.environ['NUMBA_DISABLE_JIT'] = '1'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/../')
from backtest.backtest_pipeline import BacktestEngine, BacktestConfig, DataLoader
from risk_rules import TREND_TP_LADDER, CHASE_BAN_PCT, TIME_STOP_TRADING_DAYS

# P3 2026-10-26 (t_81fad29b, pytest 门禁快档 §5.2): 整族 marker。
# 本文件=BacktestEngine 策略一致性族：全文件共用模块级 DataLoader（一次初始化
# ~60s, 成本随首个 get_loader() 调用者转移, 实测 46s）→ 门禁快档整族排除,
# 防成本转移；全量/夜间档照常跑，断言语义零改动。
import pytest

pytestmark = [pytest.mark.backtest]

# 模块级共享 DataLoader（初始化约60秒，只初始化一次）
_loader = None

def get_loader():
    global _loader
    if _loader is None:
        _loader = DataLoader()
    return _loader


def _make_stock_data(prices: List[float], dates: List[date]) -> List[Dict]:
    return [
        {"date": str(d), "open": float(p), "high": float(p), "low": float(p), "close": float(p), "volume": 100000}
        for d, p in zip(dates, prices)
    ]


def _make_config(**kwargs) -> BacktestConfig:
    defaults = dict(
        name="test",
        stop_loss=-0.10,
        time_stop_days=120,
        chase_ban_pct=4.0,
        tp_ladder=TREND_TP_LADDER['up'],
    )
    defaults.update(kwargs)
    return BacktestConfig(**defaults)  # type: ignore


class TestTpLadderExecution(unittest.TestCase):
    """测试 tp_ladder 触发卖出的实际路径"""

    def test_empty_ladder_no_sell(self):
        """tp_ladder=[] 时浮盈不触发卖出"""
        prices = [100.0] * 130
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(tp_ladder=[])
        engine = BacktestEngine(config, get_loader())
        position = ("sh600000", dates[60], 100.0, 1000.0)
        result = engine._check_exit(dates[65], 65, position, stocks_data, 100000.0)
        self.assertIsNone(result, "tp_ladder为空时应继续持有")

    def test_chase_ban_disabled_does_not_interfere(self):
        """chase_ban_pct=None 时不影响 tp_ladder 测试"""
        prices = [100.0] * 130
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(chase_ban_pct=None)
        engine = BacktestEngine(config, get_loader())
        position = ("sh600000", dates[60], 100.0, 1000.0)
        result = engine._check_exit(dates[65], 65, position, stocks_data, 100000.0)
        self.assertIsNone(result, "浮盈0%未达阈值应继续持有")


class TestChaseBanBoundary(unittest.TestCase):
    """测试 chase_ban_pct 边界条件"""

    def test_prev_close_zero_no_division_by_zero(self):
        """prev_close=0 时不触发除零错误"""
        prices = [0.0, 100.0] + [101.0] * 65
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(chase_ban_pct=4.0)
        engine = BacktestEngine(config, get_loader())
        try:
            engine._select_stock(dates[62], 62, stocks_data)
        except ZeroDivisionError:
            self.fail("_select_stock 不应触发除零错误")

    def test_chase_ban_blocks_5pct(self):
        """信号日涨幅5%应被拦截"""
        prices = [100.0] * 60 + [100.0, 105.0]
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(chase_ban_pct=4.0)
        engine = BacktestEngine(config, get_loader())
        result = engine._select_stock(dates[61], 61, stocks_data)
        self.assertIsNone(result, "信号日涨幅5%>4%应被拦截")

    def test_chase_ban_allows_2pct(self):
        """信号日涨幅2%应放行"""
        prices = [100.0] * 60 + [100.0, 102.0]
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(chase_ban_pct=4.0)
        engine = BacktestEngine(config, get_loader())
        result = engine._select_stock(dates[61], 61, stocks_data)
        self.assertIsNotNone(result, "信号日涨幅2%<4%不应被拦截")


class TestPathConsistency(unittest.TestCase):
    """测试 pipeline 和 rotation 的 chase_ban_pct 一致性"""

    def test_pipeline_blocks_5pct(self):
        """backtest_pipeline._select_stock 正确拦截5%涨幅"""
        prices = [100.0] * 60 + [100.0, 105.0]
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(chase_ban_pct=4.0)
        engine = BacktestEngine(config, get_loader())
        result = engine._select_stock(dates[61], 61, stocks_data)
        self.assertIsNone(result)

    def test_pipeline_allows_2pct(self):
        """backtest_pipeline._select_stock 正确放行2%涨幅"""
        prices = [100.0] * 60 + [100.0, 102.0]
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(chase_ban_pct=4.0)
        engine = BacktestEngine(config, get_loader())
        result = engine._select_stock(dates[61], 61, stocks_data)
        self.assertIsNotNone(result)

    def test_rotation_blocks_5pct(self):
        """backtest_rotation.signal_day_chg 正确识别5%涨幅"""
        from backtest.backtest_rotation import signal_day_chg
        prices = [100.0] * 60 + [100.0, 105.0]
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        records = _make_stock_data(prices, dates)
        # signal_day_chg 使用字符串日期索引
        chg = signal_day_chg(records, str(dates[61]))
        self.assertIsNotNone(chg)
        self.assertGreater(chg[1], 4.0)

    def test_rotation_allows_2pct(self):
        """backtest_rotation.signal_day_chg 正确放行2%涨幅"""
        from backtest.backtest_rotation import signal_day_chg
        prices = [100.0] * 60 + [100.0, 102.0]
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        records = _make_stock_data(prices, dates)
        chg = signal_day_chg(records, str(dates[61]))
        self.assertIsNotNone(chg)
        self.assertLessEqual(chg[1], 4.0)


class TestMarketRegime(unittest.TestCase):
    """测试市场状态风控系数"""

    def test_neutral_regime_no_adjustment(self):
        """neutral市场状态: 止损不调整"""
        prices = [100.0] * 130
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(stop_loss=-0.10, market_regime="neutral")
        engine = BacktestEngine(config, get_loader())
        # 跌幅10%不应触发止损(neutral无调整)
        position = ("sh600000", dates[60], 100.0, 1000.0)
        result = engine._check_exit(dates[65], 65, position, stocks_data, 100000.0)
        self.assertIsNone(result, "neutral市场下-10%浮亏不应触发止损")

    def test_bull_regime_looser_stop(self):
        """bull市场状态: 止损放宽10%(-11%)"""
        prices = [100.0] + [99.0] * 129
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(stop_loss=-0.10, market_regime="bull")
        engine = BacktestEngine(config, get_loader())
        # 跌幅10%在bull市场(止损放宽到11%)不应触发
        position = ("sh600000", dates[60], 100.0, 1000.0)
        result = engine._check_exit(dates[65], 65, position, stocks_data, 100000.0)
        self.assertIsNone(result, "bull市场下-10%浮亏不应触发(止损放宽至11%)")

    def test_panic_regime_tighter_stop(self):
        """panic市场状态: 止损收紧45%(-5.5%)"""
        prices = [100.0] + [94.0] * 129
        dates = [date(2021, 1, 4) + timedelta(days=i) for i in range(len(prices))]
        stocks_data = {"sh600000": _make_stock_data(prices, dates)}
        config = _make_config(stop_loss=-0.10, market_regime="panic")
        engine = BacktestEngine(config, get_loader())
        # 跌幅6%在panic市场(止损收紧至5.5%)应触发
        position = ("sh600000", dates[60], 100.0, 1000.0)
        result = engine._check_exit(dates[65], 65, position, stocks_data, 100000.0)
        self.assertIsNotNone(result, "panic市场下-6%浮亏应触发(止损收紧至5.5%)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
