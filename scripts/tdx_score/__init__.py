"""
tdx_score 兼容层 — 所有符号保持向后兼容
2026-09-23 Phase C-2: 模块化拆分入口
"""
import sys
import os
# 导入所有公开API，外部调用零改动
from tdx_score.heat import get_industry_heat, _INDUSTRY_HEAT_CACHE, _INDUSTRY_HEAT_DATE, _INDUSTRY_HEAT_FILE
from tdx_score.ranker import compute_cross_section_ranks
from tdx_score.contribution import calc_feature_contributions
from tdx_score.market_state import (
    analyze_market,
    _get_position_limit,
    _get_stop_loss_pct,
    _get_target_pct,
)
from tdx_score.trailing import calc_trailing_stop, format_stop_advice, compute_swing_analysis
from tdx_score.utils import has_recent_gap

# 导入策略配置（tdx_core.py 依赖）
from tdx_strategies import STRATEGIES, STRATEGY_DEFAULT  # noqa: F401

# score_stock 从原模块直接导入（保持行为一致）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tdx_score_original import (  # noqa: F401
    score_stock,
    build_cross_rank,
    build_zscore,
    calc_relative_strength,
    get_fund_flow_bonus_for_stocks,
    get_fundamental_bonus_for_stocks,
    compute_cross_section_zscores,
)

__all__ = [
    'score_stock',
    'has_recent_gap',
    'compute_cross_section_ranks',
    'calc_feature_contributions',
    'get_industry_heat',
    'analyze_market',
    '_get_position_limit',
    '_get_stop_loss_pct',
    '_get_target_pct',
    'calc_trailing_stop',
    'format_stop_advice',
    'compute_swing_analysis',
]
