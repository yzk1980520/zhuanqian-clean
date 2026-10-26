# -*- coding: utf-8 -*-
"""因子IC重新评估脚本 v2 - 带异常值过滤和正确的前向收益计算"""
import sys, os, json, random, math
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from tdx_indicators import compute_indicators

def spearman_ic(xs, ys):
    n = len(xs)
    if n < 30:
        return None
    def rank(arr):
        indexed = sorted(range(len(arr)), key=lambda i: arr[i])
        r = [0.0] * len(arr)
        for rv, idx in enumerate(indexed):
            r[idx] = rv + 1
        i = 0
        while i < len(r):
            j = i
            while j < len(r) - 1 and abs(arr[indexed[j]] - arr[indexed[j+1]]) < 1e-12:
                j += 1
            avg = sum(r[k] for k in range(i, j+1)) / (j - i + 1)
            for k in range(i, j+1):
                r[k] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den = math.sqrt(sum((x-mx)**2 for x in rx) * sum((y-my)**2 for y in ry))
    if den < 1e-15:
        return None
    return num / den

def winsorize(xs, bounds=(0.01, 0.99)):
    """Winsorize extreme values."""
    if not xs:
        return xs
    s = sorted(xs)
    lo = s[max(0, int(len(s)*bounds[0]))]
    hi = s[min(len(s)-1, int(len(s)*bounds[1]))]
    return [max(lo, min(hi, x)) for x in xs]

def main():
    print("=" * 60)
    print("因子IC重新评估 v2 (2026-09-19)")
    print("=" * 60)

    data_dir = "data/history_daily"
    files = [f for f in os.listdir(data_dir)
             if f.endswith(".json") and f != "download_errors.json"
             and not f.startswith("sh000") and not f.startswith("sz399")]
    print(f"Total stock files: {len(files)}")

    rnd = random.Random(42)
    sample_files = rnd.sample(files, min(800, len(files)))
    print(f"Sampling {len(sample_files)} files...")

    # Collect scans - use single scan date per stock for speed
    all_scans = []
    skipped = 0
    
    for fpath in sample_files:
        try:
            data = json.load(open(os.path.join(data_dir, fpath)))
            if not data or len(data) < 100:
                continue
            n = len(data)
            # Use last 10 valid positions
            positions = list(range(max(100, n-50), n-10, 5))
            if not positions:
                continue
            # Take only first 2 positions to speed up
            positions = positions[:2]
            
            for pos in positions:
                past = data[:pos+1]
                future = data[pos+1:]
                if len(future) < 5:
                    continue
                
                inds = compute_indicators(past)
                if inds is None:
                    continue
                
                fwd_close = future[4]["close"] if len(future) > 4 else future[-1]["close"]
                base_close = past[-1]["close"]
                if base_close <= 0:
                    continue
                ret5 = (fwd_close - base_close) / base_close * 100
                
                ret10 = None
                if len(future) > 9:
                    ret10 = (future[9]["close"] - base_close) / base_close * 100
                elif len(future) > 5:
                    ret10 = (future[-1]["close"] - base_close) / base_close * 100
                
                if abs(ret5) > 20 or (ret10 is not None and abs(ret10) > 20):
                    continue
                
                entry = {"code": fpath.replace(".json",""),
                         "scan_date": str(past[-1]["date"]),
                         "ret5": ret5, "ret10": ret10}
                entry.update(inds)
                all_scans.append(entry)
        except Exception:
            skipped += 1

    print(f"Valid scans: {len(all_scans)}, skipped: {skipped}")
    
    # Check date distribution
    dates = sorted(set(s["scan_date"] for s in all_scans))
    print(f"Date range: {dates[0]} to {dates[-1]}, {len(dates)} unique dates")

    # ── Define factors to test ──────────────────────────────
    FACTORS = {
        "chg5": {"name": "5日涨跌幅", "expected_sign": 1},
        "chg10": {"name": "10日涨跌幅", "expected_sign": 1},
        "chg20": {"name": "20日涨跌幅", "expected_sign": 1},
        "pos_vs_ma20": {"name": "距MA20距离%", "expected_sign": -1},
        "rsi14": {"name": "RSI14", "expected_sign": -1},
        "vol_ratio": {"name": "量比(vol5/MA5)", "expected_sign": 1},
        "vol_shrink20": {"name": "缩量因子(vol20/vol60)", "expected_sign": -1},
        "vol_floor": {"name": "量地板(vol/最小20日)", "expected_sign": -1},
        "alpha13": {"name": "Alpha13(价量背离)", "expected_sign": -1},
        "alpha16_fix": {"name": "Alpha16_fix", "expected_sign": -1},
        "amount_q_reversal": {"name": "成交额分位反转", "expected_sign": -1},
        "vol_price_corr_20": {"name": "量价相关20日", "expected_sign": -1},
        "std20": {"name": "20日波动率", "expected_sign": -1},
        "max_ret5": {"name": "最大单日涨幅", "expected_sign": -1},
        "turn5": {"name": "5日涨跌停次数", "expected_sign": -1},
        "fund_flow_intensity": {"name": "资金流向强度", "expected_sign": 1},
        "macd_hist": {"name": "MACD柱", "expected_sign": 1},
        "dif": {"name": "DIF", "expected_sign": 1},
        "rms": {"name": "RMS相对动量", "expected_sign": 1},
        "breakout_strength": {"name": "突破力度", "expected_sign": 1},
        "unlocked_pressure": {"name": "解套盘压力", "expected_sign": -1},
        "price_volume_divergence": {"name": "量价背离", "expected_sign": -1},
        "rsi_extreme": {"name": "RSI极端值", "expected_sign": -1},
    }

    # ── Compute overall IC ──────────────────────────────────
    print("\n" + "=" * 60)
    print("整体IC分析 (Spearman, 全样本)")
    print("=" * 60)
    header = f"{'因子':<24} {'IC(ret5)':>10} {'IC(ret10)':>10} {'方向率%':>8} {'样本数':>8} {'状态':>8}"
    print(header)
    print("-" * 75)

    results = {}
    for fname, finfo in FACTORS.items():
        xs, ys5, ys10 = [], [], []
        for s in all_scans:
            val = s.get(fname)
            r5 = s.get("ret5")
            r10 = s.get("ret10")
            if val is None or r5 is None:
                continue
            if math.isnan(val) or math.isnan(r5):
                continue
            xs.append(float(val))
            ys5.append(float(r5))
            if r10 is not None and not math.isnan(r10):
                ys10.append(float(r10))
        
        ic5 = spearman_ic(xs, ys5) if xs else None
        ic10 = spearman_ic(xs[:len(ys10)], ys10) if xs and ys10 else None
        
        if ic5 is None:
            status = "无数据"
            dir5 = None
        else:
            sign = finfo["expected_sign"]
            # Direction rate: % where (factor - median)(return - median) has expected sign
            med_x = sorted(xs)[len(xs)//2]
            med_y = sorted(ys5)[len(ys5)//2]
            matches = sum(1 for x, y in zip(xs, ys5) 
                         if (x - med_x) * (y - med_y) * sign > 0)
            dir5 = matches / len(xs)
            ic_ok = abs(ic5) > 0.03
            dir_ok = dir5 > 0.55
            status = "✅通过" if (ic_ok and dir_ok and len(xs) > 200) else \
                     ("⚠️弱信号" if ic_ok else "❌淘汰")
        
        ic5_s = f"{ic5:.4f}" if ic5 else "N/A"
        ic10_s = f"{ic10:.4f}" if ic10 else "N/A"
        dir5_s = f"{dir5*100:.0f}" if dir5 else "N/A"
        print(f"{finfo['name']:<24} {ic5_s:>10} {ic10_s:>10} {dir5_s:>8} {len(xs):>8} {status:>8}")
        
        results[fname] = {
            "name": finfo["name"],
            "ic5": round(ic5, 4) if ic5 else None,
            "ic10": round(ic10, 4) if ic10 else None,
            "dir5": round(dir5, 4) if dir5 else None,
            "n": len(xs),
            "expected_sign": finfo["expected_sign"],
            "status": status
        }

    # ── chg5_rev detailed analysis ──────────────────────────
    print("\n" + "=" * 60)
    print("反转因子 (chg5_rev = -chg5) 深度分析")
    print("=" * 60)
    
    chg5_vals, ret5_vals = [], []
    for s in all_scans:
        c5 = s.get("chg5")
        r5 = s.get("ret5")
        if c5 is not None and r5 is not None and not math.isnan(c5):
            chg5_vals.append(c5)
            ret5_vals.append(r5)
    
    if chg5_vals:
        direct_ic = spearman_ic(chg5_vals, ret5_vals)
        rev_ic = spearman_ic([-x for x in chg5_vals], ret5_vals)
        print(f"chg5 IC (原始动量): {direct_ic:.4f}")
        print(f"chg5_rev IC (= -chg5, 反转): {rev_ic:.4f}")
        
        # Quartile analysis
        sorted_pairs = sorted(zip(chg5_vals, ret5_vals), key=lambda x: x[0])
        q_size = len(sorted_pairs) // 5
        print(f"\n按chg5分5组 (Q1=最跌, Q5=最涨):")
        for i in range(5):
            start = i * q_size
            end = start + q_size if i < 4 else len(sorted_pairs)
            group = [p[1] for p in sorted_pairs[start:end]]
            avg_r = sum(group) / len(group)
            win_r = sum(1 for r in group if r > 0) / len(group) * 100
            range_str = f"{sorted_pairs[start][0]:.1f}% ~ {sorted_pairs[end-1][0]:.1f}%"
            print(f"  Q{i+1} {range_str}: avg_ret5={avg_r:.2f}%, win_rate={win_r:.1f}%, n={len(group)}")
    
    # chg10_rev
    chg10_vals, ret10_valid = [], []
    for s in all_scans:
        c10 = s.get("chg10")
        r10 = s.get("ret10")
        if c10 is not None and r10 is not None and not math.isnan(c10):
            chg10_vals.append(c10)
            ret10_valid.append(r10)
    if chg10_vals:
        direct_ic10 = spearman_ic(chg10_vals, ret10_valid)
        rev_ic10 = spearman_ic([-x for x in chg10_vals], ret10_valid)
        print(f"\nchg10 IC (原始): {direct_ic10:.4f}")
        print(f"chg10_rev IC (= -chg10): {rev_ic10:.4f}")

    # ── fund_flow_intensity analysis ────────────────────────
    print("\n" + "=" * 60)
    print("资金流向因子(fund_flow_intensity)分析")
    print("=" * 60)
    
    by_group = defaultdict(list)
    ffi_nonzero = 0
    for s in all_scans:
        ffi = s.get("fund_flow_intensity")
        r5 = s.get("ret5")
        if ffi is not None and r5 is not None:
            if ffi != 0:
                ffi_nonzero += 1
            by_group[int(ffi)].append(r5)
    
    print(f"非零资金流向样本: {ffi_nonzero}/{len(all_scans)}")
    for g in sorted(by_group.keys()):
        rets = by_group[g]
        avg = sum(rets) / len(rets)
        win = sum(1 for r in rets if r > 0) / len(rets) * 100
        label = "资金流入强(+1)" if g == 1 else ("资金流出(-1)" if g == -1 else "资金中性(0)")
        print(f"  {label} (n={len(rets)}): avg_ret5={avg:.2f}%, win_rate={win:.1f}%")
    
    # ── MACD above 0 analysis ───────────────────────────────
    print("\n" + "=" * 60)
    print("MACD零轴上方因子分析")
    print("=" * 60)
    
    macd_above, macd_below = [], []
    for s in all_scans:
        dif = s.get("dif")
        r5 = s.get("ret5")
        if dif is not None and r5 is not None and not math.isnan(dif):
            if dif > 0:
                macd_above.append(r5)
            else:
                macd_below.append(r5)
    
    if macd_above:
        avg_a = sum(macd_above) / len(macd_above)
        win_a = sum(1 for r in macd_above if r > 0) / len(macd_above) * 100
        print(f"  MACD>0 (n={len(macd_above)}): avg_ret5={avg_a:.2f}%, win_rate={win_a:.1f}%")
    if macd_below:
        avg_b = sum(macd_below) / len(macd_below)
        win_b = sum(1 for r in macd_below if r > 0) / len(macd_below) * 100
        print(f"  MACD<0 (n={len(macd_below)}): avg_ret5={avg_b:.2f}%, win_rate={win_b:.1f}%")

    # ── 缩量企稳 vol_shrink20 analysis ─────────────────────
    print("\n" + "=" * 60)
    print("缩量企稳因子(vol_shrink20)分析")
    print("=" * 60)
    
    vs_data = []
    for s in all_scans:
        vs = s.get("vol_shrink20")
        r5 = s.get("ret5")
        if vs is not None and r5 is not None and not math.isnan(vs):
            vs_data.append((vs, r5))
    
    if vs_data:
        sorted_v = sorted(vs_data, key=lambda x: x[0])
        q_size = len(sorted_v) // 5
        print("按vol_shrink20分5组 (越低=越缩量):")
        for i in range(5):
            start = i * q_size
            end = start + q_size if i < 4 else len(sorted_v)
            group = [p[1] for p in sorted_v[start:end]]
            avg_r = sum(group) / len(group)
            win_r = sum(1 for r in group if r > 0) / len(group) * 100
            print(f"  Q{i+1} [{sorted_v[start][0]:.2f} ~ {sorted_v[end-1][0]:.2f}]: avg_ret5={avg_r:.2f}%, win_rate={win_r:.1f}%, n={len(group)}")

    # ── 低波动异象 std20 analysis ───────────────────────────
    print("\n" + "=" * 60)
    print("低波动异象(std20)分析")
    print("=" * 60)
    
    std_data = []
    for s in all_scans:
        st = s.get("std20")
        r5 = s.get("ret5")
        if st is not None and r5 is not None and not math.isnan(st):
            std_data.append((st, r5))
    
    if std_data:
        sorted_s = sorted(std_data, key=lambda x: x[0])
        q_size = len(sorted_s) // 5
        print("按std20分5组 (越低=越低波动):")
        for i in range(5):
            start = i * q_size
            end = start + q_size if i < 4 else len(sorted_s)
            group = [p[1] for p in sorted_s[start:end]]
            avg_r = sum(group) / len(group)
            win_r = sum(1 for r in group if r > 0) / len(group) * 100
            print(f"  Q{i+1} [{sorted_s[start][0]:.2f} ~ {sorted_s[end-1][0]:.2f}]: avg_ret5={avg_r:.2f}%, win_rate={win_r:.1f}%, n={len(group)}")

    # ── chg20 (长周期动量) analysis ────────────────────────
    print("\n" + "=" * 60)
    print("20日涨跌幅(chg20)分析 - 长期动量")
    print("=" * 60)
    
    c20_data = []
    for s in all_scans:
        c20 = s.get("chg20")
        r5 = s.get("ret5")
        if c20 is not None and r5 is not None and not math.isnan(c20):
            c20_data.append((c20, r5))
    
    if c20_data:
        sorted_c20 = sorted(c20_data, key=lambda x: x[0])
        q_size = len(sorted_c20) // 5
        print("按chg20分5组 (Q1=最跌, Q5=最涨):")
        for i in range(5):
            start = i * q_size
            end = start + q_size if i < 4 else len(sorted_c20)
            group = [p[1] for p in sorted_c20[start:end]]
            avg_r = sum(group) / len(group)
            win_r = sum(1 for r in group if r > 0) / len(group) * 100
            print(f"  Q{i+1} [{sorted_c20[start][0]:.1f}% ~ {sorted_c20[end-1][0]:.1f}%]: avg_ret5={avg_r:.2f}%, win_rate={win_r:.1f}%, n={len(group)}")

    # ── Rolling IC for top factors ──────────────────────────
    print("\n" + "=" * 60)
    print("滚动IC趋势分析 (30日窗口)")
    print("=" * 60)
    
    # Group by date
    by_date = defaultdict(list)
    for s in all_scans:
        by_date[s["scan_date"]].append(s)
    sorted_dates = sorted(by_date.keys())
    print(f"扫描日期数: {len(sorted_dates)} ({sorted_dates[0]} ~ {sorted_dates[-1]})")
    
    top_for_analysis = ["chg5", "chg10", "chg20", "vol_ratio", "amount_q_reversal", 
                        "dif", "vol_shrink20", "rsi14", "std20", "unlocked_pressure"]
    
    for fname in top_for_analysis:
        # Build rolling IC
        ics = []
        window_size = 30  # 30 scan dates
        for i in range(len(sorted_dates) - window_size):
            window_dates = sorted_dates[i:i+window_size]
            window_scans = []
            for d in window_dates:
                window_scans.extend(by_date[d])
            
            xs, ys = [], []
            for s in window_scans:
                val = s.get(fname)
                r5 = s.get("ret5")
                if val is not None and r5 is not None and not math.isnan(val) and not math.isnan(r5):
                    xs.append(float(val))
                    ys.append(float(r5))
            
            if len(xs) < 50:
                continue
            ic = spearman_ic(xs, ys)
            if ic is not None:
                ics.append({"date_start": window_dates[0], "date_end": window_dates[-1], "ic": ic, "n": len(xs)})
        
        if ics:
            ic_vals = [r["ic"] for r in ics]
            mean_ic = sum(ic_vals) / len(ic_vals)
            pos_cnt = sum(1 for x in ic_vals if x > 0)
            trend = "稳定" if abs(ic_vals[-1] - mean_ic) < 0.02 else ("转弱" if ic_vals[-1] < mean_ic * 0.5 else "转强")
            last3 = [f'{r["ic"]:.4f}' for r in ics[-3:]]
            print(f"\n{fname}: 滚动IC均值={mean_ic:.4f}, 正向={pos_cnt}/{len(ics)} ({pos_cnt/len(ics)*100:.0f}%), 趋势={trend}")
            print(f"  最新3窗口: {last3}")

    # ── Save results ────────────────────────────────────────
    output = {
        "timestamp": "2026-09-19",
        "total_scans": len(all_scans),
        "date_range": f"{sorted_dates[0]} ~ {sorted_dates[-1]}" if sorted_dates else "",
        "factor_results": results,
    }
    
    out_path = "data/factor_ic_recheck_20260919.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 结果已保存: {out_path}")


if __name__ == "__main__":
    main()
