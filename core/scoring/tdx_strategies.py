"""TDX 策略配置模块 — Phase C-1 拆分自 tdx_core.py (2026-08-31)

职责:
- STRATEGY_DEFAULT 默认策略名
- STRATEGIES dict — 20 个策略的权重与阈值配置
- load_strategy — 按 config.json 合并用户自定义权重

兼容性: tdx_core.py 仍作为兼容入口 re-export 本模块所有符号。
"""

import os
import struct
import urllib.request
import json
import sys
from datetime import date


STRATEGY_DEFAULT = "低波动异象"  # P0修复(2026-09-18): 切换为最优策略(胜率36.2%,超额-0.29%)


STRATEGIES = {
    # 2026-09-05: 删除momentum_core（验证失败：胜率21.5% vs 37.2%）
    # 保留P0修复：alpha13/alpha16_fix权重=0，chg10已接入综合策略
    "综合": {
        # 均衡策略 — 所有因子适度加权
        # P0-2026-08-23 老大拍板: 降追高增基本面
        # P2评分重构(2026-08-24): 进一步降权无效因子, 强化有效因子
        #   chg5 GT8: 2→0 (IC=+0.031无预测力, 纯噪音)
        #   chg5 GT3: 1→0 (同上)
        #   max_ret5_low: 10→20 (IC=-0.173强负向, 应更重)
        # P3优化(2026-08-24): 增加均线/MACD权重, 拉大score_spread
        "ma_mlt": 20, "ma_above60": 8, "ma_above120": 5,
        "macd_golden_red": 15, "macd_golden": 10, "macd_above0": 6,
        "rsi_strong": 2, "rsi_weak": 1, "rsi_rising": 1,
        "kdj_golden": 5, "kdj_overbought": -8,
        "vol_gt2": 10, "vol_gt1.5": 6, "vol_gt1.2": 3,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # P2: chg5无预测力全部归零
        "chg5": 0,            # P0-2026-09-13: 删除直接权重（z-score路径已覆盖，防双重计分）
        "max_ret5_low": 25,   # P3: 彩票型回避
        "vol_breakout": -5, "vol_shrink": 4, "vol_dump": -12,
        "vol_shrink20_bonus": 0,
        "vol_floor": -5,  # Phase C-2: 低波动筛选辅助(负权重=偏好低vol_floor)
        "chg5_rev": 30, "chg10_rev": 12, "chg20_rev": 10,  # Phase2-2026-09-25: 反转因子权重调整（IC=0.3053最强）
        "volatility20": 15,  # P1-2026-09-04: 反转权重(-25→+15), 奖励高波动突破票(真突破vol=57% vs 横盘16%)
        "lhb_signal": 8,    # P0-2026-09-05: 龙虎榜因子IC=0.0991全场最强，提升至权重8（Level 2/1专用）
        "rsi_oversold": 8,   # RSI超卖反弹
        # P2-2 Phase1子任务4后续 Alpha101策略族 (2026-08-31):
        # 门禁结果: alpha13 IC=+0.0341 IR=0.38 ✅, alpha15≈0(噪声,移除), vol_price_corr_20 IC=-0.0566 IR=0.51 ✅(替代alpha15)
        # 剔除 rms (IR=0.24<0.3, 方向率47%<55%), 剔除 alpha34/rsv5d (IC<0.02 无信号)
        # Phase2-2026-09-25: alpha13 IC=0.0083弱信号禁用, alpha16_fix IC=0.1038通过门禁启用
        "alpha13": 0,
        "vol_price_corr_20": -10, "alpha16": -3,  # P0-2026-09-20: vol_price_corr_20 -8→-10 (IC=-0.066稳定)
        # KIMI审查-20 (2026-09-05): 因子体系重建
        "alpha16_fix": 25,  # Phase2-2026-09-25: IC5=0.1038通过门禁，启用
        "amount_q_reversal": 0,   # 2026年IC=+0.003，冻结（原权重10）
        # chg10动量因子接入（KIMI审查-20新增，IC=+0.244全场最强）
        # 2026-09-07 方案1：提升chg10权重12→20→25，强化动量驱动
        # 2026-09-08 P0修复：alpha13/alpha16_fix死亡，amount_q_reversal接入
        "chg10": 0,               # P0-2026-09-13: 删除直接权重（z-score路径已覆盖，防双重计分）
        "amount_q_reversal": -8,  # P0修复: 成交额分位数切割反转（2026年IC=-0.069稳定负向）
        # P0-2026-09-20 牛马P0因子权重（market_adaptation_report.md Phase2）:
        # pos_vs_ma20: IC5=-0.2263最强负向，均线偏离回归，权重-15
        # unlocked_pressure: IC5=-0.1696强负向，解套盘压力，权重-12
        # vol_ratio: IC5=+0.1045最强正向，量能因子，权重+10
        # std20: IC10=-0.3349极强负向，波动率收敛，权重-8
        # rsi14: IC5=-0.1630稳定负向，RSI反转，权重-8（z-score路径已覆盖，此处为备用）
        "pos_vs_ma20": -15,       # P0新增: 距MA20距离%，强负向IC=-0.2263
        "unlocked_pressure": -12, # P0新增: 解套盘压力%，强负向IC=-0.1696
        "vol_ratio": 10,          # P0新增: 量比，强正向IC=+0.1045
        "std20": -8,              # P0新增: 20日波动率，强负向IC=-0.3349
        "rsi14_direct": -8,       # P0新增: RSI直接权重（z-score路径为主）
        "weekly_bullish": 8, "weekly_macd_red": 5,
        "industry_hot_top5": 15, "industry_cold_bottom5": -12,
        "fund_flow_pos": 8, "fund_flow_neg": -8,
        "penalty_far": -12, "penalty_chase_high": -5,
        "penalty_kdj_ob": -6, "penalty_vol_dump": -5,
        "pattern_bonus": 8,
        # P1-2026-09-11: 基本面加分项（非硬门槛，仅提升区分度）
        "fund_min_roe": 0.05,           # ROE≥5%时+5分
        "fund_min_profit_growth": 0.0,   # 利润增长≥0%时+3分
        "fund_min_net_margin": 0.0,      # 净利率≥0%时+2分
        "fund_min_cashflow": 0.0,        # 现金流为正时+2分
    },
    "趋势": {
        # 趋势跟踪 — 均线+MACD+周线占比60%以上
        # 2026-09-18 主板单票策略优化: 提升趋势权重，强化基本面硬门槛
        "ma_mlt": 28, "ma_above60": 12, "ma_above120": 10,
        "macd_golden_red": 18, "macd_golden": 12, "macd_above0": 8,
        "rsi_strong": 8, "rsi_weak": 2, "rsi_rising": 3,
        "kdj_golden": 5, "kdj_overbought": -5,
        "vol_gt2": 8, "vol_gt1.5": 5, "vol_gt1.2": 3,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # P0: chg5 2026年IC=-0.01，冻结
        "chg5": 0,            # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "chg10": 0,           # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "amount_q_reversal": -8,  # P0修复: 成交额分位数切割反转（2026年IC=-0.069稳定负向）
        "vol_breakout": 5, "vol_shrink": 3, "vol_dump": -5,
        "vol_shrink20_bonus": 0,   # T-2026-08-20 缩量企稳因子
        "weekly_bullish": 15, "weekly_macd_red": 10,
        "industry_hot_top5": 5, "industry_cold_bottom5": -5,
        "fund_flow_pos": 8, "fund_flow_neg": -8,
        "penalty_far": -10, "penalty_chase_high": -12,
        "penalty_kdj_ob": -5, "penalty_vol_dump": -5,
        "pattern_bonus": 8,
        # 基本面硬门槛参数（2026-09-18 主板单票策略）
        "fund_min_roe": 0.10,           # ROE≥10%
        "fund_min_profit_growth": 0.05,  # 利润增长≥5%
        "fund_min_net_margin": 0.05,     # 净利率≥5%
        "fund_max_debt_ratio": 0.55,     # 负债率≤55%
        "fund_min_cashflow": 0.5,        # 现金流≥0.5
    },
    "突破": {
        # 爆发捕捉 — 成交量+形态+量价形态占比60%
        "ma_mlt": 8, "ma_above60": 3, "ma_above120": 2,
        "macd_golden_red": 12, "macd_golden": 8, "macd_above0": 5,
        "rsi_strong": 5, "rsi_weak": 3, "rsi_rising": 3,
        "kdj_golden": 5, "kdj_overbought": -3,
        "vol_gt2": 18, "vol_gt1.5": 12, "vol_gt1.2": 5,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # P0: chg5 2026年IC=-0.01，冻结
        "chg5": 0,            # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "chg10": 0,           # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "amount_q_reversal": -8,  # P0修复: 成交额分位数切割反转（2026年IC=-0.069稳定负向）
        "vol_breakout": 12, "vol_shrink": 2, "vol_dump": -12,
        "vol_shrink20_bonus": 0,   # T-2026-08-20 缩量企稳因子
        "weekly_bullish": 2, "weekly_macd_red": 2,
        "industry_hot_top5": 8, "industry_cold_bottom5": -5,
        "fund_flow_pos": 8, "fund_flow_neg": -8,
        "penalty_far": -5, "penalty_chase_high": -8,
        "penalty_kdj_ob": -3, "penalty_vol_dump": -8,
        "pattern_bonus": 10,
    },
    "抄底": {
        # 超跌反弹 — RSI+远离均线+缩量占比60%
        "ma_mlt": 5, "ma_above60": 2, "ma_above120": 2,
        "macd_golden_red": 8, "macd_golden": 5, "macd_above0": 2,
        "rsi_strong": 3, "rsi_weak": 18, "rsi_rising": 12,
        "kdj_golden": 8, "kdj_overbought": -8,
        "vol_gt2": 2, "vol_gt1.5": 2, "vol_gt1.2": 2,
        "chg5_gt8": 2, "chg5_gt3": 3, "chg5_accel": 2,
        "vol_breakout": 2, "vol_shrink": 10, "vol_dump": -2,
        "vol_shrink20_bonus": 5,   # T-2026-08-20 缩量企稳因子(抄底策略重点)
        "weekly_bullish": 2, "weekly_macd_red": 3,
        "industry_hot_top5": 3, "industry_cold_bottom5": -3,
        "fund_flow_pos": 3, "fund_flow_neg": -3,
        "penalty_far": -15, "penalty_chase_high": -20,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -3,
        "pattern_bonus": 3,
    },
    "全仓": {
        # 全仓单只 — 最强信号共振，只选一只最优
        # 原则: 趋势为王 | 量价配合 | 不追高 | 风险重罚
        "ma_mlt": 20, "ma_above60": 8, "ma_above120": 5,
        "macd_golden_red": 15, "macd_golden": 8, "macd_above0": 5,
        "rsi_strong": 10, "rsi_weak": 0, "rsi_rising": 5,
        "kdj_golden": 5, "kdj_overbought": -10,
        "vol_gt2": 20, "vol_gt1.5": 12, "vol_gt1.2": 5,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # P0: chg5 2026年IC=-0.01，冻结
        "chg5": 0,            # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "chg10": 0,           # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "amount_q_reversal": -8,  # P0修复: 成交额分位数切割反转（2026年IC=-0.069稳定负向）
        "vol_breakout": 15, "vol_shrink": 0, "vol_dump": -15,
        "vol_shrink20_bonus": 3,   # T-2026-08-20 缩量企稳因子
        "weekly_bullish": 8, "weekly_macd_red": 5,
        "industry_hot_top5": 8, "industry_cold_bottom5": -5,
        "fund_flow_pos": 8, "fund_flow_neg": -8,
        "penalty_far": -15, "penalty_chase_high": -20,
        "penalty_kdj_ob": -10, "penalty_vol_dump": -10,
        "pattern_bonus": 10,
    },
    "断层": {
        # 净利润断层 — 业绩超预期跳空缺口，A股最强alpha因子
        # 原则: 缺口不补 | 量价确认 | 均线共振 | 不追高
        "ma_mlt": 10, "ma_above60": 5, "ma_above120": 3,
        "macd_golden_red": 12, "macd_golden": 6, "macd_above0": 3,
        "rsi_strong": 6, "rsi_weak": 2, "rsi_rising": 3,
        "kdj_golden": 3, "kdj_overbought": -8,
        "vol_gt2": 10, "vol_gt1.5": 6, "vol_gt1.2": 3,
        "chg5_gt8": 5, "chg5_gt3": 3, "chg5_accel": 5,
        "vol_breakout": 8, "vol_shrink": 2, "vol_dump": -8,
        "vol_shrink20_bonus": 0,   # T-2026-08-20 缩量企稳因子
        "weekly_bullish": 5, "weekly_macd_red": 3,
        "industry_hot_top5": 8, "industry_cold_bottom5": -5,
        "fund_flow_pos": 5, "fund_flow_neg": -5,
        "penalty_far": -8, "penalty_chase_high": -12,
        "penalty_kdj_ob": -5, "penalty_vol_dump": -5,
        "pattern_bonus": 8,
        "earnings_gap_bonus": 15,   # 断层加分
    },
    "北向精选": {
        # 北向+机构增持 — 聪明钱持续买入的优质标的
        # 原则: 北向重仓 | 趋势增持 | 低位共振 | 基本面配合
        "ma_mlt": 8, "ma_above60": 5, "ma_above120": 3,
        "macd_golden_red": 8, "macd_golden": 5, "macd_above0": 3,
        "rsi_strong": 5, "rsi_weak": 2, "rsi_rising": 2,
        "kdj_golden": 3, "kdj_overbought": -5,
        "vol_gt2": 5, "vol_gt1.5": 3, "vol_gt1.2": 2,
        "chg5_gt8": 3, "chg5_gt3": 2, "chg5_accel": 2,
        "vol_breakout": 3, "vol_shrink": 2, "vol_dump": -3,
        "vol_shrink20_bonus": 0,   # T-2026-08-20 缩量企稳因子
        "turn5_penalty": 0,        # T-20260820 筹码松动代理
        "ma_tight_bonus": 0,       # T-20260820 均线粘合共振
        "weekly_bullish": 5, "weekly_macd_red": 3,
        "industry_hot_top5": 5, "industry_cold_bottom5": -3,
        "fund_flow_pos": 8, "fund_flow_neg": -8,
        "penalty_far": -5, "penalty_chase_high": -8,
        "penalty_kdj_ob": -3, "penalty_vol_dump": -3,
        "pattern_bonus": 3,
        "earnings_gap_bonus": 8,    # 断层加分
    },
    "三线共振": {
        # 2026-08-20 P0-3修复: vol_shrink20=-40拖累超额-30pp, 回滚至0
        # 回测: 基线(综合)+56.35% → 三线共振(+vol_shrink20=-20)+26.04%, 超额-30.31pp
        # 决策: 不合入生产, 权重回滚至0
        "vol_shrink20_bonus": 0,     # P0-3修复: -40→0 (回滚)
        "turn5_penalty": 0,          # P0-3修复: 同步移除
        "ma_tight_bonus": 0,         # P0-3修复: 同步移除
    },
    # ── P2-2 新策略族 (2026-08-30) ──
    "反转+低波": {
        # 策略族A: 反转5/10日 + 低波动率 (IC=-0.21/-0.33)
        # 原则: 超跌反弹 + 低波异象, 完全放弃趋势/动量
        # 2026-08-30 Phase1子任务4优化: 权重收紧至 ±10~15, 避免极端值挤压评分空间
        "chg5_rev": -15, "chg10_rev": -15, "chg20_rev": -10,  # 反转强化(目标±10~15)
        "volatility20": 12,  # P1: 反转权重(-15→+12), 奖励高波动突破票
        "max_ret5_low": 15,   # 彩票型回避强化(原30超限)
        "rsi_oversold": 15,   # RSI超卖反弹
        "vol_shrink": 10,     # 缩量企稳(反转前兆)
        "vol_gt2": 0,         # 成交量放大不选(回避追高)
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # 动量不选
        "ma_mlt": 5, "ma_above60": 3, "ma_above120": 2,  # 均线弱依赖
        "macd_golden_red": 5, "macd_golden": 3, "macd_above0": 2,
        "rsi_strong": 3, "rsi_weak": 10, "rsi_rising": 5,
        "kdj_golden": 3, "kdj_overbought": -10,
        "vol_breakout": -5, "vol_dump": -10,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "industry_hot_top5": -3, "industry_cold_bottom5": 3,
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "penalty_far": -15, "penalty_chase_high": -15,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -8,
        "pattern_bonus": 0,
    },
    "龙头+形态": {
        # 策略族B: 龙头特征 + 形态突破 (IC=+0.31/+0.06)
        # 原则: 行业龙头 + 放量突破, 趋势跟随
        # 2026-08-30 Phase1子任务4优化: 权重收紧至 ±10~15, 避免极端值挤压评分空间
        "industry_hot_top5": 15,   # 行业强势加分(IC=+0.31龙头特征)
        "fund_flow_pos": 15,       # 资金流入加分(原12→15强化)
        "vol_breakout": 15,        # 放量突破强化(IC=+0.06过门禁, 原18超限)
        "vol_gt2": 12, "vol_gt1.5": 8, "vol_gt1.2": 5,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # P0: chg5 2026年IC=-0.01，冻结
        "chg10": 0,              # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "amount_q_reversal": -8,  # P0修复: 成交额分位数切割反转（2026年IC=-0.069稳定负向）
        "ma_mlt": 15, "ma_above60": 8, "ma_above120": 5,
        "macd_golden_red": 15, "macd_golden": 10, "macd_above0": 5,
        "rsi_strong": 8, "rsi_weak": 0, "rsi_rising": 5,
        "kdj_golden": 5, "kdj_overbought": -5,
        "vol_shrink": 0, "vol_dump": -10,
        "vol_shrink20_bonus": 0,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,  # 不选反转
        "volatility20": 0,        # 不重视波动率
        "weekly_bullish": 10, "weekly_macd_red": 8,
        "industry_cold_bottom5": -8,
        "fund_flow_neg": -8,
        "penalty_far": -8, "penalty_chase_high": -12,
        "penalty_kdj_ob": -5, "penalty_vol_dump": -8,
        "pattern_bonus": 10,
        # P2-2 Phase1子任务4后续 (2026-08-31): 剔除 rms (IR=0.24<0.3),
        # P2-2 Phase1子任务4后续 (2026-08-31): 升权 alpha13 + vol_price_corr_20 (alpha15是噪声IC≈0已移除)
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)
        "alpha16_fix": 35,        # Phase2-2026-09-25: IC5=0.1038通过门禁，启用(原冻结0)
        "vol_floor": 5,               # Phase C-2: 低波异象辅助(+5)
    },
    "成交额切割反转": {
        # 策略族C: 反转10日 + 成交额分位数 (IC=-0.21)
        # 原则: 高成交额日的跌幅 > 低成交额日的跌幅 → 理想反转降级版
        # 2026-08-30 Phase1子任务4优化: 权重收紧至 ±10~15, 避免极端值挤压评分空间
        "chg10_rev": -15,          # 反转10日强化(IC=-0.21, 原-20超限)
        "chg5_rev": -12,           # 短期反转配合
        "chg20_rev": -10,          # 长期反转
        "vol_shrink": 10,          # 缩量回调(成交额低时跌)
        "vol_gt2": -5,             # 放量日涨幅不选(反向信号)
        "vol_breakout": -10,       # 放量突破反向(回避追高)
        "volatility20": -15,       # 低波配合反转(原-25超限)
        "max_ret5_low": 15,        # 回避彩票型(原20超限)
        "rsi_oversold": 15,        # RSI超卖(原12→15强化)
        "rsi_weak": 10, "rsi_rising": 5,
        "ma_mlt": 5, "ma_above60": 3, "ma_above120": 2,
        "macd_golden_red": 5, "macd_golden": 3, "macd_above0": 2,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "kdj_golden": 3, "kdj_overbought": -10,
        "vol_dump": -10,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "industry_hot_top5": -3, "industry_cold_bottom5": 2,
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "penalty_far": -15, "penalty_chase_high": -15,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -8,
        "pattern_bonus": 0,
        # P2-2 Phase1子任务4后续 (2026-08-31): 升权 alpha13 + vol_price_corr_20 (alpha15是噪声IC≈0已移除)
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)
    },
    # ── P2-2 扩展策略族 (2026-08-30, 总管Phase1子任务4-后续) ──
    # 目标: 凑够15策略, 引入真正异构的信号源以拉低 avg|corr| 到 <0.3
    # 参考: 老五评审报告建议增加 族D资金流动量 / 族E RSI超卖反弹 / 族F价值 / 族G质量 / 族H低波动
    "资金流动量": {
        # 策略族D: 主力资金净流入 + 北向资金 + 量价配合
        # 原则: 聪明钱持续买入, 用真实资金流信号选股, 与S14龙头部分重叠但更聚焦资金维度
        # 完全放弃反转/超卖/趋势, 让评分函数中主力资金/北向/换手加分独立生效
        "fund_flow_pos": 15,          # 主力资金流入(核心, 通过fund_flow_bonus生效)
        "fund_flow_neg": -15,         # 主力资金流出重罚
        "vol_gt2": 8, "vol_gt1.5": 5, "vol_gt1.2": 3,  # 温和放量配合资金流
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,  # P0: chg5 2026年IC=-0.01，冻结
        "chg10": 0,              # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "amount_q_reversal": -8,  # P0修复: 成交额分位数切割反转（2026年IC=-0.069稳定负向）
        # 小幅涨幅(资金推升特征) 改为chg10
        "vol_shrink": 3,              # 缩量配合(不追高)
        "turn5_penalty": -5,          # 换手异常惩罚(通过turn5_penalty逻辑)
        "ma_mlt": 3, "ma_above60": 2, "ma_above120": 1,  # 弱趋势依赖
        "macd_golden_red": 3, "macd_golden": 2, "macd_above0": 1,
        "rsi_strong": 3, "rsi_weak": 0, "rsi_rising": 3,  # RSI中性偏强(不选超卖)
        "rsi_oversold": 0,             # 不选RSI超卖(避免与S17重叠)
        "kdj_golden": 2, "kdj_overbought": -8,
        "vol_breakout": 5,             # 温和突破(不追极端放量)
        "vol_dump": -12,
        "vol_shrink20_bonus": 0,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,  # 完全放弃反转(与S13/S15解耦)
        "volatility20": 0,             # 不重视波动率(与S20解耦)
        "max_ret5_low": 0,
        "weekly_bullish": 3, "weekly_macd_red": 2,
        "industry_hot_top5": 5, "industry_cold_bottom5": -3,
        "penalty_far": -12, "penalty_chase_high": -12,  # 中追高惩罚(允许资金推动上涨)
        "penalty_kdj_ob": -5, "penalty_vol_dump": -8,
        "pattern_bonus": 3,
        # P2-2 Phase1子任务4后续 (2026-08-31): 剔除 rms (IR=0.24<0.3), 升权 alpha13/alpha15
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)  # alpha15移除(IC≈0噪声)
        "alpha16_fix": 35,        # Phase2-2026-09-25: IC5=0.1038通过门禁，启用(原冻结0)
    },
    "RSI超卖反弹": {
        # 策略族E: RSI6/14 超卖反弹 (纯超卖反转, 与S13/S15低重叠)
        # 原则: 极端超卖 → 均值回归, 用 rsi_oversold 与 rsi_rising 主导评分
        # 与S13反转+低波区分: S13强调低波+多因子, 本族强调RSI超卖单因子
        # 与S15成交额切割反转区分: S15强调成交额分层, 本族强调RSI阈值
        "rsi_oversold": 15,           # RSI超卖反弹(核心)
        "rsi_weak": 12,               # 偏弱区间
        "rsi_rising": 10,             # RSI回升(反弹启动信号)
        "rsi_strong": -5,             # 强势不选(与超卖对立)
        "kdj_overbought": -15,        # 超买重罚(避免反弹到顶)
        "kdj_golden": 3,              # 弱KDJ金叉加分
        "chg5_rev": -10, "chg10_rev": -8, "chg20_rev": -8,  # 温和反转配合
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "vol_shrink": 8,              # 缩量企稳(超卖底部)
        "vol_dump": -10,
        "vol_shrink20_bonus": 5,      # 20日缩量企稳
        "ma_mlt": 3, "ma_above60": 0, "ma_above120": 0,   # 不要求均线多头
        "macd_golden_red": 2, "macd_golden": 2, "macd_above0": 0,
        "vol_gt2": -5,                # 放量不选(超卖阶段不放量)
        "vol_breakout": -8,           # 放量突破反向
        "volatility20": -8,           # 低波温和(不过度强调,与S20解耦)
        "max_ret5_low": 8,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "industry_hot_top5": 0, "industry_cold_bottom5": 3,  # 略偏好冷门(超卖多在冷门股)
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "penalty_far": -8, "penalty_chase_high": -12,  # 超卖阶段通常不追高,轻罚
        "penalty_kdj_ob": -10, "penalty_vol_dump": -8,
        "pattern_bonus": 2,
        # P2-2 Phase1子任务4后续 (2026-08-31): 升权 alpha13 + vol_price_corr_20 (alpha15是噪声IC≈0已移除)
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)
        "alpha16_fix": 35,        # Phase2-2026-09-25: IC5=0.1038通过门禁，启用(原冻结0)
    },
    "价值代理": {
        # 策略族F: 价值因子代理 (PE/PB/PS不可用, 用已有低估值代理因子代替)
        # 原则: 低估值 = 低单日最大涨幅 + 缩量(无人问津) + 冷门板块
        # (2026-08-31: 剔除 rms 作低估值代理, IR=0.24<0.3 不过门禁)
        # 与S13/S15反转族区分: 反转族押注短期反弹, 本族押注长期价值回归
        # 与S17 RSI超卖区分: 超卖是极端情绪, 本族是温和低估值
        "max_ret5_low": 15,           # 回避彩票型(低估值特征)
        "vol_shrink": 10,             # 缩量(无人问津)
        "vol_shrink20_bonus": 10,     # 20日缩量(长期被忽视)
        "turn5_penalty": -8,          # 换手过低(低估值特征)
        "ma_above120": -3,            # 弱势股(120日线下, 低估值)
        "chg20_rev": -10,             # 长期跌幅(温和低估值)
        "chg5_rev": -5, "chg10_rev": -5,
        "volatility20": -5,           # 温和低波
        "ma_mlt": 0,                  # 不要求均线多头(低估值通常均线走平)
        "macd_golden_red": 0, "macd_golden": 0, "macd_above0": 0,
        "rsi_strong": 0, "rsi_weak": 3, "rsi_rising": 2,
        "rsi_oversold": 3,            # 略选超卖(但不主导)
        "kdj_golden": 2, "kdj_overbought": -10,
        "vol_gt2": -3, "vol_gt1.5": -2, "vol_gt1.2": -1,  # 不放量(避免热度)
        "vol_breakout": -10,          # 放量突破反向
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "vol_dump": -10,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "industry_hot_top5": -5, "industry_cold_bottom5": 5,  # 冷门板块加分(低估值)
        "fund_flow_pos": 0, "fund_flow_neg": 0,  # 资金流不加分(价值股不受热捧)
        "penalty_far": -8, "penalty_chase_high": -10,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -8,
        "pattern_bonus": 0,
        # P2-2 Phase1子任务4后续 (2026-08-31): 剔除 rms (IR=0.24<0.3, 方向歧义),
        # 升权 alpha13/alpha15 至 10~12 (✅门禁) — 价值代理用 Alpha101 协方差作为辅助
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)  # alpha15移除(IC≈0噪声)
        "alpha16_fix": 35,        # Phase2-2026-09-25: IC5=0.1038通过门禁，启用(原冻结0)
    },
    "质量代理": {
        # 策略族G: 质量因子代理 (ROE/毛利率/现金流不可用, 用强趋势+低ATR波动代替)
        # 原则: 高质量 = 稳定趋势 + 强势相对动量 + 温和波动 + 无极端单日
        # 与S14龙头+形态区分: 龙头押注形态突破/爆量, 本族押注长期稳健趋势
        # 与S19低波动区分: 本族强调趋势+动量质量, S20强调纯低波动率
        "ma_mlt": 15,                 # 均线多头(核心, 稳定趋势)
        "ma_above60": 12,             # 强势60日均线上(核心)
        "ma_above120": 10,            # 强势120日均线上
        # P2-2 Phase1子任务4后续 (2026-08-31): 剔除 rms (IR=0.24<0.3), 升权 alpha13/alpha15
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)  # alpha15移除(IC≈0噪声)
        "alpha16_fix": 35,        # Phase2-2026-09-25: IC5=0.1038通过门禁，启用(原冻结0)
        "volatility20": -10,          # 低波动率(高质量代理)
        "max_ret5_low": 10,           # 回避极端单日(高质代理)
        "macd_golden_red": 10,        # 稳定MACD金叉红柱
        "macd_golden": 8, "macd_above0": 5,
        "rsi_strong": 8, "rsi_weak": 0, "rsi_rising": 5,  # RSI强势(不超卖)
        "rsi_oversold": 0,
        "kdj_golden": 5, "kdj_overbought": -10,  # 避免超买
        "weekly_bullish": 10, "weekly_macd_red": 8,  # 周线共振(高质量股周线稳)
        "vol_shrink": 3,              # 温和缩量(健康回调)
        "vol_gt2": 3, "vol_gt1.5": 2, "vol_gt1.2": 1,  # 温和放量
        "vol_breakout": 5,            # 温和突破(不追极端爆量)
        "chg5_gt8": 3, "chg5_gt3": 3, "chg5_accel": 5,
        "vol_dump": -10,
        "vol_shrink20_bonus": 3,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,  # 放弃反转(与S13/S15/S17/S18解耦)
        "industry_hot_top5": 5, "industry_cold_bottom5": -5,  # 偏好强势板块
        "fund_flow_pos": 5, "fund_flow_neg": -5,
        "penalty_far": -10, "penalty_chase_high": -12,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -8,
        "pattern_bonus": 3,
    },
    "低波动异象": {
        # 策略族H: 低波动异象 (IC=-0.33 最强负向因子)
        # 原则: 低波动率股票长期超额收益显著, 纯 volatility20 主导评分
        # 与S13反转+低波区分: S13同时用反转+低波, 本族只用纯低波动+稳定趋势
        # 与S18质量代理区分: 质量强调趋势+动量, 本族强调波动率异象
        "volatility20": -15,          # 低波动率(核心, IC=-0.33最强)
        "max_ret5_low": 15,           # 回避彩票型(与低波协同)
        "vol_shrink": 10,             # 缩量(低波代理)
        "vol_shrink20_bonus": 8,      # 20日缩量
        "turn5_penalty": -5,          # 换手过低(低波代理)
        "ma_above60": 3, "ma_above120": 3,  # 温和趋势(不要求多头)
        "ma_mlt": 3,                  # 弱均线多头
        "macd_golden_red": 3, "macd_golden": 2, "macd_above0": 1,
        "rsi_strong": 3, "rsi_weak": 3, "rsi_rising": 2,  # RSI中性
        "rsi_oversold": 0,
        "kdj_golden": 3, "kdj_overbought": -10,
        "weekly_bullish": 5, "weekly_macd_red": 3,
        "vol_gt2": -8,                # 放量不选(与低波对立)
        "vol_breakout": -12,          # 放量突破重罚
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "vol_dump": -8,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,  # 放弃反转(与S13/S15/S17解耦)
        # P2-2 Phase1子任务4后续 (2026-08-31): 剔除 rms (IR=0.24<0.3), 升权 alpha13/alpha15
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083配合alpha16_fix启用(原冻结0)  # alpha15移除(IC≈0噪声)  # Alpha101协方差加分
        "vol_floor": 8,               # Phase C-2: 强化低波信号(+8)
        "industry_hot_top5": 0, "industry_cold_bottom5": 0,  # 板块中性
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "penalty_far": -8, "penalty_chase_high": -10,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -10,
        "pattern_bonus": 0,
    },
    # ── P2-2 Phase1子任务4后续: S17 Alpha101协方差策略族 (2026-08-31) ──
    # Phase D-2 (2026-09-01): 引入 alpha16_fix 至S17核心, 与alpha13+vol_price_corr_20并列为三大协方差因子
    # 独立策略族: 仅用 alpha13+vol_price_corr_20+alpha16_fix 三个过门禁因子, 权重 ±12
    # 设计原则:
    #   - alpha13: close-vol 5日协方差 (IC=+0.0341, IR=0.38, 方向率65%, 单调差+0.084) ✅
    #   - vol_price_corr_20: 20日量价相关 (IC=-0.0566, IR=0.51, 替换alpha15噪声) ✅
    #   - alpha16_fix: alpha16单调性修复 (IC=+0.0556, IR=0.53, 方向率68%, 单调差+0.229) ✅
    #   - 与 S12~S16 区分: 其他族用 Alpha101 作辅助, 本族作核心 (权重 ±12)
    #   - 完全放弃传统趋势/反转/超卖/放量因子, 让三因子协方差主导评分
    #   - 与所有 S01~S16 正交: 无 chg5_rev/ma_mlt/volatility20 等共享因子
    # 门禁数据源: data/audit/alpha101_extended_ic_20260831.json
    "Alpha101协方差": {
        # 策略族I: Alpha101 协方差独立族 (三因子 alpha13+alpha15+alpha16_fix + vol_floor辅助)
        # 原则: 协方差信号 = close/price 与 volume 的 5日 rank 相关 + high/price 与 volume 的 3日相关求和
        #        + alpha16 单调性修复后的 3日协方差修正项 (Phase D-2)
        # 与其他族正交: 完全放弃趋势/反转/超卖/放量, 让协方差信号独立主导
        # 权重 ±12 (门禁通过因子的最高权重档位, 参考 max_ret5_low=25 的 0.5x)
        # Phase C-2: 加入 vol_floor 低波异象辅助 (+5)
        "alpha13": 25,  # Phase2-2026-09-25: IC5=0.0083弱信号配合alpha16_fix启用(原冻结0)
        "vol_price_corr_20": -12,     # 20日量价相关 (IC=-0.0566, 替换alpha15噪声, 核心)
        "alpha16_fix": 35,        # Phase2-2026-09-25: IC5=0.1038通过门禁，启用(原冻结0)
        "vol_floor": 5,               # Phase C-2: 低波异象辅助(+5)
        # 完全放弃传统技术因子, 让 alpha13/alpha15 独立主导评分
        "ma_mlt": 0, "ma_above60": 0, "ma_above120": 0,
        "macd_golden_red": 0, "macd_golden": 0, "macd_above0": 0,
        "rsi_strong": 0, "rsi_weak": 0, "rsi_rising": 0, "rsi_oversold": 0,
        "kdj_golden": 0, "kdj_overbought": 0,
        "vol_gt2": 0, "vol_gt1.5": 0, "vol_gt1.2": 0,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,
        "vol_breakout": 0, "vol_shrink": 0, "vol_dump": 0,
        "vol_shrink20_bonus": 0, "turn5_penalty": 0,
        "volatility20": 0, "max_ret5_low": 0,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "industry_hot_top5": 0, "industry_cold_bottom5": 0,
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "penalty_far": -10, "penalty_chase_high": -12,  # 保留基础追高惩罚(风控)
        "penalty_kdj_ob": -8, "penalty_vol_dump": -8,
        "pattern_bonus": 0,
    },
    # ── P2-2 Phase1子任务4后续: S18-行业动量策略族 (2026-08-31) ──
    # 独立策略族: 基于 industry_hot_top5/industry_cold_bottom5 因子
    # 权重 ±12~15 (行业动量是强信号 IC=+0.31)
    "行业动量": {
        "industry_hot_top5": 15,
        "industry_cold_bottom5": -12,
        "ma_mlt": 0, "ma_above60": 0, "ma_above120": 0,
        "macd_golden_red": 0, "macd_golden": 0, "macd_above0": 0,
        "rsi_strong": 0, "rsi_weak": 0, "rsi_rising": 0, "rsi_oversold": 0,
        "kdj_golden": 0, "kdj_overbought": 0,
        "vol_gt2": 0, "vol_gt1.5": 0, "vol_gt1.2": 0,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,
        "vol_breakout": 0, "vol_shrink": 0, "vol_dump": 0,
        "vol_shrink20_bonus": 0, "turn5_penalty": 0,
        "volatility20": 0, "max_ret5_low": 0,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "alpha13": 25,  # Phase2-2026-09-25: 启用配合alpha16_fix
        "vol_price_corr_20": 0,
        "penalty_far": -8, "penalty_chase_high": -10,
        "penalty_kdj_ob": -5, "penalty_vol_dump": -5,
        "pattern_bonus": 0,
    },
    # ── P2-2 Phase1子任务4后续: S19-放量突破策略族 (2026-08-31) ──
    # 独立策略族: 基于 vol_breakout 因子 (IC=+0.06 过门禁)
    # 权重 ±15 (放量突破是强信号)
    "放量突破": {
        "vol_breakout": 15,
        "ma_mlt": 0, "ma_above60": 0, "ma_above120": 0,
        "macd_golden_red": 0, "macd_golden": 0, "macd_above0": 0,
        "rsi_strong": 0, "rsi_weak": 0, "rsi_rising": 0, "rsi_oversold": 0,
        "kdj_golden": 0, "kdj_overbought": 0,
        "vol_gt2": 0, "vol_gt1.5": 0, "vol_gt1.2": 0,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,
        "vol_shrink": 0, "vol_dump": 0,
        "vol_shrink20_bonus": 0, "turn5_penalty": 0,
        "volatility20": 0, "max_ret5_low": 0,
        "weekly_bullish": 0, "weekly_macd_red": 0,
        "industry_hot_top5": 0, "industry_cold_bottom5": 0,
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "alpha13": 25,  # Phase2-2026-09-25: 启用配合alpha16_fix
        "vol_price_corr_20": 0,
        "penalty_far": -10, "penalty_chase_high": -12,
        "penalty_kdj_ob": -8, "penalty_vol_dump": -8,
        "pattern_bonus": 0,
    },
    # ── P2-2 Phase1子任务4后续: S20-周线多头策略族 (2026-08-31) ──
    # 独立策略族: 基于 weekly_bullish / weekly_macd_red 因子
    # 权重 ±12 (周线趋势确认信号)
    "周线多头": {
        "weekly_bullish": 12,
        "weekly_macd_red": 12,
        "ma_mlt": 0, "ma_above60": 0, "ma_above120": 0,
        "macd_golden_red": 0, "macd_golden": 0, "macd_above0": 0,
        "rsi_strong": 0, "rsi_weak": 0, "rsi_rising": 0, "rsi_oversold": 0,
        "kdj_golden": 0, "kdj_overbought": 0,
        "vol_gt2": 0, "vol_gt1.5": 0, "vol_gt1.2": 0,
        "chg5_gt8": 0, "chg5_gt3": 0, "chg5_accel": 0,
        "chg5_rev": 0, "chg10_rev": 0, "chg20_rev": 0,
        "vol_breakout": 0, "vol_shrink": 0, "vol_dump": 0,
        "vol_shrink20_bonus": 0, "turn5_penalty": 0,
        "volatility20": 0, "max_ret5_low": 0,
        "industry_hot_top5": 0, "industry_cold_bottom5": 0,
        "fund_flow_pos": 0, "fund_flow_neg": 0,
        "alpha13": 25,  # Phase2-2026-09-25: 启用配合alpha16_fix
        "vol_price_corr_20": 0,
        "penalty_far": -8, "penalty_chase_high": -10,
        "penalty_kdj_ob": -5, "penalty_vol_dump": -5,
        "pattern_bonus": 0,
    },
    # ── P1-2026-09-08: 基本面+策略族（激进版：基本面硬过滤+技术排序）──
    # 方案：基本面因子作为硬门槛（不通过则跳过），技术因子负责排序
    # 根因：原方案基本面权重过低，无法修正技术因子排序偏差
    "基本面+": {
        # 技术因子权重 (保留用于排序)
        # 2026-09-18 主板单票策略: 强化基本面硬门槛
        "ma_mlt": 10, "ma_above60": 4, "ma_above120": 3,
        "macd_golden_red": 8, "macd_golden": 5, "macd_above0": 3,
        "rsi_strong": 1, "rsi_weak": 1, "rsi_rising": 1,
        "kdj_golden": 3, "kdj_overbought": -5,
        "vol_gt2": 5, "vol_gt1.5": 3, "vol_gt1.2": 1,
        "chg5": 0, "chg10": 0,  # P0-2026-09-13: 删除直接权重（z-score路径已覆盖）
        "max_ret5_low": 10,
        "vol_breakout": -3, "vol_shrink": 2, "vol_dump": -6,
        "chg5_rev": -4, "chg10_rev": -3, "chg20_rev": -3,
        "volatility20": 8,
        "fund_flow_pos": 5, "fund_flow_neg": -5,
        "penalty_far": -6, "penalty_chase_high": -5,
        "penalty_kdj_ob": -3, "penalty_vol_dump": -3,
        # 基本面门槛参数（硬过滤，2026-09-18 主板单票策略）
        "fund_min_roe": 0.10,        # ROE≥10%
        "fund_min_profit_growth": 0.05,  # 利润增长≥5%
        "fund_min_revenue_growth": 0.05,  # 营收增长≥5%
        "fund_min_net_margin": 0.05,    # 净利率≥5%
        "fund_max_debt_ratio": 0.55,   # 负债率≤55%
        "fund_min_cashflow": 0.5,      # 现金流≥0.5
    },
}


def load_strategy(name=None):
    cfg_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "config.json")  # 基地化S3: 根锚点(根级 config.json)
    cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    if name and name in STRATEGIES:
        sn = name
    elif "strategy" in cfg and cfg["strategy"] in STRATEGIES:
        sn = cfg["strategy"]
    else:
        sn = STRATEGY_DEFAULT
    s = dict(STRATEGIES[sn])
    # Only apply config weights when the strategy matches config's strategy
    # Prevents config.json "综合" weights from overriding "趋势" / "突破" / "抄底" weights
    cfg_strategy = cfg.get("strategy", STRATEGY_DEFAULT)
    # P0修复(2026-09-15): 优先读取factor_weights配置，其次weights配置
    # factor_weights是新的标准配置，weights是旧配置（保留兼容性）
    # 注意：对所有策略都应用factor_weights，确保权重一致性
    if "factor_weights" in cfg and isinstance(cfg["factor_weights"], dict):
        s.update(cfg["factor_weights"])
    elif "weights" in cfg and isinstance(cfg["weights"], dict):
        s.update(cfg["weights"])
    return s, sn


