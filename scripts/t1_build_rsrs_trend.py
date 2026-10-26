# -*- coding: utf-8 -*-
"""T1 (t_5457c400) RSRS_TREND: 上证指数 close/open 比率 10 日滚动线性回归斜率

数据源: data/history_daily/sh000001.json (TDX 上证指数日线, 本地数据, 不出本机)
口径 (任务定调): r_t = close_t / open_t; 取最近 10 日 r 序列, 对 x=0..9 做 OLS,
斜率 slope = cov(x,y)/var(x) 即 RSRS 信号。

输出: data/factor_ic/rsrs_trend_132d.json (atomic_json 原子写)
  {"series": {date: slope}, "window": 10, "stats": {...}, "source": ...}

用法: python scripts/t1_build_rsrs_trend.py
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if "PYTHONPATH" in os.environ:
    del os.environ["PYTHONPATH"]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import atomic_json  # noqa: E402

INDEX_FILE = ROOT / "data" / "history_daily" / "sh000001.json"
OUT = ROOT / "data" / "factor_ic" / "rsrs_trend_132d.json"
WIN = 10


def _ols_slope(ys):
    n = len(ys)
    mx = (n - 1) / 2
    my = sum(ys) / n
    cov = sum((i - mx) * (y - my) for i, y in enumerate(ys))
    var = sum((i - mx) ** 2 for i in range(n))
    if var == 0:
        return None
    return cov / var


def main() -> int:
    recs = json.load(open(INDEX_FILE, encoding="utf-8"))
    recs = sorted(recs, key=lambda r: r.get("date", ""))
    series = {}
    for i in range(WIN - 1, len(recs)):
        win = recs[i - WIN + 1: i + 1]
        rs = []
        good = True
        for r in win:
            o, c = r.get("open") or 0, r.get("close") or 0
            if o <= 0 or c <= 0:
                good = False
                break
            rs.append(c / o)
        if not good:
            continue
        d = win[-1].get("date")
        slope = _ols_slope(rs)
        if slope is not None:
            series[d] = round(slope, 8)
    vals = [v for v in series.values()]
    n = len(vals)
    mean = sum(vals) / n
    std = (sum((x - mean) ** 2 for x in vals) / n) ** 0.5
    stats = {
        "n_dates": n,
        "first": min(series), "last": max(series),
        "mean": round(mean, 8), "std": round(std, 8),
        "frac_positive_slope": round(sum(1 for v in vals if v > 0) / n, 4),
        "note": "全市场常数信号: 逐日截面内所有个股取值相同 → 截面 IC 无定义(退化), "
                "本文件为 RSRS 择时证据序列, 截面门禁判定按退化截面如实记 dead",
    }

    def _mut(d):
        d["series"] = series
        d["window"] = WIN
        d["stats"] = stats
        d["source"] = "TDX sh000001 (上证指数) 本地日线, close/open 10日OLS斜率"
        d["task"] = "t_5457c400 T1 RSRS_TREND"
        d["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        return d  # R3: mutator 必须返回 data, 返回 None 会被 update_json 视为放弃修改

    atomic_json.update_json(str(OUT), _mut, default={})
    # 写后读回断言 (防 update_json R3 静默 no-op: mutator 返回 None 会跳过写盘)
    rb = json.load(open(OUT, encoding="utf-8"))
    assert rb.get("series") and len(rb["series"]) == n, "读回断言失败: RSRS 序列未落盘"
    print(f"[OK] RSRS_TREND 序列 {n} 日, 写入 {OUT} (读回断言通过)")
    print(f"  mean={stats['mean']:+.6f} std={stats['std']:.6f} "
          f"pos={stats['frac_positive_slope']:.1%} 窗口 {stats['first']}~{stats['last']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
