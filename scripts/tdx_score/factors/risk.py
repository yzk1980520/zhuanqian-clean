"""
风控因子模块 — 扣分项/IC因子 (2026-09-23)
从 tdx_score_original.py score_stock 提取
"""
import math


def score_risk_factors(inds, strategy, zscore=None, cross_rank=None,
                       momentum_mode=False, chase_penalty=1.0, reversal_bonus=0.0,
                       weak_mode=False):
    """
    风控因子评分: 追高惩罚/异常因子/波动率等
    
    Returns:
        (score_delta, signals)
    """
    s = strategy
    sigs = []
    score = 0.0
    
    # ─── 追高惩罚 ───
    pos20 = inds.get("pos_vs_ma20")
    use_zscore = zscore is not None
    use_cross_rank = cross_rank is not None and not use_zscore
    
    if use_zscore and zscore and zscore.get("pos_vs_ma20") is not None:
        pz = zscore["pos_vs_ma20"]
        if pz >= 1.5:
            score += s.get("penalty_chase_high", -8) * 1.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"🚫 严重追高({pos20:+.0f}%, z={pz:.2f})")
        elif pz >= 1.0:
            score += s.get("penalty_chase_high", -8) * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 追高{pos20:+.0f}%(z={pz:.2f})")
        elif pz >= 0.5:
            score += s.get("penalty_chase_high", -8) * 0.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 偏高{pos20:+.0f}%(z={pz:.2f})")
        elif pz <= -1.5:
            score += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 严重超跌{pos20:+.0f}%(z={pz:.2f})")
        elif pz <= -1.0:
            score += s.get("rsi_weak", 5) * 0.6 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 温和回落{pos20:+.0f}%(z={pz:.2f})")
    elif use_cross_rank and cross_rank and cross_rank.get("pos_vs_ma20") is not None:
        pp = cross_rank["pos_vs_ma20"]
        if pp >= 0.90:
            score += s.get("penalty_chase_high", -12) * 1.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"🚫 严重追高({pos20:+.0f}%)")
        elif pp >= 0.80:
            score += s.get("penalty_chase_high", -12) * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 追高{pos20:+.0f}%")
        elif pp >= 0.70:
            score += s.get("penalty_chase_high", -12) * 0.5 * (1.0 if momentum_mode else chase_penalty)
            sigs.append(f"⚠️ 偏高{pos20:+.0f}%")
        elif pp <= 0.1:
            score += s.get("rsi_weak", 5) * 0.5 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 严重超跌{pos20:+.0f}%")
        elif pp <= 0.2:
            score += s.get("rsi_weak", 5) * 0.6 * reversal_bonus * (1.6 if weak_mode else 1.0)
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 温和回落{pos20:+.0f}%")
    else:
        if pos20 and pos20 > 20:
            score += s.get("penalty_far", -10); sigs.append("⚠️ 远离均线")
        elif pos20 and pos20 > 15:
            score += s.get("penalty_chase_high", -12); sigs.append(f"🚫 追高{pos20:.0f}%")
        elif pos20 and pos20 > 12:
            score += s.get("penalty_far", -10); sigs.append(f"⚠️ 偏离{pos20:.0f}%")
        elif pos20 and pos20 < -10:
            score += s.get("penalty_far", -10); sigs.append(f"⚠️ 偏低{pos20:.0f}%")
    
    # ─── IC因子组 ───
    # unlocked_pressure (IC=-0.1696)
    _up = inds.get("unlocked_pressure", 0)
    _up_w = s.get("unlocked_pressure", 0)
    if _up_w != 0 and _up is not None and isinstance(_up, (int, float)) and math.isfinite(_up):
        if _up > 50:
            score += _up_w * 1.0; sigs.append(f"⚠️ 解套盘压力大({_up:.0f}%)")
        elif _up > 30:
            score += _up_w * 0.6; sigs.append(f"📊 解套盘偏高({_up:.0f}%)")
        elif _up > 10:
            score += _up_w * 0.3
        else:
            score += abs(_up_w) * 0.3
    
    # vol_ratio 量比因子 (IC=+0.1045)
    _vr = inds.get("vol_ratio", 0)
    _vr_w = s.get("vol_ratio", 0)
    if _vr_w != 0 and _vr is not None and isinstance(_vr, (int, float)) and math.isfinite(_vr):
        if _vr >= 3.0:
            score += _vr_w * 0.5; sigs.append(f"⚠️ 天量({_vr:.1f}倍)")
        elif _vr >= 2.0:
            score += _vr_w * 0.8; sigs.append(f"✅ 放量({_vr:.1f}倍)")
        elif _vr >= 1.5:
            score += _vr_w * 0.5; sigs.append(f"📊 温和放量({_vr:.1f}倍)")
        elif _vr >= 1.2:
            score += _vr_w * 0.3
    
    # pos_vs_ma20 直接权重 (IC=-0.2263)
    _pv = inds.get("pos_vs_ma20", 0)
    _pv_w = s.get("pos_vs_ma20", 0)
    if _pv_w != 0 and _pv is not None and isinstance(_pv, (int, float)) and math.isfinite(_pv):
        if _pv > 15:
            score += _pv_w * 1.0; sigs.append(f"🚫 追高严重({_pv:+.0f}%)")
        elif _pv > 10:
            score += _pv_w * 0.7; sigs.append(f"⚠️ 偏离均线({_pv:+.0f}%)")
        elif _pv > 5:
            score += _pv_w * 0.3
        elif _pv < -10:
            score += abs(_pv_w) * 0.5; sigs.append(f"🔄 超跌({_pv:+.0f}%)")
        elif _pv < -5:
            score += abs(_pv_w) * 0.2
    
    # std20 波动率因子 (IC=-0.3349)
    _sd = inds.get("std20", 0)
    _sd_w = s.get("std20", 0)
    if _sd_w != 0 and _sd is not None and isinstance(_sd, (int, float)) and math.isfinite(_sd):
        if _sd > 10:
            score += _sd_w * 0.8; sigs.append(f"⚡ 高波动(std20={_sd:.2f})")
        elif _sd > 5:
            score += _sd_w * 0.4
        else:
            score += abs(_sd_w) * 0.2
    
    # volatility20 (IC=+0.x)
    volatility20 = inds.get("std20", 0)
    volatility_bonus = s.get("volatility20", 0)
    if volatility_bonus > 0 and volatility20 > 0:
        score += volatility_bonus * min(volatility20 / 20.0, 1.0)
        if volatility20 > 15:
            sigs.append(f"🚀 高波动突破(std20={volatility20:.2f})")
    elif volatility_bonus < 0:
        score += volatility_bonus * 1.0
        sigs.append(f"⚡ 波动率回避(std20={volatility20:.2f})")
    
    # lhb_signal 龙虎榜 (IC=0.0991)
    lhb_signal = inds.get("lhb_signal", 0)
    lhb_weight = s.get("lhb_signal", 0)
    if lhb_weight != 0 and lhb_signal != 0:
        if lhb_signal > 0:
            score += lhb_weight
            sigs.append(f"🐉 龙虎榜机构净买(lhb={lhb_signal:+.0f})")
        else:
            score -= lhb_weight
            sigs.append(f"🐉 龙虎榜机构净卖(lhb={lhb_signal:+.0f})")
    
    # rsi_oversold (IC=+0.07)
    rsi14 = inds.get("rsi14", 50)
    rsi_oversold = s.get("rsi_oversold", 0)
    if rsi_oversold > 0 and rsi14 < 30:
        score += rsi_oversold
        sigs.append(f"📈 RSI超卖反弹(rsi14={rsi14:.0f})")
    
    # volume_abnormal (IC=-0.70)
    va_w = s.get("volume_abnormal", 0)
    va_v = inds.get("volume_abnormal")
    if va_w != 0 and va_v is not None:
        if va_v > 0.5:
            score += va_w; sigs.append(f"⚠️ volume_abnormal={va_v:.2f} 成交异常度高")
        elif va_v > 0.3:
            score += va_w * 0.5
            sigs.append(f"⚡ volume_abnormal={va_v:.2f} 成交轻度异常")
    
    # rsi_extreme (IC=-0.0567)
    rsi_ext_w = s.get("rsi_extreme", 0)
    rsi_ext_v = inds.get("rsi_extreme")
    if rsi_ext_w != 0 and rsi_ext_v is not None:
        if rsi_ext_v == 1:
            score += rsi_ext_w; sigs.append(f"⚠️ rsi_extreme={rsi_ext_v} RSI极端值")
    
    # price_volume_divergence (IC=+0.0871)
    pvd_w = s.get("price_volume_divergence", 0)
    pvd_v = inds.get("price_volume_divergence")
    if pvd_w != 0 and pvd_v is not None:
        if pvd_v == 1:
            score += pvd_w
            sigs.append(f"📊 price_volume_div={pvd_v} 量价背离")
    
    # vol_floor (IC=-0.0375)
    vol_floor_w = s.get("vol_floor", 0)
    vol_floor_v = inds.get("vol_floor")
    if vol_floor_w != 0 and vol_floor_v is not None:
        if vol_floor_v <= 1.0:
            score += vol_floor_w * 1.5
            sigs.append(f"💎 vol_floor={vol_floor_v:.2f}(地量) 低波异象强")
        elif vol_floor_v <= 1.5:
            score += vol_floor_w * 1.0
            sigs.append(f"💎 vol_floor={vol_floor_v:.2f}(缩量) 低波异象")
        elif vol_floor_v <= 2.0:
            score += vol_floor_w * 0.5
            sigs.append(f"📊 vol_floor={vol_floor_v:.2f}(温和放量) 中性")
        elif vol_floor_v <= 3.0:
            score -= vol_floor_w * 0.5
            sigs.append(f"📉 vol_floor={vol_floor_v:.2f}(放量) 回避")
        else:
            score -= vol_floor_w * 1.0
            sigs.append(f"📉 vol_floor={vol_floor_v:.2f}(爆量) 重罚")
    
    # amount_q_reversal (IC=-0.0502)
    aqr_w = s.get("amount_q_reversal", 0)
    aqr_v = inds.get("amount_q_reversal")
    if aqr_w != 0 and aqr_v is not None:
        if aqr_v < -0.015:
            score += aqr_w; sigs.append(f"🔷 amount_q_rev={aqr_v:+.4f} 成交反转强")
        elif aqr_v < -0.010:
            score += aqr_w * 0.7; sigs.append(f"🔶 amount_q_rev={aqr_v:+.4f} 成交反转中")
        elif aqr_v < 0.0:
            score += aqr_w * 0.4; sigs.append(f"📊 amount_q_rev={aqr_v:+.4f} 反转温和")
        elif aqr_v < 0.010:
            score += aqr_w * 0.2; sigs.append(f"📈 amount_q_rev={aqr_v:+.4f} 高成交日涨幅低")
        elif aqr_v < 0.015:
            score -= aqr_w * 0.5; sigs.append(f"📉 amount_q_rev={aqr_v:+.4f} 无反转")
        else:
            score -= aqr_w; sigs.append(f"📉 amount_q_rev={aqr_v:+.4f} 动量主导")
    
    # sector_correlation (IC=+0.0819)
    sector_corr_w = s.get("sector_correlation", 0)
    sector_corr_v = inds.get("sector_correlation")
    if sector_corr_w != 0 and sector_corr_v is not None:
        if sector_corr_v >= 0.5:
            score += sector_corr_w * 1.5
            sigs.append(f"🔗 板块高联动(sector_corr={sector_corr_v:.3f})")
        elif sector_corr_v >= 0.2:
            score += sector_corr_w * 1.0
            sigs.append(f"📊 板块中联动(sector_corr={sector_corr_v:.3f})")
        elif sector_corr_v >= 0.0:
            score += sector_corr_w * 0.5
            sigs.append(f"➡️ 板块弱联动(sector_corr={sector_corr_v:.3f})")
        else:
            score -= sector_corr_w * 0.5
            sigs.append(f"📉 板块负联动(sector_corr={sector_corr_v:.3f})")
    
    # momentum_reversal (IC=+0.62)
    mr_w = s.get("momentum_reversal", 0)
    mr_v = inds.get("momentum_reversal")
    if mr_w != 0 and mr_v is not None:
        if mr_v > 0.05:
            score += mr_w
            sigs.append(f"📈 momentum_reversal={mr_v:.4f} 动量反转强")
        elif mr_v > 0.02:
            score += mr_w * 0.5
            sigs.append(f"📊 momentum_reversal={mr_v:.4f} 动量反转温和")
    
    # vol_price_corr_20 (IC=-0.0566)
    vpc_w = s.get("vol_price_corr_20", 0)
    vpc_v = inds.get("vol_price_corr_20")
    if vpc_w != 0 and vpc_v is not None:
        if vpc_v < -0.15:
            score += abs(vpc_w)
            sigs.append(f"📐 vol_price_corr_20={vpc_v:+.2f} 量价相关强")
        elif vpc_v < -0.05:
            score += abs(vpc_w) * 0.5
            sigs.append(f"📊 vol_price_corr_20={vpc_v:+.2f} 量价相关温和")
        elif vpc_v > 0.15:
            score -= abs(vpc_w)
            sigs.append(f"📉 vol_price_corr_20={vpc_v:+.2f} 量价相关反向")
        elif vpc_v > 0.0:
            score -= abs(vpc_w) * 0.5
            sigs.append(f"📉 vol_price_corr_20={vpc_v:+.2f} 量价相关偏弱")
    
    return score, sigs
