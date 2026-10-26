# -*- coding: utf-8 -*-
"""pca_factor_synthesis.py — PCA 因子合成模块（纯 Python 核心 + numpy SVD，无 numba）

Kimi 方案(P0)落地: 用 PCA 对"同经济含义因子组"提纯正交化, 消除多重共线性导致的
IC 虚低/不稳, 产出合成"超级因子", 用 RankIC/ICIR 与原始单因子对比验收。

核心原则(红线, Kimi 踩坑清单):
  1. 防泄露: 去极值/标准化/PCA 的 fit 只在训练段做, 测试段只 transform。
  2. 必须截面标准化(否则量纲大因子霸占主成分)。
  3. 按经济含义分组做, 不全局 PCA(得不可解释杂烩主成分)。
  4. 主成分数看累积解释方差曲线定, 不拍脑袋。
  5. PCA 只抓线性结构。

因子值一律纯 Python 现场生成(不依赖已坏的 numba fast_compute_all), 与
.scratch/factor_ic_scan.py 同算术口径, 可复现、可测试。

公共 seam(测试边界):
  mad_winsorize(vals)                 -> list[float]  MAD去极值
  cross_section_zscore(vals)          -> list[float]  截面标准化(独立真值可验)
  pca_eigh(X)                         -> (vectors, eigvals)  对称阵特征分解(numpy)
  fit_zscore(params, cols)            -> dict           训练段标准化参数
  transform_zscore(params, cols)      -> list            测试段套用参数(防泄露)
  grouped_pca(panel, groups, n_pc)   -> dict            组内PCA(PC1..PCn+载荷+累积方差)
  spearman_rank_ic(x, y)              -> Optional[float] 逐日截面 RankIC
  icir(ic_series)                     -> Optional[float] RankIC均值/标准差
  build_factor_panel(records, horizon)-> (dates, panel, fut)  截面因子值矩阵+未来收益

无未来价: 目标日 T=有效末根-horizon, 因子值只用 T 及以前, 未来收益=close[T+horizon]。
"""
import math
import numpy as np
from typing import Dict, List, Optional, Tuple, Callable

# ─────────────────────────────────────────────────────────────
# 1. 纯 Python 数值原语(可独立真值验证, 不依赖 numpy)
# ─────────────────────────────────────────────────────────────

def mad_winsorize(vals: List[float], n_sigma: float = 5.0) -> List[float]:
    """MAD 去极值: clip 到 median ± n_sigma*1.4826*MAD。纯 Python。

    真值: [1,2,3,4,100] -> med=3, mad=|x-3|=[2,1,0,1,97]->sorted=[0,1,1,2,97]->mad=1
           lo=3-5*1.4826*1=-4.413, hi=3+7.413=10.413 -> 100 clip 到 10.413
    """
    vals = list(vals)
    n = len(vals)
    if n < 5:
        return vals
    med = sorted(vals)[n // 2]
    mad = sorted(abs(x - med) for x in vals)[n // 2]
    lo, hi = med - n_sigma * 1.4826 * mad, med + n_sigma * 1.4826 * mad
    return [max(lo, min(hi, x)) for x in vals]


def cross_section_zscore(vals: List[float]) -> List[float]:
    """截面标准化: (x-mean)/std, 缺失填0。std=总体std(ddof=0)。

    真值: [1,2,3,4,5] -> mean=3, std=sqrt(2)=1.4142 -> [-1.414,-0.707,0,0.707,1.414]
    """
    clean = [v for v in vals if v is not None and math.isfinite(v)]
    if not clean:
        return [0.0] * len(vals)
    mean = sum(clean) / len(clean)
    var = sum((x - mean) ** 2 for x in clean) / len(clean)
    std = math.sqrt(var) if var > 0 else 1.0
    out = []
    for v in vals:
        if v is None or not math.isfinite(v):
            out.append(0.0)
        else:
            out.append((v - mean) / std)
    return out


def spearman_rank_ic(x: List[float], y: List[float]) -> Optional[float]:
    """Spearman 秩相关(与 factor_ic_scan.spearman 同算术)。n<30 返回 None。

    真值: x=[1,2,3,4,5], y=[1,2,3,4,5] -> 完全同序 -> IC=1.0
          x=[1,2,3,4,5], y=[5,4,3,2,1] -> 完全逆序 -> IC=-1.0
    """
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None
             and math.isfinite(a) and math.isfinite(b)]
    n = len(pairs)
    if n < 30:
        return None
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]

    def rank(arr):
        idx = sorted(range(len(arr)), key=lambda i: arr[i])
        r = [0.0] * len(arr)
        for rv, i in enumerate(idx):
            r[i] = rv + 1
        i = 0
        while i < len(r):
            j = i
            while j < len(r) - 1 and abs(arr[idx[j]] - arr[idx[j + 1]]) < 1e-12:
                j += 1
            avg = sum(r[k] for k in range(i, j + 1)) / (j - i + 1)
            for k in range(i, j + 1):
                r[k] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(sum((v - mx) ** 2 for v in rx) * sum((v - my) ** 2 for v in ry))
    return num / den if den > 1e-15 else None


def icir(ic_series: List[Optional[float]]) -> Optional[float]:
    """ICIR = mean(IC)/std(IC, ddof=1)。剔除 None, 需 >=2 个点。

    真值: [0.1,0.2,0.3,0.4] -> mean=0.25, std=sqrt(0.0025/...)=0.129 -> ICIR≈1.9365
    """
    s = [v for v in ic_series if v is not None]
    if len(s) < 2:
        return None
    m = sum(s) / len(s)
    var = sum((v - m) ** 2 for v in s) / (len(s) - 1)
    std = math.sqrt(var)
    return m / std if std > 1e-15 else None


# ─────────────────────────────────────────────────────────────
# 2. PCA fit/transform (防泄露: 参数只在训练段算, 测试段套用)
# ─────────────────────────────────────────────────────────────

def fit_zscore(cols: Dict[str, List[float]]) -> Dict[str, dict]:
    """训练段: 每个因子算 mean/std, 返回参数表。防泄露红线1: 只用传入(=训练)数据。"""
    params = {}
    for name, vals in cols.items():
        z = cross_section_zscore(vals)
        # 参数 = 标准化后该因子的均值方差(=1), 真正要存的是原始 mean/std 供 transform 复用
        clean = [v for v in vals if v is not None and math.isfinite(v)]
        if clean:
            mean = sum(clean) / len(clean)
            var = sum((v - mean) ** 2 for v in clean) / len(clean)
            params[name] = {"mean": mean, "std": math.sqrt(var) if var > 0 else 1.0}
        else:
            params[name] = {"mean": 0.0, "std": 1.0}
    return params


def transform_zscore(params: Dict[str, dict], cols: Dict[str, List[float]]) -> Dict[str, List[float]]:
    """测试段: 用训练段参数标准化, 不用测试段自身均值(防泄露)。"""
    out = {}
    for name, vals in cols.items():
        p = params.get(name, {"mean": 0.0, "std": 1.0})
        m, s = p["mean"], p["std"]
        out[name] = [((v - m) / s if (v is not None and math.isfinite(v)) else 0.0) for v in vals]
    return out


def pca_eigh(X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """对称阵 X@Xᵀ 的特征分解(协方差型, X 已去极值+标准化后)。

    返回 (vectors: m×m 降序, eigvals: 降序)。用 numpy eigh(确定性, 无 JIT)。
    真值: 完全共线两因子 X=[[1,1],[2,2],[3,3]] -> PC1=[0.707,0.707], 特征值一个非零一个~0

    边界: 单因子组(X 只有1列) -> 退化 1×1, PC1 即该因子本身(无正交化收益)。
    """
    X = np.asarray(X, dtype=np.float64)
    C = np.cov(X, rowvar=False, bias=True)
    C = np.atleast_2d(C)            # 单因子时 np.cov 返回标量(0-d) -> 升成 1×1
    C = (C + C.T) / 2.0             # 对称化(数值噪声)
    eigvals, eigvecs = np.linalg.eigh(C)   # 升序
    idx = np.argsort(eigvals)[::-1]         # 降序
    eigvals = eigvals[idx]
    eigvecs = eigvecs[:, idx]
    eigvals = np.clip(eigvals, 0.0, None)   # 数值负零裁剪
    return eigvecs, eigvals


def grouped_pca(panel: Dict[str, List[float]], groups: Dict[str, List[str]],
                n_pc: int = 1) -> Dict[str, dict]:
    """按经济分组做 PCA。每组: MAD去极值->标准化->PCA->取前 n_pc 主成分。

    返回 {组名: {"pc1": 合成因子值list, "loadings": {因子:载荷}, "pc_values":[...],
                 "eigvals":[...], "cum_var":[...], "pc_chosen": 实际取的成分数}}
    n_pc 默认1(原文场景一: 组内取PC1, 可解释性最强)。
    """
    result = {}
    for gname, factor_names in groups.items():
        cols = {}
        for fn in factor_names:
            if fn in panel:
                cols[fn] = panel[fn]
        if len(cols) < 1:
            continue
        # 2. 组内截面去极值 + 标准化
        zcols = {}
        for fn, vals in cols.items():
            zcols[fn] = cross_section_zscore(mad_winsorize([v if v is not None else 0.0 for v in vals]))
        # 3. 组内因子矩阵 (n_stocks × n_factors)
        X = _stack(cols, zcols)
        eigvecs, eigvals = pca_eigh(X)
        k = min(n_pc, X.shape[0], X.shape[1])
        pc_values = []
        for j in range(k):
            # numpy eigh: 特征向量为列, eigvecs[i, j] = 因子i 在主成分j 的载荷
            loadings = {fn: float(eigvecs[i, j]) for i, fn in enumerate(cols)}
            # 合成因子值 PC_j: X @ eigvecs[:, j] = 逐样本 sum_i X[s,i]*eigvecs[i,j]
            comp = [float(sum(X[s, i] * eigvecs[i, j] for i in range(X.shape[1])))
                    for s in range(X.shape[0])]
            pc_values.append({"idx": j + 1, "loadings": loadings, "value": comp,
                             "var": float(eigvals[j] if j < len(eigvals) else 0.0)})
        total_var = float(sum(eigvals)) if len(eigvals) else 0.0
        cum = [float(sum(eigvals[:j + 1]) / total_var) if total_var > 0 else 0.0
               for j in range(len(eigvals))]
        result[gname] = {
            "pc1": pc_values[0]["value"] if pc_values else [],
            "pcs": pc_values,
            "eigvals": [float(v) for v in eigvals],
            "cum_var": cum,
            "pc_chosen": k,
            "n_factors": len(cols),
        }
    return result


def _stack(cols, zcols):
    """把 {因子: [逐股值]} 堆成 (n_stocks × n_factors) 矩阵。"""
    order = list(cols.keys())
    n_stocks = len(cols[order[0]])
    X = np.zeros((n_stocks, len(order)), dtype=np.float64)
    for j, fn in enumerate(order):
        for s in range(n_stocks):
            X[s, j] = zcols[fn][s]
    return X


def ic_vs_baseline(synthetic: List[float], baseline: Dict[str, List[float]],
                   future: List[float]) -> dict:
    """验收: 合成因子 vs 组内原始单因子, 比 RankIC/ICIR。

    单截面只能给 RankIC(点), ICIR 需 ic_series(时间序列)——此函数给单截面 RankIC,
    多截面时间序列用 rank_ic_series + icir。
    返回 {"synthetic": {"rank_ic":..}, "baselines": {因子:{"rank_ic":..}},
          "best_baseline": 因子名}
    """
    si = spearman_rank_ic(synthetic, future)
    b = {}
    best, best_ic = None, None
    for fn, vals in baseline.items():
        bi = spearman_rank_ic(vals, future)
        b[fn] = {"rank_ic": bi}
        if bi is not None and (best_ic is None or bi > best_ic):
            best, best_ic = fn, bi
    return {"synthetic": {"rank_ic": si}, "baselines": b, "best_baseline": best}


def rank_ic_series(panel_by_date: Dict[str, Dict[str, List[float]]],
                   future_by_date: Dict[str, List[float]],
                   factor_key: str) -> Dict[str, List[Optional[float]]]:
    """逐日截面 RankIC 时间序列 -> {factor: [ic_d1, ic_d2, ...]}。喂给 icir 得 ICIR。"""
    names = set()
    for d, p in panel_by_date.items():
        names.update(p.keys())
    out = {fn: [] for fn in names}
    for d in sorted(panel_by_date):
        fut = future_by_date.get(d, [])
        for fn in out:
            if fn in panel_by_date[d]:
                out[fn].append(spearman_rank_ic(panel_by_date[d][fn], fut))
    return out


# ─────────────────────────────────────────────────────────────
# 3. 因子值现场生成(纯 Python, 与 factor_ic_scan 同口径, 无未来价)
# ─────────────────────────────────────────────────────────────

def build_factor_panel(records: Dict[str, List[dict]], horizon: int = 5,
                       factors: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, List[float]], List[float]]:
    """从逐股 {code:[{date,open,high,low,close,volume,amount}...]} 构建
    单截面因子值矩阵 + 未来 horizon 收益。

    目标日 T = 每只股有效末根 - horizon(保证 T+horizon 在窗口内, 全点 in-time 无前视)。
    因子值只用 T 及以前数据; 未来收益 = close[T+horizon]。

    返回 (date_strs, panel{因子:[逐股值, 对齐 codes]}, future[逐股收益])。
    codes 顺序: 只保留能算出所有值的股票(面板对齐)。
    """
    FACTORS = factors or DEFAULT_FACTORS
    panel: Dict[str, List[float]] = {}
    fut: List[float] = []
    kept_codes: List[str] = []
    for code, bars in records.items():
        valid = [b for b in bars if b.get("close", 0) > 0]
        if len(valid) < 25 + horizon:
            continue
        T = len(valid) - 1 - horizon
        if T < 20:
            continue
        cl = [b["close"] for b in valid]
        vo = [b["volume"] for b in valid]
        am = [b["amount"] for b in valid]
        i = T
        vals = {}
        vals["chg5"] = ((cl[i] - cl[i - 5]) / cl[i - 5] * 100) if i >= 5 and cl[i - 5] > 0 else 0.0
        vals["chg10"] = ((cl[i] - cl[i - 10]) / cl[i - 10] * 100) if i >= 10 and cl[i - 10] > 0 else 0.0
        v20 = sum(vo[i - 19:i + 1]) / 20
        vals["vol_ratio"] = vo[i] / v20 if v20 > 0 else 1.0
        g = l = 0.0
        for k in range(i - 13, i + 1):
            ch = cl[k] - cl[k - 1]
            g += max(ch, 0); l += max(-ch, 0)
        vals["rsi14"] = 100 - 100 / (1 + g / max(l, 1e-9)) if (g + l) > 0 else 50.0
        vals["value_proxy"] = -am[i]
        fut.append((cl[i + horizon] - cl[i]) / cl[i] if cl[i] > 0 else 0.0)
        for fn in FACTORS:
            panel.setdefault(fn, []).append(vals.get(fn, 0.0))
        kept_codes.append(code)
    return (kept_codes, panel, fut)


# 默认分组(Kimi 4 组: 动量/波动率/流动性/估值)。只用可再生因子, 缺失6因子留待老三补。
DEFAULT_FACTORS = ["chg5", "chg10", "vol_ratio", "rsi14", "value_proxy"]
DEFAULT_GROUPS = {
    "momentum": ["chg5", "chg10"],
    "volatility": ["vol_ratio", "rsi14"],
    "valuation": ["value_proxy"],
}

# ─────────────────────────────────────────────────────────────
# 4. 可再生因子取值器(单一真源, 纯 Python, 无未来价) + 经济分组
# ─────────────────────────────────────────────────────────────
# 全部因子值只用 cl[i] 及以前数据; 未来收益由面板层单独取 cl[i+horizon]。
# MACD/DEA 需全序列 EMA(截断窗口近似偏差大) -> 本轮 defer, 留老二重建。

def _ema(arr, n):
    if len(arr) < n:
        return [arr[-1] if arr else 0.0]
    k = 2.0 / (n + 1)
    out = [sum(arr[:n]) / n]
    for x in arr[n:]:
        out.append(k * x + (1 - k) * out[-1])
    return out

def _rsi(cl, i, period):
    if i < period:
        return 50.0
    g = l = 0.0
    for k in range(i - period + 1, i + 1):
        ch = cl[k] - cl[k - 1]
        g += max(ch, 0); l += max(-ch, 0)
    if g + l == 0:
        return 50.0
    if l == 0:
        return 100.0  # 纯上涨无阴线, RSI=100
    if g == 0:
        return 0.0    # 纯下跌无阳线, RSI=0
    return 100 - 100 / (1 + g / l)

def _atr(hi, lo, cl, i, period=14):
    if i < period:
        return 0.0
    trs = []
    for k in range(i - period + 1, i + 1):
        trs.append(max(hi[k] - lo[k], abs(hi[k] - cl[k-1]), abs(lo[k] - cl[k-1])))
    return sum(trs) / period

def _red_ratio10(cl, ope, i):
    if i < 9:
        return 0.0
    return sum(1 for k in range(i - 9, i + 1) if cl[k] > ope[k]) / 10.0

def _overnight_sum20(cl, ope, i):
    if i < 20 or any(cl[k-1] <= 0 for k in range(i - 18, i + 1)):
        return 0.0
    return sum(ope[k] / cl[k-1] - 1 for k in range(i - 19, i + 1)) * 100

def _low60_dist(cl, i):
    if i < 59 or min(cl[i - 59:i + 1]) <= 0:
        return 0.0
    return (cl[i] / min(cl[i - 59:i + 1]) - 1) * 100

def _vol_dryup(vo, i):
    if i < 59:
        return 0.0
    v60 = sum(vo[i - 59:i + 1]) / 60.0
    return max(vo[i - 4:i + 1]) / v60 if v60 > 0 else 0.0

def _amount_price_corr(am, cl, i):
    if i < 19:
        return 0.0
    ca = am[i - 19:i + 1]; cc = cl[i - 19:i + 1]
    n = len(ca); ma = sum(ca) / n; mc = sum(cc) / n
    cov = sum((ca[t] - ma) * (cc[t] - mc) for t in range(n))
    va = math.sqrt(sum((x - ma) ** 2 for x in ca)); vc = math.sqrt(sum((x - mc) ** 2 for x in cc))
    return cov / (va * vc) if va and vc else 0.0

def _amihud(cl, am, i):
    """Amihud 非流动性: 近20日 mean(|ret|/amount), 值越大越不流动。"""
    vals = []
    for k in range(max(0, i - 18), i + 1):
        if k > 0 and cl[k - 1] > 0 and am[k] > 0:
            vals.append(abs((cl[k] - cl[k - 1]) / cl[k - 1]) / am[k])
    return (sum(vals) / len(vals)) if vals else 0.0

def _pearson5(c, v, i):
    """近5日量价Pearson相关(6个点: i-5..i)。"""
    if i < 5:
        return None
    c5 = c[i-5:i+1]; v5 = v[i-5:i+1]
    n = len(c5)
    mc = sum(c5)/n; mv = sum(v5)/n
    cov = sum((c5[t]-mc)*(v5[t]-mv) for t in range(n))
    sc = math.sqrt(sum((x-mc)**2 for x in c5))
    sv = math.sqrt(sum((x-mv)**2 for x in v5))
    return cov/(sc*sv) if sc > 1e-15 and sv > 1e-15 else None

# 因子取值器: 统一签名 fn(c, o, h, l, v, a, i), 只用 i 及以前数据
REPRO_FACTORS = {
    # 动量
    "chg5":            lambda c, o, h, l, v, a, i: ((c[i] - c[i-5]) / c[i-5] * 100) if i >= 5 and c[i-5] > 0 else 0.0,
    "chg10":           lambda c, o, h, l, v, a, i: ((c[i] - c[i-10]) / c[i-10] * 100) if i >= 10 and c[i-10] > 0 else 0.0,
    "chg20":           lambda c, o, h, l, v, a, i: ((c[i] - c[i-20]) / c[i-20] * 100) if i >= 20 and c[i-20] > 0 else 0.0,
    "red_ratio10":     lambda c, o, h, l, v, a, i: _red_ratio10(c, o, i),
    "overnight_sum20": lambda c, o, h, l, v, a, i: _overnight_sum20(c, o, i),
    "low60_dist":      lambda c, o, h, l, v, a, i: _low60_dist(c, i),
    # 波动率
    "atr":             lambda c, o, h, l, v, a, i: _atr(h, l, c, i),
    "rsi6":            lambda c, o, h, l, v, a, i: _rsi(c, i, 6),
    "rsi14":           lambda c, o, h, l, v, a, i: _rsi(c, i, 14),
    "rsi24":           lambda c, o, h, l, v, a, i: _rsi(c, i, 24),
    "vol_ratio":       lambda c, o, h, l, v, a, i: v[i] / (sum(v[i-19:i+1]) / 20) if i >= 19 and sum(v[i-19:i+1]) > 0 else 1.0,
    # 流动性
    "AMIHUD":            lambda c, o, h, l, v, a, i: _amihud(c, a, i),
    "amount_price_corr": lambda c, o, h, l, v, a, i: _amount_price_corr(a, c, i),
    "vol_dryup":         lambda c, o, h, l, v, a, i: _vol_dryup(v, i),
    # 估值(仅成交额代理, 无真 PE/市值)
    "value_proxy":       lambda c, o, h, l, v, a, i: -a[i],
    # 新增6因子 (PCA二轮补全, 2026-10-08)
    "VR5_20":            lambda c, o, h, l, v, a, i: (sum(v[i-4:i+1])/5.0) / (sum(v[i-19:i+1])/20.0) if i >= 19 and sum(v[i-19:i+1]) > 0 else 1.0,
    "VCHG":              lambda c, o, h, l, v, a, i: ((sum(a[i-4:i+1])/5.0) - a[i-20]) / a[i-20] * 100 if i >= 20 and a[i-20] > 0 else None,
    "VMR5":              lambda c, o, h, l, v, a, i: _pearson5(c, v, i) if i >= 4 else None,
    "VOL_FLOOR":         lambda c, o, h, l, v, a, i: v[i] / min(v[i-19:i+1]) if i >= 19 and min(v[i-19:i+1]) > 0 else None,
    "VOL_SHRINK20":      lambda c, o, h, l, v, a, i: (sum(v[i-20:i])/20.0) / (sum(v[i-60:i])/60.0) if i >= 60 and sum(v[i-60:i]) > 0 else 1.0,
    "TURN5":             lambda c, o, h, l, v, a, i: sum(a[i-4:i+1]) / 5.0 if i >= 4 else 0.0,
}

# 经济分组(Kimi 4 组, 含PCA二轮新增6因子)。valuation 仅 1 因子 -> 前置条件: 本轮 defer。
ECONOMIC_GROUPS = {
    "momentum":   ["chg5", "chg10", "chg20", "red_ratio10", "overnight_sum20", "low60_dist"],
    "volatility": ["atr", "rsi6", "rsi14", "rsi24", "vol_ratio", "VR5_20", "VMR5", "VOL_FLOOR", "VOL_SHRINK20"],
    "liquidity":  ["AMIHUD", "amount_price_corr", "vol_dryup", "VCHG", "TURN5"],
    "valuation":  ["value_proxy"],
}

def group_coverage(groups=None, available=None):
    """前置条件检查: 各组可再生因子数。>=2 组本轮可做 PCA; 0-1 组 defer(待老二补算)。

    返回 {组: {"factors": [...], "n": int, "eligible_this_round": bool}}
    """
    groups = groups or ECONOMIC_GROUPS
    available = set(available) if available is not None else set(REPRO_FACTORS.keys())
    out = {}
    for g, fns in groups.items():
        have = [f for f in fns if f in available]
        out[g] = {"factors": have, "n": len(have), "eligible_this_round": len(have) >= 2}
    return out


def compute_all_factors(cl, ope, hi, lo, vo, am, i):
    """单股在目标日 i 的全部可再生因子值(只用 i 及以前数据, 无未来价)。"""
    return {name: fn(cl, ope, hi, lo, vo, am, i) for name, fn in REPRO_FACTORS.items()}

