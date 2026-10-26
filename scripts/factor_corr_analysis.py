#!/usr/bin/env python3
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
factor_corr_analysis.py — 因子池相关性分析 (Kimi建议: 根治区分度)
检查9个技术因子是否同质化(高相关=重复计权=区分度不足根因)
"""
import sys, io, os
if __name__ == "__main__":
    sys.path.insert(0, r"D:\open code\zhuanqian")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    os.chdir(r"D:\open code\zhuanqian")

from core.pipeline.tdx_core import get_tdx_data, compute_indicators
from scipy.stats import spearmanr

if __name__ == "__main__":
    FACTORS = {
        "均线多头": lambda i: 1 if (i.get("ma5",0) > i.get("ma10",0) > i.get("ma20",0)) else 0.5 if (i.get("ma5",0) > i.get("ma10",0)) else 0,
        "MACD金叉": lambda i: 1 if (i.get("dif",-999) > i.get("dea",-999)) else 0,
        "RSI适中": lambda i: 1 if 35 <= i.get("rsi14",50) <= 65 else 0,
        "放量突破": lambda i: 1 if i.get("vol_pattern") in ("放量突破","放量拉升") else 0,
        "缩量回调": lambda i: 1 if i.get("vol_pattern") == "缩量回调" else 0,
        "W底形态": lambda i: 1 if i.get("pattern_name") == "W底" else 0,
        "杯柄形态": lambda i: 1 if i.get("pattern_name") == "杯柄" else 0,
        "周线多头": lambda i: 1 if i.get("weekly_bullish") else 0,
        "低风险(偏离<5%)": lambda i: 1 if -5 <= i.get("pos_vs_ma20", 999) <= 10 else 0,
    }

# 采样300只股票
from backtest import collect_all_stocks
if __name__ == "__main__":
    stocks = collect_all_stocks()
    codes = list(stocks.keys())[:300]
    
    rows = {f: [] for f in FACTORS}
    count = 0
    for code in codes:
        recs = get_tdx_data(code, 120)
        if not recs or len(recs) < 60:
            continue
        inds = compute_indicators(recs)
        if not inds:
            continue
        for fname, ffunc in FACTORS.items():
            val = ffunc(inds)
            if val is not None:
                rows[fname].append(val)
        count += 1
    
    print("采样股票: %d" % count)
    print("=" * 60)
    print("因子相关性矩阵 (|r|>0.5 高相关, >0.7 严重同质)")
    print("=" * 60)
    
    names = list(FACTORS.keys())
    corr = {}
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            a, b = names[i], names[j]
            n = min(len(rows[a]), len(rows[b]))
            if n < 30:
                continue
            r, p = spearmanr(rows[a][:n], rows[b][:n])
            corr[(a, b)] = r
    
    # 高相关对
    high = [(k, v) for k, v in corr.items() if abs(v) > 0.5]
    high.sort(key=lambda x: -abs(x[1]))
    
    print("\n高相关因子对 (|r|>0.5):")
    if high:
        for (a, b), r in high[:10]:
            flag = "🚨严重同质" if abs(r) > 0.7 else "⚠️同质"
            print("  %s vs %s: r=%+.3f %s" % (a[:8], b[:8], r, flag))
    else:
        print("  ✅ 无高相关因子对, 因子独立性良好")
    
    # 因子覆盖度(触发率)
    print("\n因子触发率 (低触发率=死因子/高触发率=无区分):")
    for f in names:
        vals = rows[f]
        if vals:
            rate = sum(1 for v in vals if v > 0) / len(vals) * 100
            flag = ""
            if rate < 5: flag = "⚠️几乎不触发(死因子)"
            elif rate > 90: flag = "⚠️几乎全触发(无区分度)"
            print("  %s: %5.1f%% (n=%d) %s" % (f[:14], rate, len(vals), flag))
    
    print("\n结论:")
    print("  因子独立 → 区分度来自因子本身 (P1-1调系数有效)")
    print("  因子同质 → 需去共线性/引入新因子 (根治方向)")
