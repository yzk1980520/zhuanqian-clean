# -*- coding: utf-8 -*-
"""run_pca_ic_analysis.py v2 — PCA 因子合成: 方向修正 + ICIR 重叠折算 + 240日稳健性

Kimi 审查-36 退回补测清单:
  P0-1 全量方向修正: 每个原始因子与 PC1 合成因子都测正负两个方向,
       入库候选 = |IC| 较大的方向; PC1 符号统一约定: 定向到 IC 为正。
       验收线改为 PC1 合成 vs 同组"最优翻向单因子"(双门槛: 折算ICIR提升 且 RankIC>=80%不降)。
  P0-2 ICIR 重叠修正: 所有 ICIR 同时报原始值 + 折算值(÷√5 粗折, 注明是粗折),
       入库门槛以折算后 ICIR 为准。
  P1   240日稳健性: 对 liquidity 组(唯一可能入库的)跑 240 日, 看 RankIC 曲线是否稳定,
       月度胜率补上。
防泄露红线: zscore + PCA特征向量 fit 只用窗口前 40 日(训练段), 验收段只 transform。
matplotlib 崩(同 numpy ABI 点) -> 图用 PIL 直接画 PNG。
序列约定: 所有 *_ic_series 返回与 common 等长的列表(训练段位置=None), 对齐不出错。
"""
import json, math, time, sys, argparse
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np
from PIL import Image, ImageDraw

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
from pca_factor_synthesis import (
    fit_zscore, transform_zscore, pca_eigh, spearman_rank_ic, icir,
    compute_all_factors, group_coverage,
)

DATA_DIR = BASE / "data" / "history_daily"
HORIZON = 5
ICIR_ADJ_K = math.sqrt(HORIZON)   # Kimi 粗折: 相邻IC重叠4/5 -> ICIR 虚高约 √5 倍
ROLL_60 = 60
ROLL_240 = 240
TRAIN_DAYS = 40                   # zscore+特征向量 fit 只用窗口前 40 日
N_STOCK_CAP = 4000
OUT_JSON = BASE / "data" / "pca_factor_ic_report.json"
OUT_MD = BASE / "docs" / "pca_factor_ic_report.md"
PNG_60 = BASE / "docs" / "pca_ic_curve_60d.png"
PNG_240 = BASE / "docs" / "pca_ic_curve_240d_liquidity.png"
PNG_CV = BASE / "docs" / "pca_cumvar.png"


# ───────────────────────── 数据层 ─────────────────────────
def load_universe(codes, tail=400):
    """逐股载入有效 bar(末 tail 根), 防御式跳过脏条目。

    Kimi-41 Q4债2: 检测 newest-first(倒序)数据 → loud fail + 诊断 + 拒绝继续。
    拍板口径: 静默翻转会让 TDX 数据问题永远不暴露(修症状不修根因),
    故此处强制上游修数据, 不自动 reverse()。
    """
    records = {}
    offenders = []
    for c in codes:
        fp = DATA_DIR / f"{c}.json"
        if not fp.exists():
            continue
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            print(f"🔴 [scripts\run_pca_ic_analysis.py] CR-01: except Exception:", file=sys.stderr)
        if not isinstance(raw, list):
            continue
        valid = [b for b in raw if isinstance(b, dict) and b.get("close", 0) > 0]
        if len(valid) < 70:
            continue
        # newest-first 检测: 有效 bar 的 date 序列, 存在前>后(倒序对)即为倒序数据
        ds = [b.get("date") for b in valid]
        ds = [d for d in ds if isinstance(d, str) and d]
        if ds and any(ds[i - 1] > ds[i] for i in range(1, min(len(ds), 10))):
            offenders.append((c, ds[0], ds[-1]))
            continue
        records[c] = valid[-tail:]
    if offenders:
        diag = "; ".join(f"{c}(first={f}, last={l})" for c, f, l in offenders)
        print(f"❌ [load_universe] 检测到 {len(offenders)} 只 newest-first(倒序)数据, 拒绝继续: {diag}", file=sys.stderr)
        print(f"   要求上游修复 TDX 数据排序(应 oldest-first): {','.join(c for c, _, _ in offenders)}", file=sys.stderr)
        raise RuntimeError(f"newest-first data detected in {len(offenders)} stock(s); upstream must fix TDX ordering (oldest-first): {diag}")
    return records


def build_cross_sections(records, roll_days, horizon, factors, min_need=100):
    """逐日截面: 因子值(compute_all_factors 只用 i 及以前) + 未来收益。

    返回 (panel_by_date, future_by_date, common_dates[等长])。
    """
    stock_series = []
    for c, bars in records.items():
        L = len(bars)
        cl = [b["close"] for b in bars]; op = [b["open"] for b in bars]
        hi = [b["high"] for b in bars]; lo = [b["low"] for b in bars]
        vo = [b["volume"] for b in bars]; am = [b["amount"] for b in bars]
        dates = [b["date"] for b in bars]
        s = {}
        last = L - 1 - horizon
        start = max(60, last - roll_days + 1)
        for i in range(last, start - 1, -1):
            if i < 60:
                break
            fvals = compute_all_factors(cl, op, hi, lo, vo, am, i)
            fut = (cl[i + horizon] - cl[i]) / cl[i] if cl[i] > 0 else 0.0
            s[dates[i]] = (fvals, fut)
        if len(s) >= TRAIN_DAYS:
            stock_series.append(s)
    if not stock_series:
        return {}, {}, []
    date_count = Counter()
    for s in stock_series:
        for d in s:
            date_count[d] += 1
    need = min(min_need, len(stock_series))
    common = sorted(d for d, cnt in date_count.items() if cnt >= need)[-roll_days:]
    if not common:
        common = sorted(date_count)[-roll_days:]
    panel = {d: {fn: [] for fn in factors} for d in common}
    future = {d: [] for d in common}
    for s in stock_series:
        for d in common:
            if d in s:
                fvals, fut = s[d]
                for fn in factors:
                    panel[d][fn].append(fvals.get(fn, 0.0))
                future[d].append(fut)
    return panel, future, common


def group_corr_mean(panel, fns):
    """因子对截面 Pearson 相关(全日平均)。"""
    acc = defaultdict(list)
    for d, p in panel.items():
        if not fns or fns[0] not in p or len(p[fns[0]]) < 30:
            continue
        n = len(p[fns[0]])
        for a in fns:
            for b in fns:
                if a < b and a in p and b in p:
                    xa = p[a]; xb = p[b]
                    if len(xa) < n or len(xb) < n:
                        continue
                    ma = sum(xa) / n; mb = sum(xb) / n
                    cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(n))
                    va = math.sqrt(sum((x - ma) ** 2 for x in xa))
                    vb = math.sqrt(sum((x - mb) ** 2 for x in xb))
                    if va and vb:
                        acc[(a, b)].append(cov / (va * vb))
    return {k: sum(v) / len(v) for k, v in acc.items() if v}


# ───────────────────────── PCA fit(只用训练段) + transform(验收段) ─────────────────────────
def fit_group(fns, panel, train_dates):
    """zscore 参数池化训练段 + 训练段池化 z 矩阵做 eigh -> PC1 特征向量。

    返回 (v1, zparams, cum_var, loadings)。
    """
    params = {}
    for f in fns:
        flat = [v for dd in train_dates for v in panel[dd].get(f, [])]
        params[f] = fit_zscore({f: flat})[f] if flat else {"mean": 0.0, "std": 1.0}
    rows = []
    for dd in train_dates:
        zcols = transform_zscore(params, {f: panel[dd][f] for f in fns
                                          if len(panel[dd].get(f, [])) >= 30})
        if len(zcols) != len(fns):
            continue
        n = len(zcols[fns[0]])
        for s in range(n):
            rows.append([zcols[fn][s] for fn in fns])
    Xtr = np.array(rows, dtype=np.float64)
    vecs, eig = pca_eigh(Xtr)
    ev = np.clip(eig, 0, None)
    tot = ev.sum()
    cum_var = [float(ev[:j + 1].sum() / tot) for j in range(len(ev))] if tot > 0 else []
    loadings = {fns[i]: float(vecs[i, 0]) for i in range(len(fns))}
    return vecs[:, 0], params, cum_var, loadings


def pc1_ic_series(fns, panel, future, common, v1, params, start_idx=0):
    """逐截面 PC1 = X_z @ v1(固定训练段特征向量)。返回与 common 等长列表(前段=None)。"""
    out = []
    for idx, d in enumerate(common):
        if idx < start_idx:
            out.append(None)
            continue
        if len(panel[d].get(fns[0], [])) < 30:
            out.append(None)
            continue
        zcols = transform_zscore(params, {f: panel[d][f] for f in fns})
        n = len(zcols[fns[0]])
        X = np.array([[zcols[fn][s] for fn in fns] for s in range(n)], dtype=np.float64)
        out.append(spearman_rank_ic(list(X @ v1), future[d]))
    return out


def single_ic_series(f, panel, future, common, start_idx=0):
    """单因子逐截面 RankIC。返回与 common 等长列表(前段=None)。"""
    out = []
    for idx, d in enumerate(common):
        if idx < start_idx:
            out.append(None)
            continue
        col = panel[d].get(f, [])
        out.append(spearman_rank_ic(col, future[d]) if len(col) >= 30 else None)
    return out


# ───────────────────────── 方向修正 + 统计量 ─────────────────────────
def orient_series(series):
    """Kimi P0-1: 因子方向任意, 翻向到 IC 为正(取 |IC| 较大的方向)。

    返回 (sign, oriented_series[等长])。
    """
    s = [x for x in series if x is not None]
    if not s:
        return 1.0, list(series)
    sign = 1.0 if sum(s) >= 0 else -1.0
    return sign, [None if x is None else sign * x for x in series]


def series_stats(series):
    s = [x for x in series if x is not None]
    if len(s) < 2:
        return {"ic_mean": None, "icir_raw": None, "icir_adj": None, "n": len(s), "win_ratio": None}
    m = sum(s) / len(s)
    raw = icir(s)
    adj = raw / ICIR_ADJ_K if raw is not None else None
    return {"ic_mean": round(m, 4),
            "icir_raw": round(raw, 4) if raw is not None else None,
            "icir_adj": round(adj, 4) if adj is not None else None,
            "n": len(s),
            "win_ratio": round(sum(1 for x in s if x > 0) / len(s), 3)}


def monthly_win(series, dates):
    """月度胜率: 按月(YYYY-MM)分桶, 桶内 IC 均值 >0 记胜。series/dates 等长。"""
    bins = defaultdict(list)
    for d, v in zip(dates, series):
        if v is None:
            continue
        bins[d[:7]].append(v)
    if not bins:
        return None
    wins = sum(1 for vs in bins.values() if sum(vs) / len(vs) > 0)
    return {"months": len(bins), "wins": wins, "rate": round(wins / len(bins), 3)}


def segment_stats(series, dates, seg_len):
    """分段稳定性: 每 seg_len 日一段, 报每段 IC 均值/ICIR。series/dates 等长。"""
    out = []
    valid = [(d, v) for d, v in zip(dates, series) if v is not None]
    for j in range(0, len(valid), seg_len):
        chunk = valid[j:j + seg_len]
        if not chunk:
            continue
        vs = [v for _, v in chunk]
        out.append({"days": len(chunk), "ic_mean": round(sum(vs) / len(vs), 4),
                    "icir": icir(vs), "from": chunk[0][0], "to": chunk[-1][0]})
    return out


# ───────────────────────── B: 单截面冒烟(验管线正确性) ─────────────────────────
def smoke_test(panel, future, common, active_groups, train_days):
    """验: 合成值无 NaN / 训练段 PC1 载荷与强相关因子同号 / 防泄露(改未来 bar 不影响
    T 日值, 已独立验证; 本轮 zscore+特征向量 fit 全部锁在训练段)。"""
    train_dates = common[:min(train_days, len(common))]
    test_d = common[-1]
    result = {"passed": True, "checks": {}}
    for g, fns in active_groups.items():
        fns = [f for f in fns if f in panel.get(test_d, {}) and len(panel[test_d][f]) >= 30]
        if len(fns) < 2:
            result["checks"][g] = {"skipped": True, "reason": "因子<2"}
            continue
        v1, params, cum_var, loadings = fit_group(fns, panel, train_dates)
        zcols = transform_zscore(params, {f: panel[test_d][f] for f in fns})
        n = len(zcols[fns[0]])
        X = np.array([[zcols[fn][s] for fn in fns] for s in range(n)], dtype=np.float64)
        pc1 = list(X @ v1)
        finite = all(math.isfinite(x) for x in pc1)
        corr = group_corr_mean({test_d: panel[test_d]}, fns)
        same_sign = True
        for (a, b), cv in corr.items():
            if abs(cv) > 0.6 and loadings.get(a, 0) * loadings.get(b, 0) < 0:
                same_sign = False
        result["checks"][g] = {
            "pc1_finite": finite, "same_sign_strong_corr": same_sign,
            "n_factors": len(fns), "loadings_pc1": loadings,
            "cum_var_pc1": cum_var[0] if cum_var else None,
        }
        result["passed"] = result["passed"] and finite and same_sign
    result["note"] = ("fit=zscore+特征向量 全在训练段(前%d日池化), 验收段只 transform; "
                      "改未来 bar 不影响 T 日因子值(独立验证过)" % min(train_days, len(common)))
    return result


# ───────────────────────── 验收核心: 方向修正 + 折算ICIR 双门槛 ─────────────────────────
def acceptance_group(g, fns, panel, future, common, train_dates):
    """单组验收(Kimi P0-1/P0-2):
    PC1 合成(翻向到 IC>0) vs 同组最优翻向单因子; 双门槛 = 折算ICIR提升 且 RankIC>=80%不降。
    common 是验收窗(如 60 日窗), 序列与 common 等长, 训练段位置=None。
    """
    v1, params, cum_var, loadings = fit_group(fns, panel, train_dates)
    start = len(train_dates)  # 验收段起点(序列前段=None)
    # PC1 合成: 翻向
    raw_pc1 = pc1_ic_series(fns, panel, future, common, v1, params, start_idx=start)
    sign1, pc1_series = orient_series(raw_pc1)
    pc1_stat = series_stats(pc1_series)
    # 单因子: 逐个翻向, 取 |IC| 较大方向
    singles = {}
    for f in fns:
        raw_s = single_ic_series(f, panel, future, common, start_idx=start)
        sgn, oriented = orient_series(raw_s)
        st = series_stats(oriented)
        singles[f] = {"dir": "+" if sgn > 0 else "−",
                      "ic_mean": st["ic_mean"], "icir_raw": st["icir_raw"],
                      "icir_adj": st["icir_adj"], "win_ratio": st["win_ratio"],
                      "series": oriented}
    valid_singles = {f: s for f, s in singles.items() if s["ic_mean"] is not None}
    # Kimi 量化惯例: ICIR 为主、RankIC 均值次之、日胜率参考
    def _key(item):
        f, s = item
        return (s["icir_adj"] or -999, s["ic_mean"] or -999, s["win_ratio"] or 0)
    best_f, best_s = sorted(valid_singles.items(), key=_key, reverse=True)[0]
    improved = (pc1_stat["icir_adj"] or 0) > (best_s["icir_adj"] or 0)
    rankic_ok = (pc1_stat["ic_mean"] is not None and best_s["ic_mean"] is not None
                 and pc1_stat["ic_mean"] >= best_s["ic_mean"] * 0.8)
    return {
        "group": g, "factors": fns, "pc1_sign": sign1,
        "pc1": {"ic_mean": pc1_stat["ic_mean"], "icir_raw": pc1_stat["icir_raw"],
                 "icir_adj": pc1_stat["icir_adj"], "n": pc1_stat["n"]},
        "best_single": best_f,
        "single": {"dir": best_s.get("dir"), "ic_mean": best_s.get("ic_mean"),
                   "icir_raw": best_s.get("icir_raw"), "icir_adj": best_s.get("icir_adj")},
        "singles_detail": {f: {k: v for k, v in s.items() if k != "series"} for f, s in singles.items()},
        "improved_icir_adj": improved, "rankic_ok": rankic_ok,
        "allow_inbound": improved and rankic_ok,
        "cum_var": cum_var, "loadings_pc1": loadings,
        "_pc1_series": pc1_series,
        "_single_series": best_s.get("series") if best_s["ic_mean"] != -9 else [],
        "_dates": common,
    }


# ───────────────────────── PIL 出图(matplotlib 崩, 零依赖替代) ─────────────────────────
BG = (15, 15, 20); GRID = (42, 42, 53); TXT = (230, 230, 230); MUT = (136, 136, 136)
COLORS = [(230, 25, 75), (60, 180, 75), (67, 99, 216), (245, 130, 49), (145, 30, 180), (15, 127, 127)]


def chart_lines(title, series, fname, markers=(), w=1000, h=560):
    """series: [(label, [vals]), ...] 折线图; markers: 需画竖线的 x 位置(0-based 索引, 相对全长)。"""
    pad_l, pad_r, pad_t, pad_b = 70, 230, 60, 40
    pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
    allv = [v for _, vals in series for v in vals if v is not None]
    if not allv:
        return
    lo, hi = min(allv + [-1]), max(allv + [1])
    if hi == lo:
        hi = lo + 1
    L = max(len(v) for _, v in series)

    def X(i, n):
        return pad_l + i * pw / max(1, n - 1)

    def Y(v):
        return pad_t + (1 - (v - lo) / (hi - lo)) * ph

    img = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(img)
    dr.text((pad_l, 22), title, fill=TXT)
    for k in range(5):
        yy = pad_t + k * ph / 4
        vv = hi - k * (hi - lo) / 4
        dr.line([(pad_l, yy), (w - pad_r, yy)], fill=GRID)
        dr.text((6, yy - 6), f"{vv:+.3f}", fill=MUT)
    if lo < 0 < hi:
        y0 = Y(0)
        dr.line([(pad_l, y0), (w - pad_r, y0)], fill=(85, 85, 85))
    for ci, (lab, vals) in enumerate(series):
        col = COLORS[ci % 6]
        n = len(vals)
        prev = None
        for i, v in enumerate(vals):
            if v is None:
                prev = None
                continue
            pt = (X(i, n), Y(v))
            if prev:
                dr.line([prev, pt], fill=col, width=2)
            prev = pt
        dr.text((w - pad_r + 10, pad_t + 22 * ci + 6), lab, fill=col)
    for mi in markers:
        xx = X(min(mi, L - 1), L)
        dr.line([(xx, pad_t), (xx, pad_t + ph)], fill=(100, 100, 120), width=1)
    img.save(fname)


def chart_cumvar(cumvar_by_group, fname, w=760, h=460):
    pad_l, pad_r, pad_t, pad_b = 80, 210, 60, 50
    pw, ph = w - pad_l - pad_r, h - pad_t - pad_b
    img = Image.new("RGB", (w, h), BG)
    dr = ImageDraw.Draw(img)
    dr.text((pad_l, 22), "累积解释方差 (各组 PC1..PCK, 训练段 fit)", fill=TXT)
    for k in range(5):
        yy = pad_t + (1 - k / 4) * ph
        dr.line([(pad_l, yy), (w - pad_r, yy)], fill=GRID)
        dr.text((6, yy - 6), f"{k / 4:.0%}", fill=MUT)
    for ci, (g, cums) in enumerate(cumvar_by_group.items()):
        n = max(len(cums), 1)
        col = COLORS[ci % 6]
        pts = [(pad_l + (j + 1) * pw / (n + 1), pad_t + (1 - min(v, 1.0)) * ph)
               for j, v in enumerate(cums)]
        for a, b in zip(pts, pts[1:]):
            dr.line([a, b], fill=col, width=2)
        for p in pts:
            dr.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=col)
        dr.text((w - pad_r + 10, pad_t + 22 * ci + 6), f"{g} ({len(cums)}PC)", fill=col)
    dr.text((w // 2, h - 24), "主成分序号 →", fill=MUT)
    img.save(fname)


def write_md(report, cumvar):
    L = ["# PCA 因子合成 IC 对比报告 v2 (方向修正 + ICIR折算 + 240日稳健性)", "",
         f"生成: {report['generated_at']} | universe={report['universe_size']} | "
         f"60日验收窗={report['win60_dates']}日 / 240日稳健窗={report['win240_dates']}日 | "
         f"horizon={report['horizon']}日 | 折算系数=1/√{report['horizon']} (Kimi P0-2 粗折)",
         f"本轮组: { {g: len(v) for g, v in report['active_groups'].items()} } | "
         f"DEFER: {report.get('deferred_groups', {})}",
         "红线: zscore+PCA特征向量 fit 只用窗口前40日(训练段), 验收段只 transform。",
         "因子方向: 全部翻向到 IC 为正(P0-1); PC1 符号同此约定。",
         ""]
    s = report.get("smoke")
    if s:
        L += ["## 0. B 冒烟(单截面验管线)", f"  结果 PASS={s['passed']}", ""]
        for g, ch in s["checks"].items():
            if ch.get("skipped"):
                L.append(f"  - {g}: {ch['reason']}")
            else:
                L.append(f"  - {g}: finite={ch['pc1_finite']} 强相关载荷同号="
                         f"{ch['same_sign_strong_corr']} PC1解释方差={ch['cum_var_pc1']}")
    if report.get("collinearity_pairs"):
        L += ["", "## 1. 共线性诊断(|corr|>0.6, 因子'打架'证据)", ""]
        L += [f"  - {k}: corr={v:+.3f}" for k, v in report["collinearity_pairs"].items()]
    L += ["", "## 2. 60日验收: 单因子 vs 组内 PC1 合成 (双门槛按折算ICIR)", "",
          "| 组 | 最优翻向单因子 (IC均值/ICIR原始/ICIR折算) | PC1合成 (IC均值/ICIR原始/ICIR折算) | 判定 |",
          "|---|---|---|---|"]
    for g, r in report["rolling60"].items():
        sm = r["single"]["ic_mean"]; sr = r["single"]["icir_raw"]; sa = r["single"]["icir_adj"]
        pm = r["pc1"]["ic_mean"]; pr = r["pc1"]["icir_raw"]; pa = r["pc1"]["icir_adj"]
        verdict = "✅ 允许入库" if r["allow_inbound"] else "↩️ 保留单因子"
        L.append(f"| {g} | {r['best_single']}×{r['single']['dir']} ({sm}/{sr}/{sa}) "
                 f"| PC1 ({pm}/{pr}/{pa}) | {verdict} |")
    if cumvar:
        L += ["", "## 3. 累积解释方差 (训练段 fit)", ""]
        L += [f"  - {g}: " + " ".join(f"PC{j + 1}={v:.2f}" for j, v in enumerate(cv[:4]))
              for g, cv in cumvar.items()]
    if report.get("stability240"):
        st = report["stability240"]
        L += ["", "## 4. P1 240日稳健性 (liquidity 组)", ""]
        L.append(f"  月度胜率: PC1={st['pc1_monthly_win']}  最优单={st['single_monthly_win']}")
        L.append(f"  PC1 全窗: ic_mean={st['pc1_ic_mean']} icir_adj={st['pc1_icir_adj']} "
                 f"| 单{st['best_single']}×{st['single_dir']}: icir_adj={st['single_icir_adj']}")
        L.append("  分段(50日) IC 稳定性:")
        for lab, segs in (("PC1", st["pc1_segments"]),
                          (f"{st['best_single']}×{st['single_dir']}", st["single_segments"])):
            L.append(f"  - {lab}: " + " | ".join(
                f"[{seg['from'][:10]}..{seg['to'][:10]}] μ={seg['ic_mean']} "
                f"ir={round(seg['icir'], 3) if seg['icir'] is not None else 'n/a'}"
                for seg in segs))
    L += ["", "## 5. 单因子明细 (翻向后, 60日验收段)", "",
          "| 因子 | 方向 | IC均值 | ICIR原始 | ICIR折算(÷√5) | 日胜率 |", "|---|---|---|---|---|---|"]
    for g, r in report["rolling60"].items():
        for f, s in r["singles_detail"].items():
            mark = " ←组内最优" if f == r["best_single"] else ""
            L.append(f"| {f}{mark} | {s['dir']} | {s['ic_mean']} | {s['icir_raw']} "
                     f"| {s['icir_adj']} | {s.get('win_ratio')} |")
    L += ["", "## 6. 结论", ""]
    for g, r in report["rolling60"].items():
        L.append(f"- **{g}**: " + ("PC1 合成双门槛通过 → 允许入库" if r["allow_inbound"]
                   else f"PC1 未跑赢 最优翻向单因子 {r['best_single']}×{r['single']['dir']} → 保留单因子"))
    if report.get("deferred_groups"):
        L.append(f"- **defer 组** {list(report['deferred_groups'].keys())}: 因子<2, 本轮不合成, "
                 f"待老二补算 6 缺失因子后二轮")
    L += ["", "> 注: ICIR 折算值=原始÷√5, 为 Kimi 指定的粗折(相邻 IC 重叠 4/5 的系统性虚高), 仅入库门槛用。",
          "> 60日口径=冒烟级证据; 入库最终依据=240日稳健窗+月度胜率(本报告 §4)。"]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["smoke", "all"], default="all")
    args = ap.parse_args()
    t0 = time.time()

    print("═══ 载入 universe (tail=400 bars) ═══", flush=True)
    codes = [p.stem for p in sorted(DATA_DIR.glob("sh*.json")) + sorted(DATA_DIR.glob("sz*.json"))]

    def is_stock(c):
        # 扩大范围: sh6/sz0/sz3(主板+中小板+创业板) + sh0/sz1/sz2/sz4/sh5等
        # 排除指数/基金: sh000*, sh9*, sh5*, sz399*
        if c.startswith('sh') and c[2:].isdigit():
            if c == 'sh_index':
                return False
            if c[2:5] in ('000', '9', '5'):  # 指数类
                return False
            return True
        if c.startswith('sz') and c[2:].isdigit():
            if c[2:5] == '399':  # 创业板指数
                return False
            return True
        return False

    codes = [c for c in codes if is_stock(c)]
    if len(codes) > N_STOCK_CAP:
        step = len(codes) / N_STOCK_CAP
        codes = [codes[int(i * step)] for i in range(N_STOCK_CAP)]
    records = load_universe(codes, tail=400)
    print(f"  载入 {len(records)} 只, {time.time() - t0:.1f}s", flush=True)

    cov = group_coverage()
    active_groups = {g: d["factors"] for g, d in cov.items() if d["eligible_this_round"]}
    deferred_groups = {g: d["factors"] for g, d in cov.items() if not d["eligible_this_round"]}
    factors = sorted({f for g in active_groups.values() for f in g})
    print(f"  本轮 PCA 组: { {g: len(v) for g, v in active_groups.items()} }", flush=True)
    print(f"  DEFER 组(0-1因子, 待老二补): { deferred_groups }", flush=True)

    # 240 日截面(60 日验收窗 = 其末尾 60 日, 同源数据, 因子值一致)
    panel, future, common = build_cross_sections(records, ROLL_240, HORIZON, factors)
    nd = len(common)
    print(f"═══ {nd} 个共同交易日截面 (240日窗) ═══", flush=True)
    win240 = common                        # 240日稳健窗
    win60 = common[-ROLL_60:]              # 60日验收窗(最近60日)
    if len(win60) < 41:
        print("  ✗ 60日验收窗不足 41 日(需 40 训练 + 20 验收), 无法执行")
        sys.exit(3)

    report = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "universe_size": len(records), "horizon": HORIZON,
              "win60_dates": len(win60), "win240_dates": len(win240),
              "train_days": TRAIN_DAYS, "factors_used": factors,
              "active_groups": active_groups, "deferred_groups": deferred_groups,
              "icir_adj_coeff": round(1.0 / ICIR_ADJ_K, 4),
              "runtime_s": None}

    # 60 日窗子面板(与 240 日窗同源, 仅取最后 60 日)
    p60 = {d: {f: panel[d][f] for f in factors if f in panel[d]} for d in win60}
    fu60 = {d: future[d] for d in win60}
    train60 = win60[:TRAIN_DAYS]

    # ── B: 单截面冒烟(验管线) ──
    smoke = None
    if args.mode in ("smoke", "all"):
        print("═══ B: 单截面冒烟(验管线) ═══", flush=True)
        smoke = smoke_test(p60, fu60, win60, active_groups, TRAIN_DAYS)
        print(f"  冒烟 PASS={smoke['passed']}", flush=True)
        for g, ch in smoke["checks"].items():
            if ch.get("skipped"):
                print(f"    {g}: {ch['reason']}")
            else:
                print(f"    {g}: finite={ch['pc1_finite']} 同号={ch['same_sign_strong_corr']} "
                      f"PC1解释方差={ch['cum_var_pc1']}", flush=True)
        if not smoke["passed"]:
            print("  ✗ 冒烟未通过 -> 不进验收(避免空跑)")
            report["smoke"] = smoke
            OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
            OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float),
                                encoding="utf-8")
            sys.exit(2)

    # ── A: 60日验收(方向修正 + 折算ICIR 双门槛) ──
    print("═══ A: 60日验收 (翻向单因子 vs PC1合成, 折算ICIR) ═══", flush=True)
    rolling60 = {}
    cumvar = {}
    for g, fns in active_groups.items():
        r = acceptance_group(g, fns, p60, fu60, win60, train60)
        rolling60[g] = {k: v for k, v in r.items() if not k.startswith("_")}
        cumvar[g] = r["cum_var"]
        print(f"  {g}: PC1(翻向) ic={r['pc1']['ic_mean']} icir_adj={r['pc1']['icir_adj']} "
              f"vs 最优翻向单{r['best_single']}×{r['single']['dir']} ic={r['single']['ic_mean']} "
              f"icir_adj={r['single']['icir_adj']} -> "
              f"{'✅ 允许入库' if r['allow_inbound'] else '↩️ 保留单因子'}", flush=True)
        rolling60[g]["_series_ref"] = None  # 占位, 图用重新 fit(确定性 eigh, 结果一致)

    # ── P1: 240日稳健性(三组全补, Kimi 审查-38 拍板指令: 三组新冠军全部跑240日) ──
    stability240 = None
    if "liquidity" in active_groups or "momentum" in active_groups:
        print("═══ P1: 三组冠军 240日稳健性 (liquidity + momentum + volatility) ═══", flush=True)
        gdata = {}
        for g in ("liquidity", "momentum", "volatility"):
            gfns = active_groups.get(g)
            g60 = rolling60.get(g)
            if not gfns or not g60 or g60.get("best_single") is None:
                continue
            v1, prm, _cv, _ld = fit_group(gfns, panel, win240[:TRAIN_DAYS])
            raw_pc1 = pc1_ic_series(gfns, panel, future, win240, v1, prm, start_idx=TRAIN_DAYS)
            s1, pc1_240 = orient_series(raw_pc1)
            best_f = g60["best_single"]
            single_dir = g60["single"]["dir"]
            raw_s = single_ic_series(best_f, panel, future, win240, start_idx=TRAIN_DAYS)
            single_240 = [None if v is None else (-v if single_dir == "−" else v) for v in raw_s]
            val240 = win240[TRAIN_DAYS:]
            pc1_val = pc1_240[TRAIN_DAYS:]      # 与 val240 对齐(丢掉前40训练日None)
            single_val = single_240[TRAIN_DAYS:]
            pc1_st = series_stats(pc1_val)
            single_st = series_stats(single_val)
            gdata[g] = {
                "pc1_sign": s1,
                "pc1_ic_mean": pc1_st["ic_mean"],
                "pc1_icir_adj": pc1_st["icir_adj"],
                "pc1_segments": segment_stats(pc1_val, val240, 50),
                "pc1_monthly_win": monthly_win(pc1_val, val240),
                "best_single": best_f, "single_dir": single_dir,
                "single_ic_mean": single_st["ic_mean"],
                "single_icir_adj": single_st["icir_adj"],
                "single_segments": segment_stats(single_val, val240, 50),
                "single_monthly_win": monthly_win(single_val, val240),
                "single_win_ratio_240d": single_st["win_ratio"],
            }
            print(f"  {g}: 冠军 {best_f}×{single_dir} 240日 ic_mean={gdata[g]['single_ic_mean']} "
                  f"icir_adj={gdata[g]['single_icir_adj']} win240={gdata[g]['single_win_ratio_240d']} "
                  f"月胜={gdata[g]['single_monthly_win']} (PC1: icir_adj={gdata[g]['pc1_icir_adj']})",
                  flush=True)
            for lab, segs in (("PC1", gdata[g]["pc1_segments"]),
                              (f"{best_f}×{single_dir}", gdata[g]["single_segments"])):
                print(f"  {lab}分段: " + " | ".join(
                    f"[{s_['from'][:10]}..μ{s_['ic_mean']}/ir{round(s_['icir'] or 0, 2)}]"
                    for s_ in segs), flush=True)
        report["stability240_all"] = gdata
        report["stability240"] = gdata.get("liquidity")  # 向后兼容旧 schema

    # ── 共线性诊断(60日窗) ──
    report["collinearity_pairs"] = {
        "%s↔%s" % (a, b): round(v, 3)
        for (a, b), v in group_corr_mean(p60, factors).items() if abs(v) > 0.6}
    report["rolling60"] = rolling60
    report["cum_var"] = cumvar
    report["smoke"] = smoke
    report["runtime_s"] = round(time.time() - t0, 1)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float),
                        encoding="utf-8")
    write_md(report, cumvar)

    # ── 图(确定性 eigh 重新 fit, 与验收数字同源) ──
    pairs60 = []
    for g in active_groups:
        r = rolling60[g]
        v1, prm, _c, _l = fit_group(g_fns if (g_fns := active_groups[g]) else [], p60, train60)
        pc1s = pc1_ic_series(g_fns, p60, fu60, win60, v1, prm, start_idx=TRAIN_DAYS)
        pc1s = [None if v is None else (v if r["pc1"]["ic_mean"] is not None and r["pc1"]["ic_mean"] >= 0 else -v) for v in pc1s]
        bs = r["best_single"]
        ss = single_ic_series(bs, p60, fu60, win60, start_idx=TRAIN_DAYS)
        ss = [None if v is None else (-v if r["single"]["dir"] == "−" else v) for v in ss]
        pairs60.append((f"{g}/PC1(翻向)", pc1s))
        pairs60.append((f"{g}/{bs}×{r['single']['dir']}", ss))
    chart_lines("60日验收窗 (竖线=训练40日/验收20日分界)", pairs60, str(PNG_60), markers=[40])
    chart_cumvar(cumvar, str(PNG_CV))
    if stability240:
        liq = active_groups["liquidity"]
        v1, prm, _c, _l = fit_group(liq, panel, win240[:TRAIN_DAYS])
        pc1s = pc1_ic_series(liq, panel, future, win240, v1, prm, start_idx=TRAIN_DAYS)
        pc1s = [None if v is None else (v if stability240["pc1_sign"] > 0 else -v) for v in pc1s]
        ss = single_ic_series(stability240["best_single"], panel, future, win240, start_idx=TRAIN_DAYS)
        ss = [None if v is None else (-v if stability240["single_dir"] == "−" else v) for v in ss]
        chart_lines("liquidity 240日稳健窗 (竖线=50日分段)",
                    [(f"PC1(翻向)", pc1s),
                     (f"{stability240['best_single']}×{stability240['single_dir']}", ss)],
                    str(PNG_240), markers=[40, 90, 140, 190])
    print(f"\n═══ 完成 {report['runtime_s']}s | JSON={OUT_JSON.name} MD={OUT_MD.name} ═══")
    print(f"  60日判定: " + ", ".join(
        f"{g}:{'入库' if rolling60[g]['allow_inbound'] else '保留单因子'}" for g in active_groups))
    if stability240:
        print(f"  240日流动性: PC1 icir_adj={stability240['pc1_icir_adj']} vs 单 "
              f"{stability240['best_single']}×{stability240['single_dir']} icir_adj="
              f"{stability240['single_icir_adj']} | 月胜率 PC1={stability240['pc1_monthly_win']} 单={stability240['single_monthly_win']}")
    print(f"  图: {PNG_60.name} {PNG_CV.name} {PNG_240.name if stability240 else '-'}")


if __name__ == "__main__":
    main()
