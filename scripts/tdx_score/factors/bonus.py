"""
Bonus因子模块 — 基本面/资金流加分 (2026-09-23)
从 tdx_score_original.py score_stock 提取
"""


def score_bonus_factors(inds, strategy, fund_flow_bonus=0, fund_flow_signal="",
                        rs_bonus=0, industry_heat=None, pattern_bonus_info=None,
                        weekly=None):
    """
    Bonus因子评分: 板块热度/资金流/技术形态/相对强弱
    
    Returns:
        (score_delta, signals)
    """
    s = strategy
    sigs = []
    score = 0.0
    
    # ─── 板块轮动 ───
    heat_penalty = s.get("industry_cold_bottom5", -3)
    if industry_heat and isinstance(industry_heat, dict):
        heat = industry_heat.get("percentile", 0.5)
        if heat >= 0.8:
            score += s.get("industry_hot_top5", 5); sigs.append(f"🔥 板块热点 TOP{(1-heat)*100:.0f}%")
        elif heat <= 0.2:
            score += heat_penalty; sigs.append("❄️ 板块弱势")
    
    # ─── 主力资金流 ───
    if fund_flow_bonus:
        fb_max = max(abs(s.get("fund_flow_pos", 5)), abs(s.get("fund_flow_neg", -5)))
        fb = min(abs(fund_flow_bonus), fb_max) * (1 if fund_flow_bonus > 0 else -1)
        score += fb
        if fund_flow_signal: sigs.append(f"{fund_flow_signal}")
    
    # ─── 技术形态加分 ───
    if pattern_bonus_info:
        pscore = pattern_bonus_info.get("pscore", 0)
        pdesc = pattern_bonus_info.get("pdesc", "")
        bonus = min(pscore, s.get("pattern_bonus", 5))
        score += bonus
        sigs.append(f"🏆 {pdesc[:30]}")
    
    # ─── 相对强弱 ───
    if rs_bonus:
        score += min(abs(rs_bonus), 10) * (1 if rs_bonus > 0 else -1)
    
    # ─── 周线共振 ───
    if weekly:
        w_bull = weekly.get("w_bullish", False)
        w_hist = weekly.get("w_hist", 0)
        is_ma_bull = inds.get("ma5") and inds.get("ma10") and inds.get("ma20")
        if isinstance(is_ma_bull, list): is_ma_bull = all(x > 0 for x in is_ma_bull)
        ma5, ma10, ma20 = inds.get("ma5"), inds.get("ma10"), inds.get("ma20")
        if isinstance(ma5, list): ma5 = ma5[-1]
        if isinstance(ma10, list): ma10 = ma10[-1]
        if isinstance(ma20, list): ma20 = ma20[-1]
        is_ma_bull = (ma5 and ma10 and ma20 and ma5 > ma10 > ma20 > 0)
        
        if w_bull and is_ma_bull:
            score += s.get("weekly_bullish", 6); sigs.append("⏫ 多周期共振")
        elif w_bull:
            score += s.get("weekly_bullish", 6); sigs.append("📈 周线多头")
        if w_hist and w_hist > 0 and is_ma_bull:
            score += s.get("weekly_macd_red", 3); sigs.append("⏫ 周线MACD红柱+日线多头")
    
    return score, sigs
