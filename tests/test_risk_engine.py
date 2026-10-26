# -*- coding: utf-8 -*-
"""test_risk_engine.py: RiskEngine单元测试"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from risk_rules_config import RiskConfig
from risk_rules_adapter import MockMarketState
from risk_rules_engine import RiskEngine, Position, ExitDecision


class TestRiskConfig:
    def test_default_config(self):
        config = RiskConfig.default()
        assert config.stop_loss_base == 0.10
        assert config.chase_ban_pct == 4.0
        assert config.time_stop_days == 120
        assert config.time_stop_warning_days == 5

    def test_custom_config(self):
        config = RiskConfig(stop_loss_base=0.08, time_stop_days=90)
        assert config.stop_loss_base == 0.08
        assert config.time_stop_days == 90

    def test_validate(self):
        config = RiskConfig()
        assert config.validate() is True

    def test_validate_invalid(self):
        with pytest.raises(ValueError):
            RiskConfig(stop_loss_base=0.6)


class TestPosition:
    def test_holding_days(self):
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        assert position.holding_days >= 0

    def test_is_time_stop_warning(self):
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date.today() - timedelta(days=115),
            quantity=100
        )
        assert position.is_time_stop_warning is True


class TestStopLoss:
    def test_basic_stop_loss(self):
        from risk_rules_adapter import MockMarketState
        config = RiskConfig(stop_loss_base=0.10)
        mock = MockMarketState(regime="强", confidence=0.85)
        engine = RiskEngine(config=config, market_state=mock)
        sl = engine.calculate_stop_loss(100.0, "全仓")
        assert sl == pytest.approx(89.0, abs=0.1)

    def test_panic_market_stop_loss(self):
        config = RiskConfig(stop_loss_base=0.10)
        mock = MockMarketState(regime="恐慌", confidence=0.5)
        engine = RiskEngine(config=config, market_state=mock)
        sl = engine.calculate_stop_loss(100.0, "全仓")
        assert sl == pytest.approx(94.5, abs=0.1)

    def test_oscillation_market_stop_loss(self):
        config = RiskConfig(stop_loss_base=0.10)
        mock = MockMarketState(regime="震荡", confidence=0.6)
        engine = RiskEngine(config=config, market_state=mock)
        sl = engine.calculate_stop_loss(100.0, "全仓")
        assert sl == pytest.approx(93.8, abs=0.1)

    def test_signal_bonus(self):
        config = RiskConfig(stop_loss_base=0.10)
        mock = MockMarketState(regime="强", confidence=0.85)
        engine = RiskEngine(config=config, market_state=mock)
        sl_no_signal = engine.calculate_stop_loss(100.0, "全仓", gap_score=0)
        sl_with_signal = engine.calculate_stop_loss(100.0, "全仓", gap_score=5)
        assert sl_with_signal <= sl_no_signal

    def test_atr_adjustment(self):
        config = RiskConfig(stop_loss_base=0.10)
        engine = RiskEngine(config=config)
        sl = engine.calculate_stop_loss(100.0, "全仓", atr=15.0)
        assert sl <= 85.0


class TestTakeProfit:
    def test_tp_levels_up_trend(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        tp_levels = engine.calculate_tp_levels(100.0, trend="up")
        assert len(tp_levels) == 5  # S3五档：(6,15%)(10,5%)(15,7%)(25,9%)(999,12%)
        assert tp_levels[0][0] > 100.0
        assert tp_levels[-1][0] > tp_levels[0][0]

    def test_tp_levels_sideways(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        tp_levels = engine.calculate_tp_levels(100.0, trend="sideways")
        assert len(tp_levels) == 5
        assert tp_levels[0][0] < 105.0


class TestEvaluateExit:
    def test_no_exit_in_range(self):
        config = RiskConfig(stop_loss_base=0.10, time_stop_days=120)
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        decision = engine.evaluate_exit(position, current_price=95.0)
        assert decision.should_exit is False
        assert decision.reason == "继续持仓"

    def test_stop_loss_trigger(self):
        config = RiskConfig(stop_loss_base=0.10)
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        decision = engine.evaluate_exit(position, current_price=89.0)
        assert decision.should_exit is True
        assert decision.is_stop_loss is True
        assert "硬止损" in decision.reason

    def test_custom_stop_loss_trigger(self):
        config = RiskConfig(stop_loss_base=0.10)
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100,
            sl=92.0
        )
        decision = engine.evaluate_exit(position, current_price=91.0)
        assert decision.should_exit is True
        assert decision.is_stop_loss is True

    def test_time_stop_trigger(self):
        config = RiskConfig(stop_loss_base=0.10, time_stop_days=120)
        engine = RiskEngine(config=config)
        entry_date = date.today() - timedelta(days=121)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=entry_date,
            quantity=100
        )
        decision = engine.evaluate_exit(position, current_price=105.0)
        assert decision.should_exit is True
        assert decision.is_time_stop is True
        assert "时间止损" in decision.reason

    def test_time_stop_warning(self):
        config = RiskConfig(stop_loss_base=0.10, time_stop_days=120, time_stop_warning_days=5)
        engine = RiskEngine(config=config)
        # 使用asof_date参数确保确定性
        asof_date = date.today()
        entry_date = asof_date - timedelta(days=116)  # 剩余4天
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=entry_date,
            quantity=100
        )
        decision = engine.evaluate_exit(position, current_price=105.0, asof_date=asof_date)
        assert decision.should_exit is False
        # 检查reason包含预警信息
        assert "预警" in decision.reason or "剩余" in decision.reason

    def test_tp1_trigger(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100,
            tp1=106.0
        )
        decision = engine.evaluate_exit(position, current_price=107.0)
        assert decision.should_exit is True
        assert decision.exit_type == "take_profit_half"
        assert "TP1" in decision.reason

    def test_tp2_trigger(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100,
            tp1=106.0,
            tp2=112.0
        )
        decision = engine.evaluate_exit(position, current_price=113.0)
        assert decision.should_exit is True
        assert decision.exit_type == "take_profit"
        assert "TP2" in decision.reason

    def test_partial_take_profit_trigger(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        decision = engine.evaluate_exit(position, current_price=115.1)
        assert decision.should_exit is True
        assert decision.is_partial_take_profit is True
        assert "+15.1%" in decision.reason

    def test_partial_take_profit_skip_exited(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100,
            exited_at_15=True
        )
        decision = engine.evaluate_exit(position, current_price=126.0)
        assert decision.should_exit is True
        assert decision.is_partial_take_profit is True
        assert "+26.0%" in decision.reason
        assert "15%" not in decision.reason

    def test_stop_loss_priority_over_tp(self):
        config = RiskConfig(stop_loss_base=0.10)
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100,
            tp1=106.0
        )
        decision = engine.evaluate_exit(position, current_price=89.0)
        assert decision.should_exit is True
        assert decision.is_stop_loss is True
        assert "止损" in decision.reason

    def test_market_panic_exit(self):
        config = RiskConfig()
        mock = MockMarketState(regime="恐慌", confidence=0.3)
        engine = RiskEngine(config=config, market_state=mock)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        decision = engine.evaluate_exit(position, current_price=105.0)
        assert decision.should_exit is True
        assert decision.is_market_exit is True
        assert "恐慌" in decision.reason

    def test_no_state_pollution(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)
        position = Position(
            stock_code="600519",
            entry_price=100.0,
            entry_date=date(2026, 10, 1),
            quantity=100
        )
        decision1 = engine.evaluate_exit(position, current_price=115.1)
        assert decision1.should_exit is True
        decision2 = engine.evaluate_exit(position, current_price=115.1)
        assert decision2.should_exit is True
        assert not getattr(position, 'exited_at_15', False)


class TestGenerateTradePlan:
    def test_basic_trade_plan(self):
        config = RiskConfig()
        mock = MockMarketState(regime="强", confidence=0.85)
        engine = RiskEngine(config=config, market_state=mock)

        class Signal:
            stock_code = "600519"
            strategy = "全仓"

        plan = engine.generate_trade_plan(Signal(), current_price=100.0)
        assert plan["stock_code"] == "600519"
        assert plan["entry_price"] == 100.0
        assert plan["stop_loss_price"] == 89.0
        assert plan["risk_reward_ratio"] > 0

    def test_trade_plan_with_atr(self):
        config = RiskConfig()
        engine = RiskEngine(config=config)

        class Signal:
            stock_code = "600519"
            strategy = "全仓"

        plan = engine.generate_trade_plan(Signal(), current_price=100.0, atr=15.0)
        assert plan["stop_loss_price"] <= 90.0


class TestMockMarketState:
    def test_mock_creation(self):
        mock = MockMarketState(regime="强", confidence=0.85)
        assert mock.get_regime() == "强"
        assert mock.get_confidence() == 0.85

    def test_mock_chain_call(self):
        mock = MockMarketState()
        mock.with_regime("震荡").with_confidence(0.6)
        assert mock.get_regime() == "震荡"
        assert mock.get_confidence() == 0.6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
