# -*- coding: utf-8 -*-
"""tdx_factor_v2.py — V2新因子模块 (2026-09-26)

来源: data/audit/new_factor_ic_scan_20260926.json 全样本IC门禁 (1521股×278截面日含退市股)
      + data/audit/new_factor_corr_20260926.json 相关性去重
设计原则:
  1. 因子算术与 .scratch/factor_ic_scan.py 逐行一致 (IC证据仅对同算术有效)
  2. 调整为线性单调罚分+封顶, 方向与IC一致, 幅度∝|IC|
  3. 门控: data/factor_v2.json {"enabled": bool} — 缺失/异常=关闭(零行为变化), 回滚只需改配置
  4. 不改 score_stock 核心 — 调整在调用方叠加 (backtest_rotation / 实盘picker)
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "data", "factor_v2.json")  # 基地化S3: 根锚点

# ══ 因子计算 (输入为等长序列: 收/开/高/低/量/额, 至少60根) ══

def compute_v2_factors(c, o, h, l, v, a):
    """返回 {factor_name: value}。数据不足的因子缺省(不放入dict)→adjust按0处理"""
    out = {}
    n = len(c)
    if n < 21:
        return out
    # low60_dist: 距60日最低收盘涨幅% (20d IC=-0.103, t=-11.0, 单调差-1.35%)
    if n >= 60:
        lo = min(c[-60:])
        if lo > 0:
            out['low60_dist'] = (c[-1] / lo - 1) * 100
    # intraday_sum20: 近20日日内收益和% (IC=-0.085, t=-10.2, 单调差-1.50%; 与IC扫描同: range(n-19,n))
    s = 0.0
    ok = True
    for i in range(n - 19, n):
        if o[i] <= 0:
            ok = False
            break
        s += c[i] / o[i] - 1
    if ok:
        out['intraday_sum20'] = s * 100
    # vol_dryup: 近5日最大量/近60日均量 (IC=-0.074, IR=-0.76 最稳)
    if n >= 60:
        v60 = sum(v[-60:]) / 60.0
        if v60 > 0:
            out['vol_dryup'] = max(v[-5:]) / v60
    # gap_down_cnt: 近20日跳空低开>2%次数 (IC=-0.072, t=-10.2; 与IC扫描同: range(n-19,n) 19日跨度)
    out['gap_down_cnt'] = float(sum(1 for i in range(n - 19, n) if o[i] < c[i - 1] * 0.98))
    # amount_price_corr: 近20日成交额-价格相关 (IC=-0.060)
    if n >= 20 and max(a[-20:]) > 0:
        mc = sum(c[-20:]) / 20
        ma_ = sum(a[-20:]) / 20
        cov = sc2 = sa2 = 0.0
        for j in range(n - 20, n):
            cov += (c[j] - mc) * (a[j] - ma_)
            sc2 += (c[j] - mc) ** 2
            sa2 += (a[j] - ma_) ** 2
        if sc2 > 0 and sa2 > 0:
            out['amount_price_corr'] = cov / (sc2 ** 0.5 * sa2 ** 0.5)
    # red_ratio10: 近10日阳线占比 (IC=-0.042)
    out['red_ratio10'] = sum(1 for i in range(n - 10, n) if c[i] > o[i]) / 10.0
    # overnight_sum20: 近20日隔夜收益和% (唯一正向IC=+0.024, t=+5.7; 与IC扫描同: range(n-19,n))
    s = 0.0
    ok = True
    for i in range(n - 19, n):
        if c[i - 1] <= 0:
            ok = False
            break
        s += o[i] / c[i - 1] - 1
    if ok:
        out['overnight_sum20'] = s * 100
    return out


# ══ 权重设计: 线性单调 + 封顶, 方向=IC方向, 幅度∝|IC| ══
# 去重 (data/audit/new_factor_corr_20260926.json, 阈值|ρ|>=0.5):
#   intraday_sum20 与 low60_dist ρ=0.582 → 剔除低|IC|方(intraday 0.085<low60 0.103), 记第一替补
# (x0, 斜率, 下限, 上限)  adj = clip((x - x0)*k, lo, hi)
DEFAULT_RULES = {
    'low60_dist':       (10.0, -0.50, -8.0, +5.0),   # 贴近低点+5, 追高26%以上-8
    'vol_dryup':        (0.8, +4.00, -6.0, +4.0),    # 极致缩量+4, 放量-6
    'gap_down_cnt':     (0.0, -1.50, -6.0,  0.0),    # 接飞刀计数罚
    'amount_price_corr':(0.0, -4.00, -4.0, +2.0),    # 量价齐升罚, 背离+
    'red_ratio10':      (0.4, +8.00, -4.0, +2.0),    # 阳线密集罚, 阴跌+
    'overnight_sum20':  (0.0, +0.15, -2.0, +2.0),    # 唯一正向: 隔夜结构
}

_CFG_CACHE = None

# P2 保险丝证据留痕 (2026-09-27 老五条件1): 由 backtest_rotation._v2_fuse_check 在触发时写入,
# P2 runner 跑完读取本模块属性写进结果 JSON (不靠日志解析)。
# 初值=未触发; runner 每次主跑前必须重置, 防跨跑残留污染 (老五条件2 顺序留痕)。
_fuse_triggered = False
_fuse_trigger_date = None
_fuse_trigger_reason = None
# P2 重标定 recovery_on=True 专用留痕 (2026-09-27, 老三; 默认 recovery_on=False 不置位)
_fuse_recovered = False
_fuse_recovery_date = None
_fuse_recovery_reason = None
# P2 reason 串修复(老五② 2026-09-28): 观测胜率单列, reason 串 < 后打阈值而非观测值
_fuse_observed_winrate = None
# v4 机制留痕(老五设计签 2026-09-28): 触发时权益快照(C1恢复基线/C3确认线) + 恢复模式
_fuse_equity_at_trigger = None
_fuse_recovery_mode = None
# P2 事件列表化(老五④ 2026-09-28): 多次 trip 场景顶层单值字段只留"最后一次", 序列会丢顺序.
# 完整时间序事件流在此 append ({type:trip/recovery, date, reason, ...}), 成对留痕防跨版误读.
_fuse_events = []


def load_config(force=False):
    """读门控配置。缺失/损坏 → {'enabled': False} (零行为变化, 天然可回滚)"""
    global _CFG_CACHE
    if _CFG_CACHE is not None and not force:
        return _CFG_CACHE
    cfg = {'enabled': False, 'rules': DEFAULT_RULES}
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding='utf-8') as f:
                disk = json.load(f)
            if isinstance(disk, dict):
                if 'enabled' in disk:
                    cfg['enabled'] = bool(disk['enabled'])
                if isinstance(disk.get('rules'), dict) and disk['rules']:
                    cfg['rules'] = disk['rules']
    except Exception:
        pass  # 配置损坏=关闭, 保守
    _CFG_CACHE = cfg
    return cfg


def v2_adjust(factors, config=None):
    """按因子值计算调整分。factors=None/缺key → 该因子按0值处理(即x0基准处, adj=0除非封顶)"""
    if config is None:
        config = load_config()
    if not config.get('enabled'):
        return 0.0
    rules = config.get('rules') or DEFAULT_RULES
    total = 0.0
    if not factors:
        return 0.0
    for name, (x0, k, lo, hi) in rules.items():
        x = factors.get(name)
        if x is None:
            continue  # 数据不足的因子跳过, 不罚不加
        try:
            total += max(lo, min(hi, (float(x) - x0) * k))
        except (TypeError, ValueError):
            continue
    return total
