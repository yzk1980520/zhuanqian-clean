# -*- coding: utf-8 -*-
"""TDX日线数据读取模块 - scripts兼容版

从根目录的 tdx_data/tdx_indicators/tdx_score 重新导出所有符号
避免与根目录 tdx_core.py 的循环导入
"""
import sys
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# P0修复(20261023): 基地化S4迁入core/pipeline/后单层dirname误指core/pipeline/, 改用L10 PROJECT_ROOT
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 直接从子模块导入，避免通过 tdx_core 导入
from tdx_data import (
    ALLOWED_PREFIXES_SH,
    ALLOWED_PREFIXES_SZ,
    BROAD_INDUSTRY,
    INDUSTRY_FILE,
    NAME_CACHE_FILE,
    SW_INDUSTRY_MAP_FILE,
    VIPDOC,
    batch_fetch_names,
    fetch_realtime_prices,
    get_industry,
    get_latest_tdx_date,
    get_tdx_data,
    is_st_stock,
    load_industry_map,
    load_name_cache,
    parse_tdx_day,
    save_name_cache,
    should_include,
)

from core.scoring.tdx_indicators import (
    aggregate_weekly,
    calc_atr,
    calc_atr_stop,
    calc_ema_list,
    calc_macd,
    calc_rsi,
    calc_sma,
    compute_indicators,
    compute_weekly_indicators,
    analyze_volume_pattern,
)

from tdx_score import (
    STRATEGIES,
    STRATEGY_DEFAULT,
    _INDUSTRY_HEAT_CACHE,
    _INDUSTRY_HEAT_DATE,
    _INDUSTRY_HEAT_FILE,
    _get_position_limit,
    _get_stop_loss_pct,
    _get_target_pct,
    analyze_market,
    build_cross_rank,
    build_zscore,
    calc_feature_contributions,
    calc_relative_strength,
    compute_cross_section_ranks,
    compute_cross_section_zscores,
    format_stop_advice,
    get_fund_flow_bonus_for_stocks,
    get_fundamental_bonus_for_stocks,
    has_recent_gap,
    score_stock,
)

# 从 trailing 模块导入
from tdx_score.trailing import (
    calc_trailing_stop,
    compute_swing_analysis,
)

# 从 helpers 导入行业热度
from integrated_picker.helpers import get_industry_heat_bonus

# 从 tdx_score.heat 导入 get_industry_heat
from tdx_score.heat import get_industry_heat

from core.scoring.tdx_strategies import (
    load_strategy,
)


# ============================================================================
# 自定义函数（从 tdx_core.py 复制）
# ============================================================================
def get_last_bar_gap_pct(records):
    """最后一根K线跳空百分比 (黑天鹅/高开识别) — 2026-09-09 Bug B 补齐

    契约 (tests/test_sequence_risk.py::TestTdxGapHelper):
      - records: K线list, 每项含 open/close 键 (TDX bars)
      - 返回 (今开/昨收 - 1) * 100 (百分比, 保留正负号)
      - 安全降级: records<2 / 昨收==0 / 今开==0 → 返回 None
    """
    if not records or len(records) < 2:
        return None
    prev_close = records[-2].get("close", 0)
    today_open = records[-1].get("open", 0)
    if not prev_close or not today_open:
        return None
    return round((today_open / prev_close - 1.0) * 100.0, 6)


# 导出 __all__
__all__ = [
    'ALLOWED_PREFIXES_SH', 'ALLOWED_PREFIXES_SZ',
    'BROAD_INDUSTRY', 'INDUSTRY_FILE', 'NAME_CACHE_FILE',
    'SW_INDUSTRY_MAP_FILE', 'VIPDOC',
    '_INDUSTRY_HEAT_CACHE', '_INDUSTRY_HEAT_DATE', '_INDUSTRY_HEAT_FILE',
    '_get_position_limit', '_get_stop_loss_pct', '_get_target_pct',
    'batch_fetch_names', 'fetch_realtime_prices',
    'get_industry', 'get_latest_tdx_date',
    'get_tdx_data', 'is_st_stock',
    'load_industry_map', 'load_name_cache', 'parse_tdx_day', 'save_name_cache',
    'should_include',
    'aggregate_weekly', 'calc_atr', 'calc_atr_stop', 'calc_ema_list',
    'calc_macd', 'calc_rsi', 'calc_sma',
    'compute_indicators', 'compute_weekly_indicators',
    'analyze_volume_pattern',
    'STRATEGIES', 'STRATEGY_DEFAULT',
    'analyze_market', 'build_cross_rank', 'build_zscore',
    'calc_feature_contributions', 'calc_relative_strength',
    'calc_trailing_stop', 'compute_swing_analysis',
    'compute_cross_section_ranks', 'compute_cross_section_zscores',
    'compute_swing_analysis', 'format_stop_advice',
    'get_fund_flow_bonus_for_stocks', 'get_fundamental_bonus_for_stocks',
    'get_industry_heat', 'get_industry_heat_bonus', 'has_recent_gap', 'score_stock',
    'load_strategy',
    'get_last_bar_gap_pct',
]
