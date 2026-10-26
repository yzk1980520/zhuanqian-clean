# -*- coding: utf-8 -*-
"""
震荡市因子相关性矩阵分析
"""
import sys, os, json, math
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

from core.scoring.tdx_indicators import compute_indicators

def spearman(xs, ys):
    n = len(xs)
    if n < 30: return None
    def rank(arr):
        indexed = sorted(range(len(arr)), key=lambda i: arr[i])
        r = [0.0] * len(arr)
        for rv, idx in enumerate(indexed): r[idx] = rv + 1
        i = 0
        while i < len(r):
            j = i
            while j < len(r) - 1 and abs(arr[indexed[j]] - arr[indexed[j+1]]) < 1e-12:
                j += 1
            avg = sum(r[k] for k in range(i, j+1)) / (j - i + 1)
            for k in range(i, j+1): r[k] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx)/n, sum(ry)/n
    num = sum((rx[i]-mx)*(ry[i]-my) for i in range(n))
    den = (sum((x-mx)**2 for x in rx) * sum((y-my)**2 for y in ry))**0.5
    return num/den if den > 1e-15 else None

# 加载历史扫描数据
data_dir = "data/history_daily"
files = [f for f in os.listdir(data_dir) if f.endswith(".json") and not f.startswith("sh000") and not f.startswith("sz399")]
print(f"Total stock files: {len(files)}")

# 采样
import random
rnd = random.Random(42)
sample_files = rnd.sample(files, min(500, len(files)))

# 收集因子值
factor_names = [
    "chg5", "chg10", "chg20",
    "vol_ratio", "vol_shrink20", "vol_floor",
    "std20", "max_ret5", "turn5",
    "rsi14", "rsi_extreme", "pos_vs_ma20",
    "amount_q_reversal", "vol_price_corr_20", "price_volume_divergence",
    "alpha13", "alpha16_fix", "unlocked_pressure",
    "fund_flow_intensity", "macd_hist", "dif", "rms", "breakout_strength"
]

factor_data = {f: [] for f in factor_names}

for fpath in sample_files:
    try:
        data = json.load(open(os.path.join(data_dir, fpath)))
        if not data or len(data) < 60: continue
        n = len(data)
        for pos in [n-30, n-20, n-10]:
            if pos < 30: continue
            past = data[:pos+1]
            inds = compute_indicators(past)
            if not inds: continue
            for f in factor_names:
                val = inds.get(f)
                if val is not None and not math.isnan(float(val)):
                    factor_data[f].append(float(val))
    except (AttributeError, KeyError):
        print(f"🔴 [scripts\factor_correlation_analysis.py] CR-01: except (AttributeError, KeyError):", file=sys.stderr)
print(f"Collected {len(factor_data['chg5'])} valid samples")

# 计算相关性矩阵

valid_factors = [f for f in factor_names if len(factor_data[f]) >= 100]
print(f"Valid factors: {len(valid_factors)}")

corr_matrix = {}
for f1 in valid_factors:
    corr_matrix[f1] = {}
    for f2 in valid_factors:
        if f1 == f2:
            corr_matrix[f1][f2] = 1.0
        elif f2 in corr_matrix and f1 in corr_matrix[f2]:
            corr_matrix[f1][f2] = corr_matrix[f2][f1]
        else:
            v1 = factor_data[f1][:min(len(factor_data[f1]), len(factor_data[f2]))]
            v2 = factor_data[f2][:len(v1)]
            # P2-b (K56 §二): 保留 None (不可算) 不洗 0.0 — 与 L113 写层一致, 防"内存0.0/文件null"双源
            corr_matrix[f1][f2] = spearman(v1, v2)

# 输出矩阵
short_names = [f[:12] for f in valid_factors[:15]]
header = f"{'':25s}"
for sn in short_names:
    header += f"{sn:>12s}"
for f1 in valid_factors[:15]:
    row = f"{f1[:25]:25s}"
    for f2 in valid_factors[:15]:
        c = corr_matrix[f1].get(f2, 0)
        if c is None: c = 0
        row += f"{c:+.3f}" + "       "

# 保存到文件
# P2-b (K56 §二): None (不可算) → null, 不洗 0 (0 会暗示"零相关", 掩盖不可算=假绿)。
# 0.0 (真实零相关) 保留 0.0; 与 L94 in-memory 保留 None 一致, 内存/文件同语义, 无双源。
output = {
    "timestamp": "2026-09-20",
    "sample_size": len(factor_data['chg5']),
    "valid_factors": valid_factors,
    "correlation_matrix": {k: {kk: round(vv, 4) if vv is not None else None for kk, vv in v.items()}
                           for k, v in corr_matrix.items()}
}
from core.pipeline.atomic_json import atomic_dump  # R4c #6 (K54 §六 全量替换语义): 全量覆盖+原子写, 行为等同原裸 open('w'), 零读侧改动
atomic_dump(output, "data/factor_correlation_matrix.json")
print(f"\nSaved: data/factor_correlation_matrix.json")

# 高相关因子对
high_corr = []
for i, f1 in enumerate(valid_factors[:15]):
    for f2 in valid_factors[i+1:i+15]:
        c = corr_matrix[f1].get(f2, 0)
        if c is not None and abs(c) > 0.5:
            high_corr.append((f1, f2, c))
            tag = "[REDUNDANT]" if abs(c) > 0.7 else "[CORR]"
            print(f"  {tag} {f1[:20]} vs {f2[:20]} = {c:+.3f}")

if not high_corr:
    pass