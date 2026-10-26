import os
import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""持仓分析报告 v2 — 基于MCP数据 + 手动计算波段指标"""

# ===== 基础数据 =====
if __name__ == "__main__":
    HOLDINGS = [
        {"code": "sz002415", "name": "海康威视", "cost": 34.167, "shares": 300},
        {"code": "sz002881", "name": "美格智能", "cost": 39.974, "shares": 300},
    ]
    CASH = 677.04
    TOTAL_ASSETS = 22796.04
    
    # 实时行情（新浪API 2026-07-27）
    REALTIME = {
        "sz002415": {"price": 35.49, "chg_pct": -0.78, "high": 35.78, "low": 34.76, "open": 35.40},
        "sz002881": {"price": 38.24, "chg_pct": -5.25, "high": 40.28, "low": 38.21, "open": 38.80},
    }
    
    # 海康威视20日收盘价（2026-06-29 至 2026-07-24）
    hik_20d_close = [32.99, 34.20, 34.03, 33.61, 34.00, 33.83, 33.86, 34.35,
                     35.39, 34.45, 33.19, 33.58, 34.10, 34.12, 33.15, 34.28,
                     35.11, 35.63, 35.77, 35.49]
    # 海康威视20日成交量（万股）
    hik_20d_vol = [10120, 12340, 14460, 9740, 9338, 9187, 8768, 10620,
                   10920, 11560, 9396, 6619, 6543, 6970, 9612, 10120,
                   13070, 12190, 9090, 7815]
    
    # 美格智能20日收盘价
    mge_20d_close = [34.14, 36.35, 39.98, 37.56, 38.62, 37.47, 36.21, 36.03,
                     36.29, 37.61, 37.55, 35.69, 35.41, 38.95, 40.58, 39.13,
                     41.91, 42.99, 40.36, 38.24]
    # 美格智能20日成交量（万股）
    mge_20d_vol = [722.8, 789.8, 1461, 997.8, 842.4, 630.9, 511.4, 478.8,
                   544.1, 1421, 1179, 984.2, 627.2, 1236, 2720, 1954,
                   2126, 2235, 1488, 1068]
    
    # 上证指数收盘价
    sh_10d_close = [3913.79, 3967.13, 3955.58, 3882.41, 3764.15, 3796.28,
                    3864.37, 3867.03, 3876.78, 3814.20]
    sh_10d_chg = [-2.061, 1.363, -0.291, -1.85, -3.046, 0.8535,
                  1.793, 0.069, 0.252, -1.614]
    
    # 新闻评分
    NEWS = {
        "sz002415": {"sentiment": "strong_positive", "desc": "浙商/国金/财通维持买入, 半年报净利+39.57%, 中期分红50亿, 营收有望破千亿"},
        "sz002881": {"sentiment": "neutral_positive", "desc": "山西/中信建投维持买入, AI模组概念, 但主力资金净流出, 短期业绩承压"},
    }

# ===== 手动计算指标 =====
def calc_sma(data, period):
    if len(data) < period:
        return None
    return sum(data[-period:]) / period

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        chg = closes[i] - closes[i - 1]
        if chg > 0:
            gains += chg
        else:
            losses -= chg
    return 100.0 - 100.0 / (1.0 + gains / losses) if losses != 0 else 100.0

def calc_vol_pattern(closes, vols):
    """简化的量价形态识别"""
    if len(closes) < 5 or len(vols) < 5:
        return None, None
    v5 = calc_sma(vols, 5) or 1
    v10 = calc_sma(vols, 10) or 1
    vr = vols[-1] / v5  # 量比
    c1 = (closes[-1] - closes[-2]) / closes[-2] * 100
    c5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) > 5 else 0

    if vr > 2.0 and c1 > 3:
        return "放量突破", f"倍量{vr:.1f}+涨{c1:.1f}%"
    if vr > 1.8 and c1 > 5:
        return "放量拉升", f"量{vr:.1f}+涨{c1:.1f}%"
    if vr > 1.5 and c1 < -3:
        return "放量下跌", f"量{vr:.1f}+跌{c1:.1f}%"
    if vr < 0.6 and c1 > 0 and c5 > 0:
        return "缩量上涨", f"量{vr:.1f}+5日涨{c5:.1f}%"
    if vr < 0.6 and c1 < 0 and c5 < 0:
        return "缩量阴跌", f"量{vr:.1f}+5日跌{c5:.1f}%"
    if vr < 0.6 and c1 < 0 and c5 > 0:
        return "缩量回调", f"量{vr:.1f}+5日涨{c5:.1f}%"
    if vr > 1.5 and c1 > 0 and c1 <= 3:
        return "温和放量", f"量{vr:.1f}+涨{c1:.1f}%"
    return None, None

def analyze_stock(code, name, cost, closes, vols, rt, news):
    """综合分析和评分"""
    cur_price = rt["price"]
    chg_today = rt["chg_pct"]

    # 盈亏
    pnl = (cur_price - cost) * 300
    pnl_pct = (cur_price - cost) / cost * 100

    # MA系统
    ma5 = calc_sma(closes, 5)
    ma10 = calc_sma(closes, 10)
    ma20 = calc_sma(closes, 20)
    ma5_10 = calc_sma(closes, 5)
    ma20_val = ma20

    # 5日/10日/20日涨跌幅
    def chg_n(n):
        if len(closes) > n:
            return (closes[-1] - closes[-n-1]) / closes[-n-1] * 100
        return 0

    chg1 = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0
    chg5 = chg_n(5)
    chg10 = chg_n(10)
    chg20 = chg_n(20)

    # RSI
    rsi14 = calc_rsi(closes, 14)

    # 量比（5日均量）
    vol_ratio = vols[-1] / (calc_sma(vols, 5) or 1)

    # 量价形态
    vp, vpd = calc_vol_pattern(closes, vols)

    # 20日高低
    highs_20 = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    lows_20 = min(closes[-20:]) if len(closes) >= 20 else min(closes)

    # 偏离20日线
    pos_vs_ma20 = (cur_price - ma20_val) / ma20_val * 100 if ma20_val else 0

    # 趋势判断
    daily_trend = 0
    if ma5 and ma10 and ma20:
        if ma5 > ma10 > ma20:
            daily_trend = 2  # 多头
        elif ma5 > ma10:
            daily_trend = 1  # 偏多
        elif ma5 < ma10 < ma20:
            daily_trend = -2  # 空头
        elif ma5 < ma10:
            daily_trend = -1  # 偏空

    # 入场位置评分
    if 0 < pos_vs_ma20 < 10:
        entry_score = 2
    elif -3 < pos_vs_ma20 <= 0:
        entry_score = 1
    elif pos_vs_ma20 > 15:
        entry_score = -2
    elif pos_vs_ma20 < -5:
        entry_score = -1
    else:
        entry_score = 0

    # RSI评分
    rsi_score = 1 if 40 <= rsi14 <= 65 else (0 if 65 < rsi14 <= 75 or (30 <= rsi14 < 40) else -1)

    # 量价评分
    vol_score = 1 if vp in ("放量突破", "放量拉升", "缩量回调") else (-2 if vp == "放量下跌" else 0)

    # MACD简化评分（近似）
    macd_score = 0
    if ma5 and ma10 and ma5 > ma10:
        macd_score = 1  # 近似金叉
    elif ma5 and ma10 and ma5 < ma10:
        macd_score = -1

    # 周线近似
    weekly_bullish = ma10 and ma20 and ma10 > ma20  # 近似周线多头
    week_align = 1 if (weekly_bullish and daily_trend > 0) else 0
    week_conflict = not weekly_bullish and daily_trend > 0

    # 综合波段评分
    total_score = daily_trend + week_align - (1 if week_conflict else 0) + entry_score + rsi_score + vol_score + macd_score

    # 若周线偏弱且总分>=4, 降级
    if not weekly_bullish and total_score >= 4:
        total_score = min(total_score, 3)

    # 弱市折扣
    market_discount = 0.7
    adjusted_score = int(total_score * market_discount)

    # 综合评分（0-100）
    raw_comp_score = 60 + total_score * 8
    if rsi14 and rsi14 > 45:
        raw_comp_score += 5
    if vp == "放量突破":
        raw_comp_score += 10
    elif vp == "放量下跌":
        raw_comp_score -= 10
    if pos_vs_ma20 > 15:
        raw_comp_score -= 10
    elif pos_vs_ma20 > 10:
        raw_comp_score -= 5

    # 新闻情绪加分
    if news["sentiment"] == "strong_positive":
        raw_comp_score += 12
    elif news["sentiment"] == "neutral_positive":
        raw_comp_score += 3

    comp_score = max(min(raw_comp_score, 100), 0)
    # 弱市折扣
    comp_score = int(comp_score * 0.7)

    # 决策
    if total_score >= 3 and comp_score >= 45:
        decision, decision_icon = "买入", "✅"
    elif total_score >= 1:
        decision, decision_icon = "轻仓", "⚠️"
    elif total_score <= -2:
        decision, decision_icon = "不适合", "❌"
    else:
        decision, decision_icon = "观望", "🔄"

    # 止损/支撑/压力
    atr_approx = (max(closes[-14:]) - min(closes[-14:])) / 14 if len(closes) >= 14 else cur_price * 0.03
    stop_loss = cur_price - atr_approx * 2.5
    support = max(ma10 or 0, lows_20 * 0.98) if ma10 else lows_20 * 0.95
    resistance = highs_20
    trailing_stop = highs_20 * 0.93  # 自高点回撤7%
    risk_pct = (cur_price - stop_loss) / cur_price * 100
    reward_pct = (resistance - cur_price) / cur_price * 100 if resistance > cur_price else 5.0
    rr = reward_pct / risk_pct if risk_pct > 0 else 0

    # 风险提示
    risks = []
    if daily_trend < 2:
        risks.append("日线趋势未完全转多，可能是反弹而非反转")
    if week_conflict:
        risks.append("周线偏弱，日线上涨持续性存疑")
    if ma10 and cur_price > ma10 * 1.08:
        risks.append(f"股价高于MA10超8%，短线乖离偏大")
    if rsi14 and rsi14 > 70:
        risks.append(f"RSI={rsi14:.0f}偏高，短线可能回调")
    if pos_vs_ma20 > 15:
        risks.append(f"股价偏离20日线+{pos_vs_ma20:.0f}%，追高回撤风险大")
    if vp == "放量下跌":
        risks.append("放量下跌，资金出逃信号")
    if chg_today < -4:
        risks.append(f"今日大跌{chg_today:.1f}%，短期空头强势")
    if rr < 2:
        risks.append("风报比不足")
    risks.append(f"市场:弱市(仓位建议≤50%) | 新闻:{news['desc']}")

    return {
        "name": name, "code": code,
        "price": cur_price, "chg_today": chg_today,
        "cost": cost, "pnl": pnl, "pnl_pct": pnl_pct,
        "ma5": ma5, "ma10": ma10, "ma20": ma20,
        "rsi14": rsi14, "vol_ratio": vol_ratio,
        "chg1": chg1, "chg5": chg5, "chg10": chg10, "chg20": chg20,
        "highs_20": highs_20, "lows_20": lows_20,
        "pos_vs_ma20": pos_vs_ma20,
        "vol_pattern": vp, "vol_pattern_detail": vpd,
        "daily_trend": daily_trend,
        "entry_score": entry_score,
        "rsi_score": rsi_score,
        "vol_score": vol_score,
        "macd_score": macd_score,
        "weekly_bullish": weekly_bullish,
        "total_score": total_score,
        "adjusted_score": adjusted_score,
        "comp_score": comp_score,
        "decision": decision, "decision_icon": decision_icon,
        "stop_loss": stop_loss, "support": support,
        "resistance": resistance, "trailing_stop": trailing_stop,
        "risk_pct": risk_pct, "reward_pct": reward_pct,
        "rr": rr, "risks": risks,
    }

# 分析两只股票
if __name__ == "__main__":
    r1 = analyze_stock("sz002415", "海康威视", 34.167, hik_20d_close, hik_20d_vol, REALTIME["sz002415"], NEWS["sz002415"])
    r2 = analyze_stock("sz002881", "美格智能", 39.974, mge_20d_close, mge_20d_vol, REALTIME["sz002881"], NEWS["sz002881"])
    
    results = [r1, r2]
    
    # ===== 输出报告 =====
    print("█" * 62)
    print("█" + " " * 18 + "📋 持仓分析报告 📋" + " " * 19 + "█")
    print("█" * 62)
    
    print(f"""
    📅 报告日期: 2026-07-27
    💼 总资产: {TOTAL_ASSETS:.2f}元   现金: {CASH:.2f}元   仓位: 97.0%
    🟡 风控评分: 75/100 (中等风险)
    📉 市场状态: 弱市
    """)
    
    # 大盘概况
    sh_latest = sh_10d_close[-1]
    sh_chg_latest = sh_10d_chg[-1]
    print(f"📊 大盘概况:")
    print(f"   上证指数: {sh_latest:.2f}  最近一日涨跌: {sh_chg_latest:+.2f}%")
    print(f"   近5日: {sh_10d_close[-1]:.2f} vs {sh_10d_close[-6]:.2f} = {(sh_10d_close[-1]/sh_10d_close[-6]-1)*100:+.1f}%")
    print(f"   大盘趋势: 冲高回落, 短期偏弱 (7/24收跌-1.61%)")
    print(f"   弱市确认: 上证持续在MA20下方运行")
    
    print(f"\n{'═' * 62}")
    
    for r in results:
        bar = "─" * 54
        print(f"\n┌{bar}┐")
        print(f"│  🏷️  {r['name']} ({r['code']})")
        print(f"├{bar}┤")
    
        print(f"│  📊 实时行情: 最新 {r['price']:.2f}  今日涨跌 {r['chg_today']:+.2f}%")
        print(f"│  💵 持仓明细: {300}股 × 成本 {r['cost']:.3f}")
        print(f"│     市值: {r['price']*300:.0f}元  浮动盈亏: {r['pnl']:+.0f}元 ({r['pnl_pct']:+.2f}%)")
        print(f"│")
        print(f"│  📈 技术评分: {r['comp_score']}/100")
        print(f"│")
        print(f"│  📐 均线系统:")
        print(f"│     MA5={r['ma5']:.2f}  MA10={r['ma10']:.2f}  MA20={r['ma20']:.2f}")
        print(f"│     {'✅ 多头排列' if r['daily_trend']==2 else '📈 MA5>MA10' if r['daily_trend']==1 else '📉 短期偏空' if r['daily_trend']==-1 else '❌ 空头排列'}")
        print(f"│")
        print(f"│  📉 技术指标:")
        print(f"│     RSI(14)={r['rsi14']:.0f}  量比={r['vol_ratio']:.1f}")
        print(f"│     5日涨跌: {r['chg5']:+.2f}%  20日涨跌: {r['chg20']:+.2f}%")
        print(f"│     偏离20日线: {r['pos_vs_ma20']:+.1f}%")
        print(f"│")
    
        # 量价形态
        if r['vol_pattern']:
            print(f"│  📊 量价形态: {r['vol_pattern']} ({r.get('vol_pattern_detail', '')})")
        else:
            print(f"│  📊 量价形态: 无明显信号")
        print(f"│")
        print(f"│  🎯 波段评分: 趋势{r['daily_trend']} 入场{r['entry_score']} RSI{r['rsi_score']} 量价{r['vol_score']} MACD{r['macd_score']} 周线{'✅' if r['weekly_bullish'] else '❌偏弱'}")
        print(f"│     综合总分: {r['total_score']} (弱市折扣→{r['adjusted_score']})")
        print(f"│     波段决策: {r['decision_icon']} {r['decision']}")
        print(f"│")
        print(f"│  📍 关键价位:")
        print(f"│     🔵 支撑位: {r['support']:.2f}")
        print(f"│     🔴 压力位: {r['resistance']:.2f}")
        print(f"│     🛑 止损位: {r['stop_loss']:.2f}  (距现价 {abs(r['risk_pct']):.1f}%)")
        # 移动止盈显示(参考值,非实盘): 用P17分级移动止盈
        print(f"│     🔄 移动止盈(P17分级): 浮盈≥10%回撤8% / ≥20%回撤12% / ≥40%回撤18% / ≥99%回撤25%")
        print(f"│     ⚠️ 注意: 分析脚本trailing_stop=高点回撤7%为旧口径, 非P17")
        print(f"│     🎯 目标1(+5%): {r['price']*1.05:.2f}  目标2(+10%): {r['price']*1.10:.2f}")
        print(f"│")
        print(f"│  ⚖️ 风报比: 1:{r['rr']:.1f}")
    
        # 今日操作建议（基于持仓+波段+风控）
        print(f"│")
        if r['code'] == "sz002415":
            # 海康威视 — 盈利中
            if r['decision'] in ("买入", "轻仓"):
                advice = "持有（已有盈利+3.87%，基本面强劲）"
                detail = "半年报超预期+AI大模型落地+中期分红50亿，中长期看好。短期随大盘回调，建议继续持有，跌破止损位再考虑减仓。"
                action = "持有"
            elif r['decision'] == "观望":
                advice = "持有/减仓（弱市仓位过高，建议锁利）"
                detail = "虽有利好支撑，但弱市仓位97%严重超限。建议减仓1/3(约100股)锁利，回笼资金降低风险。剩余仓位以移动止盈保护利润。"
                action = "减仓"
            else:
                advice = "减仓/卖出"
                detail = "波段信号偏空，建议减仓。"
                action = "减仓"
        else:
            # 美格智能 — 亏损中
            if r['decision'] == "买入":
                advice = "观望/谨慎持有（亏损-4.34%）"
                detail = "近3日暴跌-11%，从42.99高点快速回落。虽然AI模组长期逻辑在，但短期技术面破位+弱市，不宜加仓。建议持仓观望，等企稳再定夺。"
                action = "观望"
            elif r['decision'] in ("轻仓", "观望"):
                advice = "观望/减仓（亏损+弱市+高位回落）"
                detail = "近3日从42.99暴跌至38.24(-11%)，量比仍高，短期空头强势。弱市环境下不宜持有亏损股。建议：①减仓一半(150股)止损控风险；②或严格设止损于35.70(-7%)，触发即出。"
                action = "减仓"
            else:
                advice = "卖出/止损"
                detail = "波段信号差+亏损，建议止损。"
                action = "卖出"
    
        print(f"│  💡 今日操作建议: [{action}] {advice}")
        print(f"│  📝 {detail}")
        print(f"│")
        print(f"│  ⚠️ 风险提示:")
        for risk in r['risks']:
            print(f"│     - {risk}")
    
        print(f"└{bar}┘")
    
    # ====== 仓位管理建议 ======
    print(f"\n{'█' * 62}")
    print(f"█{' ' * 18}💼 仓位管理建议 💼{' ' * 18}█")
    print(f"{'█' * 62}")
    
    print(f"""
    {'=' * 60}
      当前状况
    {'=' * 60}
      📊 当前仓位: 97.0% (股票市值22,119元 + 现金677元)
      📉 市场状态: 弱市
      ✅ 风控建议仓位: ≤50%
      🔴 超限幅度: 47个百分点 (严重超限)
    
    {'=' * 60}
      建议方案
    {'=' * 60}
    
      【方案一 ⭐推荐】减仓至50%以下
      ────────────────────────────────────
      操作: 卖出约一半持仓(回笼约11,000元)
      
      优先减仓: 美格智能(300股, 现价38.24, 亏损-4.34%)
        → AI模组概念长期看好, 但近期从42.99暴跌至38.24
        → 弱势股应优先处理, 控制整体回撤
        → 建议清仓美格智能, 回笼约11,470元
      
      保留仓位: 海康威视(300股, 盈利+3.87%)
        → 基本面强劲: 半年报净利+39.57%, 中期分红50亿
        → 多家券商维持买入评级, 营收有望破千亿
        → 保留仓位, 设止损于约33.00(-7%)
      
      减仓后仓位: 约50% ✅
    
      【方案二】清弱势留强势
      ────────────────────────────────────
      操作: 
      ① 清仓美格智能(300股×38.24≈11,470元)
      ② 海康威视减仓100股×35.49≈3,549元
      ③ 合计回笼: ≈15,019元
      
      减仓后: 海康威视200股(市值≈7,098元), 现金≈15,696元
      仓位≈31%, 非常安全
    
      【方案三】严格止损暂持不动
      ────────────────────────────────────
      海康止损: {r1['stop_loss']:.2f} (约-{abs(r1['risk_pct']):.1f}%, 触发则清仓)
      美格止损: {r2['stop_loss']:.2f} (约-{abs(r2['risk_pct']):.1f}%, 触发则清仓)
      任一触发无条件执行
    
    {'=' * 60}
      总结与建议
    {'=' * 60}
    
      🔴 核心问题: 弱市持仓97%, 风控评分仅75分(主要扣分项)
      
      💡 操作优先级:
        1. 立即降低仓位至50%以下 (最紧迫!)
        2. 优先处理: 美格智能(亏损+高位回落+弱市)
        3. 保留: 海康威视(盈利+基本面强)
        4. 市场未转暖前不再加仓
        5. 等待上证站上20日线+MACD金叉再考虑加仓
    
      📊 上证指数关键观察位:
        支撑: 3,764 (7/17低点) → 3,700整数关口
        压力: 3,882 (7/16高点) → 3,960 (20日线附近)
        若跌破3,764, 需进一步降低仓位
    
      ⏰ 今日操作窗口: 开盘30分钟观察方向, 避免追涨杀跌
    """)
    
    print("=" * 60)
    print("✅ 报告生成完成")
    print("=" * 60)
