import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
earnings_gap.py — 净利润断层策略 (Earnings Surprise Gap)
=======================================================
A股最强alpha策略之一：财报超预期→跳空缺口→不回补→机构追买

核心逻辑：
  1. 跳空缺口（开盘价 > 前日最高价 × gap_pct）
  2. 缺口未被回补（最低价 > 缺口支撑位）
  3. 成交量放大确认
  4. 价格在净利润公告附近

数据源：
  - TDX日线数据用于价格跳空检测（纯本地，不需要MCP）
  - MCP 公告查询作为增强信号（可选，通过_async_fetch_announcements）

用法:
  from core.scoring.earnings_gap import batch_score_gaps
  scores = batch_score_gaps(all_codes, recs_dict, weekly_dict)
"""

# ═══════════════════════════════════════════
#  跳空检测
# ═══════════════════════════════════════════

GAP_MIN_PCT = 2.0        # 最小跳空幅度(%)
GAP_LOOKBACK = 15        # 检测过去多少个交易日
GAP_PERSIST_DAYS = 10    # 缺口有效天数（10个交易日内有效）

def detect_gaps(recs, gap_pct=GAP_MIN_PCT, lookback=GAP_LOOKBACK):
    """
    检测价格跳空缺口。
    
    参数:
        recs: TDX日线数据列表（最新在前或从旧到新均可，自动处理）
        gap_pct: 最小跳空幅度（百分比，如2.0=2%）
        lookback: 回看天数
    
    返回:
        [gap_info, ...] 每个缺口的信息dict:
            - date: 缺口发生日期
            - gap_pct: 跳空幅度（%）
            - open: 开盘价
            - prev_high: 前日最高价
            - support: 缺口支撑位 = max(open, prev_high) 的较低者...实际取缺口下沿
            - volume_ratio: 当日量比
            - days_since: 距今交易日数
            - gap_filled: 缺口是否已回补
    """
    if not recs or len(recs) < 5:
        return []
    
    # 确保按时间升序（旧→新）
    if recs[-1]["date"] > recs[0]["date"]:
        recs_sorted = recs
    else:
        recs_sorted = list(reversed(recs))
    
    gaps = []
    for i in range(1, min(lookback + 1, len(recs_sorted))):
        cur = recs_sorted[-i] if i > 0 else recs_sorted[-1]
        prev = recs_sorted[-i-1] if i+1 < len(recs_sorted) else None
        if not prev:
            continue
        
        # 跳空：开盘价 > 前日最高价
        gap_up_pct = (cur["open"] / prev["high"] - 1) * 100
        gap_down_pct = (prev["low"] / cur["open"] - 1) * 100  # 向下跳空
        
        if gap_up_pct >= gap_pct:
            # 向上跳空缺口
            # 缺口下沿 = max(cur_open, prev_high) 中的较小者... 
            # 标准定义：缺口下沿 = min(cur_open, prev_high)... 
            # 向上跳空缺口中 = prev["high"], 因为cur["open"] > prev["high"]
            gap_lower = prev["high"]   # 缺口下沿
            gap_upper = cur["open"]    # 缺口上沿
            
            # 检查缺口是否已被回补
            gap_filled = False
            fill_pct = 0.0
            # 从缺口之后检查是否有任何一天的收盘价/最低价跌到缺口下沿
            for j in range(len(recs_sorted) - i, len(recs_sorted)):
                r = recs_sorted[j]
                if r["low"] <= gap_lower * 0.995:  # 允许0.5%误差
                    gap_filled = True
                    fill_pct = (gap_lower / r["low"] - 1) * 100
                    break
            
            # 计算量比（当日成交量 / 前20日均量）
            vol_ratio = 1.0
            if len(recs_sorted) > 20:
                recent_vols = [r["volume"] for r in recs_sorted[-21:-1]]
                avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 1
                vol_ratio = cur["volume"] / avg_vol if avg_vol > 0 else 1.0
            
            gaps.append({
                "date": cur["date"],
                "gap_pct": round(gap_up_pct, 2),
                "open": cur["open"],
                "close": cur["close"],
                "prev_high": prev["high"],
                "gap_lower": round(gap_lower, 2),
                "gap_upper": round(gap_upper, 2),
                "volume_ratio": round(vol_ratio, 2),
                "days_since": i,
                "gap_filled": gap_filled,
                "fill_pct": round(fill_pct, 2),
                "direction": "up",
            })
        
        elif gap_down_pct >= gap_pct:
            # 向下跳空（记录但暂不评分，用于风险判断）
            gaps.append({
                "date": cur["date"],
                "gap_pct": round(-gap_down_pct, 2),
                "open": cur["open"],
                "close": cur["close"],
                "prev_low": prev["low"],
                "gap_lower": round(cur["open"], 2),
                "gap_upper": round(prev["low"], 2),
                "volume_ratio": 0,
                "days_since": i,
                "gap_filled": False,
                "fill_pct": 0,
                "direction": "down",
            })
    
    return gaps

# ═══════════════════════════════════════════
#  缺口评分
# ═══════════════════════════════════════════

def score_gaps(gaps, inds, weekly=None, strategy_weights=None):
    """
    对检测到的跳空缺口进行评分。
    
    评分维度:
      - 缺口大小: 越大越好（但太大警惕）
      - 量比: 越大越好
      - 天数: 越近越好
      - 是否回补: 未回补更好
      - 价格位置: 缺口后横盘/上涨更好
    
    返回:
        (总评分, 最佳缺口描述, 信号列表)
    """
    if not gaps:
        return 0, "", []
    
    s = strategy_weights or {}
    score = 0
    sigs = []
    
    # 只取向上缺口
    up_gaps = [g for g in gaps if g["direction"] == "up" 
               and g["days_since"] <= GAP_PERSIST_DAYS]
    
    if not up_gaps:
        return 0, "", []
    
    # 取最近且未回补的最佳缺口
    active_gaps = [g for g in up_gaps if not g["gap_filled"]]
    if not active_gaps:
        # 所有缺口都已回补，但近期的回补缺口仍有参考价值
        recent = up_gaps[0]  # 最近的
        # 已回补的缺口权重打折
        for g in up_gaps[:2]:
            g_score = 0
            g_sigs = []
            
            # 幅度评分
            if 2.0 <= g["gap_pct"] <= 15.0:
                pct_score = min(g["gap_pct"] * 3, 15)
                g_score += pct_score
                g_sigs.append(f"跳空{g['gap_pct']:.1f}%")
            
            # 量能（重要）
            if g["volume_ratio"] > 2.0:
                g_score += 8
                g_sigs.append(f"放量{g['volume_ratio']:.1f}倍")
            elif g["volume_ratio"] > 1.5:
                g_score += 4
            
            # 缺口已回补折扣
            if g["gap_filled"]:
                g_score = int(g_score * 0.3)
            else:
                g_score = int(g_score * 1.0)
            
            score += g_score
            if g_sigs:
                sigs.extend(g_sigs)
        
        if score > 0:
            sigs.append("⚠️ 缺口已回补(折扣)")
        
        # 已回补缺口分值上限
        score = min(score, 10)
        gap_label = f"回补缺口(up{up_gaps[0]['gap_pct']:.1f}%)" if up_gaps else ""
        return score, gap_label, sigs
    
    # 有活跃缺口（未回补）
    best_gap = active_gaps[0]
    for g in active_gaps:
        if g["days_since"] < best_gap["days_since"]:
            best_gap = g
    
    gap = best_gap
    gap_score = 0
    
    # ── 1. 幅度评分 ──
    # 2-5% 最优（太小没意义，太大不可持续）
    if 2.0 <= gap["gap_pct"] <= 5.0:
        gap_score += 15
        sigs.append(f"✅ 完美缺口{gap['gap_pct']:.1f}%")
    elif 5.0 < gap["gap_pct"] <= 10.0:
        gap_score += 12
        sigs.append(f"✅ 强劲缺口{gap['gap_pct']:.1f}%")
    elif gap["gap_pct"] > 10.0:
        gap_score += 8
        sigs.append(f"✅ 大幅跳空{gap['gap_pct']:.1f}%")
    else:
        gap_score += 5
    
    # ── 2. 量能确认 ──
    if gap["volume_ratio"] > 2.5:
        gap_score += 10
        sigs.append(f"🔥 巨量突破{gap['volume_ratio']:.1f}倍")
    elif gap["volume_ratio"] > 1.8:
        gap_score += 8
        sigs.append(f"📊 放量突破{gap['volume_ratio']:.1f}倍")
    elif gap["volume_ratio"] > 1.3:
        gap_score += 5
    else:
        gap_score -= 3  # 无量跳空不可靠
    
    # ── 3. 时间衰减 ──
    # 越近权重越高
    recency = max(0, 1 - gap["days_since"] / GAP_PERSIST_DAYS)
    gap_score = int(gap_score * (0.6 + recency * 0.4))
    
    # ── 4. 缺口后表现 ──
    # 当前价在缺口上方越多越好
    current_price = inds.get("price", 0)
    if current_price and current_price > gap["gap_upper"] * 0.98:
        # 在缺口上方运行
        distance = (current_price / gap["gap_lower"] - 1) * 100
        if 0 < distance < 10:
            gap_score += 8
            sigs.append(f"📈 缺口上方{distance:.1f}%运行")
        elif distance >= 10:
            gap_score += 5
            sigs.append(f"📈 上行{distance:.1f}%远离缺口")
    else:
        gap_score = int(gap_score * 0.6)
        sigs.append("⚠️ 逼近缺口下沿")
    
    # ── 5. 技术面共振（与主策略配合） ──
    # 如果均线多头排列，加分
    if inds.get("ma5") and inds.get("ma10") and inds.get("ma20"):
        if inds["ma5"] > inds["ma10"] > inds["ma20"]:
            gap_score += 5
            sigs.append("📊 均线多头共振")
    
    # ── 6. 市场状态修正 ──
    market_state = inds.get("market_state", "")
    if market_state == "强":
        gap_score = int(gap_score * 1.2)
    elif market_state == "弱":
        gap_score = int(gap_score * 0.7)
    
    # 最终分有界
    gap_score = max(0, min(gap_score, 30))
    
    return gap_score, f"净利润缺口+{gap['gap_pct']:.1f}%未补({gap['days_since']}d)", sigs

# ═══════════════════════════════════════════
#  批量评分（供 pipeline 调用）
# ═══════════════════════════════════════════

def batch_score_gaps(all_codes, recs_dict, inds_dict, strategy_weights=None):
    """
    批量对所有股票计算净利润断层评分。

    参数:
        all_codes: 股票代码列表
        recs_dict: {code: [recs]} 日线数据
        inds_dict: {code: inds} 日线指标(含 price/ma5/ma10/ma20/market_state)
        strategy_weights: 策略权重dict

    返回:
        {code: (gap_score, gap_desc, sigs)}
    """
    results = {}
    s = strategy_weights or {}
    
    for code in all_codes:
        recs = recs_dict.get(code)
        if not recs or len(recs) < 20:
            results[code] = (0, "", [])
            continue
        
        # 检测跳空
        gaps = detect_gaps(recs, gap_pct=GAP_MIN_PCT, lookback=GAP_LOOKBACK)
        
        # 评分（用日线指标，修复 H4: 此前误传周线指标导致 current_price=0）
        gap_score, gap_desc, gap_sigs = score_gaps(
            gaps, 
            inds_dict.get(code, {}), 
            None, 
            s
        )
        
        results[code] = (gap_score, gap_desc, gap_sigs)
    
    return results

# ═══════════════════════════════════════════
#  独立运行测试
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print("📡 净利润断层策略 — 独立测试模式")
    print("=" * 50)
    
    # 测试
    from core.pipeline.tdx_core import get_tdx_data, compute_indicators, compute_weekly_indicators
    
    test_codes = ["002415", "002242", "000333", "000858", "002594"]
    
    for code in test_codes:
        recs = get_tdx_data(code, 150)
        if not recs:
            print(f"  {code}: 无数据")
            continue
        
        gaps = detect_gaps(recs, gap_pct=2.0, lookback=15)
        inds = compute_indicators(recs, code=code)  # 2026-10-14: LHB复活接线(单一读点)
        weekly = compute_weekly_indicators(recs)
        gap_score, gap_desc, sigs = score_gaps(gaps, inds, weekly)
        
        if gap_score > 0:
            print(f"\n  ✅ {code} (score={gap_score}): {gap_desc}")
            for s in sigs:
                print(f"     {s}")
        else:
            print(f"  {code}: 无活跃缺口")
    
    print("\n✅ 净利润断层策略测试完成")
