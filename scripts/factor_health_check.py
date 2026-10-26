# DEPRECATED → use scripts/check_all.py data-quality
# -*- coding: utf-8 -*-
"""factor_health_check.py — 满分因子体检 (v2 报告 flagged 的三个因子)

Kimi P0-2 退回补测清单:
  vol_dryup×− (liquidity 组 ICIR折算 1.2004, 日胜率1.0)
  vol_ratio×− (volatility 组 ICIR折算 1.0062, 日胜率1.0)
  chg20×−     (momentum 组, 日胜率 0.95)

排查三类异常:
  A. 截面退化: 因子值在多数截面接近常数(std极低, 去极值 clip 率高)
  B. 重叠IC虚高: 非重叠 IC 的胜率大幅下降 → 窗口自相关主导
  C. universe 耦合: 因子排名前列股票与 universe 筛选条件强相关(上市时长/ST标签)
"""
import sys, json, math
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy import stats as sp_stats

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
from core.scoring.pca_factor_synthesis import compute_all_factors, group_coverage

DATA_DIR = BASE / "data" / "history_daily"
N_STOCK_CAP = 4000


def is_stock(c):
    return c.startswith("sh6") or c.startswith("sz0") or \
        (c.startswith("sz3") and not c.startswith("sz399"))


def spearman_rank_ic(x, y):
    """spearman 秩相关(用 scipy, 同 factor_ic_scan.spearman 等价)。"""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None
              and math.isfinite(a) and math.isfinite(b)]
    if len(pairs) < 30:
        return None
    ax, ay = [p[0] for p in pairs], [p[1] for p in pairs]
    r, _ = sp_stats.spearmanr(ax, ay)
    return float(r) if not math.isnan(r) else None


def load_records(codes, tail=600):
    records = {}
    for c in codes:
        fp = DATA_DIR / f"{c}.json"
        if not fp.exists():
            continue
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            print(f"🔴 [scripts\factor_health_check.py] CR-01: except Exception:", file=sys.stderr)
            continue
        valid = [b for b in raw if isinstance(b, dict) and b.get("close", 0) > 0]
        if len(valid) < 70:
            continue
        records[c] = valid[-tail:]
    return records


def build_panel(records, roll_days, factors, horizon=5):
    """240 日截面。"""
    stock_series = []
    for c, bars in records.items():
        L = len(bars)
        cl = [b["close"] for b in bars]; vo = [b["volume"] for b in bars]
        am = [b["amount"] for b in bars]
        dates = [b["date"] for b in bars]
        s = {}
        last = L - 1 - horizon
        start = max(60, last - roll_days + 1)
        for i in range(last, start - 1, -1):
            if i < 60:
                break
            fvals = compute_all_factors(cl, [b["open"] for b in bars],
                                        [b["high"] for b in bars], [b["low"] for b in bars],
                                        vo, am, i)
            fut = (cl[i + horizon] - cl[i]) / cl[i] if cl[i] > 0 else 0.0
            s[dates[i]] = (fvals, fut)
        if len(s) >= 200:
            stock_series.append(s)
    date_count = defaultdict(int)
    for s in stock_series:
        for d in s:
            date_count[d] += 1
    common = sorted(d for d, cnt in date_count.items() if cnt >= 300)[-roll_days:]
    if not common:
        common = sorted(date_count)[-roll_days:]
    panel = {d: {f: [] for f in factors} for d in common}
    future = {d: [] for d in common}
    for s in stock_series:
        for d in common:
            if d in s:
                fvals, fut = s[d]
                for f in factors:
                    panel[d][f].append(fvals.get(f, 0.0))
                future[d].append(fut)
    return panel, future, common


def check_panel(panel, future, factors, dates):
    """A+B: 截面退化 + 非重叠 IC。"""
    results = {}
    for f in factors:
        col = panel[dates[0]][f]
        nonan = sum(1 for v in col if v is not None and math.isfinite(v))
        stds = [np.std(panel[d][f]) for d in dates if len(panel[d][f]) >= 30]
        # MAD clip 率
        clip_rates = []
        for d in dates:
            if len(panel[d][f]) < 30:
                continue
            vals = [v for v in panel[d][f] if v is not None and math.isfinite(v)]
            if not vals:
                continue
            med = np.median(vals)
            mad = np.median([abs(v - med) for v in vals])
            if mad < 1e-12:
                clip_rates.append(1.0)
                continue
            lo = med - 5 * 1.4826 * mad
            hi = med + 5 * 1.4826 * mad
            clipped = sum(1 for v in vals if v < lo or v > hi)
            clip_rates.append(clipped / len(vals))
        # IC
        ic_all = []
        ic_nonoverlap = []
        for j, d in enumerate(dates):
            if len(panel[d][f]) < 30:
                continue
            ic = spearman_rank_ic(panel[d][f], future[d])
            if ic is not None:
                ic_all.append(ic)
            if j % 5 == 0:  # 每 5 日一个非重叠截面
                ic_nonoverlap.append(ic)
        win_all = sum(1 for x in ic_all if x > 0) / len(ic_all) if ic_all else 0
        win_no = sum(1 for x in ic_nonoverlap if x > 0) / len(ic_nonoverlap) if ic_nonoverlap else 0
        results[f] = {
            "n_stocks_per_date": [len(panel[d][f]) for d in dates[:5]],
            "nonan_pct": round(nonan / len(col), 4),
            "std_mean": round(float(np.mean(stds)), 4) if stds else None,
            "std_min": round(float(np.min(stds)), 6) if stds else None,
            "clip_rate_mean": round(sum(clip_rates) / len(clip_rates), 4) if clip_rates else None,
            "ic_n": len(ic_all),
            "ic_mean": round(sum(ic_all) / len(ic_all), 4) if ic_all else None,
            "ic_std": round(float(np.std(ic_all, ddof=1)), 4) if len(ic_all) >= 2 else None,
            "icir_raw": round(
                (sum(ic_all) / len(ic_all)) / float(np.std(ic_all, ddof=1)), 4
            ) if ic_all and len(ic_all) >= 2 and np.std(ic_all, ddof=1) > 1e-12 else None,
            "win_ratio_all": round(win_all, 3),
            "win_ratio_nonoverlap": round(win_no, 3),
            "ic_overlap_lift": round((win_all - win_no) / max(win_no, 1e-6), 3) if win_no else None,
        }
    return results


def check_universe_coupling(panel, factors, dates, codes):
    """C: 因子排名前列的股票是否与 universe 筛选条件强相关(上市时长)。

    按因子分位数分组(top 5% vs bot 5%), 比较组内平均上市天数, 用 t 检验看差异是否显著。
    """
    # 预处理: 每股上市时长(有效 bar 数 ≈ 上市交易日数)
    age_map = {}
    for c in codes:
        fp = DATA_DIR / f"{c}.json"
        if not fp.exists():
            continue
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except (ValueError, json.JSONDecodeError):
            print(f"🔴 [scripts\factor_health_check.py] CR-01: except Exception:", file=sys.stderr)
        valid = [b for b in raw if isinstance(b, dict) and b.get("close", 0) > 0]
        if len(valid) >= 70:
            age_map[c] = len(valid)
    # 按因子分位数分组, 比较 top/bot 平均 age
    report = {}
    for f in factors:
        rows = []
        for d in dates:
            col = panel[d].get(f, [])
            if len(col) < 30:
                continue
            for idx, v in enumerate(col):
                c = codes[idx] if idx < len(codes) else None
                if v is None or not math.isfinite(v):
                    continue
                age = age_map.get(c, 0)
                if age <= 0:
                    continue
                rows.append((f, c, v, age))
        if len(rows) < 100:
            continue
        vals = [r[2] for r in rows]
        sorted_rows = sorted(rows, key=lambda r: r[2])
        n = len(sorted_rows)
        q05_idx = max(0, int(n * 0.05))
        q95_idx = min(n - 1, int(n * 0.95))
        top = sorted_rows[q95_idx:]
        bot = sorted_rows[:q05_idx]
        if not top or not bot:
            continue
        avg_top = sum(r[3] for r in top) / len(top)
        avg_bot = sum(r[3] for r in bot) / len(bot)
        try:
            t_stat, p_val = sp_stats.ttest_ind([r[3] for r in top], [r[3] for r in bot])
        except Exception as e:
            # P1-4b R1 (t_bae6c7d6): 原 except 静默 t_stat,p_val=None,None → p_val=None 灌入因子健康报告假绿；现响铃（p_val=None 作为"不可算"标记保留，报告可见）
            print(f"🔴 [factor_health_check] 因子 {f} t检验失败: {e} (报告 p_val 标记为 None)", file=sys.stderr, flush=True)
            t_stat, p_val = None, None
        report[f] = {"top95_age": round(avg_top), "bot5_age": round(avg_bot),
                      "age_diff_pct": round((avg_top - avg_bot) / max(avg_bot, 1), 4),
                      "p_val": round(p_val, 4) if p_val is not None else None}
    return report


def main():
    print("═══ 载入 universe ═══", flush=True)
    codes = [p.stem for p in sorted(DATA_DIR.glob("sh*.json")) + sorted(DATA_DIR.glob("sz*.json"))]
    codes = [c for c in codes if is_stock(c)]
    if len(codes) > N_STOCK_CAP:
        step = len(codes) / N_STOCK_CAP
        codes = [codes[int(i * step)] for i in range(N_STOCK_CAP)]
    records = load_records(codes, tail=600)
    print(f"  载入 {len(records)} 只, tail=600", flush=True)

    cov = group_coverage()
    # 体检目标: v2 报告 flagged 的三个满分因子 + 各组 ICIR 冠军候选
    TARGETS = {
        "momentum.chg20": "chg20",
        "volatility.vol_ratio": "vol_ratio",
        "liquidity.vol_dryup": "vol_dryup",
        "liquidity.amount_price_corr": "amount_price_corr",
        "volatility.rsi14": "rsi14",
        "liquidity.AMIHUD": "AMIHUD",
    }
    factors = sorted(set(TARGETS.values()))
    print(f"  体检因子: {factors}", flush=True)

    # 240 日截面
    panel, future, dates = build_panel(records, 240, factors)
    print(f"  共同交易日: {len(dates)}", flush=True)

    # A+B: 截面退化 + 非重叠 IC
    print("═══ A+B: 截面退化 + 非重叠 IC ═══", flush=True)
    ab = check_panel(panel, future, factors, dates)
    for f, r in ab.items():
        flag = ""
        if r["std_min"] and r["std_min"] < 1e-6:
            flag += " ⚠️ std→0 退化"
        if r["clip_rate_mean"] and r["clip_rate_mean"] > 0.3:
            flag += f" ⚠️ MAD clip {r['clip_rate_mean']:.0%}"
        if r["ic_overlap_lift"] and abs(r["ic_overlap_lift"]) > 0.5:
            flag += f" ⚠️ 重叠虚高(+{r['ic_overlap_lift']:+.2f})"
        if r["ic_overlap_lift"] and r["ic_overlap_lift"] < -0.2:
            flag += f" ⚠️ 重叠虚低({r['ic_overlap_lift']:+.2f})"
        print(f"  {f}: "
              f"n_stock={r['n_stocks_per_date'][0]} "
              f"std_mean={r['std_mean']} std_min={r['std_min']} "
              f"clip={r['clip_rate_mean']:.2%} "
              f"IC_win={r['win_ratio_all']:.0%}({r['ic_n']}天) "
              f"vs 非重叠={r['win_ratio_nonoverlap']:.0%} "
              f"lift={r['ic_overlap_lift']:+.3f} {flag}", flush=True)

    # C: universe 耦合
    print("═══ C: universe 耦合 ═══", flush=True)
    coupling = check_universe_coupling(panel, factors, dates, codes)
    for f, r in coupling.items():
        flag = " ⚠️ age_diff>50%" if abs(r["age_diff_pct"]) > 0.5 else ""
        flag += " p<0.01" if r["p_val"] and r["p_val"] < 0.01 else ""
        print(f"  {f}: top95_age={r['top95_age']:.0f} bot5_age={r['bot5_age']:.0f} "
              f"age_diff={r['age_diff_pct']:.1%} p={r['p_val']} {flag}", flush=True)

    # 关键对比: 60 日 vs 240 日胜率
    print("\n═══ 60日 vs 240日 胜率对比 ═══", flush=True)
    win60 = dates[-60:]
    for f in ["vol_dryup", "vol_ratio", "chg20"]:
        ic_all_240 = [spearman_rank_ic(panel[d][f], future[d]) for d in dates
                      if len(panel[d][f]) >= 30 and spearman_rank_ic(panel[d][f], future[d]) is not None]
        ic_all_60 = [spearman_rank_ic(panel[d][f], future[d]) for d in win60
                     if len(panel[d][f]) >= 30 and spearman_rank_ic(panel[d][f], future[d]) is not None]
        win240 = sum(1 for x in ic_all_240 if x > 0) / len(ic_all_240) if ic_all_240 else 0
        win60_v = sum(1 for x in ic_all_60 if x > 0) / len(ic_all_60) if ic_all_60 else 0
        print(f"  {f}: 240日胜率={win240:.0%}({len(ic_all_240)}天) vs 60日胜率={win60_v:.0%}({len(ic_all_60)}天)", flush=True)


if __name__ == "__main__":
    main()
