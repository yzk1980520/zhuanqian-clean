"""
特征重要性分析模块 — 从 tdx_score.py 提取 (2026-09-23)
"""
from tdx_strategies import STRATEGIES


def calc_feature_contributions(inds, weekly=None, strategy=None):
    """
    计算每个评分维度对总分的贡献（用于特征重要性分析）。
    返回: {feature_name: score_contribution}
    """
    if not inds:
        return {}
    
    s = strategy or STRATEGIES["综合"]
    contribs = {}
    
    # 1. 均线
    ma_score = 0
    if inds.get("ma5") and inds.get("ma10") and inds.get("ma20"):
        if inds["ma5"] > inds["ma10"] > inds["ma20"]:
            ma_score += s.get("ma_mlt", 15)
        elif inds["ma5"] > inds["ma10"]:
            ma_score += s.get("ma_mlt", 15) // 2
    if inds.get("ma60") and inds.get("price") and inds["price"] > inds["ma60"]:
        ma_score += s.get("ma_above60", 5)
    if inds.get("ma120") and inds.get("price") and inds["price"] > inds["ma120"]:
        ma_score += s.get("ma_above120", 3)
    contribs["均线"] = ma_score
    
    # 2. MACD
    macd_score = 0
    d, e, h = inds.get("dif"), inds.get("dea"), inds.get("macd_hist")
    if d is not None and e is not None and h is not None:
        if d > e and h > 0:
            macd_score += s.get("macd_golden_red", 12)
        elif d > e:
            macd_score += s.get("macd_golden", 7)
        if d > 0:
            macd_score += s.get("macd_above0", 4)
    contribs["MACD"] = macd_score
    
    # 3. RSI
    rsi_score = 0
    rsi14 = inds.get("rsi14", 50)
    if 45 <= rsi14 <= 75:
        rsi_score += s.get("rsi_strong", 2)
    elif 30 <= rsi14 < 45:
        rsi_score += s.get("rsi_weak", 1)
    if inds.get("rsi6") and inds["rsi6"] > rsi14:
        rsi_score += s.get("rsi_rising", 1)
    contribs["RSI"] = rsi_score
    
    # 4. KDJ
    kdj_score = 0
    if (inds.get("kdj_k") and inds.get("kdj_d") and 
        inds["kdj_k"] > inds["kdj_d"] and inds.get("kdj_j", 100) < 100):
        kdj_score += s.get("kdj_golden", 5)
    contribs["KDJ"] = kdj_score
    
    # 5. 成交量
    vol_score = 0
    vr = inds.get("vol_ratio", 1.0)
    if vr > 2.0:
        vol_score += s.get("vol_gt2", 10)
    elif vr > 1.5:
        vol_score += s.get("vol_gt1.5", 6)
    elif vr > 1.2:
        vol_score += s.get("vol_gt1.2", 3)
    contribs["成交量"] = vol_score
    
    # 6. 短期趋势
    trend_score = 0
    chg5 = inds.get("chg5", 0)
    chg10 = inds.get("chg10", 0)
    if chg5 > 8:
        trend_score += s.get("chg5_gt8", 0)
    elif chg5 > 3:
        trend_score += s.get("chg5_gt3", 0)
    if chg5 > chg10 and chg5 > 0:
        trend_score += s.get("chg5_accel", 0)
    contribs["短期趋势"] = trend_score
    
    # 7. 量价形态
    vp_score = 0
    vp = inds.get("vol_pattern")
    if vp in ("放量突破", "放量拉升"):
        vp_score += s.get("vol_breakout", -5)
    elif vp == "缩量回调":
        vp_score += s.get("vol_shrink", 4)
    elif vp == "放量下跌":
        vp_score += s.get("vol_dump", -12)
    contribs["量价形态"] = vp_score
    
    # 8. 周线
    wk_score = 0
    if weekly and weekly.get("w_bullish"):
        wk_score += s.get("weekly_bullish", 8)
    if weekly and weekly.get("w_hist") and weekly["w_hist"] > 0:
        wk_score += s.get("weekly_macd_red", 5)
    contribs["周线"] = wk_score
    
    # 9. 扣分
    penalty = 0
    if inds.get("pos_vs_ma20", 0) > 20:
        penalty += s.get("penalty_far", -12)
    if inds.get("kdj_j", 50) > 100:
        penalty += s.get("penalty_kdj_ob", -6)
    if inds.get("vol_pattern") == "放量下跌":
        penalty += s.get("penalty_vol_dump", -5)
    contribs["扣分"] = penalty
    
    # 10. 板块热度
    contribs["板块热度"] = inds.get("industry_heat_bonus", 0)
    
    # 11. 资金流
    contribs["资金流"] = inds.get("fund_flow_bonus", 0)
    
    return contribs
