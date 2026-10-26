# -*- coding: utf-8 -*-
"""T1 (t_5457c400) 申万行业映射表构建: stock_code -> 申万一级行业代码

数据源 (全本地/公开, 数据不出本机):
  - mainline/sw_names.json : 申万一级 31 行业 code->name (本地真源)
  - akshare.index_component_sw : 各行业成分股公开列表 (仅拉取公开数据, 不上传)
  - archive/scripts-20261023/sw_industry_bridge_demo.py 的行业代码表为参照 (同 31 码)

输出: data/industry_mapping.json (atomic_json 原子写)
  {
    "mapping": { "<sh/sz/bj前缀+6位代码>": {"sw_code","sw_name","name","in_date"} },
    "stats": {...}, "source": ..., "fetched_at": ...
  }

用法: python scripts/t1_build_industry_mapping.py [--max-attempts 3]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

if "PYTHONPATH" in os.environ:
    del os.environ["PYTHONPATH"]

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import atomic_json  # noqa: E402  统一原子写入口


def _prefix6(code6: str) -> str:
    """6 位代码 -> sh/sz/bj 前缀 (与 data/history_daily 的 universe 键名一致)"""
    c = code6.zfill(6)
    if c[0] in ("5", "6", "9"):
        return "sh" + c
    if c[0] in ("4", "8"):
        return "bj" + c
    return "sz" + c  # 0/1/2/3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-attempts", type=int, default=3)
    args = ap.parse_args()

    sw_names = json.load(open(ROOT / "mainline" / "sw_names.json", encoding="utf-8"))
    codes = sorted(sw_names.keys())
    print(f"申万一级行业 {len(codes)} 个 (真源 mainline/sw_names.json)")

    import akshare as ak  # 延迟 import: 无网环境下尽早明确失败

    mapping = {}
    per_ind = {}
    for i, code in enumerate(codes, 1):
        ok = False
        last_err = None
        for attempt in range(args.max_attempts):
            try:
                df = ak.index_component_sw(symbol=code)
                members = []
                for _, r in df.iterrows():
                    try:
                        c6 = str(r["证券代码"]).zfill(6)
                        in_date = str(r.get("计入日期", ""))
                        members.append({
                            "code6": c6,
                            "prefixed": _prefix6(c6),
                            "name": str(r.get("证券名称", "")),
                            "in_date": in_date,
                        })
                    except Exception:
                        continue
                for m in members:
                    mapping[m["prefixed"]] = {
                        "sw_code": code,
                        "sw_name": sw_names[code],
                        "name": m["name"],
                        "in_date": m["in_date"],
                    }
                per_ind[code] = len(members)
                print(f"  [{i:2d}/{len(codes)}] {code} {sw_names[code]}: {len(members)} 成分",
                      flush=True)
                ok = len(members) > 0
                break
            except Exception as e:
                last_err = e
                print(f"  [{i:2d}/{len(codes)}] {code} attempt {attempt + 1} FAIL: "
                      f"{type(e).__name__}: {str(e)[:120]}", flush=True)
                time.sleep(2)
        if not ok:
            per_ind[code] = 0
            print(f"  [FAIL] {code} {sw_names[code]}: 3次拉取均失败 ({last_err and str(last_err)[:80]})",
                  flush=True)
        time.sleep(0.5)

    # universe 可映射率 (与 132d 池 universe 口径对齐: 非指数非ETF)
    hist = ROOT / "data" / "history_daily"
    universe = []
    for fp in sorted(hist.glob("*.json")):
        stem = fp.stem
        if stem.startswith(("sh000", "sz399")):
            continue
        if stem.startswith(("sh5", "sz1")):  # ETF 粗筛 (5 开头 sh / 15x/16x sz)
            continue
        universe.append(stem)
    mapped = [c for c in universe if c in mapping]
    stats = {
        "n_industries": len(codes),
        "n_industries_fetched": sum(1 for v in per_ind.values() if v > 0),
        "per_industry_counts": per_ind,
        "n_stocks_mapped": len(mapping),
        "universe_size_scanned": len(universe),
        "universe_mappable": len(mapped),
        "universe_mappable_pct": round(len(mapped) / max(1, len(universe)), 4),
    }
    print(f"\n映射: {len(mapping)} 只个股; universe 扫描 {len(universe)} 只, "
          f"可映射 {len(mapped)} ({stats['universe_mappable_pct']:.1%})")

    out = ROOT / "data" / "industry_mapping.json"

    def _mut(d):
        d["mapping"] = mapping
        d["stats"] = stats
        d["sw_names"] = sw_names
        d["source"] = "akshare index_component_sw (公开数据, 未上传) + mainline/sw_names.json"
        d["task"] = "t_5457c400 T1 行业中性残差动量映射"
        d["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        return d  # R3: mutator 必须返回 data, 返回 None 会被 update_json 视为放弃修改

    atomic_json.update_json(str(out), _mut, default={})
    # 写后读回断言 (防 update_json R3 静默 no-op: mutator 返回 None 会跳过写盘)
    rb = json.load(open(out, encoding="utf-8"))
    assert rb.get("mapping") and len(rb["mapping"]) == len(mapping), "读回断言失败: 映射未落盘"
    print(f"[OK] 原子写入 {out} (读回断言通过, {len(rb['mapping'])} 条)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
