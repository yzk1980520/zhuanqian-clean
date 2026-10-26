"""
市场状态分析模块 — 从 tdx_score.py 提取 (2026-09-23)
延迟导入避免循环依赖
"""


def _get_position_limit(market_state):
    """仓位上限: 铁律全仓1只，不按市场状态调整(2026-08-11 老大决策)"""
    return 100


def _get_stop_loss_pct(market_state):
    """止损幅度(百分数): 单一真源 = risk_rules.STRATEGY_STOP_LOSS_PCT["全仓"]

    O-2修复(2026-10-17): 原此处硬编码 `return 8`, 与 risk_rules 契约 0.10 打架。
    全场三处各写各的口径(tdx_score_original / 本文件 / cron.daily_monitor),
    改一处不生效、改错地方以为已生效。现统一引用真源, 保持"不按市场状态调整"原语义
    (市场系数由 risk_rules.calculate_stop_loss 负责)。

    注: 返回百分数(10.0 = 10%), 与 risk_rules 小数口径(0.10)相差 100 倍, 勿混用。
    """
    from risk_rules import STRATEGY_STOP_LOSS_PCT
    return round(STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10) * 100, 2)


def _get_target_pct(market_state):
    """根据市场状态返回建议目标收益"""
    return {
        "牛": 25, "强": 20, "突破": 15,
        "震荡": 15, "弱": 10, "恐慌": 0,
    }.get(market_state, 15)


def analyze_market(scored_results=None):
    """
    分析当前市场行情，推荐最佳选股策略。
    
    scored_results: 可选，本次扫描的评分结果列表，用于判断市场宽度。
    返回 dict:
    {
        "market_state": str,       # 市场状态标签
        "recommended_strategy": str,  # 建议策略名
        "index_close": float,      # 上证收盘价
        "index_chg": float,        # 上证涨跌幅
        "index_trend": str,        # 上证趋势
        "index_rsi": float,        # 上证RSI
        "breadth": str,            # 市场宽度描述
        "reason": str,             # 推理说明
    }
    """
    # 延迟导入避免循环依赖
    from tdx_core import get_tdx_data, compute_indicators
    
    # ── 1. 上证指数分析 ─────────────────
    sh_records = get_tdx_data("sh000001", 120)
    result = {
        "market_state": "震荡",     # 默认震荡而非未知
        "recommended_strategy": "综合",
        "index_close": 0,
        "index_chg": 0,
        "index_trend": "未知",
        "index_rsi": 50,
        "breadth": "未知",
        "reason": "默认震荡市, 综合策略均衡配置",
    }
    
    # ── 降级方案：TDX无数据时用评分分布推断 ──
    if not sh_records or len(sh_records) < 30 or not compute_indicators(sh_records):
        if scored_results and len(scored_results) >= 50:  # 降低阈值: 100→50
            total = len(scored_results)
            high = sum(1 for item in scored_results if item[0] >= 60)
            low = sum(1 for item in scored_results if item[0] <= 20)
            high_ratio = high / total
            low_ratio = low / total
            if high_ratio > 0.25:
                result["market_state"] = "强"
                result["recommended_strategy"] = "综合"
                result["reason"] = f"市场宽度强势(>60分占{high_ratio*100:.0f}%), 综合策略配置"
            elif low_ratio > 0.5:
                result["market_state"] = "弱"
                result["recommended_strategy"] = "抄底"
                result["reason"] = f"市场宽度弱势(<20分占{low_ratio*100:.0f}%), 抄底策略小仓位"
            else:
                result["market_state"] = "震荡"
                result["reason"] = f"市场宽度分化(高{high}中{total-high-low}低{low}), 综合策略均衡配置"
            result["breadth"] = f"强势>{high_ratio*100:.0f}%/弱势>{low_ratio*100:.0f}%"
        return result
    
    sh_inds = compute_indicators(sh_records)
    
    sh_close = sh_inds["price"]
    sh_chg = sh_inds["chg1"]
    sh_rsi = sh_inds["rsi14"]
    sh_ma5 = sh_inds["ma5"]
    sh_ma10 = sh_inds["ma10"]
    sh_ma20 = sh_inds["ma20"]
    sh_ma60 = sh_inds["ma60"]
    sh_dif = sh_inds["dif"]
    sh_dea = sh_inds["dea"]
    sh_macd_hist = sh_inds["macd_hist"]
    sh_pos20 = sh_inds["pos_vs_ma20"]
    sh_vol_ratio = sh_inds["vol_ratio"]
    
    # ── 2. 指数趋势判定 ────────────────
    ma_bullish = bool(sh_ma5 and sh_ma10 and sh_ma20 and sh_ma5 > sh_ma10 > sh_ma20)
    ma_bearish = bool(sh_ma5 and sh_ma10 and sh_ma20 and sh_ma5 < sh_ma10 < sh_ma20)
    above_ma60 = bool(sh_ma60 and sh_close > sh_ma60)
    far_above = sh_pos20 > 15 if sh_pos20 else False
    far_below = sh_pos20 < -10 if sh_pos20 else False
    
    macd_bullish = bool(sh_dif and sh_dea and sh_dif > sh_dea and sh_macd_hist and sh_macd_hist > 0)
    macd_bearish = bool(sh_dif and sh_dea and sh_dif < sh_dea)
    
    heavy_volume = sh_vol_ratio > 1.8 if sh_vol_ratio else False
    low_volume = sh_vol_ratio < 0.6 if sh_vol_ratio else False
    
    # ── 3. 市场宽度（从评分结果推断） ──
    breadth_desc = "未知"
    high_score_ratio = 0
    low_score_ratio = 0
    if scored_results and len(scored_results) > 100:
        total = len(scored_results)
        high = sum(1 for item in scored_results if item[0] >= 60)
        low = sum(1 for item in scored_results if item[0] <= 20)
        mid = total - high - low
        high_score_ratio = high / total
        low_score_ratio = low / total
        if high_score_ratio > 0.3:
            breadth_desc = f"强势(>60分占{high_score_ratio*100:.0f}%)"
        elif low_score_ratio > 0.4:
            breadth_desc = f"弱势(<20分占{low_score_ratio*100:.0f}%)"
        else:
            breadth_desc = f"分化(高{high}中{mid}低{low})"
    
    # ── 4. 综合判定市场状态 ────────────
    if ma_bullish and above_ma60 and macd_bullish and not far_above:
        market_state = "牛"
        rec = "趋势"
        reason = "上证均线多头+MACD金叉+站上MA60, 趋势行情首选趋势策略跟踪主升浪"
    elif above_ma60 and (macd_bullish or (sh_rsi and sh_rsi > 55)) and not far_above:
        market_state = "强"
        rec = "综合"
        reason = "上证偏强震荡, 均衡配置用综合策略, 关注突破信号可切换突破策略"
    elif heavy_volume and sh_rsi and 40 <= sh_rsi <= 60 and not ma_bullish:
        market_state = "突破"
        rec = "突破"
        reason = "上证放量+RSI中性, 变盘信号明显, 突破策略捕捉爆发点"
    elif far_below and sh_rsi and sh_rsi < 35:
        market_state = "恐慌"
        rec = "抄底"
        reason = f"上证超卖(RSI{sh_rsi:.0f})+远离均线, 恐慌后往往反弹, 抄底策略捕捉超跌机会"
    elif ma_bearish or (sh_ma60 and sh_close < sh_ma60):
        market_state = "弱"
        rec = "抄底"
        if sh_rsi and sh_rsi < 40:
            reason = f"上证偏弱但RSI已低({sh_rsi:.0f}), 超跌反弹机会用抄底策略"
        else:
            reason = "上证趋势偏弱, 建议轻仓观望或抄底策略小仓位试错"
    else:
        market_state = "震荡"
        rec = "综合"
        reason = "上证无明显方向, 综合策略均衡配置, 等待趋势明朗"
    
    result = {
        "market_state": market_state,
        "recommended_strategy": rec,
        "index_close": round(sh_close, 2),
        "index_chg": round(sh_chg, 2),
        "index_trend": "多头" if ma_bullish else ("空头" if ma_bearish else "震荡"),
        "index_rsi": round(sh_rsi, 0),
        "macd": f"{'金叉' if macd_bullish else '死叉' if macd_bearish else '中性'}",
        "breadth": breadth_desc,
        "pos_vs_ma20": round(sh_pos20, 1),
        "vol_ratio": round(sh_vol_ratio, 1),
        "reason": reason,
        "max_position": _get_position_limit(market_state),
        "stop_loss_pct": _get_stop_loss_pct(market_state),
        "target_pct": _get_target_pct(market_state),
        "strategies": {
            "综合": {"suit": "中", "note": "震荡市通用"},
            "趋势": {"suit": "高" if rec == "趋势" else ("低" if market_state in ("恐慌","弱") else "中"), "note": "单边行情"},
            "突破": {"suit": "高" if rec == "突破" else "中", "note": "变盘信号时"},
            "抄底": {"suit": "高" if rec == "抄底" else "低", "note": "超卖/恐慌后"},
        }
    }
    return result
