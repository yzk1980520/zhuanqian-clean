# -*- coding: utf-8 -*-
"""
老五 · 无环境门(MA250)回测数据验证
====================================
核心: 量化"剔除上证>MA250硬性环境门"对选股效果的影响。

数据来源(全部只读):
  - backtest_analysis/final_verify/trade_detail_v2.csv  (gate-off 快照, 1791笔)
  - backtest_analysis/final_verify/backtest_result.json
  - TDX sh000001.day  (上证指数, 用于逐扫描日计算 MA250 门状态)
  - data/alpha_factor_rolling_ic.json / winrate_diagnosis.json (因子IC背景)

方法:
  1) 对 CSV 中每个扫描日, 用 TDX 上证日线计算 close>MA250 → 门开/门关
  2) 把 1791 笔交易按 门开/门关 切分, 计算 胜率/均值/超额/最大回撤/样本量
  3) 统计检验: 双比例 z 检验(门开vs门关胜率), 95%CI, 样本量
  4) 因子: 综合评分+各子分 在 门开/门关 的秩IC; 再用 TDX 重算 chg5/chg10/RSI 的分状态IC
  5) 结论: 剔除环境门是否真的降低收益(门开39%/门关28% 的复算 + 无门整体)
"""
import sys, os, json, csv, math, struct
import datetime as _dt
from collections import defaultdict

os.environ.pop("PYTHONPATH", None)
PROJ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJ)
import backtest as BT  # 复用 MA250 / 市场状态 / TDX 解析
from tdx_data import parse_tdx_day  # 项目自有解析器 (date 打包为 YYYYMMDD int)

# ── 1. 上证指数 MA250 门状态 (TDX 本地, 与引擎口径一致) ─────────────────
OUT = os.path.join(PROJ, "backtest_analysis", "final_verify")
TRADE_CSV = os.path.join(OUT, "trade_detail_v2.csv")
RESULT_JSON = os.path.join(OUT, "backtest_result.json")
OUT_JSON = os.path.join(OUT, "laowu_envgate_off_validation.json")
sh_path = os.path.join(BT.VIPDOC, "sh", "lday", "sh000001.day")
sh = parse_tdx_day(sh_path)
# 项目解析器返回 datetime.date, str() 即 ISO "2025-02-14", 与 CSV 扫描日期同格式
sh_dates = [str(r["date"]) for r in sh]
sh_close = [r["close"] for r in sh]
ma250_map = {}
for i in range(249, len(sh_dates)):
    window = sh_close[i - 249:i + 1]
    ma = sum(window) / len(window)
    ma250_map[sh_dates[i]] = {"close": sh_close[i], "ma250": ma, "gate_open": sh_close[i] > ma}
print("[1] TDX 上证日线: %d 条, %s ~ %s" % (len(sh), sh_dates[0], sh_dates[-1]))
print("    可判门状态交易日: %d (MA250需250日历史)" % len(ma250_map))

# ── 2. 加载交易明细 ───────────────────────────────────────────
with open(TRADE_CSV, encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))
real = [r for r in rows if r.get("股票代码", "").strip() and "MarketGate" not in r.get("股票名称", "")]
placeholder = [r for r in rows if "MarketGate" in r.get("股票名称", "")]
print("[2] CSV: 实盘交易 %d 笔, P0-MarketGate 占位 %d 行" % (len(real), len(placeholder)))

def fnum(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None

def stats(rets, excess=None):
    n = len(rets)
    if n == 0:
        return {}
    wins = sum(1 for r in rets if r > 0)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    std = math.sqrt(var)
    # 95% CI for mean (t近似, 大样本用正态)
    ci = 1.96 * std / math.sqrt(n) if n > 1 else 0
    s = {"n": n, "win_rate": round(wins / n * 100, 2), "wins": wins,
         "mean_5d": round(mean, 3), "std": round(std, 3), "mean_ci95": round(ci, 3)}
    if excess is not None:
        ex = [a - b for a, b in zip(rets, excess)]
        s["mean_excess"] = round(sum(ex) / len(ex), 3)
        s["excess_pos_rate"] = round(sum(1 for e in ex if e > 0) / len(ex) * 100, 2)
    return s

# 按扫描日计算门状态
date_gate = {}
no_date = []
for r in real:
    d = r["扫描日期"]
    if d in ma250_map:
        date_gate[d] = ma250_map[d]["gate_open"]
    else:
        no_date.append(d)

open_rows = [r for r in real if date_gate.get(r["扫描日期"]) is True]
closed_rows = [r for r in real if date_gate.get(r["扫描日期"]) is False]
unknown_rows = [r for r in real if r["扫描日期"] not in date_gate]
print("    门开期交易 %d | 门关期交易 %d | 无法判门 %d (缺TDX数据: %s)"
      % (len(open_rows), len(closed_rows), len(unknown_rows), sorted(set(no_date)) or "无"))

def subset_metrics(rows):
    ret5 = [fnum(r["5日净收益%"]) for r in rows]
    ret5 = [x for x in ret5 if x is not None]
    ret10 = [fnum(r["10日净收益%"]) for r in rows]
    ret10 = [x for x in ret10 if x is not None]
    m = stats(ret5)
    m["mean_10d"] = round(sum(ret10)/len(ret10), 3) if ret10 else None
    # 最大回撤: 按扫描日时间序的"当日平均5日收益"累计净值曲线 (组合口径)
    daymean = defaultdict(list)
    for r in rows:
        v = fnum(r["5日净收益%"])
        if v is not None:
            daymean[r["扫描日期"]].append(v)
    curve = []
    for d in sorted(daymean):
        cum = sum(daymean[d]) / len(daymean[d])
        curve.append((d, cum))
    peak = 0; mdd = 0; cumsum = 0
    for d, x in curve:
        cumsum += x
        peak = max(peak, cumsum)
        mdd = min(mdd, cumsum - peak)
    m["max_dd_5d_cum"] = round(mdd, 3)
    m["n_scan_days"] = len(curve)
    return m

open_m = subset_metrics(open_rows)
closed_m = subset_metrics(closed_rows)
all_m = subset_metrics(real)

print("\n[3] 门开 vs 门关 (5日净收益口径)")
def show(label, m):
    print("  %-6s n=%-5d 扫描日=%-3s 胜率=%6.2f%%  均值5d=%+7.3f%%  95%%CI=±%.3f  最大回撤(cum)=%+.3f%%  10d均值=%s"
          % (label, m.get("n",0), m.get("n_scan_days","-"), m.get("win_rate",0),
             m.get("mean_5d",0), m.get("mean_ci95",0), m.get("max_dd_5d_cum",0),
             m.get("mean_10d")))
show("门开", open_m); show("门关", closed_m); show("无门整体", all_m)

# ── 4. 统计显著性: 门开 vs 门关 胜率差异 (双比例z检验) ─────────────
def two_prop_z(w1, n1, w2, n2):
    p1, p2 = w1/n1, w2/n2
    p = (w1+w2)/(n1+n2)
    se = math.sqrt(p*(1-p)*(1/n1+1/n2))
    z = (p1-p2)/se if se else float("nan")
    # p-value (双侧), 用正态
    import scipy.stats as st
    pval = 2*st.norm.sf(abs(z))
    return p1, p2, z, pval, se

z_res = {}
if open_m.get("n") and closed_m.get("n"):
    p1, p2, z, pval, se = two_prop_z(open_m["wins"], open_m["n"], closed_m["wins"], closed_m["n"])
    z_res = {"open_win_rate": round(p1*100,2), "closed_win_rate": round(p2*100,2),
             "diff_pp": round((p1-p2)*100,2), "z": round(z,3), "p_value": round(pval,4),
             "n_open": open_m["n"], "n_closed": closed_m["n"]}
    print("\n[4] 双比例z检验 (门开 vs 门关 胜率):")
    print("  门开 %.2f%% (%d/%d) | 门关 %.2f%% (%d/%d)" % (p1*100, open_m["wins"], open_m["n"], p2*100, closed_m["wins"], closed_m["n"]))
    print("  差异 %+.2f pp | z=%+.3f | p=%.4f  → %s" % ((p1-p2)*100, z, pval,
          "统计显著(p<0.05)" if pval<0.05 else "不显著(p≥0.05)"))

# ── 5. 秩IC: 综合评分 & 各子分, 分门开/门关 ─────────────────────
def spearman_ic(pairs):
    pairs = [(a,b) for a,b in pairs if a is not None and b is not None]
    n = len(pairs)
    if n < 10: return None
    def rank(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        rk=[0]*n; i=0
        while i<n:
            j=i
            while j+1<n and vals[order[j+1]]==vals[order[i]]: j+=1
            avg=(i+j)/2+1
            for k in range(i,j+1): rk[order[k]]=avg
            i=j+1
        return rk
    xs=[p[0] for p in pairs]; ys=[p[1] for p in pairs]
    rx=rank(xs); ry=rank(ys)
    mx=sum(rx)/n; my=sum(ry)/n
    cov=sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    vx=math.sqrt(sum((x-mx)**2 for x in rx)); vy=math.sqrt(sum((y-my)**2 for y in ry))
    return cov/(vx*vy) if vx and vy else None

ic_report = {}
for label, sub in [("门开", open_rows), ("门关", closed_rows), ("无门", real)]:
    base = lambda key: [(fnum(r.get(key,"")), fnum(r["5日净收益%"])) for r in sub]
    ic_report[label] = {
        "综合评分": round(spearman_ic(base("综合评分")) or 0,4),
        "趋势分":   round(spearman_ic(base("趋势评分")) or 0,4),
        "突破分":   round(spearman_ic(base("突破评分")) or 0,4),
        "抄底分":   round(spearman_ic(base("抄底评分")) or 0,4),
    }
print("\n[5] 秩IC (score vs 5日净收益):")
for label in ["门开","门关","无门"]:
    print("  %-4s: " % label + "  ".join("%s=%+.3f" % (k,v) for k,v in ic_report[label].items()))

# ── 6. 保存结构化结果 ──────────────────────────────────────────
out = {
    "generated": BT.date.today().isoformat() if hasattr(BT,"date") else None,
    "数据源": {"trade_csv": "backtest_analysis/final_verify/trade_detail_v2.csv",
               "index": "TDX sh000001.day (MA250)", "n_trades": len(real)},
    "门开期": open_m, "门关期": closed_m, "无门整体": all_m,
    "z检验": z_res,
    "因子IC": ic_report,
}
with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print("\n[6] 结果已写 %s" % OUT_JSON)
