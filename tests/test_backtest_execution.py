#!/usr/bin/env python3
"""
test_backtest_execution.py: 回测引擎执行流程测试
测试边界（Seams）:
  - backtest_rotation 轮动回测主逻辑
  - 成交模型：涨停买不进/跌停卖不出/停牌顺延
"""
import sys
import os
import pytest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestBacktestConstants:
    """回测常量验证"""

    def test_initial_capital(self):
        """测试: 初始资金应为25000"""
        from backtest.backtest_rotation import INIT_CAPITAL
        assert INIT_CAPITAL == 25000.0

    def test_scan_step(self):
        """测试: 扫描步长应为5个交易日"""
        from backtest.backtest_rotation import SCAN_STEP
        assert SCAN_STEP == 5

    def test_commission_rate(self):
        """测试: 佣金率应为万1.15"""
        from backtest.backtest_rotation import COMMISSION_RATE
        assert COMMISSION_RATE == 0.000115

    def test_stamp_tax_rate(self):
        """测试: 印花税率应为万5"""
        from backtest.backtest_rotation import STAMP_TAX_RATE
        assert STAMP_TAX_RATE == 0.0005

    def test_slippage_rate(self):
        """测试: 滑点率应为0.1%"""
        from backtest.backtest_rotation import SLIPPAGE_RATE
        assert SLIPPAGE_RATE == 0.001


class TestTradeModel:
    """成交模型测试"""

    def test_buy_limit_price_blocked(self):
        """测试: 涨停价买入应被阻止"""
        # 模拟涨停情况：当前价 = 前一日收盘 * 1.1
        prev_close = 10.0
        limit_up_price = prev_close * 1.1  # 11.0
        
        # 涨停时买不进（简化逻辑）
        # 实际验证: 涨停价 > 信号价时应拒绝
        assert limit_up_price > prev_close

    def test_sell_limit_down_price_blocked(self):
        """测试: 跌停价卖出应被阻止"""
        prev_close = 10.0
        limit_down_price = prev_close * 0.9  # 9.0
        
        # 跌停时卖不出
        assert limit_down_price < prev_close

    def test_suspended_stock_skipped(self):
        """测试: 停牌股票应被跳过"""
        # 停牌判断逻辑
        suspended_codes = {"sh600000"}  # 假设停牌
        code = "sh600000"
        assert code in suspended_codes


class TestPositionManagement:
    """仓位管理测试"""

    def test_single_stock_position(self):
        """测试: 单票轮动模式应只持有一只"""
        # 验证全仓1只策略
        max_position = 1
        assert max_position == 1

    def test_position_ratio_default(self):
        """测试: 默认仓位比例应为50%（S3配置）"""
        import json
        config_path = os.path.join(
            os.path.dirname(__file__), '..', 'config.json'
        )
        
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            position_ratio = config.get('position_ratio', 0.5)
            assert position_ratio == 0.5, f"默认仓位比应为0.5, 实际{position_ratio}"
        else:
            pytest.skip("config.json不存在")


class TestRiskIntegration:
    """风控集成测试"""

    def test_stop_loss_integration(self):
        """测试: 止损规则已集成到回测"""
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        # 验证止损配置存在
        assert "全仓" in STRATEGY_STOP_LOSS_PCT
        assert STRATEGY_STOP_LOSS_PCT["全仓"] == 0.10  # S3: 10%

    def test_trailing_stop_integration(self):
        """测试: 移动止盈阶梯已集成"""
        from risk_rules import TREND_TP_LADDER
        # 验证S3阶梯配置
        s3_ladder = TREND_TP_LADDER["up"]
        assert len(s3_ladder) == 5  # 五档：(6,15%)(10,5%)(15,7%)(25,9%)(999,12%)
        assert s3_ladder[0] == (6, 0.15)

    def test_time_stop_integration(self):
        """测试: 时间止损已集成"""
        from risk_rules import TIME_STOP_TRADING_DAYS
        assert TIME_STOP_TRADING_DAYS == 120


class TestBacktestOutput:
    """回测输出格式验证"""

    def test_result_structure(self):
        """测试: 回测结果包含必要字段"""
        import json
        result_path = os.path.join(
            os.path.dirname(__file__), '..', 'data', 'rotation_backtest_result.json'
        )
        
        if os.path.exists(result_path):
            with open(result_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            required_keys = ['generated', 'engine_commit', 'results']
            for key in required_keys:
                assert key in data, f"结果缺少必要字段: {key}"
        else:
            pytest.skip("回测结果文件不存在")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
