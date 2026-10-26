# -*- coding: utf-8 -*-
"""T1 (t_5457c400) 6 分位 q_means 取证 (任务验收口径: q_means 6-quantile)

复用 scripts/factor_ic_132d_refresh.py 的 universe 加载 + compute() (单一算术源),
为 3 个新因子 (RSRS_TREND / RESID_MOM_20 / REV_5D) 逐截面日收集
(factor_value, forward_return) 对, 池化计算:
  - 5 分位 q_means (引擎 mono 惯例: 按当日秩位置 pos*5//n 分桶, 与 --mono-out 同口径)
  - 6 分位 q_means (pos*6//n 分桶, 本卡验收口径)
  - 单调性 (相邻逆序 <=1) / 方向 / 空桶留痕

输出: data/factor_ic/factor_ic_q6_t1_20261026.json (atomic_json 原子写)
交叉验证: 5 分位结果与引擎 --mono-out 文档对比 (同池同参应一致)。
"""
import argparse
import json
import os
import sys
from pathlib import Path

if "PYTHONPATH" in os.environ:
    del os.environ["PYTHONPATH"]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import atomic_json  # noqa: E402
import factor_ic_132d_refresh as rr  # noqa: E402  单一算术源

T1_FACTORS = ("RSRS_TREND", "RESID_MOM_20", "REV_5D")
OUT = ROOT / "data" / "factor_ic" / "factor_ic_q6_t1_20261026.json"


def _bucket_qmeans(pairs_per_day: list, nq: int):
    """pairs_per_day: 每个截面日的 [(val, fwd), ...]; 按当日秩位置分 nq 桶, 池化均值"""
    sums = [0.0] * nq
    ns = [0] * nq
    n_days = 0
    for day in pairs_per_day:
        if len(day) < nq:
            continue
        n_days += 1
        day_sorted = sorted(day, key=lambda p: p[0])
        for pos, (_val, fv) in enumerate(day_sorted):
            b = min(nq - 1, pos * nq // len(day_sorted))
            sums[b] += fv
            ns[b] += 1
    qmeans = [sums[i] / ns[i] if ns[i] else None for i in range(nq)]
    mono = None
    direction = None
    inv_up = inv_dn = None
    if all(m is not None for m in qmeans):
        inv_up = sum(1 for i in range(nq - 1) if qmeans[i] > qmeans[i + 1])
        inv_dn = sum(1 for i in range(nq - 1) if qmeans[i] < qmeans[i + 1])
        mono = min(inv_up, inv_dn) <= 1
        direction = ("positive" if qmeans[-1] > qmeans[0] else
                     "negative" if qmeans[-1] < qmeans[0] else "flat")
    return {
        "q_means": [round(m, 4) if m is not None else None for m in qmeans],
        "q_ns": ns,
        "n_days": n_days,
        "monotonic": mono,
        "direction": direction,
        "adjacent_inversions_up": inv_up,
        "adjacent_inversions_down": inv_dn,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-stocks", type=int, default=2000)
    ap.add_argument("--mono5-compare", default="data/factor_ic/factor_ic_mono_132d_t1_20261026.json")
    args = ap.parse_args()

    universe = rr._load_universe(args.max_stocks)
    if not universe:
        print("[FAIL] 无可用个股历史数据")
        return 2
    dates = rr._target_dates(universe, rr.WINDOW_DAYS)
    print(f"个股数={len(universe)} 截面日={len(dates)} "
          f"({dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'})")

    _, _, mono_pairs = rr.compute(
        universe, dates, rr.FORWARD_DAYS, rr.MIN_SECTION, progress=True,
        align=0, min_valid_per_date=0, mono_factors=set(T1_FACTORS))

    n_pairs_total = sum(len(day) for day in mono_pairs["REV_5D"])
    out_factors = {}
    for fname in T1_FACTORS:
        pairs = mono_pairs.get(fname, [])
        e5 = _bucket_qmeans(pairs, 5)
        e6 = _bucket_qmeans(pairs, 6)
        out_factors[fname] = {
            "n_pairs": sum(len(p) for p in pairs),
            "q5": e5,
            "q6": e6,
            "note": (f"RSRS_TREND 为全市场常数信号: 分位桶内 factor 值无差异, "
                     f"q_means 各桶相同属退化截面如实留痕, 不作为入库依据"
                     if fname == "RSRS_TREND" else None),
        }
        if fname == "RSRS_TREND":
            out_factors[fname]["note"] = "全市场常数信号: 6 桶 q_means 应近似相等 (退化留痕, 不作入库依据)"

    # 交叉验证 5 分位 vs 引擎 --mono-out
    q5_xcheck = {}
    mono5_path = ROOT / args.mono5_compare
    if mono5_path.exists():
        m5 = json.load(open(mono5_path, encoding="utf-8"))
        for fname in T1_FACTORS:
            if fname not in m5:
                continue
            mine = out_factors[fname]["q5"]["q_means"]
            theirs = m5[fname].get("q_means")
            delta = max(abs(a - b) for a, b in zip(mine, theirs)
                        if a is not None and b is not None) \
                if (mine and theirs) else None
            q5_xcheck[fname] = {
                "q5_engine": theirs, "q5_this": mine, "max_abs_delta": delta,
                "match": delta is not None and delta < 1e-3,
            }
    else:
        print(f"[WARN] {args.mono5_compare} 不存在, 5 分位交叉验证跳过 (不阻塞)")

    def _mut(d):
        d["task"] = "t_5457c400 T1 6分位 q_means 取证"
        d["max_stocks"] = args.max_stocks
        d["dates"] = [dates[0], dates[-1]] if dates else None
        d["n_pairs_total"] = n_pairs_total
        d["factors"] = out_factors
        d["q5_crosscheck_vs_engine_mono"] = q5_xcheck
        d["engine"] = rr._engine_tag()
        import datetime as _dt
        d["generated_at"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        return d  # R3: mutator 必须返回 data, 返回 None 会被 update_json 视为放弃修改

    atomic_json.update_json(str(OUT), _mut, default={})
    # 写后读回断言 (防 update_json R3 静默 no-op)
    rb = json.load(open(OUT, encoding="utf-8"))
    assert rb.get("factors") and len(rb["factors"]) == 3, "读回断言失败: q6 结果未落盘"
    print(f"[OK] 写入 {OUT} (读回断言通过)")
    for fname in T1_FACTORS:
        e = out_factors[fname]
        print(f"  {fname}: q6={e['q6']['q_means']} mono={e['q6']['monotonic']} "
              f"dir={e['q6']['direction']} | q5={e['q5']['q_means']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
