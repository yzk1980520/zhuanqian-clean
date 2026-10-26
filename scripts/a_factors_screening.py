import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""A 类纯 OHLCV 因子 IC 初筛 (零新依赖, 复用 factor_screening 面板逻辑)
A1: 日内位置 (close-low)/(high-low) - 收在高位=承接强?
A2: 地量因子 volume / 近20日最低量 - 地量见底?
A3: 振幅压缩 (high-low)/close 近20日分位 - spring/coil?
预期方向待测 (双测 |IC| 方向)
"""
import os, sys, random, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from core.pipeline.tdx_core import get_tdx_data
from backtest import get_extended_data, get_records_up_to, find_future_records

def spearman(xs, ys):
    n = len(xs)
    if n < 10:
        return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0]*len(v)
        for i, idx in enumerate(order):
            r[idx] = i
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den = (sum((x-mx)**2 for x in rx) * sum((y-my)**2 for y in ry))**0.5
    return num/den if den else None

FACTORS = ["pos_in_range", "vol_floor", "range_compress", "atr_pct"]
EXPECTED_SIGN = {"pos_in_range": 1, "vol_floor": -1, "range_compress": -1, "atr_pct": -1}

def calc_a_factors(records):
    """从原始K线计算 A 类因子 (不依赖 compute_indicators 已有字段)"""
    if len(records) < 25:
        return None
    c = [r["close"] for r in records]
    h = [r["high"] for r in records]
    l = [r["low"] for r in records]
    v = [r["volume"] for r in records]
    cur = records[-1]
    out = {}
    # A1 日内位置
    rng = cur["high"] - cur["low"]
    out["pos_in_range"] = (cur["close"] - cur["low"]) / rng if rng > 0 else 0.5
    # A2 地量: 今日量 / 近20日最低量 (低=地量, 负向)
    v20 = v[-20:]
    out["vol_floor"] = cur["volume"] / min(v20) if min(v20) > 0 else 1.0
    # A3 振幅压缩: 近5日平均振幅 / 近20日平均振幅 (低=压缩, 负向)
    amp5 = sum((h[i]-l[i])/c[i] for i in range(-5, 0)) / 5
    amp20 = sum((h[i]-l[i])/c[i] for i in range(-20, 0)) / 20
    out["range_compress"] = amp5 / amp20 if amp20 > 0 else 1.0
    # A4 ATR百分比: atr14/close (低波动, 负向)
    trs = []
    for i in range(max(1, len(records)-14), len(records)):
        tr = max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1]))
        trs.append(tr)
    atr = sum(trs)/len(trs) if trs else 0
    out["atr_pct"] = atr / cur["close"] * 100 if cur["close"] else 0
    return out

def build_panel(scan_dates, n_sample, seed=42):
    rnd = random.Random(seed)
    codes = sorted([f.replace(".json","") for f in os.listdir("data/history_daily")
                    if f.endswith(".json") and f != "download_errors.json"])
    panel = {}
    for sd in scan_dates:
        sample = rnd.sample(codes, min(n_sample, len(codes)))
        fv = {f: [] for f in FACTORS}
        rets = []
        for code in sample:
            recs = get_extended_data(code)
            if not recs:
                continue
            past = get_records_up_to(recs, sd)
            future = find_future_records(recs, sd, 5)
            if len(past) < 60 or len(future) < 5:
                continue
            fa = calc_a_factors(past)
            if not fa:
                continue
            ret = (future[4]["close"] - past[-1]["close"]) / past[-1]["close"] * 100
            for f in FACTORS:
                fv[f].append(fa[f])
            rets.append(ret)
        if len(rets) >= 30:
            panel[str(sd)] = {"factors": fv, "rets": rets}
    return panel

def main():
    # 每月1个扫描日, 2023-01 ~ 2026-07 (44 扫描日) x 200 只
    scan_dates = []
    d = datetime.date(2023, 1, 15)
    while d <= datetime.date(2026, 7, 15):
        scan_dates.append(d)
        if d.month == 12:
            d = d.replace(year=d.year+1, month=1, day=15)
        else:
            d = d.replace(month=d.month+1, day=15)
    print(f"构建面板: {len(scan_dates)} 扫描日 x 200 只...")
    panel = build_panel(scan_dates, 200)
    print(f"有效扫描日: {len(panel)}")

    from collections import defaultdict
    ic_by = defaultdict(list)
    for ds, blk in sorted(panel.items()):
        for f in FACTORS:
            ic = spearman(blk["factors"][f], blk["rets"])
            if ic is not None:
                ic_by[f].append(ic)

    print("\n%-16s %-8s %-8s %-10s %s" % ("因子", "IC均值", "IR", "方向率%", "判定"))
    for f in FACTORS:
        ics = ic_by[f]
        if not ics:
            print(f"{f:16s} 无样本")
            continue
        n = len(ics)
        ic_mean = sum(ics)/n
        sd = (sum((x-ic_mean)**2 for x in ics)/(n-1))**0.5 if n > 1 else 0
        ir = ic_mean/sd if sd > 0 else 0
        sign = EXPECTED_SIGN.get(f, 1)
        pos_ratio = sum(1 for x in ics if x*sign > 0)/n
        # 判定: |IC|>0.03 且方向率>55% 且 |IR|>0.3
        ic_ok = abs(ic_mean) > 0.03
        dir_ok = pos_ratio > 0.55
        ir_ok = abs(ir) > 0.3
        status = "✅通过" if (ic_ok and dir_ok and ir_ok) else ("⚠️待观察" if ic_ok else "❌淘汰")
        print("%-16s %-8.4f %-8.2f %-10.0f %s" % (f, ic_mean, ir, pos_ratio*100, status))

    import json
    atomic_json.atomic_dump({"generated": str(datetime.datetime.now()),
               "results": {f: {"ic_mean": sum(ic_by[f])/len(ic_by[f]) if ic_by[f] else 0,
                               "n": len(ic_by[f]),
                               "ics": ic_by[f]} for f in FACTORS}}, "data/a_factors_screening.json", ensure_ascii=False, indent=2, encoding="utf-8")
    print("\n💾 data/a_factors_screening.json")

if __name__ == "__main__":
    main()
