import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
技术形态识别模块 v2.0 — 扩展版
支持: 底部反转、K线组合、均线形态、量价形态
"""

def _sma(data, period):
    if len(data) < period:
        return None
    return sum(data[-period:]) / period

def _highest(data, period):
    if len(data) < period:
        return max(data) if data else None
    return max(data[-period:])

def _lowest(data, period):
    if len(data) < period:
        return min(data) if data else None
    return min(data[-period:])

# ═══════════════════════════════════════════
#  一、底部反转类
# ═══════════════════════════════════════════

def detect_double_bottom(records, lookback=60, tolerance=0.03):
    """双底/W底"""
    if len(records) < 50:
        return {"found": False, "score": 0, "desc": ""}
    lows = [r["low"] for r in records[-lookback:]]
    highs = [r["high"] for r in records[-lookback:]]
    n = len(lows)
    if n < 30:
        return {"found": False, "score": 0, "desc": ""}
    
    min_lows = []
    for i in range(2, n - 2):
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and
            lows[i] <= lows[i+1] and lows[i] <= lows[i+2]):
            min_lows.append((i, lows[i]))
    
    if len(min_lows) < 2:
        return {"found": False, "score": 0, "desc": ""}
    
    p1 = min_lows[-2]
    p2 = min_lows[-1]
    diff = abs(p2[1] - p1[1]) / max(p1[1], 0.01)
    if diff > tolerance:
        return {"found": False, "score": 0, "desc": ""}
    
    mid_high = max(highs[p1[0]+1:p2[0]]) if p2[0] > p1[0]+1 else 0
    valley_low = min(p1[1], p2[1])
    if mid_high < valley_low * 1.05:
        return {"found": False, "score": 0, "desc": ""}
    
    neckline = mid_high
    cur_price = records[-1]["close"]
    above_neck = cur_price > neckline
    score = 15 if above_neck else 10
    desc = (f"✅ W底确认" if above_neck else f"📐 W底雏形") + f"(颈线{neckline:.2f})"
    return {"found": True, "score": score, "desc": desc}

def detect_head_shoulders_bottom(records, lookback=60):
    """头肩底"""
    if len(records) < 50:
        return {"found": False, "score": 0, "desc": ""}
    lows = [r["low"] for r in records[-lookback:]]
    highs = [r["high"] for r in records[-lookback:]]
    n = len(lows)
    
    # 找三个低点（左肩、头部、右肩）
    left_min = min(lows[:n//3])
    right_min = min(lows[2*n//3:])
    mid_min = min(lows[n//3:2*n//3])
    
    # 头部应最低
    if mid_min >= left_min or mid_min >= right_min:
        return {"found": False, "score": 0, "desc": ""}
    
    # 左右肩高度相近
    if abs(left_min - right_min) / left_min > 0.05:
        return {"found": False, "score": 0, "desc": ""}
    
    # 颈线 = 左肩高点
    neckline = max(highs[:n//3])
    cur_price = records[-1]["close"]
    above_neck = cur_price > neckline
    score = 18 if above_neck else 12
    desc = f"🎩 头肩底{'确认' if above_neck else '雏形'}(颈线{neckline:.2f})"
    return {"found": True, "score": score, "desc": desc}

def detect_v_bottom(records, lookback=30):
    """V形底（尖底）- 重构版：提高特异性
    【⚠️ DEPRECATED】已从生产清单移除：Kimi审查发现胜率仅48.16%，FAIL标记
    保留函数供观察形态使用，不删除
    """
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": "", "direction": "neutral"}

    # 取最近lookback日数据
    closes = [r["close"] for r in records[-lookback:]]
    volumes = [r.get("volume", 0) for r in records[-lookback:]]
    n = len(closes)

    # 找到最低点
    min_idx = closes.index(min(closes))

    # 要求：底部前后各至少3日（提高特异性）
    if min_idx < 3 or min_idx > n - 4:
        return {"found": False, "score": 0, "desc": "", "direction": "neutral"}

    # 下降段：到最低点
    left_closes = closes[:min_idx+1]
    left_peak = max(left_closes[:-1]) if len(left_closes) > 1 else 0

    # 计算跌幅
    drop_pct = (left_peak - closes[min_idx]) / left_peak * 100
    if drop_pct < 10:  # 跌幅门槛
        return {"found": False, "score": 0, "desc": "", "direction": "neutral"}

    # 检查成交量：底部当日成交量需<20日均量85%（缩量见底信号）
    if len(volumes) >= 20:
        vol_avg_20 = sum(volumes[-20:]) / 20
        min_vol = volumes[min_idx]
        if min_vol > vol_avg_20 * 0.85:  # 放量见底不符合V底特征
            return {"found": False, "score": 0, "desc": "", "direction": "neutral"}
    else:
        vol_avg_20 = sum(volumes) / len(volumes) if volumes else 0

    # 反弹段：从最低点开始3日
    right_closes = closes[min_idx:min_idx+4]
    right_high = max(right_closes)
    rally_pct = (right_high - closes[min_idx]) / closes[min_idx] * 100

    # 验证反弹结构：至少12%反弹
    if rally_pct < 12:
        return {"found": False, "score": 0, "desc": "", "direction": "neutral"}

    # 计算恢复比例
    recovery = rally_pct / drop_pct
    if recovery < 0.4:
        return {"found": False, "score": 0, "desc": "", "direction": "neutral"}

    # 评分：根据恢复强度
    score = 20 if recovery > 0.8 else 15 if recovery > 0.6 else 10
    desc = f"⚡ V底(跌{drop_pct:.0f}%→反弹{rally_pct:.0f}%→缩至{vol_avg_20/1e6:.1f}M)"

    return {"found": True, "score": score, "desc": desc, "direction": "bull"}

# ═══════════════════════════════════════════
#  二、K线组合类
# ═══════════════════════════════════════════

def detect_morning_star(records, lookback=10):
    """早晨之星"""
    if len(records) < 5:
        return {"found": False, "score": 0, "desc": ""}
    r = records[-3:]
    if len(r) < 3:
        return {"found": False, "score": 0, "desc": ""}
    
    # 第一天大跌
    day1_chg = (r[0]["close"] - r[0]["open"]) / r[0]["open"] * 100
    if day1_chg > -3:
        return {"found": False, "score": 0, "desc": ""}
    
    # 第二天小星线
    day2_body = abs(r[1]["close"] - r[1]["open"]) / r[1]["open"] * 100
    if day2_body > 1:
        return {"found": False, "score": 0, "desc": ""}
    
    # 第三天大涨收复
    day3_chg = (r[2]["close"] - r[2]["open"]) / r[2]["open"] * 100
    if day3_chg < 3:
        return {"found": False, "score": 0, "desc": ""}
    
    # 第三天收盘进入第一天实体
    if r[2]["close"] < r[0]["open"]:
        return {"found": False, "score": 0, "desc": ""}
    
    return {"found": True, "score": 12, "desc": "🌅 早晨之星"}

def detect_hammer(records, lookback=10):
    """锤头线"""
    if len(records) < 3:
        return {"found": False, "score": 0, "desc": ""}
    r = records[-1]
    
    body = abs(r["close"] - r["open"])
    lower_shadow = min(r["open"], r["close"]) - r["low"]
    upper_shadow = r["high"] - max(r["open"], r["close"])
    
    # 下影线≥2倍实体，上影线很短
    if lower_shadow < body * 2:
        return {"found": False, "score": 0, "desc": ""}
    if upper_shadow > body * 0.5:
        return {"found": False, "score": 0, "desc": ""}
    
    return {"found": True, "score": 10, "desc": "🔨 锤头线"}

def detect_bullish_engulfing(records, lookback=10):
    """看涨吞没"""
    if len(records) < 2:
        return {"found": False, "score": 0, "desc": ""}
    r1, r2 = records[-2], records[-1]
    
    # 第一天阴线
    if r1["close"] >= r1["open"]:
        return {"found": False, "score": 0, "desc": ""}
    
    # 第二天阳线且吞没第一天
    body1 = r1["open"] - r1["close"]
    body2 = r2["close"] - r2["open"]
    if body2 <= body1 or r2["close"] <= r1["open"]:
        return {"found": False, "score": 0, "desc": ""}
    
    return {"found": True, "score": 12, "desc": "📈 看涨吞没"}

def detect_three_white_soldiers(records, lookback=10):
    """红三兵"""
    if len(records) < 4:
        return {"found": False, "score": 0, "desc": ""}
    r = records[-3:]
    
    # 连续三天阳线
    for i in range(3):
        if r[i]["close"] <= r[i]["open"]:
            return {"found": False, "score": 0, "desc": ""}
    
    # 每天涨幅>2%
    for i in range(1, 3):
        chg = (r[i]["close"] - r[i-1]["close"]) / r[i-1]["close"] * 100
        if chg < 2:
            return {"found": False, "score": 0, "desc": ""}
    
    return {"found": True, "score": 15, "desc": "🕯️ 红三兵"}

# ═══════════════════════════════════════════
#  三、均线形态类
# ═══════════════════════════════════════════

def detect_ma_golden_cross(records, lookback=60):
    """均线金叉（MA5上穿MA10或MA20）"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    
    closes = [r["close"] for r in records]
    
    # 计算MA5和MA10
    ma5_1 = sum(closes[-6:-1]) / 5 if len(closes) >= 6 else None
    ma5_2 = sum(closes[-5:]) / 5 if len(closes) >= 5 else None
    ma10_1 = sum(closes[-11:-1]) / 10 if len(closes) >= 11 else None
    ma10_2 = sum(closes[-10:]) / 10 if len(closes) >= 10 else None
    
    if not all([ma5_1, ma5_2, ma10_1, ma10_2]):
        return {"found": False, "score": 0, "desc": ""}
    
    # 昨天MA5<MA10，今天MA5>MA10
    if ma5_1 < ma10_1 and ma5_2 > ma10_2:
        return {"found": True, "score": 12, "desc": "⭐ MA5/MA10金叉"}
    
    # 计算MA10和MA20
    ma20_1 = sum(closes[-21:-1]) / 20 if len(closes) >= 21 else None
    ma20_2 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    
    if ma20_1 and ma20_2 and ma5_1 < ma20_1 and ma5_2 > ma20_2:
        return {"found": True, "score": 15, "desc": "⭐ MA5/MA20金叉"}
    
    return {"found": False, "score": 0, "desc": ""}

def detect_ma_bullish_alignment(records, lookback=60):
    """均线多头排列（MA5>MA10>MA20>MA60）"""
    if len(records) < 60:
        return {"found": False, "score": 0, "desc": ""}
    
    closes = [r["close"] for r in records]
    
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    
    if ma5 > ma10 > ma20 > ma60:
        return {"found": True, "score": 10, "desc": "📈 均线多头排列"}
    
    return {"found": False, "score": 0, "desc": ""}

def detect_ma_convergence(records, lookback=60):
    """均线粘合后发散"""
    if len(records) < 60:
        return {"found": False, "score": 0, "desc": ""}
    
    closes = [r["close"] for r in records]
    
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    
    # 均线粘合（价差<5%）
    spread = (max(ma5, ma10, ma20, ma60) - min(ma5, ma10, ma20, ma60)) / ma60 * 100
    if spread > 5:
        return {"found": False, "score": 0, "desc": ""}
    
    # 最近3天开始发散
    prev_ma5 = sum(closes[-8:-3]) / 5
    prev_ma10 = sum(closes[-13:-3]) / 10
    if prev_ma5 > prev_ma10:
        return {"found": True, "score": 8, "desc": "💫 均线粘合发散"}
    
    return {"found": False, "score": 0, "desc": ""}

# ═══════════════════════════════════════════
#  四、量价形态类
# ═══════════════════════════════════════════

def detect_vol_price_rising(records, lookback=10):
    """量价齐升（价涨量增）"""
    if len(records) < 5:
        return {"found": False, "score": 0, "desc": ""}
    r = records[-2:]
    
    price_up = r[1]["close"] > r[0]["close"]
    vol_up = r[1]["volume"] > r[0]["volume"] * 1.5
    
    if price_up and vol_up:
        return {"found": True, "score": -5, "desc": "⚠️ 量价齐升(陷阱)"}
    
    return {"found": False, "score": 0, "desc": ""}

def detect_vol_shrink_pullback(records, lookback=20):
    """缩量回调后企稳"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    
    vols = [r["volume"] for r in records]
    closes = [r["close"] for r in records]
    
    # 前10天平均成交量
    avg_vol = sum(vols[:-10]) / 10
    # 最近5天成交量萎缩
    recent_vol = sum(vols[-5:]) / 5
    
    if recent_vol > avg_vol * 0.7:
        return {"found": False, "score": 0, "desc": ""}
    
    # 最近3天止跌
    stable = all(closes[-i] >= closes[-i-1] for i in range(1, 4))
    if stable:
        return {"found": True, "score": 8, "desc": "📉 缩量企稳"}
    
    return {"found": False, "score": 0, "desc": ""}

# ═══════════════════════════════════════════
#  五、看跌K线形态类
# ═══════════════════════════════════════════

def detect_doji(records, lookback=10):
    """十字星（Doji）: 实体≤全日振幅×0.1, 上下影线总长≥实体×3"""
    if len(records) < 3:
        return {"found": False, "score": 0, "desc": ""}
    r = records[-1]
    body = abs(r["close"] - r["open"])
    full_range = r["high"] - r["low"]
    if full_range <= 0:
        return {"found": False, "score": 0, "desc": ""}
    upper_shadow = r["high"] - max(r["open"], r["close"])
    lower_shadow = min(r["open"], r["close"]) - r["low"]
    total_shadow = upper_shadow + lower_shadow

    if body > full_range * 0.1:
        return {"found": False, "score": 0, "desc": ""}
    if total_shadow < body * 3:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": 5, "desc": "✳️ 十字星"}

def detect_hanging_man(records, lookback=10):
    """上吊线: 上升趋势中, 下影线≥2×实体, 上影线≤实体×0.3"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    if ma5 is None or ma20 is None:
        return {"found": False, "score": 0, "desc": ""}
    # 需在上升趋势中
    if ma5 <= ma20:
        return {"found": False, "score": 0, "desc": ""}

    r = records[-1]
    body = abs(r["close"] - r["open"])
    if body <= 0:
        return {"found": False, "score": 0, "desc": ""}
    lower_shadow = min(r["open"], r["close"]) - r["low"]
    upper_shadow = r["high"] - max(r["open"], r["close"])

    if lower_shadow < body * 2:
        return {"found": False, "score": 0, "desc": ""}
    if upper_shadow > body * 0.3:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": -8, "desc": "🔴 上吊线(顶部反转)"}

def detect_shooting_star(records, lookback=10):
    """射击之星: 上升趋势中, 上影线≥2×实体, 下影线≤实体×0.3"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    if ma5 is None or ma20 is None:
        return {"found": False, "score": 0, "desc": ""}
    # 需在上升趋势中
    if ma5 <= ma20:
        return {"found": False, "score": 0, "desc": ""}

    r = records[-1]
    body = abs(r["close"] - r["open"])
    if body <= 0:
        return {"found": False, "score": 0, "desc": ""}
    upper_shadow = r["high"] - max(r["open"], r["close"])
    lower_shadow = min(r["open"], r["close"]) - r["low"]

    if upper_shadow < body * 2:
        return {"found": False, "score": 0, "desc": ""}
    if lower_shadow > body * 0.3:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": -10, "desc": "🌟 射击之星(顶部反转)"}

def detect_bearish_engulfing(records, lookback=10):
    """看跌吞没: 上升趋势中, 阴线吞没前日阳线实体
    【⚠️ DEPRECATED】已从生产清单移除：语义冲突标记
    保留函数供观察形态使用，不删除
    """
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    if ma5 is None or ma20 is None:
        return {"found": False, "score": 0, "desc": ""}
    # 需在上升趋势中
    if ma5 <= ma20:
        return {"found": False, "score": 0, "desc": ""}

    r1, r2 = records[-2], records[-1]
    # 第一天阳线
    if r1["close"] <= r1["open"]:
        return {"found": False, "score": 0, "desc": ""}
    # 第二天阴线且吞没第一天实体
    body1 = r1["close"] - r1["open"]
    body2 = r2["open"] - r2["close"]
    if body2 <= body1:
        return {"found": False, "score": 0, "desc": ""}
    if r2["close"] >= r1["open"] or r2["open"] <= r1["close"]:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": -12, "desc": "📉 看跌吞没(顶部反转)"}

def detect_inverse_hammer(records, lookback=10):
    """倒锤形: 下降趋势中, 上影线≥2×实体, 下影线≤实体×0.3"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    if ma5 is None or ma20 is None:
        return {"found": False, "score": 0, "desc": ""}
    # 需在下降趋势中
    if ma5 >= ma20:
        return {"found": False, "score": 0, "desc": ""}

    r = records[-1]
    body = abs(r["close"] - r["open"])
    if body <= 0:
        return {"found": False, "score": 0, "desc": ""}
    upper_shadow = r["high"] - max(r["open"], r["close"])
    lower_shadow = min(r["open"], r["close"]) - r["low"]

    if upper_shadow < body * 2:
        return {"found": False, "score": 0, "desc": ""}
    if lower_shadow > body * 0.3:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": 8, "desc": "🔨 倒锤形(底部反转)"}

def detect_piercing_line(records, lookback=10):
    """刺穿线: 下降趋势中, 阳线开盘低于前日最低, 收盘深入前日实体50%以上"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    if ma5 is None or ma20 is None:
        return {"found": False, "score": 0, "desc": ""}
    # 需在下降趋势中
    if ma5 >= ma20:
        return {"found": False, "score": 0, "desc": ""}

    r1, r2 = records[-2], records[-1]
    # 第一天阴线
    if r1["close"] >= r1["open"]:
        return {"found": False, "score": 0, "desc": ""}
    # 第二天阳线, 开盘低于前日最低
    if r2["close"] <= r2["open"]:
        return {"found": False, "score": 0, "desc": ""}
    if r2["open"] >= r1["low"]:
        return {"found": False, "score": 0, "desc": ""}
    # 收盘深入前日实体50%以上
    body1 = r1["open"] - r1["close"]
    midpoint = r1["open"] - body1 * 0.5
    if r2["close"] <= midpoint:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": 10, "desc": "⚔️ 刺穿线(底部反转)"}

def detect_bullish_harami(records, lookback=10):
    """看涨Harami: 下降趋势中, 大阴线后小实体完全包含在前日实体内"""
    if len(records) < 20:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records]
    ma5 = _sma(closes, 5)
    ma20 = _sma(closes, 20)
    if ma5 is None or ma20 is None:
        return {"found": False, "score": 0, "desc": ""}
    # 需在下降趋势中
    if ma5 >= ma20:
        return {"found": False, "score": 0, "desc": ""}

    r1, r2 = records[-2], records[-1]
    # 第一天大阴线
    if r1["close"] >= r1["open"]:
        return {"found": False, "score": 0, "desc": ""}
    body1 = r1["open"] - r1["close"]
    if body1 / r1["open"] * 100 < 2:
        return {"found": False, "score": 0, "desc": ""}
    # 第二天小实体完全包含在前日实体内
    body2 = abs(r2["close"] - r2["open"])
    if body2 >= body1:
        return {"found": False, "score": 0, "desc": ""}
    if r2["high"] > r1["open"] or r2["low"] < r1["close"]:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": 8, "desc": "🤰 看涨Harami(底部反转)"}

# ═══════════════════════════════════════════
#  六、图表形态类
# ═══════════════════════════════════════════

def detect_double_top(records, lookback=60, tolerance=0.03):
    """双顶/M顶: 两次涨至相近高点(价差≤3%), 颈线=两高点间最低价, 跌破确认"""
    if len(records) < 50:
        return {"found": False, "score": 0, "desc": ""}
    highs = [r["high"] for r in records[-lookback:]]
    lows = [r["low"] for r in records[-lookback:]]
    n = len(highs)
    if n < 30:
        return {"found": False, "score": 0, "desc": ""}

    # 找局部高点
    max_highs = []
    for i in range(2, n - 2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
            highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
            max_highs.append((i, highs[i]))

    if len(max_highs) < 2:
        return {"found": False, "score": 0, "desc": ""}

    p1 = max_highs[-2]
    p2 = max_highs[-1]
    diff = abs(p2[1] - p1[1]) / max(p1[1], 0.01)
    if diff > tolerance:
        return {"found": False, "score": 0, "desc": ""}

    # 颈线 = 两高点间最低价
    mid_low = min(lows[p1[0]+1:p2[0]]) if p2[0] > p1[0]+1 else min(lows[p1[0]:p2[0]+1])
    peak_high = max(p1[1], p2[1])
    cur_price = records[-1]["close"]

    below_neck = cur_price < mid_low
    score = -15 if below_neck else -10
    desc = ("❌ M顶跌破确认" if below_neck else "⚠️ M顶雏形") + f"(颈线{mid_low:.2f})"
    return {"found": True, "score": score, "desc": desc}

def detect_ascending_triangle(records, lookback=60):
    """上升三角形: 水平阻力+上升支撑, 至少2次触及上下线"""
    if len(records) < 40:
        return {"found": False, "score": 0, "desc": ""}
    highs = [r["high"] for r in records[-lookback:]]
    lows = [r["low"] for r in records[-lookback:]]
    n = len(highs)
    if n < 20:
        return {"found": False, "score": 0, "desc": ""}

    # 水平阻力线: 找至少2次触及相近高点(价差≤2%)
    max_highs = []
    for i in range(2, n - 2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
            highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
            max_highs.append((i, highs[i]))
    if len(max_highs) < 2:
        return {"found": False, "score": 0, "desc": ""}

    # 阻力线水平: 前两个高点价差≤2%
    p1, p2 = max_highs[-2], max_highs[-1]
    resistance = max(p1[1], p2[1])
    if abs(p1[1] - p2[1]) / resistance > 0.02:
        return {"found": False, "score": 0, "desc": ""}

    # 上升支撑: 低点逐步抬高
    min_lows = []
    for i in range(2, n - 2):
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and
            lows[i] <= lows[i+1] and lows[i] <= lows[i+2]):
            min_lows.append((i, lows[i]))
    if len(min_lows) < 2:
        return {"found": False, "score": 0, "desc": ""}

    # 后一个低点高于前一个
    l1, l2 = min_lows[-2], min_lows[-1]
    if l2[1] <= l1[1]:
        return {"found": False, "score": 0, "desc": ""}

    cur_price = records[-1]["close"]
    near_resistance = abs(cur_price - resistance) / resistance < 0.03
    score = 12 if near_resistance else 8
    desc = f"📐 上升三角形(阻力{resistance:.2f})"
    return {"found": True, "score": score, "desc": desc}

# ═══════════════════════════════════════════
#  七、趋势通道类
# ═══════════════════════════════════════════

def detect_ascending_channel(records, lookback=60):
    """上升通道: 两条向上平行线, 至少2个抬高低点+2个抬高高点"""
    if len(records) < 40:
        return {"found": False, "score": 0, "desc": ""}
    highs = [r["high"] for r in records[-lookback:]]
    lows = [r["low"] for r in records[-lookback:]]
    n = len(highs)
    if n < 20:
        return {"found": False, "score": 0, "desc": ""}

    # 找局部高点和低点
    max_highs = []
    for i in range(2, n - 2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
            highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
            max_highs.append((i, highs[i]))

    min_lows = []
    for i in range(2, n - 2):
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and
            lows[i] <= lows[i+1] and lows[i] <= lows[i+2]):
            min_lows.append((i, lows[i]))

    if len(max_highs) < 2 or len(min_lows) < 2:
        return {"found": False, "score": 0, "desc": ""}

    # 高点抬高
    h1, h2 = max_highs[-2], max_highs[-1]
    if h2[1] <= h1[1]:
        return {"found": False, "score": 0, "desc": ""}

    # 低点抬高
    l1, l2 = min_lows[-2], min_lows[-1]
    if l2[1] <= l1[1]:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": 10, "desc": "📈 上升通道"}

def detect_descending_channel(records, lookback=60):
    """下降通道: 两条向下平行线, 至少2个降低高点+2个降低低点"""
    if len(records) < 40:
        return {"found": False, "score": 0, "desc": ""}
    highs = [r["high"] for r in records[-lookback:]]
    lows = [r["low"] for r in records[-lookback:]]
    n = len(highs)
    if n < 20:
        return {"found": False, "score": 0, "desc": ""}

    # 找局部高点和低点
    max_highs = []
    for i in range(2, n - 2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
            highs[i] >= highs[i+1] and highs[i] >= highs[i+2]):
            max_highs.append((i, highs[i]))

    min_lows = []
    for i in range(2, n - 2):
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and
            lows[i] <= lows[i+1] and lows[i] <= lows[i+2]):
            min_lows.append((i, lows[i]))

    if len(max_highs) < 2 or len(min_lows) < 2:
        return {"found": False, "score": 0, "desc": ""}

    # 高点降低
    h1, h2 = max_highs[-2], max_highs[-1]
    if h2[1] >= h1[1]:
        return {"found": False, "score": 0, "desc": ""}

    # 低点降低
    l1, l2 = min_lows[-2], min_lows[-1]
    if l2[1] >= l1[1]:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": -10, "desc": "📉 下降通道"}

def detect_box_range(records, lookback=60):
    """箱体震荡: 60日波幅<15%, 收盘偏离MA20<5%, MA接近水平"""
    if len(records) < 60:
        return {"found": False, "score": 0, "desc": ""}
    closes = [r["close"] for r in records[-lookback:]]
    highs = [r["high"] for r in records[-lookback:]]
    lows = [r["low"] for r in records[-lookback:]]
    n = len(closes)

    # 60日波幅<15%
    period_high = max(highs)
    period_low = min(lows)
    amplitude = (period_high - period_low) / period_low * 100
    if amplitude >= 15:
        return {"found": False, "score": 0, "desc": ""}

    # MA20接近水平: 最近5日MA20变化率<2%
    ma20_vals = []
    for i in range(n - 5, n):
        if i >= 19:
            ma20_vals.append(sum(closes[i-19:i+1]) / 20)
    if len(ma20_vals) < 2:
        return {"found": False, "score": 0, "desc": ""}
    ma20_change = abs(ma20_vals[-1] - ma20_vals[0]) / ma20_vals[0] * 100
    if ma20_change >= 2:
        return {"found": False, "score": 0, "desc": ""}

    # 收盘偏离MA20<5%
    ma20 = sum(closes[-20:]) / 20
    cur_close = closes[-1]
    deviation = abs(cur_close - ma20) / ma20 * 100
    if deviation >= 5:
        return {"found": False, "score": 0, "desc": ""}

    return {"found": True, "score": 5, "desc": f"📦 箱体震荡(波幅{amplitude:.1f}%)"}

# ═══════════════════════════════════════════
#  八、L3 综合形态（威科夫/欧奈尔/圆弧）
# ═══════════════════════════════════════════

def _find_local_extrema(highs, lows, window=2):
    """找局部高点和低点索引"""
    n = len(highs)
    max_idxs = []
    min_idxs = []
    for i in range(window, n - window):
        is_max = all(highs[i] >= highs[i - j] for j in range(1, window + 1)) and \
                 all(highs[i] >= highs[i + j] for j in range(1, window + 1))
        is_min = all(lows[i] <= lows[i - j] for j in range(1, window + 1)) and \
                 all(lows[i] <= lows[i + j] for j in range(1, window + 1))
        if is_max:
            max_idxs.append(i)
        if is_min:
            min_idxs.append(i)
    return max_idxs, min_idxs


# @deprecated: 威科夫吸筹门禁FAIL（n=138 win=62.5%但pl=0.89; 优质子集n=47<100），已归档。
# 实情: 仍是「观察项」且仍执行 — identify_all_patterns 与生产 integrated_picker.py 均在调用(非摘除)。
def detect_wyckoff_accumulation(records, lookback=90):    # [观察项 2026-09-06] A股实证失效（胜率<40%），仍执行(非摘除)

    """威科夫吸筹形态 (Wyckoff Accumulation)

    识别威科夫吸筹结构，分两阶段：
    1. 宽松初筛：识别可能的吸筹区间
    2. 质量筛选：Spring假跌破 + 量价配合 + 位置过滤

    Wyckoff五阶段：
    - PS: 降价抛售（下跌趋势）
    - SC: 支撑测试（缩量企稳）
    - ST: 二次测试（确认支撑）
    - AR: 自动反弹（放量回升）
    - SOS+Spring: 突破+洗盘确认
    """
    if len(records) < lookback:
        return {"found": False, "score": 0, "desc": ""}

    tail = records[-lookback:]
    closes = [r["close"] for r in tail]
    highs = [r["high"] for r in tail]
    lows = [r["low"] for r in tail]
    vols = [r["volume"] for r in tail]
    n = len(closes)

    # ═══════════════════════════════════════════
    # 阶段一：宽松初筛 - 识别可能的吸筹区间
    # ═══════════════════════════════════════════

    # 1. 趋势检查：早期价格低于近期价格（从下跌转入横盘/反弹）
    early_ma = sum(closes[:25]) / 25 if n >= 25 else sum(closes[:n//3]) / (n//3)
    late_ma = sum(closes[-20:]) / 20
    if early_ma >= late_ma * 1.05:  # 放宽到5%
        return {"found": False, "score": 0, "desc": ""}

    # 2. 找区间边界
    max_idxs, min_idxs = _find_local_extrema(highs, lows, window=2)

    # 取最近25日的高点和低点
    recent_highs = [(i, highs[i]) for i in max_idxs if i >= n - 30][-4:]
    recent_lows = [(i, lows[i]) for i in min_idxs if i >= n - 30][-4:]

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return {"found": False, "score": 0, "desc": ""}

    resist = sum(h[1] for h in recent_highs) / len(recent_highs)
    support = sum(l[1] for l in recent_lows) / len(recent_lows)

    if resist <= support:
        return {"found": False, "score": 0, "desc": ""}

    range_pct = (resist - support) / support * 100
    if range_pct > 18 or range_pct < 2:
        return {"found": False, "score": 0, "desc": ""}

    # 3. Spring检测（宽松）：假跌破支撑后收回
    spring_found = False
    spring_idx = None
    spring_lookback = min(25, n - 5)
    for i in range(n - spring_lookback, n - 3):
        if lows[i] < support * 0.97:
            for j in range(i + 2, min(i + 6, n)):
                if highs[j] > support * 1.01 and lows[j] > support * 0.97:
                    spring_found = True
                    spring_idx = i
                    break
            if spring_found:
                break

    # 4. 当前位置：价格应在阻力附近（准备突破）
    cur_close = closes[-1]
    dist_to_resist = (resist - cur_close) / cur_close * 100 if cur_close > 0 else 999

    # ═══════════════════════════════════════════
    # 阶段二：质量筛选 - 必须满足的核心条件
    # ═══════════════════════════════════════════

    # 必需条件1：Spring必须存在（核心特征）
    if not spring_found:
        return {"found": False, "score": 0, "desc": ""}

    # 必需条件2：价格在阻力下方不远处（准备突破）
    if dist_to_resist > 5:  # 太远不算
        return {"found": False, "score": 0, "desc": ""}

    # 必需条件3：成交量未异常放大（排除已大幅拉升）
    vol_5d = sum(vols[-5:]) / 5
    vol_15d = sum(vols[-15:-5]) / 10 if n >= 15 else vol_5d
    vol_ratio = vol_5d / vol_15d if vol_15d > 0 else 1.0
    if vol_ratio > 2.0:  # 已大幅放量，可能已过突破点
        return {"found": False, "score": 0, "desc": ""}

    # 计算辅助指标
    lowest_in_range = min(lows[-25:]) if n >= 25 else min(lows)
    recovery = (cur_close - lowest_in_range) / lowest_in_range * 100 if lowest_in_range > 0 else 0
    price_pos = (cur_close - support) / (resist - support) * 100 if resist > support else 50

    # ═══════════════════════════════════════════
    # 评分系统
    # ═══════════════════════════════════════════
    score = 20  # Spring基础分

    # 距离阻力越近分越高
    if dist_to_resist < 1:
        score += 10  # 几乎突破
    elif dist_to_resist < 2:
        score += 7
    elif dist_to_resist < 3:
        score += 4
    else:
        score += 1

    # 回升幅度加分
    if recovery > 15:
        score += 5
    elif recovery > 10:
        score += 3

    # 价格位置加分（在区间上三分之一）
    if price_pos > 70:
        score += 5
    elif price_pos > 60:
        score += 3

    # 成交量温和（非异常放量）
    if 0.7 <= vol_ratio <= 1.3:
        score += 3

    # 构建描述
    desc_parts = ["✅ 威科夫吸筹确认"] if score >= 30 else ["⚠️ 威科夫吸筹雏形"]
    desc_parts.append("(含Spring洗盘)")
    desc_parts.append(f"(阻力{resist:.2f}/支撑{support:.2f},回升{recovery:.1f}%)")
    desc = "".join(desc_parts)

    return {
        "found": True,
        "score": score,
        "desc": desc,
        "_debug": {  # 调试信息，不影响主逻辑
            "dist_to_resist": round(dist_to_resist, 2),
            "price_pos": round(price_pos, 1),
            "recovery": round(recovery, 1),
            "vol_ratio": round(vol_ratio, 2)
        }
    }


def detect_wyckoff_distribution(records, lookback=90):    # [观察项 2026-09-06] A股实证失效（胜率<40%），仍执行(非摘除)

    """威科夫派发形态 (Wyckoff Distribution)
    
    威科夫派发是吸筹的反向过程：
    1. 前期上涨趋势（MA5 > MA20）
    2. 进入横盘区间（PS+UC+ST+AR 阶段）
    3. Upthrust/诱多：区间内一次性冲高后快速回落
    4. CR (Buying Climax) / SOS 反向信号
    5. 跌破支撑确认
    """
    if len(records) < lookback:
        return {"found": False, "score": 0, "desc": ""}
    
    tail = records[-lookback:]
    closes = [r["close"] for r in tail]
    highs = [r["high"] for r in tail]
    lows = [r["low"] for r in tail]
    n = len(closes)
    
    # 1. 前期上涨趋势
    pre_ma5 = sum(closes[:10]) / 10
    pre_ma20 = sum(closes[:20]) / 20 if n >= 20 else pre_ma5
    if pre_ma5 <= pre_ma20:
        return {"found": False, "score": 0, "desc": ""}
    
    # 2. 找区间
    max_idxs, min_idxs = _find_local_extrema(highs, lows, window=3)
    
    recent_highs = [(i, highs[i]) for i in max_idxs if i >= n - 40][-5:]
    recent_lows = [(i, lows[i]) for i in min_idxs if i >= n - 40][-5:]
    
    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return {"found": False, "score": 0, "desc": ""}
    
    resist = sum(h[1] for h in recent_highs) / len(recent_highs)
    support = sum(l[1] for l in recent_lows) / len(recent_lows)
    
    if resist <= support:
        return {"found": False, "score": 0, "desc": ""}
    
    range_pct = (resist - support) / support * 100
    if range_pct > 15:
        return {"found": False, "score": 0, "desc": ""}
    
    # 3. Upthrust检测：近期有一次冲高到阻力附近后回落
    last30_start = n - 30
    if last30_start < 0:
        last30_start = 0
    last30_lows = lows[last30_start:]
    last30_highs = highs[last30_start:]
    
    upthrust_idx = None
    for i in range(len(last30_highs)):
        if last30_highs[i] > resist * 0.98:
            for j in range(i + 1, min(i + 4, len(last30_lows))):
                if last30_lows[j] < resist * 0.96:
                    upthrust_idx = i
                    break
            if upthrust_idx is not None:
                break
    
    # 4. 跌破支撑确认
    cur_close = closes[-1]
    below_support = cur_close < support * 1.02
    cur_price_near_support = cur_close <= support * 1.05
    
    # 5. 价格已从区间顶部回落
    highest_in_range = max(highs[-30:]) if n >= 30 else max(highs)
    decline = (highest_in_range - cur_close) / highest_in_range * 100 if highest_in_range > 0 else 0
    
    if below_support and decline > 5:
        score = -20
        desc = "❌ 威科夫派发确认(跌破支撑)"
        if upthrust_idx is not None:
            desc += "(含Upthrust诱多)"
    elif cur_price_near_support or decline > 3:
        score = -15
        desc = "⚠️ 威科夫派发雏形(靠近支撑)"
    else:
        score = -10
        desc = "📐 威科夫派发整理中"
    
    return {"found": True, "score": score, "desc": desc + f"(阻力{resist:.2f}/支撑{support:.2f},回落{decline:.1f}%)"}


def detect_cup_handle(records, lookback=80):    # [DEPRECATED 2026-09-06] A股实证失效（胜率<40%），已降级为观察项

    """欧奈尔杯柄形态 (O'Neil Cup & Handle) — Kimi v2.0 重写版

    根据《笑傲股市》+ Kimi审查建议参数（2026-09-04）：
    - 杯体深度: 20-35%（相对前期高点，放宽至15%当n<100）
    - 杯体时间: 35-75交易日（7-15周）
    - 柄部深度: 5-15%（从杯口回调）
    - 柄部时间: 5-20交易日（1-4周）
    - 突破条件: 收盘价突破柄部上沿 + 成交量 > 50日均量 × 120%

    门禁目标: 胜率≥55% + 盈亏比≥1.5 + n≥100
    """
    if len(records) < lookback:
        return {"found": False, "score": 0, "desc": "", "direction": "bull"}

    tail = records[-lookback:]
    closes = [r["close"] for r in tail]
    highs = [r["high"] for r in tail]
    lows = [r["low"] for r in tail]
    vols = [r["volume"] for r in tail]
    n = len(closes)

    # ── 1. 趋势过滤：MA5 > MA20 且 MA20 向上 ──────────────────────────
    ma5 = sum(closes[-5:]) / 5
    ma20 = sum(closes[-20:]) / 20
    ma20_prev = sum(closes[-21:-1]) / 20 if n >= 21 else ma20
    if ma5 <= ma20 or ma20 <= ma20_prev * 0.98:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 2. 寻找杯底（在较宽范围内搜索，确保捕捉完整杯体）─────────────────
    # 搜索范围：从 n-100 到 n-20，给杯体足够空间
    search_start = max(0, n - 100)
    search_end = n - 20                    # 杯底不能太近（留柄部空间）
    if search_end <= search_start + 10:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    sub_lows = lows[search_start:search_end]
    if len(sub_lows) < 10:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    min_in_window = min(sub_lows)
    min_offset = sub_lows.index(min_in_window)
    cup_bottom_idx = search_start + min_offset
    cup_bottom = min_in_window

    # 杯底不能太偏右（需留足够柄部空间）
    right_span = n - cup_bottom_idx
    if right_span < 15:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 3. 杯左沿：左侧高点（前期高点）───────────────────────────────────
    left_end = cup_bottom_idx
    if left_end < 10:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}
    left_range = min(left_end, 50)          # 从前50日内找左沿高点
    cup_left = max(closes[:left_range])
    if cup_left <= 0:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 4. 杯深 & 杯体时间 ─────────────────────────────────────────────
    cup_depth = (cup_left - cup_bottom) / cup_left * 100

    # 杯体时间：从左沿高点位置到杯底的距离（下降段）+ 杯底到当前位置（上升段）
    cup_start_idx = left_range              # 左沿大致位置
    cup_body_days = cup_bottom_idx - cup_start_idx  # 下降段天数
    # 总杯体时间 = 下降段 + 上升段（至少35日）
    total_cup_span = n - cup_start_idx
    if total_cup_span < 35:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # 杯深门槛：默认20-35%，若样本量不足（n<100）放宽至15%
    depth_lo = 15.0 if n < 100 else 20.0
    depth_hi = 35.0
    if cup_depth < depth_lo or cup_depth > depth_hi:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # 杯体时间上限：不超过80日
    if total_cup_span > 80:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 5. 杯右沿：取杯底右侧高点作为杯口阻力 ────────────────────────────
    # 杯口定义为右沿高点（接近cup_left），容差5%
    right_start = cup_bottom_idx
    cup_right = max(closes[right_start:]) if right_start < n else cup_left
    if cup_right < cup_left * 0.85:
        # 右沿明显低于左沿，形态不完整
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 6. 柄部区域：取最近5-20日 ────────────────────────────────────────
    handle_len = min(20, right_span)
    if handle_len < 5:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}
    handle_start = n - handle_len
    handle_closes = closes[handle_start:]
    handle_highs = highs[handle_start:]
    handle_lows = lows[handle_start:]
    handle_vols = vols[handle_start:]

    # ── 7. 柄部回调幅度：5-12%（相对杯口）───────────────────────────────
    handle_max = max(handle_highs)
    handle_min = min(handle_lows)
    handle_drop = (handle_max - handle_min) / handle_max * 100 if handle_max > 0 else 0
    if handle_drop < 5 or handle_drop > 12:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 8. 柄部向右下倾斜（后半段均价低于前半段）─────────────────────────
    h_mid = len(handle_closes) // 2
    if h_mid >= 1:
        front_avg = sum(handle_closes[:h_mid]) / h_mid
        back_avg = sum(handle_closes[h_mid:]) / len(handle_closes[h_mid:])
        if back_avg > front_avg * 1.05:   # 允许5%噪音，不允许明显上翘
            return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 9. 突破确认：收盘价突破柄部上沿 + 成交量放大 ─────────────────────
    # 突破参考柄部最高点（非杯口），与原版逻辑一致
    breakout_price = closes[-1] > handle_max * 0.98  # 收盘价接近或突破柄部上沿（2%内）
    if not breakout_price:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # 成交量要求：当日量 > 50日均量 × 130%（Kimi建议值）
    vol_50ma = sum(vols[-50:]) / 50 if len(vols) >= 50 else sum(vols) / len(vols)
    vol_ratio = vols[-1] / vol_50ma if vol_50ma > 0 else 0
    vol_confirm = vol_ratio >= 1.30
    if not vol_confirm:
        return {"found": False, "name": "欧奈尔杯柄", "score": 0, "desc": "", "direction": "bull"}

    # ── 10. 评分 ──────────────────────────────────────────────────────────
    score = 25  # 基础分25（略高于原版20）
    # 额外加分：杯深居中（25-30%最优）
    if 25 <= cup_depth <= 30:
        score += 3
    if 20 <= cup_depth <= 35:
        score += 2
    # 量比加分
    if vol_ratio >= 1.5:
        score += 2
    elif vol_ratio >= 1.3:
        score += 1

    depth_flag = "(杯深放宽)" if n < 100 else ""
    desc = f"📐 欧奈尔杯柄突破{depth_flag}杯深{cup_depth:.1f}%量比{vol_ratio:.0%}"

    return {
        "found": True,
        "name": "欧奈尔杯柄",
        "score": score,
        "desc": desc,
        "direction": "bull",
        "cup_depth": cup_depth,
        "handle_drop": handle_drop,
        "vol_ratio": vol_ratio,
    }



# @deprecated: 圆弧底在A股表现为反向指标（胜率39.12% FAIL门禁），已归档。保留代码但不执行。
def detect_rounding_bottom(records, lookback=80, sh_records=None):    # [DEPRECATED 2026-09-06] A股实证失效（胜率<40%），已降级为观察项

    """圆弧底形态 (Rounding Bottom) - Kimi参数版 (2026-09-04)

    特征：
    - 价格呈U形圆弧，从下跌渐缓转为上涨渐急
    - 成交量呈圆弧状：下跌时缩量，上涨时放量
    - 深度: 20-40%（相对前期高点）
    - 时间: 40-100交易日
    - 底部量: < 60日均量 × 70%
    - 突破确认: 收盘价突破颈线 + 成交量 > 60日均量 × 150%
    - 大盘过滤: 环境门开启时（上证>MA250）才计入统计

    Args:
        records: 股票日线记录列表
        lookback: 回溯窗口（默认80日）
        sh_records: 上证指数记录（可选，用于环境门过滤）
    """
    if len(records) < lookback:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    tail = records[-lookback:]
    closes = [r["close"] for r in tail]
    highs = [r["high"] for r in tail]
    lows = [r["low"] for r in tail]
    vols = [r["volume"] for r in tail]
    n = len(closes)

    # 1. 找圆弧最低点
    min_idx = lows.index(min(lows))
    # 底部位置应在30%-85%之间（圆弧底部特征，避免两端极端值）
    if min_idx < n * 0.3 or min_idx > n * 0.85:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 2. 时间窗口检查：圆弧形成时间应在40-100日
    arc_duration = n
    if arc_duration < 40 or arc_duration > 100:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 3. 圆弧判定：用分段线性斜率变化判断U形
    left_closes = closes[:min_idx + 1]
    right_closes = closes[min_idx:]

    if len(left_closes) < 15 or len(right_closes) < 15:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 左侧斜率：前1/3段 vs 后1/3段（应减速）
    left_changes = [(left_closes[i] - left_closes[i-1]) / left_closes[i-1]
                     for i in range(1, len(left_closes))]
    left_third = len(left_changes) // 3
    if left_third < 3:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    early_drop = sum(left_changes[:left_third]) / left_third
    late_drop = sum(left_changes[-left_third:]) / left_third

    # 左侧应减速：早期跌幅更大（更负）
    if early_drop > late_drop:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 右侧斜率：前1/3段 vs 后1/3段（应加速）
    right_changes = [(right_closes[i] - right_closes[i-1]) / right_closes[i-1]
                      for i in range(1, len(right_closes))]
    right_third = len(right_changes) // 3
    if right_third < 3:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    early_rise = sum(right_changes[:right_third]) / right_third
    late_rise = sum(right_changes[-right_third:]) / right_third

    # 右侧加速：后期涨幅更大
    if late_rise <= early_rise:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 4. 深度检查：20-40%（相对前期高点）
    round_top = max(closes[:min_idx])  # 圆弧起点（前期高点）
    cup_bottom = min(lows)
    arc_height = round_top - cup_bottom

    if arc_height <= 0:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    depth_pct = arc_height / round_top * 100
    if depth_pct < 20 or depth_pct > 40:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 5. 底部成交量检查：< 60日均量 × 70%
    vol_ma60 = sum(vols) / n  # 使用实际数据长度作为均线
    # 底部附近的成交量（最低点前后各3日）
    bottom_window = min(3, min_idx, n - min_idx - 1)
    bottom_vol_start = max(0, min_idx - bottom_window)
    bottom_vol_end = min(n, min_idx + bottom_window + 1)
    bottom_vols = vols[bottom_vol_start:bottom_vol_end]
    bottom_avg_vol = sum(bottom_vols) / len(bottom_vols) if bottom_vols else 0

    if bottom_avg_vol > vol_ma60 * 0.7:
        return {"found": False, "score": 0, "desc": "", "market_gate": None}

    # 6. 大盘过滤：环境门开启时（上证>MA250）才计入统计
    market_gate_open = None
    if sh_records and len(sh_records) >= 250:
        sh_closes = [r["close"] for r in sh_records]
        ma250 = sum(sh_closes[-250:]) / 250
        market_gate_open = sh_closes[-1] > ma250
    else:
        # 无大盘数据时，默认放行（不阻断）
        market_gate_open = True

    if not market_gate_open:
        return {"found": False, "score": 0, "desc": "⚠️ 环境门关闭（上证<MA250）", "market_gate": False}

    # 7. 突破确认：收盘价突破颈线 + 成交量 > 60日均量 × 150%
    cur_close = closes[-1]
    neckline = round_top  # 颈线即圆弧起点高点

    # 检查近期成交量是否放大
    recent_vol = sum(vols[-5:]) / 5 if n >= 5 else vols[-1]
    vol_expand = recent_vol > vol_ma60 * 1.5

    # 突破判定：收盘价接近或已突破颈线
    above_neckline = cur_close > neckline * 0.97

    # 8. 评分
    if above_neckline and vol_expand:
        score = 25
        desc = f"✅ 圆弧底突破确认(深{depth_pct:.1f}%·弧长{n}日·量扩{recent_vol/vol_ma60:.1f}x)"
    elif above_neckline:
        score = 20
        desc = f"⚠️ 圆弧底接近突破(深{depth_pct:.1f}%)，等放量确认"
    elif cur_close > cup_bottom * 1.1:
        score = 15
        desc = f"📐 圆弧底雏形(已回升{cur_close/cup_bottom*100-100:.1f}%)"
    else:
        score = 10
        desc = f"📐 圆弧底整理中(底部{cup_bottom:.2f})"

    return {
        "found": True, "score": score, "desc": desc, "market_gate": True,
        "depth_pct": depth_pct, "arc_duration": arc_duration,
        "vol_ratio": bottom_avg_vol / vol_ma60 if vol_ma60 > 0 else 0
    }


def detect_rounding_top(records, lookback=80):
    """圆弧顶形态 (Rounding Top)
    
    圆弧底的反转版本：
    - 价格呈倒U形，从上涨渐缓转为下跌渐急
    - 成交量：上涨时缩量，下跌时放量
    - 形成时间通常≥60日
    - 跌破圆弧下沿时确认
    """
    if len(records) < lookback:
        return {"found": False, "score": 0, "desc": ""}
    
    tail = records[-lookback:]
    closes = [r["close"] for r in tail]
    highs = [r["high"] for r in tail]
    lows = [r["low"] for r in tail]
    vols = [r["volume"] for r in tail]
    n = len(closes)
    
    # 1. 找圆弧最高点
    max_idx = highs.index(max(highs))
    if max_idx < n * 0.15 or max_idx > n * 0.85:
        return {"found": False, "score": 0, "desc": ""}
    
    # 2. 圆弧判定：倒U形
    left_closes = closes[:max_idx + 1]
    right_closes = closes[max_idx:]
    
    if len(left_closes) < 15 or len(right_closes) < 15:
        return {"found": False, "score": 0, "desc": ""}
    
    # 左侧：上涨减速
    left_changes = [(left_closes[i] - left_closes[i-1]) / left_closes[i-1] 
                     for i in range(1, len(left_closes))]
    right_changes = [(right_closes[i] - right_closes[i-1]) / right_closes[i-1] 
                      for i in range(1, len(right_closes))]
    
    left_third = len(left_changes) // 3
    if left_third < 3:
        return {"found": False, "score": 0, "desc": ""}
    
    early_rise = sum(left_changes[:left_third]) / left_third
    late_rise = sum(left_changes[-left_third:]) / left_third
    
    # 左侧减速：早期涨幅 > 后期涨幅
    if early_rise < late_rise:
        return {"found": False, "score": 0, "desc": ""}
    
    right_third = len(right_changes) // 3
    if right_third < 3:
        return {"found": False, "score": 0, "desc": ""}
    
    early_drop = sum(right_changes[:right_third]) / right_third
    late_drop = sum(right_changes[-right_third:]) / right_third
    
    # 右侧加速下跌：后期跌幅更大
    if late_drop <= early_drop:
        return {"found": False, "score": 0, "desc": ""}
    
    # 3. 成交量配合：上涨缩量，下跌放量
    left_vols = vols[:max_idx + 1]
    right_vols = vols[max_idx:]
    
    left_vol_early = sum(left_vols[:len(left_vols)//3]) / (len(left_vols)//3) if len(left_vols) >= 3 else 0
    left_vol_late = sum(left_vols[-len(left_vols)//3:]) / (len(left_vols)//3) if len(left_vols) >= 3 else 0
    right_vol_early = sum(right_vols[:len(right_vols)//3]) / (len(right_vols)//3) if len(right_vols) >= 3 else 0
    right_vol_late = sum(right_vols[-len(right_vols)//3:]) / (len(right_vols)//3) if len(right_vols) >= 3 else 0
    
    # 4. 当前状态
    cur_close = closes[-1]
    round_bottom = min(closes[max_idx:]) if max_idx < n else closes[-1]
    peak = max(highs)
    
    if peak <= 0:
        return {"found": False, "score": 0, "desc": ""}
    
    above_peak = cur_close < peak * 0.97
    below_round = cur_close < round_bottom * 1.05
    
    # 5. 评分
    if below_round and right_vol_late > right_vol_early * 0.7:
        score = -20
        desc = f"❌ 圆弧顶跌破确认(弧高{(peak-round_bottom)/peak*100:.1f}%)"
    elif cur_close < peak * 0.95:
        score = -15
        desc = f"⚠️ 圆弧顶雏形(已从高点回落{(peak-cur_close)/peak*100:.1f}%)"
    else:
        score = -10
        desc = f"📐 圆弧顶整理中(顶部{peak:.2f})"
    
    return {"found": True, "score": score, "desc": desc}


# ═══════════════════════════════════════════
#  综合形态检测
# ═══════════════════════════════════════════

def identify_all_patterns(records):
    """运行所有形态识别，返回最佳匹配"""
    if not records or len(records) < 30:
        return {"found": False, "pattern": "", "score": 0, "desc": "数据不足", "all": []}
    
    checks = [
        ("W底", detect_double_bottom(records)),
        ("头肩底", detect_head_shoulders_bottom(records)),
        ("V底", detect_v_bottom(records)),
        ("早晨之星", detect_morning_star(records)),
        ("锤头线", detect_hammer(records)),
        ("看涨吞没", detect_bullish_engulfing(records)),
        ("红三兵", detect_three_white_soldiers(records)),
        ("MA金叉", detect_ma_golden_cross(records)),
        ("多头排列", detect_ma_bullish_alignment(records)),
        ("均线粘合", detect_ma_convergence(records)),
        ("量价齐升", detect_vol_price_rising(records)),
        ("缩量企稳", detect_vol_shrink_pullback(records)),
        # 看跌K线形态
        ("十字星", detect_doji(records)),
        ("上吊线", detect_hanging_man(records)),
        ("射击之星", detect_shooting_star(records)),
        ("看跌吞没", detect_bearish_engulfing(records)),
        ("倒锤形", detect_inverse_hammer(records)),
        ("刺穿线", detect_piercing_line(records)),
        ("看涨Harami", detect_bullish_harami(records)),
        # 图表形态
        ("双顶", detect_double_top(records)),
        ("上升三角形", detect_ascending_triangle(records)),
        # 趋势通道
        ("上升通道", detect_ascending_channel(records)),
        ("下降通道", detect_descending_channel(records)),
        ("箱体震荡", detect_box_range(records)),
        # L3 综合形态
        ("威科夫吸筹", detect_wyckoff_accumulation(records)),
        ("威科夫派发", detect_wyckoff_distribution(records)),
        ("欧奈尔杯柄", detect_cup_handle(records)),
        ("圆弧底", detect_rounding_bottom(records)),
        ("圆弧顶", detect_rounding_top(records)),
    ]
    
    found = [(name, r) for name, r in checks if r["found"]]
    if not found:
        return {"found": False, "pattern": "", "score": 0, "desc": "无明显形态", "all": []}

    # 选择得分最高的（负分表示陷阱）
    best = max(found, key=lambda x: x[1]["score"])

    # 方向推断：根据形态名称自动判断bull/bear/neutral
    BULL_PATTERNS = {"早晨之星", "锤头线", "看涨吞没", "红三兵", "MA金叉", "多头排列",
                     "量价齐升", "缩量企稳", "刺穿线", "看涨Harami", "V底", "双底", "头肩底",
                     "上升三角形", "圆弧底", "欧奈尔杯柄", "威科夫吸筹"}
    BEARISH_PATTERNS = {"十字星", "上吊线", "射击之星", "看跌吞没", "倒锤形",
                        "双顶", "下降通道", "圆弧顶", "威科夫派发", "下降三角形"}

    # 构建带direction的pattern列表（用于night_integrate过滤）
    all_patterns = []
    for name, r in found:
        direction = r.get("direction", "neutral")
        if direction == "neutral":
            # 根据名称推断
            if name in BULL_PATTERNS:
                direction = "bull"
            elif name in BEARISH_PATTERNS:
                direction = "bear"
        all_patterns.append({"name": name, "desc": r["desc"], "direction": direction})

    return {
        "found": True,
        "pattern": best[0],
        "score": best[1]["score"],
        "desc": best[1]["desc"],
        "total": len(found),
        "patterns": all_patterns,
    }

if __name__ == "__main__":
    # 自测
    sys.path.insert(0, r"D:\open code\zhuanqian")
    from core.pipeline.tdx_core import get_tdx_data
    for code in ["sh600519", "sz002415", "sh600036"]:
        recs = get_tdx_data(code, 120)
        if recs:
            p = identify_all_patterns(recs)
            print(f"{code}: {'✅ '+p['pattern']+'('+str(p['score'])+')' if p['found'] else '❌ 无形态'} | {p['desc'][:60]}")
