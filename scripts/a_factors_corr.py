import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""A 类通过因子相关性检验: vol_floor/atr_pct vs 现有因子 (重复建设判定)"""
import os, sys, random, datetime, json
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

from core.pipeline.tdx_core import compute_indicators
from backtest import get_extended_data, get_records_up_to, find_future_records

def spearman(xs, ys):
    n = len(xs)
    if n < 10: return None
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0]*len(v)
        for i, idx in enumerate(order): r[idx] = i
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den = (sum((x-mx)**2 for x in rx) * sum((y-my)**2 for y in ry))**0.5
    return num/den if den else None

def calc_a_factors(records):
    if len(records) < 25: return None
    c = [r["close"] for r in records]
    h = [r["high"] for r in records]
    l = [r["low"] for r in records]
    v = [r["volume"] for r in records]
    cur = records[-1]
    v20 = v[-20:]
    return {
        "vol_floor": cur["volume"] / min(v20) if min(v20) > 0 else 1.0,
        "atr_pct": 0,  # 用 compute_indicators 的 atr
    }

if __name__ == "__main__":
    rnd = random.Random(7)
    codes = sorted([f.replace(".json","") for f in os.listdir("data/history_daily")
                    if f.endswith(".json") and f != "download_errors.json"])
    sample = rnd.sample(codes, 300)
    
    # 单日截面相关性: 2026-07-15
    sd = datetime.date(2026, 7, 15)
    vf, atrp, chg5, maxr5, std20, vr = [], [], [], [], [], []
    for code in sample:
        recs = get_extended_data(code)
        if not recs: continue
        past = get_records_up_to(recs, sd)
        if len(past) < 60: continue
        inds = compute_indicators(past)
        fa = calc_a_factors(past)
        if not inds or not fa: continue
        vf.append(fa["vol_floor"])
        atrp.append(inds.get("atr", 0) / (inds.get("price") or 1) * 100)
        chg5.append(inds.get("chg5", 0))
        maxr5.append(inds.get("max_ret5", 0))
        std20.append(inds.get("std20", 0))
        vr.append(inds.get("vol_ratio", 0))
    
    print(f"截面样本: {len(vf)}")
    pairs = [
        ("vol_floor vs chg5", vf, chg5),
        ("vol_floor vs max_ret5", vf, maxr5),
        ("vol_floor vs vol_ratio", vf, vr),
        ("vol_floor vs std20", vf, std20),
        ("atr_pct vs std20", atrp, std20),
        ("atr_pct vs max_ret5", atrp, maxr5),
        ("atr_pct vs vol_ratio", atrp, vr),
    ]
    for name, a, b in pairs:
        r = spearman(a, b)
        print(f"{name}: Spearman = {r:+.3f} {'⚠️重复' if r is not None and abs(r) >= 0.7 else ''}")
