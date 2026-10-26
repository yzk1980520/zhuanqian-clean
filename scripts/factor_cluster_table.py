# -*- coding: utf-8 -*-
"""因子族聚类 + 符号钳定对照表生成器 (老五数据面件, K45 首权前置裁定件)

背景 (10/25 D-8 扩池后, 权威卡 17 valid 全为量能/流动性族负 IC):
  - 门禁 counted_factors=17 把高共线同族件当独立数 → 有效自由度虚高
  - 17 件 valid 全负 IC, K45 出首权前须钳定符号约定 (weight*IC >= 0)

输入:
  - ic_by_date dump: 132d 截面 IC 序列 (由 scripts/factor_ic_132d_refresh.py
    --dump-ic-series 生成, 默认 .scratch/ic_series_132d_d8_20261025.json)
  - 权威卡 data/factor_ic/factor_ic_latest.json (valid 池 + 可复现 ic 值)

输出:
  - data/factor_ic/factor_cluster_table_<YYYYMMDD>.json (确定性: 同输入同输出)
  - stdout 对照表 (17 valid 族聚类 + 相关性 top 对 + 符号稳定性 + K45 钳定断言)

断言:
  A1a 可复现性: mean(ic_series[f]) vs 权威卡 ic[f], 容差=4 位舍入量子 5e-5;
  A1b 逐值 bit-exact: 重跑候选卡 vs 权威卡 ic 字段 (同为舍入面, 零容差);
     不过 = 本表 INVALID (universe/口径漂移, fail-closed 升级, 不得消费)。
  A2 族封顶: union-find 合并 |pearson(ic_series)| >= 0.90 的因子, 每族计 1。
  A3 符号钳定: 每因子 frac_neg_dates + K45 规则: weight*IC >= 0 或 weight=0。
  A4 有效样本量: lag1 IC 自相关折扣 (132d 名义窗口 → 有效独立截面日)。

用法:
  python scripts/factor_cluster_table.py [--ic-series PATH] [--card PATH] [--corr-threshold 0.90]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs) ** 0.5
    vy = sum((b - my) ** 2 for b in ys) ** 0.5
    if vx == 0 or vy == 0:
        return None  # 零方差序列: 该因子当窗口恒值, 无法算相关 (留证)
    return cov / (vx * vy)


def _union_find_find(n):
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    return find, union


def _normalize(raw):
    """归一为 {factor: {date: ic}}。兼容 {date:{factor:ic}} / {factor:{date:ic}} / {factor:[ics]}。"""
    if not raw:
        return {}
    if all(isinstance(v, dict) for v in raw.values()):
        # refresh 脚本 --dump-ic-series 落盘格式 {date: {factor: ic}} → 转置
        out = {}
        for d, fd in raw.items():
            for f, v in fd.items():
                out.setdefault(f, {})[str(d)] = v
        return out
    out = {}
    for f, v in raw.items():
        if isinstance(v, dict):
            out[f] = {str(k): x for k, x in v.items()}
        else:
            out[f] = {str(i): x for i, x in enumerate(v)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ic-series", default=str(BASE / ".scratch" / "ic_series_132d_d8_20261025.json"))
    ap.add_argument("--card", default=str(BASE / "data" / "factor_ic" / "factor_ic_latest.json"))
    ap.add_argument("--rerun-card", default=str(BASE / "data" / "factor_ic" / "factor_ic_132d_refresh_20261025_083422.json"))
    ap.add_argument("--corr-threshold", type=float, default=0.90)
    args = ap.parse_args()

    card = json.load(open(args.card, encoding="utf-8"))
    card_factors = {f["name"]: f for f in card["factors"]}
    valids = [f["name"] for f in card["factors"] if f["status"] == "valid"]
    per = _normalize(json.load(open(args.ic_series, encoding="utf-8")))

    # ── A1 可复现性: 序列均值 vs 权威卡 ic (逐因子按公共截面对齐) ──
    aligned = {}
    all_dates = sorted(set().union(*[set(v.keys()) for v in per.values()])) if per else []
    for name in valids:
        if name not in per or not per[name]:
            print(f"[FAIL] A1: valid 因子 {name} 无 IC 序列 → 本表 INVALID")
            return 2
        aligned[name] = [per[name].get(d) for d in all_dates]

    # A1a 口径: 权威卡 ic 字段=引擎 4 位舍入值 → 序列均值 vs 卡片 ic 容差=舍入量子 5e-5
    # (1e-9 仅适用于 序列 vs 序列 的独立双跑; 序列 vs 舍入卡值 用 5e-5)
    ROUND_TOL = 5e-5
    repro = {}
    a1a_ok = True
    for name in valids:
        ics = [x for x in aligned[name] if x is not None]
        if not ics:
            repro[name] = {"mean_ic": None, "card_ic": card_factors[name]["ic"],
                           "delta": None, "n_dates": 0, "verdict": "NO_SERIES"}
            a1a_ok = False
            continue
        mean_ic = sum(ics) / len(ics)
        card_ic = card_factors[name]["ic"]
        delta = abs(mean_ic - card_ic) if card_ic is not None else None
        ok = (delta is not None and delta <= ROUND_TOL)
        a1a_ok = a1a_ok and ok
        repro[name] = {"mean_ic_full": mean_ic, "mean_ic": round(mean_ic, 6), "card_ic": card_ic,
                       "delta": delta, "n_dates": len(ics),
                       "verdict": "PASS" if ok else "FAIL"}
    max_delta = max((r["delta"] for r in repro.values() if r["delta"] is not None), default=None)

    # A1b 口径: 重跑候选卡 vs 权威卡, ic 字段逐值 bit-exact (同为 4 位舍入面, 零容差)
    a1b = {"verdict": "SKIP_NO_RERUN_CARD", "n_compared": 0, "n_mismatch": 0, "mismatch": []}
    try:
        rerun = json.load(open(args.rerun_card, encoding="utf-8"))
        rm = {f["name"]: f.get("ic") for f in rerun.get("factors", [])}
        mismatch = []
        for name, f in card_factors.items():
            ic = f.get("ic")
            if name not in rm:
                continue  # 池差 (重跑卡无此因子) 不算 mismatch, 计数留痕
            if ic != rm[name]:
                mismatch.append({"name": name, "card_ic": ic, "rerun_ic": rm[name]})
        a1b = {"verdict": "PASS" if not mismatch else "FAIL",
               "rerun_card": os.path.relpath(args.rerun_card, BASE),
               "n_compared": len([n for n in card_factors if n in rm]),
               "n_missing_in_rerun": len(card_factors) - len(rm),
               "n_mismatch": len(mismatch), "mismatch": mismatch[:10]}
    except FileNotFoundError:
        pass
    a1_ok = a1a_ok and a1b["verdict"] in ("PASS", "SKIP_NO_RERUN_CARD")

    # ── A2 族聚类: 逐对 pearson + union-find (|rho|>=thr 合族) ──
    pairs = []
    for i in range(len(valids)):
        for j in range(i + 1, len(valids)):
            a, b = valids[i], valids[j]
            xs = [x for x, y in zip(aligned[a], aligned[b]) if x is not None and y is not None]
            ys = [y for x, y in zip(aligned[a], aligned[b]) if x is not None and y is not None]
            rho = _pearson(xs, ys)
            if rho is not None:
                pairs.append((a, b, rho, len(xs)))
    pairs.sort(key=lambda t: -abs(t[2]))
    find, union = _union_find_find(len(valids))
    idx = {n: i for i, n in enumerate(valids)}
    for a, b, rho, n in pairs:
        if abs(rho) >= args.corr_threshold:
            union(idx[a], idx[b])
    fams = {}
    for n in valids:
        fams.setdefault(find(idx[n]), []).append(n)
    families = sorted(sorted(f) for f in fams.values())

    # ── A3 符号稳定性: frac_neg_dates + K45 钳定规则 ──
    sign = {}
    for name in valids:
        ics = [x for x in aligned[name] if x is not None]
        neg = sum(1 for x in ics if x < 0)
        card_ic = card_factors[name]["ic"]
        sign[name] = {
            "frac_neg_dates": round(neg / len(ics), 3) if ics else None,
            "aggregate_ic": card_ic,
            "k45_weight_rule": "negative-or-0" if (card_ic is not None and card_ic < 0)
                               else ("positive-or-0" if (card_ic is not None and card_ic > 0) else "NA"),
        }

    # ── 自相关折扣: lag1 自相关 → 有效独立截面日 (132d 名义窗口 ≠ 有效样本量) ──
    diag = card.get("diagnostics") or {}
    eff_days = {}
    for name in valids:
        dd = diag.get(name) or {}
        rho1 = dd.get("ic_lag1_autocorr")
        n = dd.get("n_dates") or len(all_dates) or 132
        eff_days[name] = {
            "lag1_autocorr": rho1,
            "effective_days": round(n * (1 - rho1) / (1 + rho1), 1) if rho1 is not None else None,
        }
    eff_min = min((v["effective_days"] for v in eff_days.values() if v["effective_days"]), default=None)

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "authority_card": os.path.relpath(args.card, BASE),
        "card_asof": card.get("asof"),
        "card_source": card.get("source"),
        "ic_series_file": os.path.relpath(args.ic_series, BASE),
        "n_dates_aligned": len(all_dates),
        "asserts": {
            "A1_reproducibility": "PASS" if a1_ok else "FAIL",
            "A1a_series_vs_card": "PASS" if a1a_ok else "FAIL",
            "A1a_max_abs_delta": max_delta,
            "A1a_tol_note": "权威卡 ic 字段=引擎 4 位舍入值, 序列均值容差 5e-5",
            "A1b_card_vs_rerun": a1b,
            "A2_families_at_thr": args.corr_threshold,
            "A2_effective_dof": len(families),
            "A2_raw_valid_count": len(valids),
        },
        "a1_repro": repro,
        "effective_autocorr_days": eff_days,
        "effective_days_min": eff_min,
        "families": families,
        "top_correlations": [
            {"a": a, "b": b, "pearson": round(rho, 4), "n": n}
            for a, b, rho, n in pairs[:30]
        ],
        "sign_stability": sign,
        "k45_sign_clamp_spec": {
            "rule": "K45 生成/发布权重时: weight_f * IC_f >= 0 (IC_f=权威卡聚合IC), 否则 weight_f 必须=0; "
                    "等价断言 sign(weight)==sign(IC) 或 weight==0",
            "all_valid_negative_ic": all(
                (card_factors[n]["ic"] or 0) < 0 for n in valids),
            "required": {n: sign[n]["k45_weight_rule"] for n in valids},
            "note": "负 IC 因子(量能/流动性族)正向 z-score 加分=反向信号; 出首权前 "
                    "tests/test_factor_layer_sign.py A 线必须全绿",
        },
    }

    out = BASE / "data" / "factor_ic" / f"factor_cluster_table_{datetime.now():%Y%m%d}.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)

    print(f"权威卡 asof={card.get('asof')} source={card.get('source')}")
    print(f"A1 可复现性: {result['asserts']['A1_reproducibility']} "
          f"(A1a max|Δ|={max_delta} 容差5e-5 / A1b {a1b['verdict']} "
          f"n_compared={a1b.get('n_compared')})")
    if not a1_ok:
        print("  → 口径漂移, 本表 INVALID, 不得消费 (需 universe/引擎对照)")
    print(f"有效独立截面日 (lag1 折扣): min={eff_min} (名义 132d)")
    print(f"A2 族聚类 (|ρ|>={args.corr_threshold}): 有效自由度 {result['asserts']['A2_effective_dof']}"
          f" (原始 valid={len(valids)})")
    for i, f in enumerate(families, 1):
        print(f"  族{i}: {f}")
    print("相关性 top:")
    for p in result["top_correlations"][:12]:
        print(f"  {p['a']} ↔ {p['b']}: ρ={p['pearson']} (n={p['n']})")
    print("符号稳定性 (frac_neg_dates):")
    for n in valids:
        s = sign[n]
        print(f"  {n}: frac_neg={s['frac_neg_dates']} IC={s['aggregate_ic']} "
              f"→ K45 {s['k45_weight_rule']}")
    print(f"写入: {out}")
    return 0 if a1_ok else 3


if __name__ == "__main__":
    sys.exit(main())
