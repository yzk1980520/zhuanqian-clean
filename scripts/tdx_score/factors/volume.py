"""
量能因子模块 — 成交量评分 (2026-09-23)
从 tdx_score_original.py score_stock 提取
"""


def score_volume(inds, strategy, zscore=None, cross_rank=None,
                 momentum_mode=False, chase_penalty=1.0, reversal_bonus=0.0):
    """
    量能因子评分: 量比/量价形态/缩量企稳
    
    Returns:
        (score_delta, signals)
    """
    s = strategy
    sigs = []
    score = 0.0
    
    vr = inds.get("vol_ratio")
    use_zscore = zscore is not None
    use_cross_rank = cross_rank is not None and not use_zscore
    
    if use_zscore and zscore and zscore.get("vol_ratio") is not None:
        vz = zscore["vol_ratio"]
        if vz >= 1.5:
            score += s.get("vol_dump", -6) * 0.5
            sigs.append(f"⚠️ 天量{vr:.1f}倍(z={vz:.2f})防见顶")
        elif vz >= 0.8:
            w = s.get("vol_gt2", 8) * min(1.0, vz / 1.5)
            score += w
            sigs.append(f"✅ 放量{vr:.1f}倍(z={vz:.2f})")
        elif vz >= 0.3:
            score += s.get("vol_gt1.5", 5) * 0.8
            sigs.append(f"📊 温和放量{vr:.1f}倍(z={vz:.2f})")
        elif vz <= -1.0:
            score += s.get("vol_shrink", 3)
            sigs.append(f"📉 缩量{vr:.1f}倍(z={vz:.2f})观望")
    elif use_cross_rank and cross_rank and cross_rank.get("vol_ratio") is not None:
        vp = cross_rank["vol_ratio"]
        if vp >= 0.97:
            score += s.get("vol_dump", -6) * 0.5
            sigs.append(f"⚠️ 天量{vr:.1f}倍 防见顶")
        elif vp >= 0.7:
            w = s.get("vol_gt2", 8) * (0.7 + 0.3 * (vp - 0.7) / 0.3)
            score += w
            sigs.append(f"✅ 放量{vr:.1f}倍(百分位{vp:.0%})")
        elif vp >= 0.5:
            score += s.get("vol_gt1.5", 5) * 0.8
            sigs.append(f"📊 温和放量{vr:.1f}倍")
        elif vp <= 0.15:
            score += s.get("vol_shrink", 3)
            sigs.append(f"📉 缩量{vr:.1f}倍 观望")
    else:
        if vr and vr > 2.0:
            score += s.get("vol_gt2", 8); sigs.append(f"✅ 放量{vr:.1f}倍")
        elif vr and vr > 1.5:
            score += s.get("vol_gt1.5", 5); sigs.append(f"📊 放量{vr:.1f}倍")
        elif vr and vr > 1.2:
            score += s.get("vol_gt1.2", 3)
    
    # ─── 量价形态 ───
    vp = inds.get("vol_pattern")
    if vp in ("放量突破", "放量拉升"):
        score += s.get("vol_breakout", 6); sigs.append(f"✅ {vp}")
    elif vp == "缩量回调":
        score += s.get("vol_shrink", 3); sigs.append(f"📊 {vp}")
    elif vp == "放量下跌":
        score += s.get("vol_dump", -6); sigs.append(f"⚠️ {vp}")
    
    # ─── 缩量企稳因子 ───
    vs_bonus = s.get("vol_shrink20_bonus", 0)
    if vs_bonus != 0 and cross_rank and cross_rank.get("vol_shrink20") is not None:
        vs_pct = cross_rank["vol_shrink20"]
        if vs_bonus > 0:
            if vs_pct <= 0.2:
                score += vs_bonus * 1.5
                sigs.append(f"📉 缩量企稳(20/60量比={inds.get('vol_shrink20', 0):.2f})")
            elif vs_pct <= 0.35:
                score += vs_bonus * 0.8
                sigs.append(f"📊 轻度缩量(20/60量比={inds.get('vol_shrink20', 0):.2f})")
        else:
            if vs_pct <= 0.2:
                score += abs(vs_bonus) * 1.5
                sigs.append(f"📉 缩量企稳(20/60量比={inds.get('vol_shrink20', 0):.2f})")
            elif vs_pct <= 0.35:
                score += abs(vs_bonus) * 0.8
                sigs.append(f"📊 轻度缩量(20/60量比={inds.get('vol_shrink20', 0):.2f})")
            elif vs_pct > 0.85:
                score += vs_bonus * 0.5
                sigs.append(f"⚠️ 放量偏高(20/60量比={inds.get('vol_shrink20', 0):.2f})")
    
    # ─── 筹码松动因子 ───
    turn5 = inds.get("turn5", 0)
    turn5_pen = s.get("turn5_penalty", 0)
    if turn5_pen < 0 and turn5 > 0:
        score += turn5_pen * turn5
        sigs.append(f"🔄 筹码松动(+{turn5}次涨跌停)")
    
    # ─── 均线粘合因子 ───
    ma_tight = s.get("ma_tight_bonus", 0)
    if ma_tight > 0 and inds.get("ma5") and inds.get("ma10") and inds.get("ma20"):
        ma5, ma10, ma20 = inds["ma5"], inds["ma10"], inds["ma20"]
        price = inds.get("price", 0)
        if price > 0:
            spread = max(abs(ma5 - ma10), abs(ma10 - ma20), abs(ma5 - ma20)) / price * 100
            if spread < 3.0:
                score += ma_tight
                sigs.append(f"📐 均线粘合(spread={spread:.1f}%)")
            elif spread < 5.0:
                score += ma_tight * 0.5
                sigs.append(f"📊 均线趋合(spread={spread:.1f}%)")
    
    return score, sigs
