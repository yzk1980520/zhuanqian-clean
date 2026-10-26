"""
趋势因子模块 — MA/MACD/RSI/KDJ 评分 (2026-09-23)
从 tdx_score_original.py score_stock 提取
"""
import math


def score_trend(inds, strategy, zscore=None, cross_rank=None,
                market_state=None, momentum_mode=False, chase_penalty=1.0,
                reversal_bonus=0.0, weak_mode=False):
    """
    趋势因子评分: MA/MACD/RSI/KDJ
    
    Returns:
        (score_delta, signals)
    """
    s = strategy
    sigs = []
    score = 0.0
    
    # ─── 1. 均线系统 ───
    ma5 = inds.get("ma5")
    ma10 = inds.get("ma10")
    ma20 = inds.get("ma20")
    ma60 = inds.get("ma60")
    ma120 = inds.get("ma120")
    price = inds.get("price")
    
    if isinstance(ma5, list): ma5 = ma5[-1]
    if isinstance(ma10, list): ma10 = ma10[-1]
    if isinstance(ma20, list): ma20 = ma20[-1]
    if isinstance(price, list): price = price[-1]
    
    is_ma_bull = (ma5 and ma10 and ma20
                  and ma5 > ma10 > ma20 > 0)
    ma_score = 0
    if is_ma_bull:
        ma_score += s.get("ma_mlt", 15); sigs.append("✅ 均线多头排列")
    elif ma5 and ma10 and ma5 > ma10:
        ma_score += s.get("ma_mlt", 15) // 2; sigs.append("📈 MA5>MA10")
    if ma60 and price and price > ma60:
        ma_score += s.get("ma_above60", 5)
    if ma120 and price and price > ma120:
        ma_score += s.get("ma_above120", 3)
    score += ma_score
    
    # ─── 2. MACD ───
    d, e, mh = inds.get("dif"), inds.get("dea"), inds.get("macd_hist")
    if d is not None and e is not None and mh is not None:
        if d > e and mh > 0:
            score += s.get("macd_golden_red", 12); sigs.append("✅ MACD金叉+红柱")
        elif d > e:
            score += s.get("macd_golden", 7); sigs.append("📈 MACD金叉")
        if d > 0:
            score += s.get("macd_above0", 4)
    
    # ─── 3. RSI ───
    rsi14 = inds.get("rsi14")
    rsi_adj = 0.0
    rsi_sigs = []
    if rsi14:
        use_zscore = zscore is not None
        use_cross_rank = cross_rank is not None and not use_zscore
        
        if use_zscore and zscore and zscore.get("rsi14") is not None:
            rz = zscore["rsi14"]
            if rz >= 1.0:
                rsi_adj += s.get("kdj_overbought", -5) * 1.5 * chase_penalty * 1.2
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超买(z={rz:.2f})")
            elif rz >= 0.5:
                extra_bonus = 1.2 if market_state in ("牛", "强") else 1.0
                rsi_adj += s.get("rsi_strong", 8) * 0.6 * extra_bonus
                rsi_sigs.append(f"📈 RSI={rsi14:.0f} 偏强(z={rz:.2f})")
            elif rz <= -1.0:
                rsi_adj += s.get("rsi_weak", 5) * (1.6 if weak_mode else 1.2) * reversal_bonus
                rsi_sigs.append(f"{'🔄' if not momentum_mode else '📉'} RSI={rsi14:.0f} 超卖(z={rz:.2f})")
            elif rz <= -0.5:
                mean_reversion = 0.8 if market_state == "震荡" else 1.0
                rsi_adj += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * mean_reversion
                rsi_sigs.append(f"📉 RSI={rsi14:.0f} 偏弱(z={rz:.2f})")
            else:
                neutral_bonus = 0.8 if market_state == "震荡" else 1.0
                rsi_adj += s.get("rsi_strong", 8) * 0.4 * neutral_bonus
                rsi_sigs.append(f"➡️ RSI={rsi14:.0f} 中性(z={rz:.2f})")
            if inds.get("rsi6") and inds["rsi6"] > rsi14:
                rsi_adj += s.get("rsi_rising", 4)
                rsi_sigs.append("📈 RSI上行")
        elif use_cross_rank and cross_rank and cross_rank.get("rsi14") is not None:
            rp = cross_rank["rsi14"]
            if 45 <= rsi14 <= 75:
                w = s.get("rsi_strong", 8) * (0.6 + 0.4 * rp)
                if momentum_mode and rsi14 >= 60:
                    w *= 1.25
                rsi_adj += w
                rsi_sigs.append(f"✅ RSI={rsi14:.0f} 强势区间(百分位{rp:.0%})")
            elif rsi14 > 80:
                rsi_adj += s.get("kdj_overbought", -5) * 1.5 * chase_penalty
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 严重超买")
            elif rsi14 > 75:
                rsi_adj += s.get("kdj_overbought", -5) * (2.0 if momentum_mode else 1.0)
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超买")
            elif rsi14 < 30:
                rsi_adj += s.get("rsi_weak", 5) * (1.6 if weak_mode else 1.2) * reversal_bonus
                rsi_sigs.append(f"{'🔄' if not momentum_mode else '📉'} RSI={rsi14:.0f} 超卖")
            elif rsi14 < 45:
                mean_reversion = 0.8 if market_state == "震荡" else 1.0
                rsi_adj += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * mean_reversion
                rsi_sigs.append(f"📉 RSI={rsi14:.0f} 偏弱")
            if inds.get("rsi6") and inds["rsi6"] > rsi14:
                rsi_adj += s.get("rsi_rising", 4)
                rsi_sigs.append("📈 RSI上行")
        else:
            if 45 <= rsi14 <= 75:
                if weak_mode:
                    rsi_adj += s.get("penalty_chase_high", -8) * 0.6
                    rsi_sigs.append(f"📉 RSI={rsi14:.0f} 弱市强势(风险)")
                else:
                    rsi_adj += s.get("rsi_strong", 8); rsi_sigs.append(f"✅ RSI={rsi14:.0f} 强势区间")
            elif 30 <= rsi14 < 45:
                rsi_adj += s.get("rsi_weak", 5); rsi_sigs.append(f"📉 RSI={rsi14:.0f} 偏弱")
            elif rsi14 > 75:
                rsi_adj += s.get("kdj_overbought", -5)
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超买")
            elif rsi14 < 30:
                rsi_adj += s.get("rsi_weak", 5) * (1.6 if weak_mode else 1.0)
                rsi_sigs.append(f"⚠️ RSI={rsi14:.0f} 超卖")
            if inds.get("rsi6") and inds["rsi6"] > rsi14:
                rsi_adj += s.get("rsi_rising", 4); rsi_sigs.append("📈 RSI上行")
        rsi_adj = max(-15.0, min(15.0, rsi_adj))
        score += rsi_adj
        sigs.extend(rsi_sigs)
    
    # ─── 4. KDJ ───
    kdj_k, kdj_d, kdj_j = inds.get("kdj_k"), inds.get("kdj_d"), inds.get("kdj_j")
    if kdj_k and kdj_d and kdj_j and kdj_k > kdj_d and kdj_j < 100:
        score += s.get("kdj_golden", 5); sigs.append("📈 KDJ金叉")
    if inds.get("kdj_j", 0) > 100:
        score += s.get("kdj_overbought", -5)
        sigs.append(f"⚠️ KDJ超买{inds['kdj_j']:.0f}")
    
    return score, sigs
