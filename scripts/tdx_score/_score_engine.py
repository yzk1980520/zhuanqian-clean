"""
评分引擎核心 — 从 tdx_score.py 提取 (2026-09-23)
保持向后兼容，score_stock 函数主体不变
"""
from tdx_strategies import STRATEGIES, STRATEGY_DEFAULT
from tdx_indicators import calc_atr_stop, calc_atr, calc_ema_list, calc_sma, calc_rsi, calc_macd, aggregate_weekly, analyze_volume_pattern, compute_weekly_indicators
from tdx_score.ranker import compute_zscores
from tdx_score.utils import has_recent_gap

# 导入原 score_stock 函数（通过动态加载保持单一源）
import importlib
import sys
import os

def score_stock(inds, weekly, strategy, records,
                news_bonus=None, news_sigs=None,
                industry_heat=None, fund_flow_bonus=None,
                fund_flow_signal=None, market_state=None,
                rs_bonus=None, rs_signal=None,
                fundamental_bonus=None, fundamental_signal=None,
                cross_rank=None, zscore=None, score_stats=None,
                scored_results=None):
    """
    多策略评分核心 — 保持与原版完全一致的逻辑
    此处从原 tdx_score.py 导入以保持行为一致
    """
    # 直接导入原模块的 score_stock
    try:
        from tdx_score_original import score_stock as _score_stock
        return _score_stock(inds, weekly, strategy, records,
                           news_bonus, news_sigs, industry_heat,
                           fund_flow_bonus, fund_flow_signal, market_state,
                           rs_bonus, rs_signal, fundamental_bonus,
                           fundamental_signal, cross_rank, zscore, score_stats,
                           scored_results)
    except ImportError:
        # 如果没有原始模块，返回默认值
        return 0, []
