"""
动量/反转因子模块 — chg5/chg20 评分 (2026-09-23)
从 tdx_score_original.py score_stock 提取
"""


def score_momentum(inds, strategy, zscore=None, cross_rank=None,
                   momentum_mode=False, chase_penalty=1.0, reversal_bonus=0.0):
    """
    动量/反转因子评分: 5日/20日涨幅
    
    Returns:
        (score_delta, signals)
    """
    s = strategy
    sigs = []
    score = 0.0
    
    chg5 = inds.get("chg5", 0)
    chg20 = inds.get("chg20", 0)
    
    # P1修复: 动态权重根据市场状态调整
    if momentum_mode:
        _momentum_w = s.get("chg5_gt8", 8) * 1.5
        _reversal_w = 0
    else:
        _momentum_w = s.get("chg5_gt8", 8) * 0.5
        _reversal_w = abs(s.get("chg5_rev", -8)) * 1.5
    
    use_zscore = zscore is not None
    use_cross_rank = cross_rank is not None and not use_zscore
    
    if use_zscore and zscore and zscore.get("chg5") is not None:
        cz = zscore["chg5"]
        if cz >= 1.5:
            if momentum_mode:
                score += _momentum_w * 1.0
                sigs.append(f"🚀 5日大涨{chg5:.1f}%动量强势(z={cz:.2f})")
            else:
                score += s.get("penalty_chase_high", -8) * 1.0
                sigs.append(f"⚠️ 5日大涨{chg5:.1f}%追高风险(z={cz:.2f})")
        elif cz >= 0.8:
            w = _momentum_w * 0.8 * (1.25 if momentum_mode else 1.0)
            score += w
            sigs.append(f"📈 5日涨{chg5:.1f}%(z={cz:.2f})")
        elif cz >= 0.0:
            sigs.append(f"➡️ 5日持平{chg5:.1f}%(z={cz:.2f})")
        elif cz <= -1.0:
            score += _reversal_w * 1.0 * reversal_bonus
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 5日超跌{chg5:.1f}%(z={cz:.2f})")
        if chg5 > inds.get("chg10", 0) and chg5 > 0:
            score += s.get("chg5_accel", 0); sigs.append("🚀 短期加速")
        if chg20 > 10:
            w = _momentum_w // 2 * (2 if momentum_mode else 1)
            score += w; sigs.append(f"20日动量强劲{chg20:.0f}%")
    elif use_cross_rank and cross_rank and cross_rank.get("chg5") is not None:
        cp = cross_rank["chg5"]
        if cp >= 0.9:
            if momentum_mode:
                score += s.get("chg5_gt8", 8) * 1.0
                sigs.append(f"🚀 5日大涨{chg5:.1f}% 动量强势")
            else:
                score += s.get("penalty_chase_high", -12)
                sigs.append(f"⚠️ 5日大涨{chg5:.1f}% 追高风险")
        elif cp >= 0.75:
            w = s.get("chg5_gt8", 8) * 0.8
            if momentum_mode:
                w *= 1.25
            score += w
            sigs.append(f"📈 5日涨{chg5:.1f}%")
        elif cp >= 0.5:
            score += s.get("chg5_gt3", 5)
            sigs.append(f"✅ 5日温和涨{chg5:.1f}%")
        elif cp <= 0.15:
            score += s.get("rsi_weak", 5) * 1.0 * reversal_bonus
            sigs.append(f"{'🔄' if not momentum_mode else '📉'} 5日超跌{chg5:.1f}%")
        if chg5 > inds.get("chg10", 0) and chg5 > 0:
            score += s.get("chg5_accel", 3); sigs.append("🚀 短期加速")
        if chg20 > 10:
            w = s.get("chg5_gt8", 8) // 2 * (2 if momentum_mode else 1)
            score += w; sigs.append(f"20日动量强劲{chg20:.0f}%")
    else:
        if chg5 > 8:
            score += s.get("chg5_gt8", 8); sigs.append(f"✅ 5日涨{chg5:.1f}%")
        elif chg5 > 3:
            score += s.get("chg5_gt3", 5); sigs.append(f"📈 5日涨{chg5:.1f}%")
        if chg5 > inds.get("chg10", 0) and chg5 > 0:
            score += s.get("chg5_accel", 3); sigs.append("🚀 短期加速")
        if chg20 > 10:
            score += s.get("chg5_gt8", 8) // 2; sigs.append(f"20日动量强劲{chg20:.0f}%")
    
    return score, sigs
