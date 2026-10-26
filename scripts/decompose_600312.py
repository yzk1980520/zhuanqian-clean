#!/usr/bin/env python3
# 600312 推荐理由拆解 (老三 10/24 晨, 用户提问件): 复现 rank_2026-10-22 的 S3 综合评分
# 只读: 读 TDX 数据 + 调生产评分函数, 不写盘. 对照锚=logs/rank_2026-10-22.json score_zonghe=100.0
import sys
from pathlib import Path

from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.pipeline.tdx_data import get_tdx_data  # noqa: E402
from core.pipeline.tdx_core import (  # noqa: E402
    compute_indicators, compute_weekly_indicators, score_stock, STRATEGIES)

TARGET = "sh600312"
ASOF = date(2026, 10, 22)      # rank 件生成日, 数据截至该收盘 (不含 10/23)
recs_all = get_tdx_data(TARGET, days=150)  # 主链路同参 (integrated_picker L567: get_tdx_data(code, 150))


def _d(r):
    """date 归一: TDX 件 date 字段可能是 str 或 datetime.date"""
    v = r["date"]
    if isinstance(v, str):
        import datetime as _dt
        return _dt.date.fromisoformat(v[:10])
    return v


assert recs_all and _d(recs_all[-1]) >= ASOF, f"数据截至 {recs_all[-1]['date'] if recs_all else 'N/A'}"
recs = [r for r in recs_all if _d(r) <= ASOF]
print(f"bars={len(recs)} last={recs[-1]['date']} close={recs[-1]['close']}")

inds = compute_indicators(recs)
weekly = compute_weekly_indicators(recs)
sc, sigs, _ = score_stock(inds, weekly, strategy=STRATEGIES["综合"], zscore=None,
                          records=recs, market_state=None)
print(f"\nscore_stock(综合, 10/22 口径) = {sc}")
print("--- 因子信号分解 (sigs_zh) ---")
for s in sigs:
    print(" ", s)

# 对照锚
import json
rank = json.load(open(Path(__file__).resolve().parent.parent / "logs" / "rank_2026-10-22.json",
                      encoding="utf-8"))
top = rank["items"][0]
print(f"\n对照锚: rank_10/22 TOP1 {top['code']} score_zonghe={top['score_zonghe']} "
      f"final_score={top['final_score']} | 本复算={sc}")
