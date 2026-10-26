# -*- coding: utf-8 -*-
"""RiskEngine - 风控引擎（深度模块）"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Tuple

from core.risk.risk_rules_config import RiskConfig
from core.risk.risk_rules_adapter import MarketStateAdapter

# P1双源收敛(2026-10-09): 删除本地阶梯副本 dict, 改延迟 import 消费 risk_rules 单一真源
# 权威 risk_rules.TREND_TP_LADDER 为 5 键全档(up/down/sideways/swing/up_contract), 与旧副本逐档一致, 归一零行为风险
# ⚠️ 不能写模块级 `from risk_rules import TREND_TP_LADDER`: risk_rules.py:39 反向 import 本模块 RiskEngine,
#    模块级互 import 会造成循环依赖; 阶梯在 calculate_tp_levels 函数体延迟 import(运行时取, 打破循环)

MARKET_STOP_ADJUST = {
    "恐慌": 0.55, "弱": 0.85, "震荡": 0.62,
    "偏暖": 1.0, "强": 1.1, "极强": 0.9,
}

SIGNAL_BONUS_ADJUST = {
    0: 1.0, 1: 1.0, 2: 1.05, 3: 1.10, 4: 1.15, 5: 1.20,
}


@dataclass
class Position:
    stock_code: str
    entry_price: float
    entry_date: date
    quantity: int
    strategy: str = "全仓"
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    entry_score: Optional[float] = None
    peak_pnl: Optional[float] = None
    high_series: Optional[List[float]] = None
    exited_at_15: bool = False
    exited_at_25: bool = False

    @property
    def holding_days(self) -> int:
        return (date.today() - self.entry_date).days

    @property
    def is_time_stop_warning(self) -> bool:
        return self.holding_days >= 115


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str
    exit_price: Optional[float] = None
    exit_type: Optional[str] = None

    @property
    def is_stop_loss(self) -> bool:
        return self.exit_type == "stop_loss"

    @property
    def is_time_stop(self) -> bool:
        return self.exit_type == "time_stop"

    @property
    def is_tp_trigger(self) -> bool:
        return self.exit_type in ("tp_ladder", "take_profit", "take_profit_half")

    @property
    def is_partial_take_profit(self) -> bool:
        return self.exit_type == "partial_take_profit"

    @property
    def is_market_exit(self) -> bool:
        return self.exit_type in ("market_exit", "market_deteriorate")


class RiskEngine:
    # DEPRECATED (2026-10-11): 已被 S3 五档移动止盈阶梯替代
    # 保留以维持向后兼容，新代码应使用 TREND_TP_LADDER['up']
    PARTIAL_EXIT_RULES = [(15, 0.30), (25, 0.30)]

    def __init__(self, config: RiskConfig = None, market_state: MarketStateAdapter = None):
        self.config = config or RiskConfig.default()
        self.market_state = market_state

    def evaluate_exit(self, position: Position, current_price: float,
                      market_label: str = "强", asof_date: date = None) -> ExitDecision:
        asof = asof_date or date.today()
        
        # 1. 时间止损检查
        time_dec = self._check_time_stop(position, asof)
        if time_dec.should_exit or time_dec.exit_type == "time_warning":
            return time_dec
        
        # 2. 硬止损检查
        sl_dec = self._check_stop_loss(position, current_price)
        if sl_dec.should_exit:
            return sl_dec
        
        # 3. 传统止盈检查
        tp_dec = self._check_traditional_tp(position, current_price)
        if tp_dec.should_exit:
            return tp_dec
        
        # 4. 分批止盈检查
        partial_dec = self._check_partial_take_profit(position, current_price)
        if partial_dec.should_exit:
            return partial_dec
        
        # 5. 市场状态恶化检查
        if self.market_state:
            market_dec = self._check_market_deterioration(position, current_price)
            if market_dec.should_exit:
                return market_dec
        
        # 6. 继续持仓
        return ExitDecision(should_exit=False, reason="继续持仓", exit_price=None, exit_type=None)

    def calculate_stop_loss(self, entry_price: float, strategy: str = "全仓",
                           gap_score: int = 0, nb_score: int = 0,
                           atr: Optional[float] = None) -> float:
        base_pct = self.config.stop_loss_base
        market_adj = 1.0
        if self.market_state:
            regime = self.market_state.get_regime()
            market_adj = MARKET_STOP_ADJUST.get(regime, 1.0)
        signal_strength = 0
        if gap_score > 15: signal_strength += 3
        elif gap_score > 8: signal_strength += 2
        elif gap_score > 0: signal_strength += 1
        if nb_score > 15: signal_strength += 3
        elif nb_score > 8: signal_strength += 2
        elif nb_score > 0: signal_strength += 1
        signal_adj = SIGNAL_BONUS_ADJUST.get(signal_strength, 1.0)
        final_pct = base_pct * market_adj * signal_adj
        if atr and atr > 0 and entry_price > 0:
            atr_pct = atr / entry_price
            if atr_pct > final_pct:
                final_pct = max(atr_pct * 1.5, final_pct * 0.8)
        final_pct = max(0.03, min(final_pct, 0.15))
        return round(entry_price * (1 - final_pct), 2)

    def calculate_tp_levels(self, entry_price: float, trend: str = "up") -> List[Tuple[float, float]]:
        # 延迟 import 打破 risk_rules↔engine 模块级循环; 消费单一真源
        import risk_rules
        ladder = risk_rules.TREND_TP_LADDER.get(trend, risk_rules.TREND_TP_LADDER["up"])
        return [(entry_price * (1 + t / 100), tr / 100) for t, tr in ladder]

    def check_time_stop_warning(self, position: Position) -> bool:
        return position.is_time_stop_warning

    def generate_trade_plan(self, signal, current_price: float,
                           market_label: str = "强", atr: Optional[float] = None) -> dict:
        sl_price = self.calculate_stop_loss(current_price, signal.strategy, atr=atr)
        tp_levels = self.calculate_tp_levels(current_price)
        rrr = self._calc_rr(sl_price, current_price, tp_levels[-1][0])
        return {
            "stock_code": signal.stock_code,
            "entry_price": current_price,
            "stop_loss_price": sl_price,
            "tp_levels": tp_levels,
            "risk_reward_ratio": rrr,
            "max_loss_pct": self.config.stop_loss_base,
            "market_label": market_label,
        }

    def _check_time_stop(self, position: Position, asof_date: date) -> ExitDecision:
        days = (asof_date - position.entry_date).days
        if days >= self.config.time_stop_days:
            return ExitDecision(True, f"时间止损触发: 已持有{days}日", None, "time_stop")
        remaining = self.config.time_stop_days - days
        if 0 < remaining <= self.config.time_stop_warning_days:
            return ExitDecision(False, f"时间预警: 剩余{remaining}日", None, "time_warning")
        return ExitDecision(False, "", None, None)

    def _check_stop_loss(self, position: Position, price: float) -> ExitDecision:
        pnl = (price - position.entry_price) / position.entry_price
        if pnl <= -self.config.stop_loss_base:
            return ExitDecision(True, f"硬止损触发: 亏损{pnl:.2%}", price, "stop_loss")
        if position.sl > 0 and price <= position.sl:
            return ExitDecision(True, f"止损触发: 跌破{position.sl:.2f}", price, "stop_loss")
        return ExitDecision(False, "", None, None)

    def _check_traditional_tp(self, position: Position, price: float) -> ExitDecision:
        pnl = (price - position.entry_price) / position.entry_price
        if position.tp2 > 0 and price >= position.tp2:
            return ExitDecision(True, f"止盈TP2: +{pnl:.1%},清仓", price, "take_profit")
        if position.tp1 > 0 and price >= position.tp1:
            return ExitDecision(True, f"止盈TP1: +{pnl:.1%},减半仓", price, "take_profit_half")
        return ExitDecision(False, "", None, None)

    def _check_partial_take_profit(self, position: Position, price: float) -> ExitDecision:
        pnl = (price - position.entry_price) / position.entry_price
        for threshold, pct in self.PARTIAL_EXIT_RULES:
            key = f"exited_at_{threshold}"
            if getattr(position, key, False):
                continue
            if pnl > threshold / 100:
                return ExitDecision(True, f"分批止盈: +{pnl:.1%}, 卖出{pct*100:.0f}%", price, "partial_take_profit")
        return ExitDecision(False, "", None, None)

    def _check_market_deterioration(self, position: Position, price: float) -> ExitDecision:
        if not self.market_state:
            return ExitDecision(False, "", None, None)
        regime = self.market_state.get_regime()
        conf = self.market_state.get_confidence()
        if regime == "恐慌":
            return ExitDecision(True, "市场恐慌,无条件减仓", price, "market_exit")
        if conf < 0.3:
            return ExitDecision(True, f"市场恶化: 置信度{conf:.2%}<30%", price, "market_deteriorate")
        return ExitDecision(False, "", None, None)

    def _calc_rr(self, entry: float, sl: float, tp: float) -> float:
        risk = entry - sl
        reward = tp - entry
        return reward / risk if risk > 0 else float("inf")
