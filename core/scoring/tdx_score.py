"""
tdx_score.py — 向后兼容入口（Phase 2: 2026-09-23）
原逻辑保留在 tdx_score_backup_20260923.py

所有符号通过 tdx_score/ 包重导出，外部调用零改动。
"""
import sys
import os

# 从新包导入所有符号
from tdx_score import (  # noqa: F401
    score_stock,
    compute_cross_section_ranks,
    get_industry_heat,
    analyze_market,
    calc_trailing_stop,
    format_stop_advice,
    compute_swing_analysis,
    calc_feature_contributions,
    has_recent_gap,
    build_cross_rank,
    build_zscore,
    compute_cross_section_zscores,
    calc_relative_strength,
    get_fund_flow_bonus_for_stocks,
    get_fundamental_bonus_for_stocks,
    STRATEGIES,
    STRATEGY_DEFAULT,
    _get_position_limit,
    _get_stop_loss_pct,
    _get_target_pct,
    _INDUSTRY_HEAT_CACHE,
    _INDUSTRY_HEAT_DATE,
    _INDUSTRY_HEAT_FILE,
)

__all__ = [
    'score_stock',
    'compute_cross_section_ranks',
    'get_industry_heat',
    'analyze_market',
    'calc_trailing_stop',
    'format_stop_advice',
    'compute_swing_analysis',
    'calc_feature_contributions',
    'has_recent_gap',
    'build_cross_rank',
    'build_zscore',
    'compute_cross_section_zscores',
    'calc_relative_strength',
    'get_fund_flow_bonus_for_stocks',
    'get_fundamental_bonus_for_stocks',
    'STRATEGIES',
    'STRATEGY_DEFAULT',
    '_get_position_limit',
    '_get_stop_loss_pct',
    '_get_target_pct',
    '_INDUSTRY_HEAT_CACHE',
    '_INDUSTRY_HEAT_DATE',
    '_INDUSTRY_HEAT_FILE',
]
