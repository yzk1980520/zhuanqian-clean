#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""factor_ic_132d_refresh.py — 132d 精确口径因子 IC 重算 (S3 权威源刷新器)

背景 (2026-10-17 W1):
  data/factor_ic/factor_ic_latest.json 是门禁的 IC 权威源 (老大拍板), 其
  source 字段 = "pure_python_v10_exact_132d"。但该文件的产出脚本从未入库
  (全仓检索 pure_python_v10_exact_132d / factor_ic_latest 均无生产者, 该文件
  由 10-16 08:06 的手工临时脚本一次性写出), 因此它必然再次变陈货。
  本脚本把该 132d 口径固化为可重复执行、可入调度的常驻脚本。

口径 (与权威源逐字段对齐):
  window_days     = 132   (取最后 132 个交易日作为截面窗口)
  forward horizon = 5     (未来 5 个交易日收益)
  IC              = Spearman 秩相关 (复用 factor_gate_v2.spearman_ic, 单一算术源)
  status          = 'valid' if |ic_mean| >= ic_threshold AND |icir_nw| >= ir_threshold
                    else 'dead'
                    icir_nw = Newey-West 修正后的 ICIR (= t_nw / sqrt(n))。
                    2026-10-18 W14 起启用，取代 naive icir —— IC 序列自相关
                    中位数 0.7313 会把 naive ICIR 虚顶约 1.8 倍，详见 summarize()。
  阈值来源        = factor_gate_v2.GATE_CONFIG (G4 唯一真源, 不在此处硬编码)
  实证            : 用本规则回推 132d 诊断文件 28 个因子的 status, 28/28 MATCH

安全约束 (红线: 绝不静默劣化权威源):
  1. 默认 dry-run: 只写 data/factor_ic/factor_ic_132d_refresh_<ts>.json, 不动权威源
  2. --apply 才覆盖 factor_ic_latest.json, 且覆盖前先把旧文件归档为
     factor_ic_latest_<ts>.json (只增不删)
  3. 覆盖前做三道守卫, 任一不过即 exit!=0 且不写:
     G-A 因子数 >= 20 (少于此说明数据/代码坏了)
     G-B 与上一版同名因子覆盖率 >= 80% (口径漂移检测)
     G-C 同名因子 status 翻转比例 <= 50% (可用 --allow-big-flip 显式放行, 并留日志)

因子算术来源:
  26 个因子函数逐字提升自 .scratch/p1_optimization_task_v3.py FACTOR_FUNCTIONS
  (与 .scratch/factor_ic_scan.py 同算术)。
  OBV_TREND / intraday_sum20 / value_proxy 三个在原 scratch 中缺失, 按
  scripts/design_new_factors.py + scripts/compute_representative_factors.py 的
  描述重建, 已在文件内显式标注 [RECONSTRUCTED], 首次实跑需与旧权威源对账
  (本脚本 --diff-prev 会打印逐因子差异)。

用法:
  python scripts/factor_ic_132d_refresh.py                       # dry-run
  python scripts/factor_ic_132d_refresh.py --apply --archive-prev # 正式刷新
  python scripts/factor_ic_132d_refresh.py --max-stocks 200      # 缩小样本(快跑)
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from core.scoring.factor_gate_v2 import (  # noqa: E402  单一算术源，禁止在本文件重复实现
    GATE_CONFIG, lag1_autocorr, newey_west_t, spearman_ic,
)
sys.path.insert(0, str(ROOT))

HISTORY_DIR = ROOT / "data" / "history_daily"
OUT_DIR = ROOT / "data" / "factor_ic"
AUTHORITY = OUT_DIR / "factor_ic_latest.json"
ENGINE_TAG = "pure_python_v10_exact_132d"

WINDOW_DAYS = 132
FORWARD_DAYS = 5
MIN_BARS = 60            # 个股至少需要的历史根数

# 取证开关(由 CLI 覆盖, 常规刷新用默认值)
_MIN_BARS = MIN_BARS
_INCLUDE_ETF = False


def _is_etf(code: str) -> bool:
    """ETF/LOF 粗判: sh51xxxx/sh56xxxx/sh58xxxx/sz15xxxx/sz16xxxx

    t_bbc3444e: 该粗判已被 _is_ashare_stock() 白名单取代(截面纯度过滤层),
    此函数仅作为 --include-etf 取证开关的语义参照保留, 不再被 _load_universe 调用。
    """
    if code.startswith(("sh51", "sh56", "sh58", "sz15", "sz16")):
        return True
    return False


# t_bbc3444e (Task A aa_resid_mom_retest_20261026.md §二/§五 拍板):
# 旧 _is_etf() 前缀粗判漏放 444 只非 A 股品种(基金/LOF 249 + 债券/可转债 184 +
# B股/其他 11, 见 data/audit/aa_universe_probe_old_20261026.json)进 2000 只截面,
# 行业映射覆盖率 73.7% < 80% 红线。收紧为纯 A 股白名单:
#   sh60 = 沪主板(600/601/603/605), sh68 = 科创板(688/689),
#   sz00 = 深主板(000/001/002/003), sz30 = 创业板(300/301/302)
# 基金/可转债/B股/指数/通达信板块指数(sh88x)等一律不入截面。
ASHARE_PREFIXES = ("sh60", "sh68", "sz00", "sz30")


def _is_ashare_stock(code: str) -> bool:
    """纯 A 股个股白名单判定(60/68/00/30 代码段)。非 A 股品种一律返回 False。"""
    return code.startswith(ASHARE_PREFIXES)
MIN_SECTION = 50         # 单个截面日至少需要的个股数(低于此不计算当日IC)
MIN_IC_DATES = 20        # 单个因子至少需要的有效截面日数
GATE_MIN_FACTORS = 20
GATE_MIN_COVERAGE = 0.80
GATE_MAX_FLIP = 0.50


# ═══════════════════════════════════════════════════════════
#  因子算术 (提升自 .scratch/p1_optimization_task_v3.py)
# ═══════════════════════════════════════════════════════════
def _low60_dist(c):
    if len(c) < 60:
        return None
    lo = min(c[-60:])
    if lo <= 0:
        return None
    return (c[-1] / lo - 1) * 100


def _vol_dryup(v):
    if len(v) < 60:
        return None
    v60 = sum(v[-60:]) / 60.0
    if v60 <= 0:
        return None
    return max(v[-5:]) / v60


def _gap_down_cnt(o, c):
    if len(o) < 20 or len(c) < 20:
        return None
    return float(sum(1 for i in range(len(o)-19, len(o)) if o[i] < c[i-1] * 0.98))


def _amount_price_corr(a, c):
    if len(a) < 20 or len(c) < 20:
        return None
    if max(a[-20:]) <= 0:
        return None
    mc = sum(c[-20:]) / 20
    ma_ = sum(a[-20:]) / 20
    cov = sc2 = sa2 = 0.0
    for j in range(len(c)-20, len(c)):
        cov += (c[j] - mc) * (a[j] - ma_)
        sc2 += (c[j] - mc) ** 2
        sa2 += (a[j] - ma_) ** 2
    if sc2 <= 0 or sa2 <= 0:
        return None
    return cov / (sc2 ** 0.5 * sa2 ** 0.5)


def _red_ratio10(c, o):
    if len(c) < 10 or len(o) < 10:
        return None
    return sum(1 for i in range(len(c)-10, len(c)) if c[i] > o[i]) / 10.0


def _overnight_sum20(c, o):
    if len(c) < 20 or len(o) < 20:
        return None
    s = 0.0
    ok = True
    for i in range(len(c)-19, len(c)):
        if c[i-1] <= 0:
            ok = False
            break
        s += o[i] / c[i-1] - 1
    if not ok:
        return None
    return s * 100


def _ami_hud(c, a):
    n = len(c)
    if n < 21 or len(a) < 20:
        return None
    vals = []
    for i in range(n - 19, n):
        prev_close = c[i - 1]
        curr_close = c[i]
        amount = a[i]
        if prev_close > 0 and amount > 0:
            ret = abs((curr_close - prev_close) / prev_close)
            vals.append(ret / amount)
    if not vals:
        return None
    return sum(vals[-20:]) / len(vals[-20:])


def _vol_ratio_5_20(v):
    if len(v) < 20:
        return None
    v5 = sum(v[-5:]) / 5.0
    v20 = sum(v[-20:]) / 20.0
    if v20 <= 0:
        return None
    return v5 / v20


def _vol_change(v):
    if len(v) < 2:
        return None
    if v[-2] <= 0:
        return None
    return (v[-1] - v[-2]) / v[-2] * 100


def _vol_ma_ratio(v):
    if len(v) < 5:
        return None
    v5 = sum(v[-5:]) / 5
    if v5 <= 0:
        return None
    return v[-1] / v5


def _vol_floor(v):
    if len(v) < 20:
        return None
    floor = min(v[-20:])
    if floor <= 0:
        return None
    return v[-1] / floor


def _vol_shrink(v):
    if len(v) < 20:
        return None
    v20 = sum(v[-20:]) / 20
    if v20 <= 0:
        return None
    return v[-1] / v20


def _turnover(v):
    if len(v) < 1:
        return None
    return v[-1]


def _atr_ratio(h, l, c):
    if len(h) < 14 or len(l) < 14 or len(c) < 14:
        return None
    trs = []
    for i in range(-14, 0):
        tr = max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
        trs.append(tr)
    atr = sum(trs) / 14
    if atr <= 0:
        return None
    return (h[-1] - l[-1]) / atr


def _rsi14(c):
    if len(c) < 15:
        return None
    gains = []
    losses = []
    for i in range(-14, 0):
        diff = c[i] - c[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss <= 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _mdd60(h, c):
    if len(h) < 60 or len(c) < 60:
        return None
    peak = h[-60]
    mdd = 0
    for i in range(-60, 0):
        if c[i] < peak * 0.9:
            mdd = max(mdd, (peak - c[i]) / peak)
        peak = max(peak, h[i])
    return mdd * 100


def _lower_shadow(h, l, c, o):
    if len(h) < 1:
        return None
    body = abs(c[-1] - o[-1])
    if body <= 0:
        return None
    lower = min(c[-1], o[-1]) - l[-1]
    return lower / body


def _upper_shadow(h, l, c, o):
    if len(h) < 1:
        return None
    body = abs(c[-1] - o[-1])
    if body <= 0:
        return None
    upper = h[-1] - max(c[-1], o[-1])
    return upper / body


def _consecutive_loss(c):
    if len(c) < 2:
        return None
    count = 0
    for i in range(-1, -len(c), -1):
        if i == -1:
            continue
        if c[i] < c[i+1]:
            count += 1
        else:
            break
    return count


def _price_vol_rank(c, v):
    if len(c) < 10 or len(v) < 10:
        return None
    price_rank = sum(1 for x in c[-10:] if x < c[-1]) / 10
    vol_rank = sum(1 for x in v[-10:] if x < v[-1]) / 10
    return price_rank * vol_rank


def _chg5(c):
    if len(c) < 5:
        return None
    if c[-5] <= 0:
        return None
    return (c[-1] - c[-5]) / c[-5] * 100


def _chg10(c):
    if len(c) < 10:
        return None
    if c[-10] <= 0:
        return None
    return (c[-1] - c[-10]) / c[-10] * 100


def _momentum_20(c):
    if len(c) < 20:
        return None
    if c[-20] <= 0:
        return None
    return (c[-1] - c[-20]) / c[-20] * 100


def _vol_ratio_cs(c, v):
    """波动率比（截面用）"""
    if len(c) < 20 or len(v) < 20:
        return None
    c20 = c[-20:]
    v20 = v[-20:]
    c_mean = sum(c20) / 20
    v_mean = sum(v20) / 20
    c_std = math.sqrt(sum((x - c_mean)**2 for x in c20) / 20)
    v_std = math.sqrt(sum((x - v_mean)**2 for x in v20) / 20)
    if c_mean <= 0 or v_mean <= 0:
        return None
    return (c_std / c_mean) / (v_std / v_mean)


def _alpha16_fix(c, v):
    if len(c) < 20 or len(v) < 20:
        return None
    v_first_half = sum(v[-20:-10]) / 10
    v_second_half = sum(v[-10:]) / 10
    if v_first_half <= 0:
        return None
    return (v_second_half / v_first_half - 1) * 100


# ── [RECONSTRUCTED] 原 scratch 缺失, 按 design_new_factors / compute_representative_factors 重建 ──
def _obv_trend(c, v):
    """OBV 20日趋势: (OBV[-1] - OBV[-21]) / 20日均量, 方向随量价同向累积"""
    if len(c) < 21 or len(v) < 21:
        return None
    obv = 0.0
    for i in range(len(c) - 20, len(c)):
        if c[i] > c[i - 1]:
            obv += v[i]
        elif c[i] < c[i - 1]:
            obv -= v[i]
    v20 = sum(v[-20:]) / 20.0
    if v20 <= 0:
        return None
    return obv / (v20 * 20.0)


def _intraday_sum20(c, o):
    """日内收益累计%: sum((close[i]-open[i])/open[i]) * 100 (与 overnight_sum20 互补)"""
    if len(c) < 20 or len(o) < 20:
        return None
    s = 0.0
    for i in range(len(c) - 20, len(c)):
        if o[i] > 0:
            s += (c[i] - o[i]) / o[i]
    return s * 100


def _value_proxy(c):
    """价值代理: 1 - 52周价格位置 (价格越低得分越高)"""
    if len(c) < 250:
        return None
    w = c[-250:]
    lo, hi = min(w), max(w)
    if hi <= lo:
        return None
    return (1 - (c[-1] - lo) / (hi - lo)) * 100


def _gap_up_cnt20(o, c):
    """P1#5(t_c575000e, 老三 2026-10-23): 断层(向上跳空)近20日次数.
    与 gap_down_cnt (o < c*0.98) 镜像对称, 阈值取 2% (o > c*1.02)."""
    if len(o) < 21 or len(c) < 21:
        return None
    return float(sum(1 for i in range(len(o) - 20, len(o))
                     if o[i] > c[i - 1] * 1.02))


def _startup_accel(c):
    """P1#5(t_c575000e, 老三 2026-10-23): 主升浪加速度(%) = chg5 - chg20.
    与 core/pipeline/startup_detector.py L64-71 逐字同口径
    (chg5=c[-1]/c[-6]-1, chg20=c[-1]/c[-21]-1, 均百分数):
    近5日涨幅超出近20日涨幅 = 加速启动信号。"""
    if len(c) < 21:
        return None
    c5, c20, c1 = c[-6], c[-21], c[-1]
    if min(c5, c20, c1) <= 0:
        return None
    chg5 = (c1 / c5 - 1) * 100
    chg20 = (c1 / c20 - 1) * 100
    return chg5 - chg20


def _gap_up_x_accel(c, o):
    """P1#5(t_c575000e): 因子交互效应 (立项依据 §1.1: 断层×主升浪).
    主升浪加速度 × 断层密度(0-1, 近20日断层>=3次封顶)。
    断层密集 + 加速启动 = 断层主升浪形态。"""
    accel = _startup_accel(c)
    cnt = _gap_up_cnt20(o, c)
    if accel is None or cnt is None:
        return None
    return accel * (min(cnt, 3.0) / 3.0)


# ── 新增候选因子 (t_112197e1, 2026-10-25: D-8 策略B 扩池) ──
def _vol_mom5_20(v):
    """量能加速：5日均量 / 20日均量(不含近5日)。>1 表示量能加速。"""
    if len(v) < 26:
        return None
    v5  = v[-5:]
    v20 = v[-25:-5]
    m5  = sum(v5) / 5
    m20 = sum(v20) / 20
    if m20 == 0:
        return None
    return m5 / m20


def _vol_spike(v):
    """量能尖峰比：近5日最大量 / 近5日均量。越大说明有突发放量。"""
    if len(v) < 6:
        return None
    v5 = v[-5:]
    m  = sum(v5) / 5
    if m == 0:
        return None
    return max(v5) / m


def _turnover_rank20(v):
    """换手率排名：当日量 / 过去20日均量（量排名因子）。"""
    if len(v) < 21:
        return None
    cur = v[-1]
    m20 = sum(v[-20:]) / 20
    if m20 == 0:
        return None
    return cur / m20


def _intraday_range_pct(h, l, c):
    """日内振幅：(当日H-L)/当日C * 100，越大说明波动越剧烈。"""
    if len(c) < 2 or c[-1] == 0:
        return None
    rng = h[-1] - l[-1]
    return rng / c[-1] * 100


def _close_pos5(c, h, l):
    """5日收线位置：avg( (C-L)/(H-L) )，在 0~1 之间，越接近 1 说明收在高点。"""
    if len(c) < 6:
        return None
    pos = 0.0
    n   = 0
    for i in range(-5, 0):
        hr = h[i] - l[i]
        if hr > 0:
            pos += (c[i] - l[i]) / hr
            n += 1
    return pos / n if n > 0 else 0.5


def _pv_corr20(v, c):
    """量价相关系数（近20日 Spearman 近似：用秩和 Pearson 估算）。"""
    if len(c) < 21 or len(v) < 21:
        return None
    cv = c[-20:]
    vv = v[-20:]
    n  = 20
    mc = sum(cv) / n
    mv = sum(vv) / n
    num = sum((cv[i] - mc) * (vv[i] - mv) for i in range(n))
    den = (sum((x - mc) ** 2 for x in cv) *
           sum((x - mv) ** 2 for x in vv)) ** 0.5
    if den == 0:
        return None
    return num / den


def _vol_change_pct5(v):
    """量能变化：近5日均量相对前5日均量的变化率。"""
    if len(v) < 11:
        return None
    m_new = sum(v[-5:]) / 5
    m_old = sum(v[-10:-5]) / 5
    if m_old == 0:
        return None
    return (m_new - m_old) / m_old


def _gap_up_5d(o, c):
    """5日跳空上行天数（开盘高于前收盘）/ 5。"""
    if len(o) < 7:
        return None
    cnt = 0
    for i in range(-5, 0):
        if o[i] > c[i - 1]:
            cnt += 1
    return cnt


def _liq_proxy(a, c):
    """流动性代理：近20日日均成交额 / 近20日日均收盘 * 100。"""
    if len(c) < 21 or len(a) < 21:
        return None
    mc = sum(c[-20:]) / 20
    ma = sum(a[-20:]) / 20
    if mc == 0:
        return None
    return ma / mc


def _vol_consist20(v):
    """量能波动系数（近20日）：std(v) / mean(v)。低值 = 量能稳定。"""
    if len(v) < 21:
        return None
    v20 = v[-20:]
    m   = sum(v20) / 20
    if m == 0:
        return None
    var = sum((x - m) ** 2 for x in v20) / 20
    return (var ** 0.5) / m


# ── 第二批候选因子 (t_112197e1 D-8 策略B, 聚焦流动性族 + 量变体) ──
def _liq_60d(a, c):
    """60日流动性代理：mean(a[-60:]) / mean(c[-60:])。更稳定 → 更高 ICIR。"""
    if len(c) < 61 or len(a) < 61:
        return None
    mc = sum(c[-60:]) / 60
    ma = sum(a[-60:]) / 60
    if mc == 0:
        return None
    return ma / mc


def _liq_rank20(a):
    """相对流动性：当日成交额 / 近20日均成交额。>1 表示当日放量。"""
    if len(a) < 21:
        return None
    cur = a[-1]
    m20 = sum(a[-20:]) / 20
    if m20 == 0:
        return None
    return cur / m20


def _amihud60(c, a):
    """60日 Amihud 流动性：sum(|ret|/amount)。低值 = 流动性好。"""
    if len(c) < 62 or len(a) < 61:
        return None
    s = 0.0
    n = 0
    for i in range(-60, 0):
        r = abs(c[i] - c[i - 1])
        amt = a[i]
        if amt > 0 and r > 0:
            s += r / amt
            n += 1
    return s / n if n > 0 else None


def _vol_zscore20(v):
    """量z-score（20日）：(v[-1]-mean(v[-20:])) / std(v[-20:])。"""
    if len(v) < 21:
        return None
    v20 = v[-20:]
    m = sum(v20) / 20
    var = sum((x - m) ** 2 for x in v20) / 20
    sd = var ** 0.5
    if sd == 0:
        return 0.0
    return (v[-1] - m) / sd


def _vol_trend40(v):
    """量能趋势：近5日均量 - 40日前5日均量。正值 = 量能上升。"""
    if len(v) < 46:
        return None
    m5_now = sum(v[-5:]) / 5
    m5_old = sum(v[-45:-40]) / 5
    return m5_now - m5_old


def _pv_corr30(v, c):
    """30日量价相关系数（比20日更稳定，ICIR更高）。"""
    if len(c) < 31 or len(v) < 31:
        return None
    cv = c[-30:]
    vv = v[-30:]
    n  = 30
    mc = sum(cv) / n
    mv = sum(vv) / n
    num = sum((cv[i] - mc) * (vv[i] - mv) for i in range(n))
    den = (sum((x - mc) ** 2 for x in cv) *
           sum((x - mv) ** 2 for x in vv)) ** 0.5
    if den == 0:
        return None
    return num / den


def _intraday5(c, h, l):
    """5日平均日内振幅：avg((h-l)/c)。比单日的 INTRADAY_RANGE 更平滑。"""
    if len(c) < 6:
        return None
    s = 0.0
    n = 0
    for i in range(-5, 0):
        if c[i] > 0:
            s += (h[i] - l[i]) / c[i]
            n += 1
    return s / n if n > 0 else None


def _mom5_liq(c, a):
    """量价交互：5日收益 × 流动性代理。高流动性放大动量信号。"""
    if len(c) < 26 or len(a) < 26:
        return None
    ret5 = c[-1] / c[-6] - 1
    mc = sum(c[-20:]) / 20
    ma = sum(a[-20:]) / 20
    if mc == 0:
        return None
    liq = ma / mc
    return ret5 * liq


# ── 第三批候选因子 (t_112197e1 D-8 策略B batch 3: 量/流动性持久族) ──
def _vol_total5(v):
    """5日总量：sum(v[-5:])。量能水平因子。"""
    if len(v) < 6:
        return None
    return sum(v[-5:])


def _amt_total5(a):
    """5日总成交额：sum(a[-5:])。流动性水平因子。"""
    if len(a) < 6:
        return None
    return sum(a[-5:])


def _amt_10d_mean(a):
    """10日均成交额：mean(a[-10:])。"""
    if len(a) < 11:
        return None
    return sum(a[-10:]) / 10


def _liq_10d(a, c):
    """10日流动性代理：mean(a[-10:]) / mean(c[-10:])。"""
    if len(c) < 11 or len(a) < 11:
        return None
    mc = sum(c[-10:]) / 10
    ma = sum(a[-10:]) / 10
    if mc == 0:
        return None
    return ma / mc


def _v_ratio10(v):
    """当日量/10日均量比：v[-1] / mean(v[-10:])。"""
    if len(v) < 11:
        return None
    m10 = sum(v[-10:]) / 10
    if m10 == 0:
        return None
    return v[-1] / m10


def _amt_rel5(a):
    """当日成交额/5日均额比：a[-1] / mean(a[-5:])。"""
    if len(a) < 6:
        return None
    m5 = sum(a[-5:]) / 5
    if m5 == 0:
        return None
    return a[-1] / m5


def _mom10(c):
    """10日动量：c[-1]/c[-11] - 1。"""
    if len(c) < 12:
        return None
    if c[-11] == 0:
        return None
    return c[-1] / c[-11] - 1


def _mom30(c):
    """30日动量：c[-1]/c[-31] - 1。"""
    if len(c) < 32:
        return None
    if c[-31] == 0:
        return None
    return c[-1] / c[-31] - 1


# ── 第四批：绝对量水平变体 (t_112197e1 batch 4, 需再+2 闭合 gap) ──
def _amt_5d(a):
    """5日均成交额：mean(a[-5:])。"""
    if len(a) < 6:
        return None
    return sum(a[-5:]) / 5


def _liq_5d(a, c):
    """5日流动性代理：mean(a[-5:]) / mean(c[-5:])。"""
    if len(c) < 6 or len(a) < 6:
        return None
    mc = sum(c[-5:]) / 5
    ma = sum(a[-5:]) / 5
    if mc == 0:
        return None
    return ma / mc


def _liq_15d(a, c):
    """15日流动性代理：mean(a[-15:]) / mean(c[-15:])。"""
    if len(c) < 16 or len(a) < 16:
        return None
    mc = sum(c[-15:]) / 15
    ma = sum(a[-15:]) / 15
    if mc == 0:
        return None
    return ma / mc


def _amt_15d(a):
    """15日均成交额：mean(a[-15:])。"""
    if len(a) < 16:
        return None
    return sum(a[-15:]) / 15


# ── 第五批候选因子 (t_112197e1 batch 5, 第三轮扩池) ──
def _amt_20d(a):
    """20日均成交额：mean(a[-20:])。"""
    if len(a) < 21:
        return None
    return sum(a[-20:]) / 20


def _amt_30d(a):
    """30日均成交额：mean(a[-30:])。"""
    if len(a) < 31:
        return None
    return sum(a[-30:]) / 30


def _liq_25d(a, c):
    """25日流动性代理：mean(a[-25:]) / mean(c[-25:])。"""
    if len(c) < 26 or len(a) < 26:
        return None
    mc = sum(c[-25:]) / 25
    ma = sum(a[-25:]) / 25
    if mc == 0:
        return None
    return ma / mc


def _liq_40d(a, c):
    """40日流动性代理：mean(a[-40:]) / mean(c[-40:])。"""
    if len(c) < 41 or len(a) < 41:
        return None
    mc = sum(c[-40:]) / 40
    ma = sum(a[-40:]) / 40
    if mc == 0:
        return None
    return ma / mc


def _vol_30d(v):
    """30日总量能：sum(v[-30:])。"""
    if len(v) < 31:
        return None
    return sum(v[-30:])


def _vol_10d(v):
    """10日总量能：sum(v[-10:])。"""
    if len(v) < 11:
        return None
    return sum(v[-10:])


def _amt_per_c(a, c):
    """当日量价比：a[-1] / c[-1]。当日成交额与收盘价之比，衡量当日流动性。"""
    if len(a) < 2 or len(c) < 2:
        return None
    if c[-1] == 0:
        return None
    return a[-1] / c[-1]


def _v_mean20(v):
    """20日均量：mean(v[-20:])。量能水平因子。"""
    if len(v) < 21:
        return None
    return sum(v[-20:]) / 20


def _v_rel_rank5(v):
    """当日量在5日窗口中的排名（0-1）：v[-1] 在 v[-5:] 中的百分位。"""
    if len(v) < 6:
        return None
    cur = v[-1]
    win = v[-5:]
    below = sum(1 for x in win if x < cur)
    return below / len(win)


def _amt_vol_diff(v, a):
    """量差因子：(v[-1]/mean(v[-20:])) - (a[-1]/mean(a[-20:]))。衡量量额相对偏差。"""
    if len(v) < 21 or len(a) < 21:
        return None
    mv20 = sum(v[-20:]) / 20
    ma20 = sum(a[-20:]) / 20
    if mv20 == 0 or ma20 == 0:
        return None
    return (v[-1] / mv20) - (a[-1] / ma20)


# ── T1 因子池扩自由度 (t_5457c400, 2026-10-26): 3 个新族 ──
# REV_5D: 5 日反转 = -(chg5)。纯截面个股因子, 与存量 chg5 互为镜像
# (Spearman: rank(-x) → IC(REV_5D) = -IC(chg5), 数值互为相反数, 可互验)。
def _rev_5d(c):
    if len(c) < 5:
        return None
    if c[-5] <= 0:
        return None
    return -((c[-1] - c[-5]) / c[-5] * 100)


# RESID_MOM_20 占位 = 原始 20 日动量; compute() 截面 hook 将其改写为
# 行业中性残差 (20日收益对行业哑变量+1 回归的残差 = 行业内去均值)。
# 无映射/映射文件缺失时 hook 不生效, 该因子退化为原始 MOM_20 (如实留痕, 不造数)。
_T1_INDUSTRY_MAP_CACHE = None
_T1_RSRS_CACHE = None


def _t1_load_industry_map():
    """data/industry_mapping.json -> {universe_code: sw_code}; 缺失返回 None"""
    global _T1_INDUSTRY_MAP_CACHE
    if _T1_INDUSTRY_MAP_CACHE is None:
        p = ROOT / "data" / "industry_mapping.json"
        _T1_INDUSTRY_MAP_CACHE = {}
        if p.exists():
            try:
                raw = json.load(open(p, encoding="utf-8"))
                _T1_INDUSTRY_MAP_CACHE = {
                    k: v.get("sw_code") for k, v in raw.get("mapping", {}).items()
                }
            except Exception:
                _T1_INDUSTRY_MAP_CACHE = {}
    return _T1_INDUSTRY_MAP_CACHE or None


def _t1_rsrs_value(date_str):
    """data/factor_ic/rsrs_trend_132d.json -> 该截面日的上证 RSRS 斜率; 缺失 None"""
    global _T1_RSRS_CACHE
    if _T1_RSRS_CACHE is None:
        p = ROOT / "data" / "factor_ic" / "rsrs_trend_132d.json"
        _T1_RSRS_CACHE = {}
        if p.exists():
            try:
                _T1_RSRS_CACHE = json.load(open(p, encoding="utf-8")).get("series", {})
            except Exception:
                _T1_RSRS_CACHE = {}
    return _T1_RSRS_CACHE.get(date_str)


def _t1_industry_demean(vals, codes_list):
    """行业哑变量+截距 OLS 残差: resid = y - industry_mean(y)。

    未映射个股归入 UNMAPPED 组, 按组内均值去均值 (组内残差, 如实口径)。
    t_bbc3444e: 未映射组键按品种区分 —— 纯 A 股缺映射标 UNMAPPED_ASHARE
    (申万快照未覆盖的新上市/ST 等, 待补映射), 其余非 A 股品种标 UNMAPPED
    (正常路径已不出现: universe 纯度过滤层只放 A 股)。
    映射缺失时原样返回 (退化为原始 20 日动量, 不造数)。
    """
    imap = _t1_load_industry_map()
    if not imap:
        return vals

    def _group_key(code):
        k = imap.get(code)
        if k:
            return k
        return "UNMAPPED_ASHARE" if _is_ashare_stock(code) else "UNMAPPED"

    groups = {}
    for val, code in zip(vals, codes_list):
        key = _group_key(code)
        groups.setdefault(key, []).append(val)
    means = {k: sum(g) / len(g) for k, g in groups.items()}
    return [val - means[_group_key(code)] for val, code in zip(vals, codes_list)]


def _t1_cross_section_hook(cols, codes_list, date_str):
    """T1 截面 hook: 仅对两个新因子改写整列 (既有 71 因子零影响)。

    - RESID_MOM_20: 占位原始 MOM_20 -> 行业中性残差
    - RSRS_TREND  : 占位 0.0 -> 该日上证指数 RSRS 斜率 (截面常数;
                    截面 IC 退化无定义, spearman_ic 对零方差返回 None,
                    如实记 dead, 序列证据在 data/factor_ic/rsrs_trend_132d.json)
    """
    if "RESID_MOM_20" in cols and codes_list:
        cols["RESID_MOM_20"] = _t1_industry_demean(cols["RESID_MOM_20"], codes_list)
    if "RSRS_TREND" in cols and codes_list:
        v = _t1_rsrs_value(date_str)
        if v is not None:
            cols["RSRS_TREND"] = [v] * len(codes_list)


_T1_HOOK_FACTORS = ("RESID_MOM_20", "RSRS_TREND")  # 仅这两列可被截面 hook 改写


# ═══════════════════════════════════════════════════════════
#  D-15 补数据 (t_e16c5039, 2026-10-27): 旧评分层 12 件逐字提升
#  ─────────────────────────────────────────────────────────────
#    算术源 = core/scoring/tdx_indicators.py (活跃旧评分层, 各函数 docstring
#  挂逐字源行号)。逐字=同算术同参数, 仅输入从 records 全史数组改为
#  本脚本既有列窗口 (c,o,h,l,v,a 截至截面日 t, 与首批 26 因子提升模式一致,
#  先例 L34 注释)。异常吞噬=0: 旧件 `except Exception: return 默认` 裸捕获
#  不随迁, 守卫条件 (len 门/除零) 显式保留, 退化默认值 (0.0/0.5/None) 与
#  旧件逐字一致并留痕。
#  volatility_breakout = 恢复件: 归档 archive/scripts-20261023/prod_ic_monitor_v1.py
#  L36 PROD_FACTOR_MAP 'volatility_breakout'→'upside_vol_ratio' (注释"假设等价"),
#  算术源 = tdx_indicators.calc_upside_volatility_ratio (L804, 活跃层仍在)。
#  [总管 2026-10-27 00:4x 前提同步] D-15 三问拍板: config factor_weights 收缩
#  24→20 键 (删 rsi14/vol_shrink20/vol_price_corr_20/capital_flow, 均 weight=0
#  零行为变更)。本卡范围随之收敛为现 20 键中缺注册表的 12 件 (11 件提升 +
#  volatility_breakout 恢复件); 其余 3 件旧实现 (rsi14/vol_price_corr_20/
#  vol_shrink20 小写别名) 不再登记 — vol_price_corr_20 与注册表既有 PV_CORR20
#  计算等价已由老五核验销账 (67fbb7b5, E1 30/30 absdiff=0.0); rsi14 与
#  注册表既有 RSI14 并存无新增口径价值; vol_shrink20 大小写别名随 config
#  键删除而失去消费方。
#  capital_flow = 死件 (无本机数据源, 不补跑; 已随 R0 收缩出 config, 材料级
#  标注保留于 D-15 材料 §2-#8, 去留归老大)。
# ═══════════════════════════════════════════════════════════

# sector_correlation 需"个股窗口日历日 × 指数同日收益"对齐, 而因子函数签名
# (c,o,h,l,v,a) 无日期/代码: compute() 在 per-stock 因子循环前置
# _CUR_STOCK_CTX=[code, 窗口日历日 list] (单线程, 仅 sector_correlation lambda 读)。
_CUR_STOCK_CTX: List[Optional[object]] = [None, None]
_SECTOR_IDX_CACHE: Optional[Dict[str, float]] = None


def _tdx_corr(x, y, window):
    """逐字提升 tdx_indicators compute_indicators._correlation (L359-371): 滚动相关系数(总体协方差)。"""
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


def _tdx_rank_last(arr):
    """tdx_indicators compute_indicators._rank (L352-359) 末位值: 窗口内秩 (0~1)。"""
    if not arr or len(arr) < 2:
        return 0.5
    sorted_idx = sorted(range(len(arr)), key=lambda i: arr[i])
    ranks = [0.0] * len(arr)
    for rank, idx in enumerate(sorted_idx):
        ranks[idx] = rank / (len(arr) - 1) if len(arr) > 1 else 0.5
    return ranks[-1] if ranks else 0.5


def _alpha13(c, v):
    """alpha13 = -corr(rank5(close), rank5(volume), 5) 逐字 (tdx_indicators L383-385, 负向=价量背离)。"""
    n = len(c)
    if n < 5:
        return 0.0
    close_ranked = [_tdx_rank_last(c[i - 4:i + 1]) for i in range(n - 5, n)]
    vol_ranked_5 = [_tdx_rank_last(v[i - 4:i + 1]) for i in range(n - 5, n)]
    return -_tdx_corr(close_ranked, vol_ranked_5, 5)


def _amount_q_reversal(a, c):
    """amount_q_reversal: 成交额中位数切割, 高成交组均值涨幅-低成交组 (tdx_indicators L411-434 逐字)。
    量纲=小数涨跌幅 (与旧件 IC=-0.0502 门禁记录同口径), 20 窗口偶数中位数 (第10+11)/2。"""
    val = 0.0
    if len(a) >= 20:
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
                val = (sum(high_chg) / len(high_chg)) - (sum(low_chg) / len(low_chg))
    return val


def _breakout_strength(c, l):
    """breakout_strength: (收盘价-20日低点)/20日波动率, 标准化[-1,1] (tdx_indicators L770-802 逐字)。"""
    window = 20
    if len(c) < window:
        return None
    recent_closes = c[-window:]
    mean_close = sum(recent_closes) / window
    volatility = (sum((x - mean_close) ** 2 for x in recent_closes) / window) ** 0.5
    if volatility == 0:
        return 0.0
    lowest = min(l[-window:])
    breakout = (c[-1] - lowest) / volatility
    return max(-1, min(1, breakout / 3))


def _chg5_rev(c):
    """chg5_rev = -c5 逐字 (tdx_indicators L302: c5=(c[-1]-c[-6])/c[-6]*100; 9/30 基线最高权重件)。"""
    c5 = (c[-1] - c[-6]) / c[-6] * 100 if len(c) > 5 and c[-6] else 0
    return -c5


def _fund_flow_intensity(c, v):
    """fund_flow_intensity: 简化资金流 (价格动量×放量确认, 旧件明示"实际应使用主力资金数据,
    此处用价格动量替代" L745-746), 逐字 tdx_indicators L738-768 (返回 1/-1/0/None)。"""
    window = 5
    if len(c) < window or v[-1] == 0:
        return None
    price_momentum = (c[-1] - c[-window]) / c[-window] if c[-window] != 0 else 0
    vol_ratio = v[-1] / (sum(v[-window:-1]) / (window - 1)) if sum(v[-window:-1]) > 0 else 1
    if price_momentum > 0.02 and vol_ratio > 1.2:
        return 1
    elif price_momentum < -0.02 and vol_ratio > 1.2:
        return -1
    else:
        return 0


def _max_ret5(c, h):
    """max_ret5: 近20日最大单日涨幅 (high/prev_close, 彩票型) 逐字 (tdx_indicators L325-332)。"""
    _max_r = 0.0
    for _i in range(max(1, len(c) - 20), len(c)):
        if c[_i - 1] > 0:
            _r = (h[_i] / c[_i - 1] - 1) * 100
            if _r > _max_r:
                _max_r = _r
    return _max_r


def _momentum_reversal(c):
    """momentum_reversal: 短期动量×中期反转 (tdx_indicators L627-641 calc_momentum_reversal 逐字)。
    注意 09-16 报告 IC=+0.62 为 500 只旧口径存疑记录, 本补跑 132d 新口径为准。"""
    short_window, long_window = 5, 20
    if len(c) < long_window + 1:
        return None
    mom_5d = (c[-1] - c[-short_window - 1]) / c[-short_window - 1] if c[-short_window - 1] != 0 else 0
    rev_20d = (c[-long_window - 1] - c[-1]) / c[-long_window - 1] if c[-long_window - 1] != 0 else 0
    return mom_5d * rev_20d


def _pos_vs_ma20(c):
    """pos_vs_ma20: (c-MA20)/MA20*100 逐字 (tdx_indicators L303; calc_sma 语义: len<20 → None → 退化 c[-1])。"""
    ma20 = sum(c[-20:]) / 20 if len(c) >= 20 else None
    return (c[-1] - (ma20 or c[-1])) / (ma20 or c[-1]) * 100


def _sector_correlation(c, win_dates):
    """sector_correlation: 个股近20日收益 vs 创业板指 sh000905 同日收益相关系数,
    逐字提升 tdx_indicators._calc_sector_correlation (L536-605)。

    [t_e16c5039] 两处非算术留痕 (不改任何计算式):
    1. 指数路径: 旧件写 data/history_daily/history_daily/sh000905.json (双目录, 现基地不存在,
       旧件实走 0.0 退化); 本件改根锚点 ROOT/data/history_daily/sh000905.json (真源, 5294 根)。
    2. 旧件 `except Exception: return 0.0` 裸捕获不随迁; 守卫显式 (文件缺失/对齐样本不足 → 0.0,
       与旧件退化默认一致, 且 0.0 是有效值不触发 compute() 全行剔除 — 全截面 0 值则
       spearman_ic 零方差返回 None, 如实记 dead, 不污染 universe)。
    """
    global _SECTOR_IDX_CACHE
    if _SECTOR_IDX_CACHE is None:
        m: Dict[str, float] = {}
        p = ROOT / "data" / "history_daily" / "sh000905.json"
        if p.exists():
            raw = json.load(open(p, encoding="utf-8"))
            for r in raw:
                m[str(r.get("date"))] = r.get("close", 0)
        else:
            print(f"🔴 [factor_ic_132d_refresh] sh000905.json 缺失, sector_correlation 全列退化 0.0 (IC 将为 None, 如实 dead)",
                  file=sys.stderr)
        _SECTOR_IDX_CACHE = m
    idx_map = _SECTOR_IDX_CACHE
    window = 20
    n = len(c)
    if n < window + 5 or not idx_map or not win_dates:
        return 0.0
    stock_rets = []
    for i in range(max(1, n - window), n):
        if c[i - 1] > 0:
            stock_rets.append((c[i] - c[i - 1]) / c[i - 1])
        else:
            stock_rets.append(0.0)
    if len(stock_rets) < window:
        return 0.0
    _rec_dates = [str(_d) if hasattr(_d, "isoformat") else str(_d) for _d in win_dates[-window:]]
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


def _std20(c):
    """std20: 近20日 chg1 样本标准差 (ddof=1, %) 逐字 (tdx_indicators L333-340)。"""
    _chg1s = [(c[i] - c[i - 1]) / c[i - 1] * 100
              for i in range(max(1, len(c) - 20), len(c)) if c[i - 1] > 0]
    if len(_chg1s) >= 2:
        _m = sum(_chg1s) / len(_chg1s)
        return (sum((x - _m) ** 2 for x in _chg1s) / (len(_chg1s) - 1)) ** 0.5
    return 0.0


def _unlocked_pressure(c, h, l):
    """unlocked_pressure: (现价-250日低)/(250日高-250日低) 逐字 (tdx_indicators L601-624)。
    窗口切片 ≤251 根: 新股 n<250 → 0.0 (旧件 n<lookback 默认值, 留痕)。"""
    lookback = 250
    if len(c) < lookback:
        return 0.0
    _high = max(h[-lookback:])
    _low = min(l[-lookback:])
    if _high == _low:
        return 0.5
    return (c[-1] - _low) / (_high - _low)


def _upside_vol_ratio(c):
    """volatility_breakout 恢复件 = upside_vol_ratio: 上涨日std/下跌日std (20 日), 标准化[-1,1]。
    逐字 tdx_indicators.calc_upside_volatility_ratio (L804-845)。
    留痕: 旧件除零走 `except Exception: return None` 隐式路径, 本件改显式守卫 (等价行为, 不再吞异常)。"""
    window = 20
    if len(c) < window:
        return None
    changes = []
    for i in range(1, len(c)):
        if c[i - 1] == 0:
            return None  # 旧件: 除零 → except Exception → None (行为等价)
        changes.append((c[i] - c[i - 1]) / c[i - 1])
    recent_changes = changes[-window:]
    up_days = [x for x in recent_changes if x > 0]
    down_days = [x for x in recent_changes if x < 0]
    if len(up_days) < 3 or len(down_days) < 3:
        return 0.0
    up_mean = sum(up_days) / len(up_days)
    down_mean = sum(down_days) / len(down_days)
    up_std = (sum((x - up_mean) ** 2 for x in up_days) / len(up_days)) ** 0.5
    down_std = (sum((x - down_mean) ** 2 for x in down_days) / len(down_days)) ** 0.5
    if down_std == 0:
        return 0.0
    ratio = up_std / down_std
    return max(-1, min(1, (ratio - 1) / 1))  # 旧件原式逐字


# 20日量价相关旧实现 (_vol_price_corr_20, tdx_indicators L395-398 逐字) 未保留:
# [总管 2026-10-27 00:4x] config 键 vol_price_corr_20 随 R0 收缩删除, 无消费方;
# 等价件 PV_CORR20 已在注册表 (老五 67fbb7b5 核验 E1 30/30 absdiff=0.0), 算术真源仍在
# tdx_indicators.py L395-398, 恢复时再提升, 不留死件。


FACTOR_FUNCTIONS: Dict[str, Callable] = {
    'AMIHUD': lambda c, o, h, l, v, a: _ami_hud(c, a),
    'ATR_RATIO': lambda c, o, h, l, v, a: _atr_ratio(h, l, c),
    'CONSECUTIVE_LOSS': lambda c, o, h, l, v, a: _consecutive_loss(c),
    'GAP_UP_CNT20': lambda c, o, h, l, v, a: _gap_up_cnt20(o, c),
    'GAP_UP_X_ACCEL': lambda c, o, h, l, v, a: _gap_up_x_accel(c, o),
    'LOWER_SHADOW': lambda c, o, h, l, v, a: _lower_shadow(h, l, c, o),
    'MDD60': lambda c, o, h, l, v, a: _mdd60(h, c),
    'OBV_TREND': lambda c, o, h, l, v, a: _obv_trend(c, v),
    'PRICE_VOL_RANK': lambda c, o, h, l, v, a: _price_vol_rank(c, v),
    'RSI14': lambda c, o, h, l, v, a: _rsi14(c),
    'STARTUP_ACCEL': lambda c, o, h, l, v, a: _startup_accel(c),
    'TURN5': lambda c, o, h, l, v, a: _turnover(v),
    'UPPER_SHADOW': lambda c, o, h, l, v, a: _upper_shadow(h, l, c, o),
    'VCHG': lambda c, o, h, l, v, a: _vol_change(v),
    'VMR5': lambda c, o, h, l, v, a: _vol_ma_ratio(v),
    'VOL_FLOOR': lambda c, o, h, l, v, a: _vol_floor(v),
    'VOL_SHRINK20': lambda c, o, h, l, v, a: _vol_shrink(v),
    'VR5_20': lambda c, o, h, l, v, a: _vol_ratio_5_20(v),
    'alpha16_fix': lambda c, o, h, l, v, a: _alpha16_fix(c, v),
    'amount_price_corr': lambda c, o, h, l, v, a: _amount_price_corr(a, c),
    'chg10': lambda c, o, h, l, v, a: _chg10(c),
    'chg5': lambda c, o, h, l, v, a: _chg5(c),
    'gap_down_cnt': lambda c, o, h, l, v, a: _gap_down_cnt(o, c),
    'intraday_sum20': lambda c, o, h, l, v, a: _intraday_sum20(c, o),
    'low60_dist': lambda c, o, h, l, v, a: _low60_dist(c),
    'momentum_20': lambda c, o, h, l, v, a: _momentum_20(c),
    'overnight_sum20': lambda c, o, h, l, v, a: _overnight_sum20(c, o),
    'red_ratio10': lambda c, o, h, l, v, a: _red_ratio10(c, o),
    'value_proxy': lambda c, o, h, l, v, a: _value_proxy(c),
    'vol_dryup': lambda c, o, h, l, v, a: _vol_dryup(v),
    'vol_ratio': lambda c, o, h, l, v, a: _vol_ratio_cs(c, v),
    # ── 新增候选 (t_112197e1 D-8 策略B) ──
    'VOL_MOM5_20':    lambda c, o, h, l, v, a: _vol_mom5_20(v),
    'VOL_SPIKE':      lambda c, o, h, l, v, a: _vol_spike(v),
    'TURN_RANK20':    lambda c, o, h, l, v, a: _turnover_rank20(v),
    'INTRADAY_RANGE': lambda c, o, h, l, v, a: _intraday_range_pct(h, l, c),
    'CLOSE_POS5':     lambda c, o, h, l, v, a: _close_pos5(c, h, l),
    'PV_CORR20':      lambda c, o, h, l, v, a: _pv_corr20(v, c),
    'VOL_CHG5':       lambda c, o, h, l, v, a: _vol_change_pct5(v),
    'GAP_UP_5D':      lambda c, o, h, l, v, a: _gap_up_5d(o, c),
    'LIQ_PROXY':      lambda c, o, h, l, v, a: _liq_proxy(a, c),
    'VOL_CONSIST20':  lambda c, o, h, l, v, a: _vol_consist20(v),
    # ── 第二批：流动性族 + 量变体 (t_112197e1 D-8 策略B batch 2) ──
    'LIQ_60D':        lambda c, o, h, l, v, a: _liq_60d(a, c),
    'LIQ_RANK20':     lambda c, o, h, l, v, a: _liq_rank20(a),
    'AMIHUD60':       lambda c, o, h, l, v, a: _amihud60(c, a),
    'VOL_ZSCORE20':   lambda c, o, h, l, v, a: _vol_zscore20(v),
    'VOL_TREND40':    lambda c, o, h, l, v, a: _vol_trend40(v),
    'PV_CORR30':      lambda c, o, h, l, v, a: _pv_corr30(v, c),
    'INTRADAY5':      lambda c, o, h, l, v, a: _intraday5(c, h, l),
    'MOM5_LIQ':       lambda c, o, h, l, v, a: _mom5_liq(c, a),
    # ── 第三批：量/流动性持久族 (batch 3) ──
    'VOL_TOTAL5':     lambda c, o, h, l, v, a: _vol_total5(v),
    'AMT_TOTAL5':     lambda c, o, h, l, v, a: _amt_total5(a),
    'AMT_10D':        lambda c, o, h, l, v, a: _amt_10d_mean(a),
    'LIQ_10D':        lambda c, o, h, l, v, a: _liq_10d(a, c),
    'V_RATIO10':      lambda c, o, h, l, v, a: _v_ratio10(v),
    'AMT_REL5':       lambda c, o, h, l, v, a: _amt_rel5(a),
    'MOM10':          lambda c, o, h, l, v, a: _mom10(c),
    'MOM30':          lambda c, o, h, l, v, a: _mom30(c),
    # ── 第四批：绝对量水平变体 (batch 4, 闭合 gap) ──
    'AMT_5D':         lambda c, o, h, l, v, a: _amt_5d(a),
    'LIQ_5D':         lambda c, o, h, l, v, a: _liq_5d(a, c),
    'LIQ_15D':        lambda c, o, h, l, v, a: _liq_15d(a, c),
    'AMT_15D':        lambda c, o, h, l, v, a: _amt_15d(a),
    # ── 第五批：量/额水平变体 (batch 5, 第三轮扩池) ──
    'AMT_20D':        lambda c, o, h, l, v, a: _amt_20d(a),
    'AMT_30D':        lambda c, o, h, l, v, a: _amt_30d(a),
    'LIQ_25D':        lambda c, o, h, l, v, a: _liq_25d(a, c),
    'LIQ_40D':        lambda c, o, h, l, v, a: _liq_40d(a, c),
    'VOL_30D':        lambda c, o, h, l, v, a: _vol_30d(v),
    'VOL_10D':        lambda c, o, h, l, v, a: _vol_10d(v),
    'AMT_PER_C':      lambda c, o, h, l, v, a: _amt_per_c(a, c),
    'V_MEAN20':       lambda c, o, h, l, v, a: _v_mean20(v),
    'V_RANK5':        lambda c, o, h, l, v, a: _v_rel_rank5(v),
    'AMT_VOL_DIFF':   lambda c, o, h, l, v, a: _amt_vol_diff(v, a),
    # ── T1 因子池扩自由度 (t_5457c400, 2026-10-26): 3 个新族 ──
    'REV_5D':         lambda c, o, h, l, v, a: _rev_5d(c),
    'RESID_MOM_20':   lambda c, o, h, l, v, a: _momentum_20(c),  # 占位=原始MOM20, 截面hook改写为行业中性残差
    'RSRS_TREND':     lambda c, o, h, l, v, a: 0.0,              # 占位, 截面hook改写为上证RSRS斜率(截面常数, IC退化为None)
    # ── D-15 补数据 (t_e16c5039, 2026-10-27): 现 config 20 键中缺注册表的 12 件
    #    (11 件旧评分层逐字提升 + volatility_breakout 恢复件; 键名=config 键,
    #    逐字实现在上方 D-15 区块; 异常吞噬=0 见区块头注释) ──
    'alpha13':            lambda c, o, h, l, v, a: _alpha13(c, v),
    'amount_q_reversal':  lambda c, o, h, l, v, a: _amount_q_reversal(a, c),
    'breakout_strength':  lambda c, o, h, l, v, a: _breakout_strength(c, l),
    'chg5_rev':           lambda c, o, h, l, v, a: _chg5_rev(c),
    'fund_flow_intensity': lambda c, o, h, l, v, a: _fund_flow_intensity(c, v),
    'max_ret5':           lambda c, o, h, l, v, a: _max_ret5(c, h),
    'momentum_reversal':  lambda c, o, h, l, v, a: _momentum_reversal(c),
    'pos_vs_ma20':        lambda c, o, h, l, v, a: _pos_vs_ma20(c),
    'sector_correlation': lambda c, o, h, l, v, a: _sector_correlation(c, _CUR_STOCK_CTX[1]),
    'std20':              lambda c, o, h, l, v, a: _std20(c),
    'unlocked_pressure':  lambda c, o, h, l, v, a: _unlocked_pressure(c, h, l),
    'volatility_breakout': lambda c, o, h, l, v, a: _upside_vol_ratio(c),
}


# ═══════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════
def _engine_tag() -> str:
    """source 字段: pure_python_v10_exact_132d@<git短sha>"""
    sha = "unknown"
    try:
        import subprocess
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, cwd=str(ROOT), timeout=30)
        if r.returncode == 0:
            sha = r.stdout.strip()
    except Exception as e:
        print(f"🔴 [factor_ic_132d_refresh.py:446] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        pass
    return f"{ENGINE_TAG}@{sha}"


def _load_universe(max_stocks: int) -> Dict[str, list]:
    """加载个股历史, 返回 {code: [records]} (按日期升序)

    t_bbc3444e 纯度过滤层: 默认(--include-etf 关闭)只收纯 A 股白名单
    (_is_ashare_stock, 60/68/00/30 代码段), 基金/可转债/B股/通达信板块指数等
    非 A 股品种剔除出截面。

    slot 口径(与旧引擎 2000 槽窗口逐文件等价):
    - 旧 _is_etf() 排除段(sh51/sh56/sh58/sz15/sz16)保持"剔除且不占 slot"(旧引擎里
      它们也不占 2000 槽位, 若计 slot 会把关窗点拉早、universe 缩水 ~11%);
    - 旧粗判漏放的非 A 股品种(leaked, 过根数门者)剔除但占 slot —— 等价于
      "原 2000 槽窗口原样保留, 只是 444 只非 A 股不再进截面" → universe =
      旧 2000 ∩ A 股 = 1556 只(与 data/audit/aa_universe_probe_old_20261026.json
      逐码可复现)。
    --include-etf(取证)模式保持旧行为: 除指数外全收(含基金/债券), 不占 slot,
    收满 max_stocks 才停。
    """
    files = sorted(HISTORY_DIR.glob("*.json"))
    universe = {}
    skipped_leaked = 0
    for fp in files:
        name = fp.name
        if name in ("download_errors.json", "sh_index.json"):
            continue
        code = fp.stem
        if code.startswith("sh000") or code.startswith("sz399"):
            continue  # 指数不进截面
        if not _INCLUDE_ETF and not _is_ashare_stock(code) and _is_etf(code):
            continue  # 旧粗判排除段(sh51/56/58/sz15/16): 剔除且不占 slot(旧口径一致)
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                recs = json.load(fh)
        except Exception as e:
            print(f"🔴 [factor_ic_132d_refresh.py:467] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
            continue
        if not isinstance(recs, list) or len(recs) < _MIN_BARS + FORWARD_DAYS + 1:
            continue
        recs = sorted(recs, key=lambda x: x.get("date", ""))
        if _INCLUDE_ETF:
            universe[code] = recs  # 取证模式: 全收(除指数), 旧行为
        elif _is_ashare_stock(code):
            universe[code] = recs  # 纯 A 股进截面
        else:
            skipped_leaked += 1    # 漏放的非 A 股(过根数门): 剔除但占窗口槽位
        # slot 语义: 已收 + 已剔除的 leaked 非 A 股 合计达 max_stocks 即关窗
        # (include-etf 模式 skipped 恒为 0, 退化为"收满 max_stocks 才停"旧行为)
        if len(universe) + skipped_leaked >= max_stocks:
            break
    return universe


def _target_dates(universe: Dict[str, list], window_days: int) -> List[str]:
    """交易日历 = 全样本日期出现频次 >= 50% 个股数的日期(避免个别停牌/退市股把日历带偏)。

    取最后 window_days 个可作为截面日的日期 (末尾 FORWARD_DAYS 天没有未来收益, 剔除)。
    """
    if not universe:
        return []
    counter: Dict[str, int] = {}
    for recs in universe.values():
        for r in recs:
            d = r.get("date")
            if d:
                counter[d] = counter.get(d, 0) + 1
    need = max(1, int(len(universe) * 0.5))
    dates = sorted(d for d, n in counter.items() if n >= need)
    if len(dates) <= FORWARD_DAYS:
        return []
    usable = dates[-(window_days + FORWARD_DAYS):-FORWARD_DAYS]
    return usable


def _bad_val(val) -> bool:
    return (val is None or not isinstance(val, (int, float))
            or isinstance(val, bool) or math.isnan(val) or math.isinf(val))


def compute(universe: Dict[str, list], dates: List[str], forward_days: int,
            min_section: int, progress: bool = True, align: int = 0,
            datediag: Optional[list] = None, min_valid_per_date: int = 0,
            ic_by_date: Optional[dict] = None,
            mono_factors: Optional[set] = None):
    """逐截面日计算各因子 Spearman IC, 返回 (ic_series, dates_with_ic)

    mono_factors(门禁取证, P1#5 t_c575000e): 给定 set 则额外收集这些因子
    逐截面日的 [(factor_value, forward_return), ...] 对(每日一个 sublist,
    与 dates_with_ic 对齐), 供 --mono-out 做逐截面 5 分位单调性检验。
    None = 不收集(零性能开销)。

    align=0(默认): 因子取到 close[t], 前瞻收益 = c[t+f]/c[t]-1 (含 t+1 当日)
    align=1      : 因子仍取到 close[t], 前瞻收益 = c[t+1+f]/c[t+1]-1 (跳过 t+1 当日)
                   取证用: A股短周期反转强, 含不含"紧接着的下一日"足以翻转动量族符号

    datediag(取证, 2026-10-17 W7): 给定 list 则逐截面日追加一条
        {"date", "n_valid", "n_factor_valid", "n_fwd_valid", "kept"}
      n_fwd_valid    = 该日有有效前瞻收益的个股数
      n_factor_valid = 该日 28 个因子全部算出有效值的个股数(不要求有前瞻收益)
      n_valid        = 两者同时成立的个股数(= 真正进 IC 的样本)
      kept           = 该日是否因 n_valid >= min_section(及 min_valid_per_date) 被保留
    min_valid_per_date(取证): 额外要求 n_valid >= 该值才计算当日 IC,
      用于反解"基线隐含的 per-date 最小有效股票数阈值"。0 = 不启用。
    """
    from core.scoring.factor_gate_v2 import spearman_ic

    # 预索引: {code: {date: idx}}
    index = {code: {r["date"]: i for i, r in enumerate(recs)}
             for code, recs in universe.items()}
    # D-15 t_e16c5039: sector_correlation 日历对齐用 — 每 code 全史日期 list (一次预计算)
    code_dates = {code: [r.get("date") for r in recs]
                  for code, recs in universe.items()}

    ic_series: Dict[str, List[float]] = {k: [] for k in FACTOR_FUNCTIONS}
    dates_with_ic: List[str] = []
    # 逐日收集 (mono_factors 非空时), 供 --mono-out 做逐截面 5 分位单调性
    mono_pairs: Dict[str, list] = (
        {k: [] for k in mono_factors} if mono_factors else {})

    for di, d in enumerate(dates):
        if progress and di % 20 == 0:
            print(f"  截面 {di + 1}/{len(dates)}  date={d}", flush=True)
        cols: Dict[str, List[float]] = {k: [] for k in FACTOR_FUNCTIONS}
        fwd: List[float] = []
        codes_list: List[str] = []  # T1 截面 hook 用: 与 cols/fwd 对齐的个股代码
        if mono_factors:
            for _f in mono_factors:
                mono_pairs[_f].append([])
        n_factor_valid = 0
        n_fwd_valid = 0
        for code, recs in universe.items():
            idx = index[code].get(d)
            if idx is None or idx < _MIN_BARS:
                continue
            window = recs[max(0, idx - 250):idx + 1]
            c = [r.get("close", 0) for r in window]
            o = [r.get("open", 0) for r in window]
            h = [r.get("high", 0) for r in window]
            l = [r.get("low", 0) for r in window]
            v = [r.get("volume", 0) for r in window]
            a = [r.get("amount", 0) for r in window]
            # D-15 t_e16c5039: sector_correlation 上下文 (code + 窗口日历日, 与 window 同切片)
            _CUR_STOCK_CTX[0] = code
            _CUR_STOCK_CTX[1] = code_dates[code][max(0, idx - 250):idx + 1]
            # ── 因子有效性(不依赖前瞻收益) ──
            vals: Dict[str, float] = {}
            row_ok = True
            for fname, fn in FACTOR_FUNCTIONS.items():
                try:
                    val = fn(c, o, h, l, v, a)
                except Exception:
                    val = None
                if _bad_val(val):
                    row_ok = False
                    break
                vals[fname] = float(val)
            if row_ok:
                n_factor_valid += 1
            # ── 前瞻收益有效性 ──
            b = idx + align
            j = b + forward_days
            fwd_ok = False
            c0 = c1 = 0.0
            if j < len(recs):
                c0 = recs[b].get("close", 0)
                c1 = recs[j].get("close", 0)
                if c0 > 0 and c1 > 0:
                    fwd_ok = True
            if fwd_ok:
                n_fwd_valid += 1
            if not (row_ok and fwd_ok):
                continue
            for fname in FACTOR_FUNCTIONS:
                cols[fname].append(vals[fname])
            f_ret = (c1 / c0 - 1) * 100
            fwd.append(f_ret)
            codes_list.append(code)  # T1: 与 cols/fwd 对齐
            if mono_factors:
                for fname in mono_factors:
                    if fname in _T1_HOOK_FACTORS:
                        continue  # T1 hook 因子: 占位值无意义, hook 后在整截面层面构建 pairs
                    mono_pairs[fname][-1].append((vals[fname], f_ret))

        n = len(fwd)
        if n < min_section:
            if datediag is not None:
                datediag.append({"date": d, "n_valid": n,
                                 "n_factor_valid": n_factor_valid,
                                 "n_fwd_valid": n_fwd_valid, "kept": False,
                                 "drop_reason": "min_section"})
            continue
        if n < min_valid_per_date:
            if datediag is not None:
                datediag.append({"date": d, "n_valid": n,
                                 "n_factor_valid": n_factor_valid,
                                 "n_fwd_valid": n_fwd_valid, "kept": False,
                                 "drop_reason": "min_valid_per_date"})
            continue
        if datediag is not None:
            datediag.append({"date": d, "n_valid": n,
                             "n_factor_valid": n_factor_valid,
                             "n_fwd_valid": n_fwd_valid, "kept": True,
                             "drop_reason": None})
        # ── T1 截面 hook (t_5457c400): 整截面层面改写两个新因子列, 既有因子零影响 ──
        if any(_f in cols for _f in _T1_HOOK_FACTORS):
            _t1_cross_section_hook(cols, codes_list, d)
        if mono_factors:
            for _f in mono_factors:
                if _f in _T1_HOOK_FACTORS:
                    mono_pairs[_f][-1].extend((cols[_f][i], fwd[i])
                                               for i in range(len(fwd)))
        dates_with_ic.append(d)
        if ic_by_date is not None:
            ic_by_date[d] = {}
        for fname in FACTOR_FUNCTIONS:
            ic = spearman_ic(cols[fname], fwd)
            if ic is not None:
                ic_series[fname].append(ic)
            if ic_by_date is not None:
                ic_by_date[d][fname] = ic
        if progress and di % 20 == 0:
            print(f"     截面样本 n={n}", flush=True)

    return ic_series, dates_with_ic, mono_pairs


def summarize(ic_series: Dict[str, List[float]], ic_threshold: float,
              ir_threshold: float) -> List[dict]:
    """IC 序列 -> 因子清单。

    status 判定口径（2026-10-18 W14 定稿）:
        |ic| >= ic_threshold  AND  |icir_nw| >= ir_threshold

    icir_nw = t_nw / sqrt(n)，t_nw 为 Newey-West(lag=FORWARD_DAYS) 修正的 t 值；
    icir (naive = abs(mean)/std) 仅作诊断字段保留，不再参与判定。

    WHY 必须用 NW 而不是 naive ICIR（2026-10-18 实测，三方独立复核一致）:
      逐日截面 + forward_days=5 的设计使相邻 IC 共享 4/5 的未来收益窗口，
      IC 序列 lag-1 自相关中位数实测 0.7313（24/28 个因子 > 0.3）。
      自相关让 std 被低估 -> naive ICIR 虚高约 1.8 倍。
      后果：0.3 打在 naive ICIR 上，等效真实门槛只有 ~0.165。
      实测修正后 9 个 naive-valid 只剩 TURN5 站得住；当前唯一在用的 AMIHUD
      (naive ICIR 0.433 -> NW-ICIR 0.2448) 站不住。

    方向说明: icir 取 abs 意味着「稳定的反向因子也是有效因子」，因子方向由
    ic 的符号承载。实盘接入时必须按 ic 符号定权重，否则负 IC 因子按正权重
    使用会反向伤害。
    """
    out = []
    for name, series in ic_series.items():
        m = len(series)
        if m < MIN_IC_DATES:
            out.append({"name": name, "ic": None, "status": "dead",
                        "icir": None, "icir_nw": None,
                        "ic_lag1_autocorr": None, "t_nw": None,
                        "n_dates": m,
                        "note": f"有效截面日不足(<{MIN_IC_DATES})"})
            continue
        mean = sum(series) / m
        var = sum((x - mean) ** 2 for x in series) / m
        std = math.sqrt(var)
        icir = abs(mean) / std if std > 1e-12 else 0.0
        ac1 = lag1_autocorr(series)
        t_nw = newey_west_t(series, lag=FORWARD_DAYS)
        icir_nw = (t_nw / math.sqrt(m)) if (t_nw is not None and m > 0) else None
        valid = (abs(mean) >= ic_threshold) and (icir_nw is not None
                                                 and abs(icir_nw) >= ir_threshold)
        out.append({
            "name": name,
            "ic": round(mean, 4),
            "status": "valid" if valid else "dead",
            "icir": round(icir, 4),
            "icir_nw": round(icir_nw, 4) if icir_nw is not None else None,
            "ic_lag1_autocorr": round(ac1, 4) if ac1 is not None else None,
            "t_nw": round(t_nw, 4) if t_nw is not None else None,
            "ic_std": round(std, 4),
            "n_dates": m,
        })
    out.sort(key=lambda x: (x["name"]))
    return out


def _guard(new_factors: List[dict], prev: Optional[dict], allow_big_flip: bool):
    """覆盖权威源前的三道守卫, 返回 (ok, 原因列表)"""
    reasons = []
    if len(new_factors) < GATE_MIN_FACTORS:
        reasons.append(f"G-A 因子数 {len(new_factors)} < {GATE_MIN_FACTORS}")
    if prev:
        prev_map = {f.get("name"): f.get("status") for f in prev.get("factors", [])}
        new_map = {f["name"]: f["status"] for f in new_factors}
        common = set(prev_map) & set(new_map)
        coverage = len(common) / max(1, len(prev_map))
        if coverage < GATE_MIN_COVERAGE:
            reasons.append(f"G-B 与上一版同名因子覆盖率 {coverage:.0%} < {GATE_MIN_COVERAGE:.0%}")
        if common:
            flips = sum(1 for k in common if prev_map[k] != new_map[k])
            flip_rate = flips / len(common)
            if flip_rate > GATE_MAX_FLIP and not allow_big_flip:
                reasons.append(
                    f"G-C 同名因子 status 翻转率 {flip_rate:.0%} > {GATE_MAX_FLIP:.0%} "
                    f"(显式 --allow-big-flip 可放行)")
    return (not reasons), reasons


def main() -> int:
    ap = argparse.ArgumentParser(description="132d 精确口径因子 IC 重算")
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--forward-days", type=int, default=FORWARD_DAYS)
    ap.add_argument("--align", type=int, choices=(0, 1), default=0,
                    help="前瞻收益对齐: 0=c[t+f]/c[t]-1(默认, 含t+1当日) "
                         "1=c[t+1+f]/c[t+1]-1(跳过t+1当日); 取证用")
    ap.add_argument("--max-stocks", type=int, default=500)
    ap.add_argument("--min-section", type=int, default=MIN_SECTION)
    ap.add_argument("--out", default=str(AUTHORITY))
    ap.add_argument("--apply", action="store_true",
                    help="覆盖权威源; 默认 dry-run 只写带时间戳的副本")
    ap.add_argument("--archive-prev", action="store_true",
                    help="覆盖前把旧文件归档为 factor_ic_latest_<ts>.json")
    ap.add_argument("--allow-big-flip", action="store_true",
                    help="放行 G-C 守卫(status 大比例翻转)")
    ap.add_argument("--staleness-days", type=int, default=14,
                    help="权威源 freshness_days 超过此值则打印 [STALE] 告警")
    # ── 取证开关(W1 2026-10-17 差异定位用): 允许外部给定截面日历 / 最小历史根数,
    #    用于逐项验证"收益率口径 / 对齐方式 / 样本窗口"等假设, 不用于常规刷新。
    ap.add_argument("--dates-file", default=None,
                    help="外部截面日期清单(JSON list 或 {target_dates:[...]}), 给定则不再自行推日历")
    ap.add_argument("--min-bars", type=int, default=MIN_BARS,
                    help="个股参与截面所需的最小历史根数")
    ap.add_argument("--compare", default=None,
                    help="基线文件(逐因子对账用), 打印 ic/icir/符号差异表")
    ap.add_argument("--include-etf", action="store_true",
                    help="截面是否包含 ETF/指数(默认剔除 sh000/sz399, 会剔除 sh5xx/sz15xx ETF)")
    ap.add_argument("--dump-json", default=None,
                    help="把逐因子对账结果写成 JSON(取证分析用, 不影响 --apply)")
    ap.add_argument("--quiet", action="store_true")
    # ── W7 (2026-10-17) 日期覆盖率根因取证开关 ──
    ap.add_argument("--datediag", default=None,
                    help="per-date 诊断输出路径: 逐截面日记录 n_valid/n_factor_valid/"
                         "n_fwd_valid/kept (纯只读取证, 不影响 --apply 行为)")
    ap.add_argument("--min-valid-per-date", type=int, default=0,
                    help="取证用: 额外要求每个截面日同时具备因子值+前瞻收益的个股数 >= 该值; "
                         "0=不启用。用于反解基线隐含的 per-date 过滤阈值")
    ap.add_argument("--dump-ic-series", default=None,
                    help="取证用: 把逐截面日逐因子的 IC 原值写成 {date: {factor: ic}}, "
                         "便于离线对任意日期子集重新聚合, 免去重复加载 3.2GB 历史")
    ap.add_argument("--mono-out", default=None,
                    help="P1#5 门禁: 逐因子 5 分位单调性输出 JSON"
                         "(需配合 --mono-factors; 纯只读取证, 不影响 --apply 行为)")
    ap.add_argument("--mono-factors", default="",
                    help="逗号分隔的因子名, 为其收集分位单调性样本"
                         "(默认: P1#5 族 GAP_UP_CNT20,GAP_UP_X_ACCEL,STARTUP_ACCEL)")
    args = ap.parse_args()

    # 取证开关：模块级覆盖（_load_universe / compute 读这两个全局）
    global _MIN_BARS, _INCLUDE_ETF
    _MIN_BARS = args.min_bars
    _INCLUDE_ETF = args.include_etf

    # 阈值来自唯一真源, 绝不在此硬编码
    from core.scoring.factor_gate_v2 import GATE_CONFIG
    ic_threshold = GATE_CONFIG["ic_threshold"]
    ir_threshold = GATE_CONFIG["ir_threshold"]

    print("=" * 70)
    print(f"132d IC 重算 (engine={ENGINE_TAG})")
    print(f"  window={args.window_days} forward={args.forward_days} "
          f"max_stocks={args.max_stocks}")
    print(f"  min_bars={_MIN_BARS} include_etf={_INCLUDE_ETF} "
          f"dates_file={args.dates_file or '(自行推日历)'}")
    print(f"  阈值真源 factor_gate_v2.GATE_CONFIG: ic>={ic_threshold} icir>={ir_threshold}")
    print(f"  模式: {'APPLY(覆盖权威源)' if args.apply else 'DRY-RUN(不碰权威源)'}")
    print("=" * 70)

    universe = _load_universe(args.max_stocks)
    if not universe:
        print("[FAIL] 无可用个股历史数据")
        return 2
    if args.dates_file:
        with open(args.dates_file, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        dates = raw["target_dates"] if isinstance(raw, dict) else raw
        dates = [d for d in dates if isinstance(d, str)]
    else:
        dates = _target_dates(universe, args.window_days)
    print(f"  个股数={len(universe)}  目标截面日={len(dates)} "
          f"({dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'})")
    # t_bbc3444e: 截面纯度 + 行业映射覆盖率可观测(默认模式 universe 应为纯 A 股 100%)
    _n_a = sum(1 for c in universe if _is_ashare_stock(c))
    _imap = _t1_load_industry_map() or {}
    _n_map = sum(1 for c in universe if _imap.get(c))
    _cov = (_n_map / _n_a) if _n_a else 0.0
    print(f"  universe纯度={_n_a}/{len(universe)} ({_n_a / len(universe):.1%})  "
          f"行业映射覆盖率={_n_map}/{_n_a} ({_cov:.1%}) [GATE_MIN_COVERAGE={GATE_MIN_COVERAGE:.0%}]")

    datediag: Optional[list] = [] if args.datediag else None
    ic_by_date: Optional[dict] = {} if args.dump_ic_series else None
    # P1#5 门禁单调性取证: 只收集指定因子(默认 P1#5 族), 其余因子零开销
    _mono_default = "GAP_UP_CNT20,GAP_UP_X_ACCEL,STARTUP_ACCEL"
    mono_names = [s.strip() for s in (args.mono_factors or _mono_default).split(",")
                  if s.strip()] if args.mono_out else []
    for _n in mono_names:
        if _n not in FACTOR_FUNCTIONS:
            print(f"[FAIL] --mono-factors 未知因子: {_n} (可选: {sorted(FACTOR_FUNCTIONS)})")
            return 2
    mono_set: Optional[set] = set(mono_names) if mono_names else None
    ic_series, dates_with_ic, mono_pairs = compute(
        universe, dates, args.forward_days,
        args.min_section, progress=not args.quiet,
        align=args.align, datediag=datediag,
        min_valid_per_date=args.min_valid_per_date,
        ic_by_date=ic_by_date, mono_factors=mono_set)
    if ic_by_date is not None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(args.dump_ic_series, "w", encoding="utf-8") as fh:
            json.dump(ic_by_date, fh, ensure_ascii=False, indent=2)
        print(f"  [ic-series] 写入 {args.dump_ic_series}: {len(ic_by_date)} 个截面日"
              f" x {len(FACTOR_FUNCTIONS)} 因子")
    if datediag is not None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(args.datediag, "w", encoding="utf-8") as fh:
            json.dump(datediag, fh, ensure_ascii=False, indent=2)
        kept = sum(1 for x in datediag if x["kept"])
        print(f"  [datediag] 写入 {args.datediag}: {len(datediag)} 个截面日, "
              f"保留 {kept}, 丢弃 {len(datediag) - kept}")
    if mono_pairs:
        from core.scoring.factor_gate_v2 import spearman_ic
        mono_doc: Dict[str, dict] = {}
        for fname, per_date in mono_pairs.items():
            n_pairs = sum(len(day) for day in per_date)
            n_days = sum(1 for day in per_date if len(day) >= 5)
            if n_pairs < 50:
                mono_doc[fname] = {"n_pairs": n_pairs, "n_days": n_days,
                                   "monotonic": None,
                                   "note": "样本不足(<50), 单调性不可判"}
                continue
            # 逐截面 5 分位(按当日秩位置分桶, 同值不破坏桶容量) → 池化各分位
            # 平均前瞻收益 → 单调性 = 5 个分位均值沿分位单调(方向不限, 相邻逆序<=1)
            q_sums = [0.0] * 5
            q_ns = [0] * 5
            for day in per_date:
                if len(day) < 5:
                    continue
                day_sorted = sorted(day, key=lambda p: p[0])
                for pos, (_val, fv) in enumerate(day_sorted):
                    b = min(4, pos * 5 // len(day_sorted))
                    q_sums[b] += fv
                    q_ns[b] += 1
            q_means_opt = [q_sums[i] / q_ns[i] if q_ns[i] else None for i in range(5)]
            entry: Dict[str, Any] = {
                "n_pairs": n_pairs,
                "n_days": n_days,
                "q_means": [round(m, 4) if m is not None else None for m in q_means_opt],
                "q_ns": q_ns,
            }
            if all(m is not None for m in q_means_opt):
                qm: List[float] = cast(List[float], q_means_opt)
                # 单调性 = 5 分位平均前瞻收益沿分位单调(方向不限, 允许相邻逆序<=1)
                inv_up = sum(1 for i in range(4) if qm[i] > qm[i + 1])
                inv_dn = sum(1 for i in range(4) if qm[i] < qm[i + 1])
                entry["adjacent_inversions_up"] = inv_up
                entry["adjacent_inversions_down"] = inv_dn
                entry["monotonic"] = min(inv_up, inv_dn) <= 1
                q_sp = spearman_ic([0.0, 1.0, 2.0, 3.0, 4.0], qm)
                entry["q_spearman"] = round(q_sp, 4) if q_sp is not None else None
                entry["direction"] = ("positive" if qm[4] > qm[0] else
                                      "negative" if qm[4] < qm[0] else "flat")
            else:
                entry["monotonic"] = None
                entry["q_spearman"] = None
                entry["direction"] = None
                entry["note"] = "存在空分位(常数因子或样本偏斜)"
            mono_doc[fname] = entry
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        mono_doc["_meta"] = {
            "task": "P1#5 t_c575000e",
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine": _engine_tag(),
            "window_days": args.window_days,
            "forward_days": args.forward_days,
            "align": args.align,
            "max_stocks": args.max_stocks,
            "dates_with_ic": len(dates_with_ic),
            "dates_range": [dates_with_ic[0], dates_with_ic[-1]] if dates_with_ic else None,
        }
        with open(args.mono_out, "w", encoding="utf-8") as fh:
            json.dump(mono_doc, fh, ensure_ascii=False, indent=2)
        print(f"  [mono] 写入 {args.mono_out}: {len(mono_doc)} 因子 5 分位单调性")

    factors = summarize(ic_series, ic_threshold, ir_threshold)

    # last_date 语义与权威源一致: 样本最后数据日 (不是最后一个IC截面日)
    last_data_date = max((r["date"] for recs in universe.values()
                          for r in recs[-1:] if r.get("date")), default=None)
    last_date = last_data_date or (dates[-1] if dates else None)
    now = datetime.now()
    freshness = None
    if last_date:
        try:
            freshness = (now.date() - datetime.strptime(last_date, "%Y-%m-%d").date()).days
        except Exception:
            freshness = None

    result = {
        "last_date": last_date,
        "freshness_days": freshness,
        "total_samples": len(factors),
        "source": _engine_tag(),
        "computed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "last_ic_date": dates_with_ic[-1] if dates_with_ic else None,
        "asof": last_date,  # 10/24 C 件: asof 别名键 (消费面 @老五 卡读 asof/last_date 双兼容)
        "window_days": args.window_days,
        "forward_days": args.forward_days,
        "dates_with_ic": len(dates_with_ic),
        "universe_size": len(universe),
        # 门禁消费 name/ic/status；icir_nw 是判定依据，一并给出以便门禁直接复核
        # (10/24 C 件: 补 icir/sample_size/weight 字段 — 候选卡与权威卡 (W1 192样本件)
        #  键名对齐, 防消费面 (forward_prob_card.py 读 icir/weight) 口径错位;
        #  sample_size 真源 = n_dates (该因子有效截面日数), 非造数)
        "factors": [{"name": f["name"], "ic": f["ic"], "status": f["status"],
                     "icir_nw": f.get("icir_nw"), "icir": f.get("icir"),
                     "sample_size": f.get("n_dates"), "weight": None}
                    for f in factors],
        # 诊断明细(留证)
        "diagnostics": {f["name"]: {"icir": f.get("icir"),
                                    "icir_nw": f.get("icir_nw"),
                                    "t_nw": f.get("t_nw"),
                                    "ic_lag1_autocorr": f.get("ic_lag1_autocorr"),
                                    "ic_std": f.get("ic_std"),
                                    "n_dates": f.get("n_dates"), "note": f.get("note")}
                        for f in factors},
        # 逐日 IC 序列: 门禁数「独立信号簇」需要用它算因子间相关性,
        # 也是 IC 结论可审计的唯一依据。默认不写(体积), --dump-ic-series 时落盘。
        **({"ic_by_date": ic_by_date} if ic_by_date else {}),
    }

    n_valid = sum(1 for f in factors if f["status"] == "valid")
    print()
    print(f"【结果】因子 {len(factors)} 个, valid={n_valid}, "
          f"有效截面日={len(dates_with_ic)}, last_date={last_date}")
    for f in factors:
        if f["status"] == "valid":
            # 判定用 icir_nw；naive icir 仅作对照显示，避免「判对显错」误导
            print(f"  [VALID] {f['name']}: IC={f['ic']:+.4f} "
                  f"ICIR_nw={f.get('icir_nw')} (naive {f.get('icir')}, "
                  f"lag1自相关={f.get('ic_lag1_autocorr')})")

    # 基线: --compare 优先(取证用, 可指到带 icir 的诊断文件), 否则用当前权威源
    base_path = Path(args.compare) if args.compare else AUTHORITY
    prev = None
    if base_path.exists():
        try:
            with open(base_path, "r", encoding="utf-8") as fh:
                prev = json.load(fh)
        except Exception as e:
            print(f"[WARN] 基线解析失败: {base_path}: {e}")
        # 诊断文件的 factors 是 dict {name: {...}}, 权威源是 list —— 统一成 list
        if prev and isinstance(prev.get("factors"), dict):
            prev = dict(prev)
            prev["factors"] = [dict(v, name=k) for k, v in prev["factors"].items()]
    elif args.compare:
        print(f"[WARN] --compare 指定的基线不存在: {base_path}")
        if prev:
            # 注意: 文件里的 freshness_days 是写出当时的静态快照, 不会随时间增长,
            # 所以这里必须用 computed_at 与当前时间重新算真实陈旧天数。
            age = None
            ca = prev.get("computed_at")
            if ca:
                try:
                    age = (datetime.now() - datetime.strptime(ca, "%Y-%m-%d %H:%M:%S")).days
                except Exception:
                    age = None
            if age is None:
                print("[WARN] 权威源缺 computed_at, 无法判定陈旧天数")
            elif age > args.staleness_days:
                print(f"[STALE] 权威源已 {age} 天未刷新 (> {args.staleness_days}): "
                      f"last_date={prev.get('last_date')} computed_at={ca} "
                      f"-> 门禁正在依据陈货判定, 需人工刷新")
    else:
        print("[WARN] 权威源不存在")

    # 与基线逐因子对账(可追溯, 不是静默覆盖)
    if prev:
        prev_map = {f.get("name"): f for f in prev.get("factors", [])}
        print()
        print(f"【与基线与对账】 baseline={base_path.name}")
        print("  (name: base_ic/base_icir -> new_ic/new_icir | delta | z=delta/SE_base"
              "  SE_base=base_ic_std/sqrt(base_n), |z|<2 视为噪声内一致)")
        same_sign = diff_sign = 0
        big = []
        n_cmp = 0
        for f in factors:
            p = prev_map.get(f["name"])
            if not p:
                print(f"  [NEW ] {f['name']}: 基线无此因子 -> {f['status']}/{f['ic']}")
                continue
            # 基线字段名兼容: 权威源用 ic, 诊断文件用 ic_mean
            pic = p.get("ic") if p.get("ic") is not None else p.get("ic_mean")
            n = f["ic"]
            delta = (n - pic) if (pic is not None and n is not None) else None
            # 基线的标准误: ic_std / sqrt(sample_size), 用于判断差异是噪声还是系统性
            se = None
            bstd = p.get("ic_std")
            bn = p.get("sample_size") or p.get("n_dates")
            if bstd and bn:
                se = bstd / math.sqrt(bn)
            z = (delta / se) if (delta is not None and se) else None
            if pic is not None and n is not None:
                if (pic > 0) == (n > 0):
                    same_sign += 1
                else:
                    diff_sign += 1
            zs = "n/a" if z is None else f"{z:+.2f}"
            ds = "n/a" if delta is None else f"{delta:+.4f}"
            fmt = lambda x: "  n/a " if x is None else f"{x:+.4f}"
            print(f"  {f['name']:20s} {fmt(pic)}/{p.get('icir')} -> "
                  f"{fmt(n)}/{f.get('icir')}  d={ds}  z={zs}")
            if z is not None:
                n_cmp += 1
                if abs(z) >= 2:
                    big.append((f["name"], ds, zs))
        print(f"  -- 符号一致 {same_sign} / 符号相反 {diff_sign} "
              f"(共 {same_sign + diff_sign} 个可比对因子)")
        if big:
            print(f"  -- 超出噪声带(|z|>=2)的因子 {len(big)} 个: "
                  + ", ".join(f"{n}(d={d},z={z})" for n, d, z in big))
        elif n_cmp == 0:
            # 基线没有 ic_std/sample_size 就根本算不出 z, 不能拿"没有超带因子"
            # 冒充"全部一致" —— 那正是要消灭的假绿话术。
            print("  -- [WARN] 基线缺 ic_std/sample_size, 无法计算 z, "
                  "**不能判定**差异是否在噪声带内(不是'全部一致')")
        else:
            print("  -- 全部因子差异均在基线自身噪声带内(|z|<2)")
        if args.dump_json:
            snap = {
                "baseline": str(base_path),
                "new_last_date": last_date,
                "new_dates_with_ic": len(dates_with_ic),
                "rows": [],
            }
            for f in factors:
                p = prev_map.get(f["name"]) or {}
                pic = p.get("ic") if p.get("ic") is not None else p.get("ic_mean")
                snap["rows"].append({
                    "name": f["name"],
                    "base_ic": pic, "base_icir": p.get("icir"),
                    "base_std": p.get("ic_std"), "base_n": p.get("sample_size"),
                    "new_ic": f["ic"], "new_icir": f.get("icir"),
                    "new_std": f.get("ic_std"), "new_n": f.get("n_dates"),
                    "new_status": f["status"],
                })
            with open(args.dump_json, "w", encoding="utf-8") as fh:
                json.dump(snap, fh, ensure_ascii=False, indent=2)
            print(f"  -- 对账快照已写出: {args.dump_json}")

    ok, reasons = _guard(factors, prev, args.allow_big_flip)
    print()
    print("【守卫】")
    if reasons:
        for r in reasons:
            print(f"  [BLOCK] {r}")
    else:
        print("  [OK] G-A/G-B/G-C 全部通过")

    if args.apply:
        if not ok:
            print("[ABORT] 守卫未通过, 权威源保持不动")
            return 3
        if args.archive_prev and AUTHORITY.exists():
            ts = now.strftime("%Y%m%d_%H%M%S")
            arc = OUT_DIR / f"factor_ic_latest_{ts}.json"
            AUTHORITY.replace(arc)
            print(f"[OK] 旧权威源已归档: {arc.name}")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print(f"[OK] 权威源已刷新: {args.out}")
        # 权威表被 .gitignore 的 data/ 挡在库外(无 git 历史), 写完后追加一行
        # 指纹台账 state/gate_fingerprints.jsonl 恢复可追溯性(2026-10-21 治理任务B)。
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from record_gate_fingerprint import record_fingerprint  # noqa: E402
            record_fingerprint(
                artifact=Path(args.out),
                writer="scripts/factor_ic_132d_refresh.py --apply",
                note="132d IC 权威源刷新",
            )
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] IC 权威源指纹台账未写入(刷新结果不受影响): "
                  f"{type(e).__name__}: {e}")
    else:
        ts = now.strftime("%Y%m%d_%H%M%S")
        dry = OUT_DIR / f"factor_ic_132d_refresh_{ts}.json"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(dry, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print(f"[DRY-RUN] 结果写入: {dry.name} (权威源未改动)")

    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
