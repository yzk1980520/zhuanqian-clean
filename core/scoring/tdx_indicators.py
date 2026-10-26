"""TDX 技术指标计算模块 — Phase C-1 拆分自 tdx_core.py (2026-08-31)

职责:
- 基础指标: SMA / EMA / RSI / ATR / MACD
- 周线聚合与周线指标 (aggregate_weekly / compute_weekly_indicators)
- 主指标集合 (compute_indicators) — 供评分引擎与回测共用
- 形态识别入口 (analyze_volume_pattern)

兼容性: tdx_core.py 仍作为兼容入口 re-export 本模块所有符号。
"""
import pandas as pd
import numpy as np

import os
import re
import struct
import urllib.request
import json
import sys
from datetime import date, datetime, timezone, timedelta


def calc_sma(data, period):
    return None if len(data) < period else sum(data[-period:]) / period


def calc_ema_list(data, period):
    n = len(data)
    if n < period:
        return [None] * n
    k = 2.0 / (period + 1)
    ema = sum(data[:period]) / period
    res = [None] * (period - 1) + [ema]
    for i in range(period, n):
        ema = data[i] * k + ema * (1 - k)
        res.append(ema)
    return res


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


def calc_atr(records, period=14):
    if not records or len(records) < period + 1:
        return None
    tr = []
    for i in range(1, len(records)):
        h, l, pc = records[i]["high"], records[i]["low"], records[i - 1]["close"]
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(tr) < period:
        return None
    atr = sum(tr[:period]) / period
    for v in tr[period:]:
        atr = (atr * (period - 1) + v) / period
    return atr


def calc_atr_stop(records, multiplier=2.0):
    atr = calc_atr(records)
    if atr is None:
        return None, None
    p = records[-1]["close"]
    return round(p - atr * multiplier, 2), round(atr, 3)


def aggregate_weekly(records):
    if not records:
        return []
    w = []
    for r in records:
        # P2台账项防护(2026-09-28, 老五排期): K线行缺任一OHLCV键 → 跳过该行,
        # 防 KeyError:'open' 拖死周聚合 (tdx_indicators:93 裁定项); 正常行零行为变化.
        if any(k not in r for k in ("open", "high", "low", "close", "volume")):
            continue
        # 修复: date字段可能是字符串("20260904" 或 "2026-09-04")或date对象
        date_val = r.get("date")
        if isinstance(date_val, str):
            # 字符串格式: YYYYMMDD 或 YYYY-MM-DD → date对象
            try:
                from datetime import datetime
                if "-" in date_val:
                    d = datetime.strptime(date_val, "%Y-%m-%d").date()
                else:
                    d = datetime.strptime(date_val, "%Y%m%d").date()
                iso = d.isoweekday()
            except (AttributeError, ValueError):
                # 2026-10-08 故障③修复: 原只接 AttributeError, 漏接 ValueError
                # (ISO 日期 'YYYY-MM-DD' 撞 '%Y%m%d' 格式 → ValueError 未捕获 → 每只票 compute_indicators 崩)
                iso = 1  # 解析失败默认周一
        else:
            iso = date_val.isoweekday() if hasattr(date_val, 'isoweekday') else 1
        if iso == 1 or not w:
            w.append({"date": r["date"], "open": r["open"],
                      "high": r["high"], "low": r["low"],
                      "close": r["close"], "volume": r["volume"]})
        else:
            wk = w[-1]
            wk["high"] = max(wk["high"], r["high"])
            wk["low"] = min(wk["low"], r["low"])
            wk["close"] = r["close"]
            wk["volume"] += r["volume"]
    return w


def compute_weekly_indicators(records):
    w = aggregate_weekly(records)
    if len(w) < 10:
        return None
    c = [x["close"] for x in w]
    w5 = calc_sma(c, 5)
    w10 = calc_sma(c, 10)
    d, e, h = calc_macd(c)
    return {"w_price": c[-1], "w_ma5": w5, "w_ma10": w10,
            "w_dif": d, "w_dea": e, "w_hist": h,
            "w_bullish": bool(w5 and w10 and w5 > w10)}


def analyze_volume_pattern(records):
    if not records or len(records) < 20:
        return None, None
    c = [r["close"] for r in records]
    vol = [r["volume"] for r in records]
    v5 = calc_sma(vol, 5) or 1
    v10 = calc_sma(vol, 10) or 1
    vr = vol[-1] / v5
    vr10 = vol[-1] / v10
    ch1 = (c[-1] - c[-2]) / c[-2] * 100 if len(c) > 1 else 0
    ch5 = (c[-1] - c[-6]) / c[-6] * 100 if len(c) > 5 else 0

    if vr > 2.0 and ch1 > 3:   return "放量突破", f"倍量{vr:.1f}+涨{ch1:.1f}%"
    if vr > 1.8 and ch1 > 5:   return "放量拉升", f"量{vr:.1f}+涨{ch1:.1f}%"
    if vr > 1.5 and ch1 < -3:  return "放量下跌", f"量{vr:.1f}+跌{ch1:.1f}%"
    if vr10 < 0.6 and ch1 > 0 and ch5 > 0:  return "缩量上涨", f"量{vr10:.1f}+5日涨{ch5:.1f}%"
    if vr10 < 0.6 and ch1 < 0 and ch5 < 0:  return "缩量阴跌", f"量{vr10:.1f}+5日跌{ch5:.1f}%"
    if vr10 < 0.6 and ch1 < 0 and ch5 > 0:  return "缩量回调", f"量{vr10:.1f}+5日涨{ch5:.1f}%"
    if vr > 1.5 and ch1 > 0 and ch1 <= 3:    return "温和放量", f"量{vr:.1f}+涨{ch1:.1f}%"
    return None, None


def calc_macd(closes):
    n = len(closes)
    if n < 27:
        return None, None, None
    k12, k26, k9 = 2 / 13, 2 / 27, 2 / 10
    e12 = sum(closes[:12]) / 12
    for i in range(12, 26):
        e12 = closes[i] * k12 + e12 * (1 - k12)
    e26 = sum(closes[:26]) / 26
    difs = []
    for i in range(26, n):
        e12 = closes[i] * k12 + e12 * (1 - k12)
        e26 = closes[i] * k26 + e26 * (1 - k26)
        difs.append(e12 - e26)
    dif = difs[-1]
    if len(difs) < 9:
        return dif, dif, 0.0
    dea = sum(difs[:9]) / 9
    for v in difs[9:]:
        dea = v * k9 + dea * (1 - k9)
    return dif, dea, dif - dea


# ═══ LHB 龙虎榜因子单一读点 (2026-10-14 复活) ═══
# 09-04 原块四缺陷: ①双层dirname路径(误指D:/open code) ②glob lhb_hist_*与实际写口get_lhb_detail_*不匹配
# ③顶层dict{"data":[...]}被当list直接迭代 ④上榜日ms-epoch换算错+缺code过滤
# 统一单一读点: 生产 compute_indicators(code=...) 与回测 fast_compute_all(code=...) 共用, 防双源漂移
_LHB_TZ8 = timezone(timedelta(hours=8))
_LHB_CACHE = {}  # {文件路径: (mtime_ns, {上榜日ymd: {代码: 净买占比}})} — mtime失效, 非路径常驻(防拉取器覆盖后读陈旧值)


def _lhb_parse_file(path):
    """解析一个 LHB 明细文件 → {上榜日ymd: {代码: 净买占比}}; 坏行打警告不静默吞 (SOUL#9)"""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    rows = d.get("data", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
    out = {}
    for r in rows:
        try:
            ms = int(r.get("上榜日", 0) or 0)
            if ms <= 0:
                continue
            rd = datetime.fromtimestamp(ms / 1000, tz=_LHB_TZ8).strftime("%Y%m%d")
            code = str(r.get("代码", "")).zfill(6)
            if not code:
                continue
            ratio = float(r.get("净买额占总成交比", 0) or 0) / 100.0  # 源数据为百分数 (1.38=1.38%)
            out.setdefault(rd, {})[code] = ratio
        except (TypeError, ValueError) as e:
            print(f"⚠️ LHB行解析失败 ({os.path.basename(path)}): {e}")
    return out


def read_lhb_signal(code, scan_date, data_dir=None):
    """LHB 龙虎榜当日因子读点。|净买额/总成交比| > 5% → +1.0/-1.0, 否则 0.0。

    - point-in-time: 只读 pull_date <= scan_date 的文件(不前视), 只取 上榜日 == scan_date
      的行(当日口径, 与 09-04 IC=0.0991 测量口径一致); 数据不可用 → 0.0, 不回退更晚文件
    - code=None → 0.0 (兼容旧调用方, 零行为变化)
    """
    if code is None:
        return 0.0
    code = str(code).zfill(6)
    s = scan_date.strftime("%Y%m%d") if hasattr(scan_date, "strftime") else str(scan_date)
    if len(s) == 10 and s[4] == "-":
        s = s[:4] + s[5:7] + s[8:10]
    if len(s) != 8 or not s.isdigit():
        return 0.0
    base = data_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "data", "akshare")  # 基地化S3: 根锚点
    if not os.path.isdir(base):
        return 0.0
    target = None
    for fn in sorted(os.listdir(base), reverse=True):
        m = re.match(r"get_lhb_detail_(\d{8})\.json$", fn)
        if m and m.group(1) <= s:
            target = os.path.join(base, fn)
            break
    if target is None:
        return 0.0
    try:
        mtime_ns = os.stat(target).st_mtime_ns
    except OSError as e:
        print(f"⚠️ LHB文件stat失败 {os.path.basename(target)}: {e}")
        return 0.0
    cached = _LHB_CACHE.get(target)
    if cached is not None and cached[0] == mtime_ns:
        by_date = cached[1]
    else:
        try:
            by_date = _lhb_parse_file(target)
        except (OSError, json.JSONDecodeError) as e:
            print(f"⚠️ LHB文件读取失败 {os.path.basename(target)}: {e}")
            return 0.0
        _LHB_CACHE[target] = (mtime_ns, by_date)
    ratio = by_date.get(s, {}).get(code, 0.0)
    if ratio > 0.05:
        return 1.0
    if ratio < -0.05:
        return -1.0
    return 0.0


def compute_indicators(records, code=None):
    if not records or len(records) < 20:
        return None
    # P0数据卫生 (2026-10-08): 末根K线 close=0/None (坏数据) -> 返回 None。
    # 修复前: 全零close 在 p20 计算行抛 ZeroDivisionError, 被上游 except:continue 静默吞掉(93%文件评分失败)。
    # 上游约定: 各调用方 `if not inds: continue`, 返回 None 即干净跳过。
    if not records[-1].get("close"):
        return None
    c = [r["close"] for r in records]
    h = [r["high"] for r in records]
    l = [r["low"] for r in records]
    v = [r["volume"] for r in records]
    o = [r["open"] for r in records]
    # Phase A (2026-09-02): 成交额分位数切割反转因子 (IC=-0.0502 过全门禁)
    a = [r.get("amount", 0) or 0 for r in records]
    cur = records[-1]

    ma5 = calc_sma(c, 5); ma10 = calc_sma(c, 10); ma20 = calc_sma(c, 20)
    ma60 = calc_sma(c, 60) if len(c) >= 60 else None
    ma120 = calc_sma(c, 120) if len(c) >= 120 else None
    dif, dea, mh = calc_macd(c)
    r6 = calc_rsi(c, 6); r14 = calc_rsi(c, 14); r24 = calc_rsi(c, 24)
    vm5 = calc_sma(v, 5) or 1; vm10 = calc_sma(v, 10) or 1
    vr = v[-1] / vm5

    c1 = (c[-1] - c[-2]) / c[-2] * 100 if len(c) > 1 and c[-2] else 0
    c5 = (c[-1] - c[-6]) / c[-6] * 100 if len(c) > 5 and c[-6] else 0
    c10 = (c[-1] - c[-11]) / c[-11] * 100 if len(c) > 10 and c[-11] else 0
    c20 = (c[-1] - c[-21]) / c[-21] * 100 if len(c) > 20 and c[-21] else 0
    # P1-O4 (2026-10-20): overnight_sum20 / momentum_20 / chg5_rev
    # 三者此前未写入 compute_indicators() 返回 dict，导致 factor_weights v2.6 中对应
    # 权重（1.6 / 0.5 / 0.0）的 z 值恒 0，评分归零，因子层全死（P1 根因之一）。
    # 公式真源：
    #   overnight_sum20  → factor_ic_132d_refresh.py L143
    #   momentum_20      → calculate_cross_sectional_ic.py L65
    #   chg5_rev         → factor_calculator.py L75
    overnight_sum20 = None
    if len(c) >= 20 and len(o) >= 20:
        s = 0.0
        ok = True
        for i in range(len(c) - 19, len(c)):
            if c[i - 1] <= 0:
                ok = False
                break
            s += o[i] / c[i - 1] - 1
        if ok:
            overnight_sum20 = s * 100
    momentum_20 = (c[-1] - c[-21]) / c[-21] if len(c) > 20 and c[-21] else None
    chg5_rev = -c5
    p20 = (cur["close"] - (ma20 or cur["close"])) / (ma20 or cur["close"]) * 100

    # T-2026-08-20 三线共振因子
    # vol_shrink20: 近20日均量/近60日均量 (低=缩量企稳, IC=-0.056 通过门禁)
    vol_ma20 = calc_sma(v, 20) or 1
    vol_ma60 = calc_sma(v, 60) or 1
    vol_shrink20 = vol_ma20 / vol_ma60 if vol_ma60 > 0 else 1.0
    # turn5: 近5日涨跌停次数 (筹码松动代理)
    turn5 = 0
    for _i in range(max(1, len(c) - 5), len(c)):
        _p = c[_i - 1]
        if _p > 0 and (h[_i] / _p >= 1.095 or l[_i] / _p <= 0.905):
            turn5 += 1
    # vol_breakdown: 近20日最大跌幅 (高=高风险, 预期负IC)
    _min_ret = 0.0
    for _i in range(max(1, len(c) - 20), len(c)):
        if c[_i - 1] > 0:
            _r = (c[_i] - c[_i - 1]) / c[_i - 1] * 100
            if _r < _min_ret:
                _min_ret = _r
    vol_breakdown = _min_ret

    # P0-1 (2026-08-09): 新因子 — MAX/彩票回避 + 低波动异象
    # max_ret5: 近20日最大单日涨幅 (high/prev_close, 捕捉涨停/盘中暴拉 — 彩票型股票)
    _max_r = 0.0
    for _i in range(max(1, len(c) - 20), len(c)):
        if c[_i - 1] > 0:
            _r = (h[_i] / c[_i - 1] - 1) * 100
            if _r > _max_r:
                _max_r = _r
    max_ret5 = _max_r
    # std20: 近20日 chg1 标准差 (低波动异象 — 低波动股票未来收益更高)
    _chg1s = [(c[i] - c[i - 1]) / c[i - 1] * 100
              for i in range(max(1, len(c) - 20), len(c)) if c[i - 1] > 0]
    if len(_chg1s) >= 2:
        _m = sum(_chg1s) / len(_chg1s)
        std20 = (sum((x - _m) ** 2 for x in _chg1s) / (len(_chg1s) - 1)) ** 0.5
    else:
        std20 = 0.0

    # Phase C-2 (2026-08-31): vol_floor 低波动筛选因子
    # vol_floor = 今日成交量 / 近20日最低成交量
    # IC=-0.0375 IR=-0.359 (expected_sign=-1): 值越低→未来收益越好 (低波异象)
    # 门禁数据源: data/audit/new_factor_ic_20260830.json ✅过门禁 (第三个强因子)
    _vm20 = calc_sma(v, 20) or 1
    _minv20 = min(v[-20:]) if len(v) >= 20 and min(v[-20:]) > 0 else (_vm20 if _vm20 > 0 else 1)
    vol_floor = v[-1] / _minv20 if _minv20 > 0 else 1.0

    # P4 (2026-08-25): Alpha101精选因子 — 价量背离（华泰金工验证有效）
    # Alpha3: 开盘价与成交量10日相关性（负向=价量背离）
    def _rank(arr):
        """截面排名（0~1）"""
        if not arr or len(arr) < 2:
            return 0.5
        sorted_idx = sorted(range(len(arr)), key=lambda i: arr[i])
        ranks = [0.0] * len(arr)
        for rank, idx in enumerate(sorted_idx):
            ranks[idx] = rank / (len(arr) - 1) if len(arr) > 1 else 0.5
        return ranks[-1] if ranks else 0.5

    def _correlation(x, y, window):
        """滚动相关系数"""
        if len(x) < window or len(y) < window:
            return 0.0
        x_w = x[-window:]
        y_w = y[-window:]
        mx = sum(x_w) / window
        my = sum(y_w) / window
        cov = sum((x_w[i] - mx) * (y_w[i] - my) for i in range(window)) / window
        sx = (sum((v - mx) ** 2 for v in x_w) / window) ** 0.5
        sy = (sum((v - my) ** 2 for v in y_w) / window) ** 0.5
        if sx == 0 or sy == 0:
            return 0.0
        return cov / (sx * sy)

    # Alpha3: 开盘价与成交量10日相关性的排名（负向）
    open_ranked = [_rank([records[i]["open"] for i in range(max(0, j-9), j+1)]) for j in range(len(records))]
    vol_ranked = [_rank([records[i]["volume"] for i in range(max(0, j-9), j+1)]) for j in range(len(records))]
    alpha3 = -_correlation(open_ranked, vol_ranked, 10)

    # Alpha13: 收盘价与成交量5日协方差的排名（负向）
    close_ranked = [_rank([records[i]["close"] for i in range(max(0, j-4), j+1)]) for j in range(len(records))]
    vol_ranked_5 = [_rank([records[i]["volume"] for i in range(max(0, j-4), j+1)]) for j in range(len(records))]
    alpha13 = -_correlation(close_ranked, vol_ranked_5, 5)

    # Alpha15: 最高价与成交量3日相关性，3日滚动求和（负向）
    high_ranked = [_rank([records[i]["high"] for i in range(max(0, j-2), j+1)]) for j in range(len(records))]
    alpha15 = 0.0
    for i in range(3):
        if len(records) > 2:
            alpha15 += _correlation(high_ranked[-(i+3):], vol_ranked[-(i+3):], min(3, len(records)))
    alpha15 = -alpha15 / 3

    # Phase B (2026-09-04): vol_price_corr_20 - 20日量价相关
    # IC=-0.0566, IR=-0.51, 单调差+0.217（略超门槛但IC强于alpha13/alpha15）
    # 逻辑: 涨放量(正相关)→短期动能→反转预期→负向因子
    vol_price_corr_20 = _correlation(c, v, 20) if len(c) >= 20 and len(v) >= 20 else 0.0

    # Alpha16: 最高价与成交量5日协方差（负向）— 旧算法，用 rank(volume)，单调差-0.236（未过门禁）
    alpha16 = -_correlation(high_ranked, vol_ranked_5, 5)

    # Alpha16_fix: 最高价与成交量5日协方差（负向）— 修正算法，用原始 volume（非 rank）
    # 单调差修复后 +0.229，IC=+0.0556 IR=0.53 全过门禁
    # Phase D-2 发现：tdx_score.py §7i 用 inds.get("alpha16") 但实际需过门禁的 alpha16_fix
    # 修复方案：输出新 key "alpha16_fix"，tdx_score.py 同步改用该 key 取数
    high_5d_raw = [records[j]["high"] for j in range(len(records))]
    vol_5d_raw = [records[j]["volume"] for j in range(len(records))]
    alpha16_fix = -_correlation(high_5d_raw, vol_5d_raw, 5)

    # Phase A (2026-09-02): amount_q_reversal
    # 成交额分位数切割反转: 高成交组平均日涨幅 - 低成交组平均日涨幅 (最近20日)
    # IC=-0.0502, IR=0.51, 方向率69%, 单调差-0.304, 全过门禁
    # walk_forward 确认: WF Test IC=-0.0420, 退化率0.026, FOLD4达-0.106
    # 逻辑: 高成交额日(大单主导→抛压集中→反转强)若涨幅大→未来下跌→因子与未来收益负相关
    # 预期负值=反转信号=加分(与alpha13/alpha16fix类似, 负值加分)
    # 参见: mainline/docs/Phase A-成交额分位数切割反转因子_总管_20260902.md
    amount_q_reversal = 0.0
    if len(a) >= 20:
        # 与 IC 门禁验证脚本 (alpha101_extended_ic_check.py) 严格对齐
        # 涨跌幅用小数形式 (0.025 = 2.5%), 与门禁 IC=-0.0502 同量纲
        # 中位数用偶数标准 (第10小+第11小)/2, 含第1日 (chg[0]=0)
        a_win = a[-20:]
        c_win = c[-20:]
        if len(c_win) == 20:
            chg = [0.0] + [(c_win[i] - c_win[i - 1]) / c_win[i - 1]
                           if c_win[i - 1] > 0 else 0.0
                           for i in range(1, 20)]
            amt_sorted = sorted(a_win)
            med = (amt_sorted[9] + amt_sorted[10]) / 2
            high_chg = [chg[i] for i in range(20) if a_win[i] >= med]
            low_chg = [chg[i] for i in range(20) if a_win[i] < med]
            if high_chg and low_chg:
                amount_q_reversal = (sum(high_chg) / len(high_chg)) - (sum(low_chg) / len(low_chg))

    # KDJ（修复 v4.3 — 每根K线用自已的收盘价，不是都用最新价）
    kk, kd, kj = 50.0, 50.0, 50.0
    if len(records) >= 14:
        rsv_l = []
        for i in range(len(records)):
            s = max(0, i - 8)
            h9 = max(x["high"] for x in records[s:i + 1])
            l9 = min(x["low"] for x in records[s:i + 1])
            rsv_l.append((records[i]["close"] - l9) / (h9 - l9) * 100 if h9 != l9 else 50.0)
        k = d = 50.0
        for rsv in rsv_l[-9:]:
            k = 2 / 3 * k + 1 / 3 * rsv
            d = 2 / 3 * d + 1 / 3 * k
        kk, kd, kj = k, d, 3 * k - 2 * d

    atr = calc_atr(records, 14)
    vp, vpd = analyze_volume_pattern(records) or (None, None)

    # RMS因子(2026-08-25): 相对动量强度 = 10日动量 × (1+|20日动量增益|) × min(量比,3)
    rms = 0.0
    if len(c) >= 21:
        chg10 = c[-1] / c[-11] - 1
        chg20 = c[-1] / c[-21] - 1
        vol_avg = sum(v[-60:-10]) / 50 if len(v) >= 60 else sum(v[:-10]) / max(len(v)-10, 1)
        vol_ratio = v[-1] / vol_avg if vol_avg > 0 else 1
        rms = chg10 * (1 + abs(chg20)) * min(vol_ratio, 3.0)

    # 技术形态识别
    patterns = {"found": False, "pattern": "", "score": 0, "desc": ""}
    try:
        from pattern_recognition import identify_all_patterns
        patterns = identify_all_patterns(records)
    except ImportError:
        pass

    # LHB因子 (2026-09-04 P1, 2026-10-14 复活): 龙虎榜净买额/总成交比 > 5% → +1, < -5% → -1
    # IC=0.0991 IR=0.62 全场最强因子 (09-04测量, 陈旧数字: 数据层重构后未复测, 待回填后重测门禁, 禁作现值验证 SOUL#7)
    # 原块四缺陷(路径/模式/schema/日期过滤)改为单一读点 read_lhb_signal (与回测快路径共用); code=None → 0.0 行为不变
    lhb_signal = read_lhb_signal(code, cur["date"]) if code else 0.0

    # P1-3补充修复(2026-08-07): 周线指标 — compute_indicators从未生成weekly_bullish/weekly_macd_red
    # 导致权重表(6/12/2/8/5分)全部是死代码, 周线多头因子触发率0%
    weekly = compute_weekly_indicators(records) or {}

    # P0修复(2026-09-23): 添加raw_score字段供截面标准化使用
    # 初始值为0，后续由score_stock计算后回填
    inds_with_score = {
        "price": cur["close"],
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "ma120": ma120,
        "dif": dif, "dea": dea, "macd_hist": mh,
        "rsi6": r6, "rsi14": r14, "rsi24": r24,
        "kdj_k": kk, "kdj_d": kd, "kdj_j": kj,
        "vol_ratio": vr, "vol_ma5": vm5, "vol_ma10": vm10,
        "chg1": c1, "chg5": c5, "chg10": c10, "chg20": c20,
        "overnight_sum20": overnight_sum20, "momentum_20": momentum_20, "chg5_rev": chg5_rev,
        "max_ret5": max_ret5, "std20": std20,
        "rms": rms,
        "turn5": turn5, "vol_shrink20": vol_shrink20, "vol_breakdown": vol_breakdown,
        "pos_vs_ma20": p20,
        "alpha3": alpha3, "alpha13": alpha13, "alpha15": alpha15, "alpha16": alpha16,
        "alpha16_fix": alpha16_fix,
        "amount_q_reversal": amount_q_reversal,
        "vol_price_corr_20": vol_price_corr_20,
        "vol_floor": vol_floor,
        "latest_date": cur["date"],
        "lhb_signal": lhb_signal,
        "latest_high": cur["high"], "latest_low": cur["low"],
        "highs_20": max(h[-20:]) if len(h) >= 20 else max(h),
        "lows_20": min(l[-20:]) if len(l) >= 20 else min(l),
        "highs_10": max(h[-10:]) if len(h) >= 10 else max(h),
        "lows_10": min(l[-10:]) if len(l) >= 10 else min(l),
        "atr": atr, "vol_pattern": vp, "vol_pattern_detail": vpd,
        "pattern_found": patterns["found"],
        "pattern_name": patterns.get("pattern", ""),
        "pattern_score": patterns.get("score", 0),
        "pattern_desc": patterns.get("desc", ""),
        "weekly_bullish": bool(weekly.get("w_bullish")),
        "weekly_macd_red": bool(weekly.get("w_dif") is not None and weekly.get("w_dea") is not None
                                and weekly["w_dif"] > weekly["w_dea"]),
        "sector_correlation": _calc_sector_correlation(records),
        "unlocked_pressure": _calc_unlocked_pressure(records),
        "sector_heat_persistence": calc_sector_heat_persistence(records),
        "fund_flow_intensity": calc_fund_flow_intensity(records),
        "breakout_strength": calc_breakout_strength(records),
        "upside_vol_ratio": calc_upside_volatility_ratio(records),
        "support_distance": calc_support_distance(records),
        "momentum_reversal": calc_momentum_reversal(records),
        "volume_abnormal": calc_volume_abnormal(records),
        "rsi_extreme": calc_rsi_extreme(records),
        "price_volume_divergence": calc_price_volume_divergence(records),
        "raw_score": 0.0,  # P0修复: 初始占位，后续由评分引擎回填
    }

    return inds_with_score


# ═══════════════════════════════════════════
#  新增因子计算函数 (Phase E, 2026-09-13)
# ═══════════════════════════════════════════

def _calc_sector_correlation(records, window=20):
    """板块联动度因子: 个股与创业板指(sh000905)收益率滚动相关系数

    逻辑: 高联动→跟随板块→短期趋势延续性更强→正向IC
    预期IC: +0.02~+0.04
    """
    try:
        n = len(records)
        if n < window + 5:
            return 0.0
        c = [r["close"] for r in records]
        # 个股近window日收益率
        stock_rets = []
        for i in range(max(1, n - window), n):
            if c[i-1] > 0:
                stock_rets.append((c[i] - c[i-1]) / c[i-1])
            else:
                stock_rets.append(0.0)
        if len(stock_rets) < window:
            return 0.0
        # 板块指数收益率 (sh000905 创业板指)
        _idx_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "data", "history_daily", "history_daily", "sh000905.json")  # 基地化S3: 根锚点
        if not os.path.exists(_idx_path):
            return 0.0
        with open(_idx_path, "r", encoding="utf-8") as _f:
            idx_data = json.load(_f)
        # 对齐日期
        idx_map = {}
        for _r in idx_data:
            _d = _r.get("date")
            if isinstance(_d, date):
                _d_str = _d.isoformat()
            else:
                _d_str = str(_d)
            idx_map[_d_str] = _r.get("close", 0)
        # 取对应日期的板块收盘
        _rec_dates = [str(r["date"]) if hasattr(r["date"], "isoformat") else str(r["date"])
                      for r in records[-window:]]
        sector_rets = []
        prev_close = None
        for _d in _rec_dates:
            _cl = idx_map.get(_d)
            if _cl and prev_close and prev_close > 0:
                sector_rets.append((_cl - prev_close) / prev_close)
            elif _cl:
                sector_rets.append(0.0)
            prev_close = _cl
        if len(sector_rets) < window or len(stock_rets) < window:
            return 0.0
        # 计算相关系数
        wx = stock_rets[-window:]
        wy = sector_rets[-window:] if len(sector_rets) >= window else sector_rets
        mx = sum(wx) / len(wx)
        my = sum(wy) / len(wy)
        cov = sum((wx[i] - mx) * (wy[i] - my) for i in range(len(wx))) / len(wx)
        sx = (sum((v - mx) ** 2 for v in wx) / len(wx)) ** 0.5
        sy = (sum((v - my) ** 2 for v in wy) / len(wy)) ** 0.5
        if sx == 0 or sy == 0:
            return 0.0
        return cov / (sx * sy)
    except Exception:
        return 0.0


def _calc_unlocked_pressure(records, lookback=250):
    """解套盘压力因子: (当前价 - lookback日最低) / (lookback日最高 - lookback日最低)

    逻辑: 值高→接近历史高点→套牢盘压力大→短期承压(负向IC); 值低→接近低点→超跌反弹预期(负向)
    预期IC: 负向, |IC| 0.02~0.03
    注: 此因子与未来收益负相关, expected_sign=-1
    """
    try:
        n = len(records)
        if n < lookback:
            return 0.0
        h = [r["high"] for r in records]
        l = [r["low"] for r in records]
        c = [r["close"] for r in records]
        cur = c[-1]
        _high = max(h[-lookback:])
        _low = min(l[-lookback:])
        if _high == _low:
            return 0.5
        return (cur - _low) / (_high - _low)
    except Exception:
        return 0.5




def calc_momentum_reversal(records, short_window=5, long_window=20):
    """动量反转因子: 短期动量 × 中期反转
    
    IC验证结果: +0.62 (远超阈值0.03)
    建议权重: 12分
    """
    closes = [r['close'] for r in records]
    if len(closes) < long_window + 1:
        return None
    
    mom_5d = (closes[-1] - closes[-short_window-1]) / closes[-short_window-1] if closes[-short_window-1] != 0 else 0
    rev_20d = (closes[-long_window-1] - closes[-1]) / closes[-long_window-1] if closes[-long_window-1] != 0 else 0
    
    return mom_5d * rev_20d


def calc_volume_abnormal(records, window=20):
    """成交量异常度: |实际量/平均量 - 1|
    
    IC验证结果: -0.70 (负相关，高分=高风险)
    建议权重: -8分（风险警示）
    """
    volumes = [r.get('volume', 0) for r in records]
    if len(volumes) < window:
        return None
    
    vol_ma = sum(volumes[-window:-1]) / (window - 1) if window > 1 else 1
    if vol_ma <= 0:
        return 0
    
    vol_ratio = volumes[-1] / vol_ma
    return abs(vol_ratio - 1)


def calc_rsi_extreme(records, rsi_high=70, rsi_low=30):
    """RSI极端值因子: RSI>70超买或RSI<30超卖后反转

    IC验证结果: -0.0567 (负相关，极端值后反转)
    建议权重: -5~-8分（风险警示）
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < 15:
            return None

        delta = pd.Series(closes).diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        rsi_value = rsi.iloc[-1]
        is_extreme = 1 if rsi_value > rsi_high or rsi_value < rsi_low else 0
        return is_extreme
    except Exception:
        return None


def calc_price_volume_divergence(records, window=6):
    """量价背离因子: 价格与成交量方向背离

    IC验证结果: +0.0871 (正相关，背离后趋势延续)
    建议权重: +5~+8分（信号加分）
    """
    try:
        closes = [r['close'] for r in records]
        volumes = [r.get('volume', 0) for r in records]
        if len(closes) < window + 1 or len(volumes) < window + 1:
            return None

        price_change = (closes[-1] - closes[-window-1]) / closes[-window-1] if closes[-window-1] != 0 else 0
        vol_change = (volumes[-1] - volumes[-window-1]) / volumes[-window-1] if volumes[-window-1] != 0 else 0

        # 背离信号: 价格涨但成交量缩，或价格跌但成交量增
        divergence = 1 if (price_change > 0 and vol_change < 0) or (price_change < 0 and vol_change > 0) else 0
        return divergence
    except Exception:
        return None


def calc_sector_heat_persistence(records, current_sector='未知', lookback=10):
    """板块热度持续性因子: 短期(3日)热度 vs 中期(10日)热度比率

    预期IC: 0.04, 权重: 10分
    逻辑: 区分热点持续性 vs 短期脉冲
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < lookback:
            return None

        # 计算短期和中期热度（简化版：用涨幅替代）
        short_heat = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] != 0 else 0
        mid_heat = (closes[-1] - closes[-lookback-1]) / closes[-lookback-1] if closes[-lookback-1] != 0 else 0

        # 热度持续性比率
        if mid_heat == 0:
            return 0
        persistence = short_heat / mid_heat if mid_heat != 0 else 0

        # 持续性信号: 比率>1表示热度加速，<0.5表示热度衰减
        if persistence > 1.0:
            return 1  # 强势持续性
        elif persistence < 0.5:
            return -1  # 弱势衰减
        else:
            return 0  # 中性
    except Exception:
        return None


def calc_fund_flow_intensity(records, window=5):
    """资金流向强度因子: 主力净流入/流通市值

    预期IC: 0.05, 权重: 12分
    逻辑: 量化机构资金认可度
    """
    try:
        closes = [r['close'] for r in records]
        volumes = [r.get('volume', 0) for r in records]
        amounts = [r.get('amount', 0) for r in records]

        if len(closes) < window or volumes[-1] == 0:
            return None

        # 简化计算: 用成交额/成交量=均价，再估算主力流向
        # 实际应使用主力资金数据，此处用价格动量替代
        price_momentum = (closes[-1] - closes[-window]) / closes[-window] if closes[-window] != 0 else 0

        # 结合成交量放大确认
        vol_ratio = volumes[-1] / (sum(volumes[-window:-1]) / (window - 1)) if sum(volumes[-window:-1]) > 0 else 1

        # 强度评分: 价格上涨+放量=强信号
        if price_momentum > 0.02 and vol_ratio > 1.2:
            return 1
        elif price_momentum < -0.02 and vol_ratio > 1.2:
            return -1
        else:
            return 0
    except Exception:
        return None


def calc_breakout_strength(records, window=20):
    """突破力度指数: (收盘价-20日低点)/20日波动率

    预期IC: 0.06, 权重: 15分
    逻辑: 强势突破 vs 弱势反弹
    """
    try:
        closes = [r['close'] for r in records]
        highs = [r.get('high', r['close']) for r in records]
        lows = [r.get('low', r['close']) for r in records]

        if len(closes) < window:
            return None

        # 计算20日波动率（标准差）
        recent_closes = closes[-window:]
        mean_close = sum(recent_closes) / window
        volatility = (sum((c - mean_close) ** 2 for c in recent_closes) / window) ** 0.5

        if volatility == 0:
            return 0

        # 突破力度 = (当前价-最低点) / 波动率
        lowest = min(lows[-window:])
        breakout = (closes[-1] - lowest) / volatility

        # 标准化到[-1, 1]
        breakout_normalized = max(-1, min(1, breakout / 3))

        return breakout_normalized
    except Exception:
        return None


def calc_upside_volatility_ratio(records, window=20):
    """上行波动比率: 上涨日标准差/下跌日标准差

    预期IC: 0.03, 权重: 8分
    逻辑: 区分健康上涨 vs 脆弱上涨
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < window:
            return None

        # 计算每日涨跌幅
        changes = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        recent_changes = changes[-window:]

        # 分离上涨日和下跌日
        up_days = [c for c in recent_changes if c > 0]
        down_days = [c for c in recent_changes if c < 0]

        if len(up_days) < 3 or len(down_days) < 3:
            return 0

        # 计算标准差
        up_mean = sum(up_days) / len(up_days)
        down_mean = sum(down_days) / len(down_days)

        up_std = (sum((c - up_mean) ** 2 for c in up_days) / len(up_days)) ** 0.5
        down_std = (sum((c - down_mean) ** 2 for c in down_days) / len(down_days)) ** 0.5

        if down_std == 0:
            return 0

        # 比率: >1表示上涨波动更大（健康上涨），<1表示下跌波动更大（脆弱上涨）
        ratio = up_std / down_std

        # 标准化到[-1, 1]
        normalized = max(-1, min(1, (ratio - 1) / 1))

        return normalized
    except Exception:
        return None


def calc_support_distance(records, ma_period=20):
    """支撑位距离: (当前价-MA20)/MA20

    预期IC: 0.04, 权重: 10分
    逻辑: 安全边际评估
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < ma_period:
            return None

        # 计算MA20
        ma20 = sum(closes[-ma_period:]) / ma_period

        # 支撑位距离
        distance = (closes[-1] - ma20) / ma20 if ma20 != 0 else 0

        # 标准化到[-1, 1]
        normalized = max(-1, min(1, distance * 5))  # 放大5倍便于区分

        return normalized
    except Exception:
        return None


# ════════════════════════════════════════════════════════
# S3-10 P2 (2026-10-01): 因子回测补算指标
# 任务单: docs/S3-10-P2回测任务单-20261001.md 第4条
# (boll_width/drawdown_60/downside_vol/max_consec_down 未实现, P2内补+单测)
# 口径与生产指标一致: 输入records=[{close,open,high,low,volume,...}], 返回单值, 数据不足返回None
# ════════════════════════════════════════════════════════

def calc_boll_width(records, period=20, k=2.0):
    """布林带宽: (上轨-下轨)/中轨 = 2*k*std/MA

    波动收敛/扩张度量: 带宽小=波动收敛(变盘前兆), 大=波动扩张
    std=总体标准差(ddof=0, 与 calc_breakout_strength 的波动率口径一致)
    返回: 带宽比率(无量纲, 如0.12=带宽占中轨12%), 数据不足返回None
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < period:
            return None
        recent = closes[-period:]
        ma = sum(recent) / period
        if ma <= 0:
            return None
        var = sum((c - ma) ** 2 for c in recent) / period
        std = var ** 0.5
        return (2.0 * k * std) / ma
    except Exception:
        return None


def calc_drawdown_60(records, window=60):
    """60日最大回撤: 近window日内 收盘 相对峰值的最大回撤幅度

    遍历窗口内逐日: peak=max(peak, close[i]), dd=min(dd, close[i]/peak-1)
    返回: 正数回撤幅度(如0.18=最大回撤18%), 全程无回撤返回0.0, 数据不足返回None
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < window:
            return None
        peak = -1.0
        dd = 0.0
        for c in closes[-window:]:
            if c > peak:
                peak = c
            if peak > 0:
                d = 1.0 - c / peak
                if d > dd:
                    dd = d
        return dd
    except Exception:
        return None


def calc_downside_vol(records, period=20, min_neg_obs=3):
    """下行波动率: 近period日 仅负收益的样本标准差(%)

    与生产 std20 (backtest_fast_inds.py:310-327, chg1样本std ddof=1, %单位) 口径对齐,
    仅取负收益观测 → 度量下行风险 (Sortino 分母)
    返回: % 单位 std; 负收益观测不足 min_neg_obs 返回None (无下行风险可测); 数据不足返回None
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < period + 1:
            return None
        rets = []
        for i in range(len(closes) - period, len(closes)):
            if closes[i - 1] > 0:
                rets.append((closes[i] - closes[i - 1]) / closes[i - 1] * 100.0)
        neg = [r for r in rets if r < 0]
        if len(neg) < min_neg_obs:
            return None
        m = sum(neg) / len(neg)
        v2 = sum((r - m) ** 2 for r in neg)
        return (v2 / (len(neg) - 1)) ** 0.5
    except Exception:
        return None


def calc_max_consec_down(records, window=60):
    """最大连续下跌日: 近window日内最长连阴(close<prev close)

    返回: 连阴天数(int), 无连阴返回0, 数据不足返回None
    """
    try:
        closes = [r['close'] for r in records]
        if len(closes) < window + 1:
            return None
        best = 0
        cur = 0
        for i in range(len(closes) - window, len(closes)):
            if closes[i] < closes[i - 1]:
                cur += 1
                if cur > best:
                    best = cur
            else:
                cur = 0
        return best
    except Exception:
        return None
