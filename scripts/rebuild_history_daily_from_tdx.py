# -*- coding: utf-8 -*-
"""Task A 前置件 (t_db07d09b, 2026-10-26): 从本机 TDX vipdoc 重建 data/history_daily。

背景: 2026-10-26 06:13 data/history_daily (9442 只个股日线 JSON) 离失于磁盘
(P0 数据完整性事件, 根因待查), 本机 TDX 真源 D:\\TDX\\vipdoc\\{sh,sz,bj}\\lday/*.day
完好。用仓库既有真源链重建:
  - core.pipeline.tdx_data.parse_tdx_day (TDX 32字节日线解析, 含 P0-20260925
    第6字段 float 成交额修复; NumPy 向量化)
  - 序列化 schema 与 scripts/auto_tdx_refresh._serialize_records 逐字段一致
    (date 字符串升序 + open/high/low/close float + amount/volume int)
  - core.pipeline.atomic_json.atomic_dump 原子写 (临时文件+os.replace)
数据不出本机 (仅读 D:\\TDX\\vipdoc)。幂等: 重复运行覆盖同名文件, 安全。
落盘审计: data/audit/aa_history_daily_rebuild_20261026.json
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.pipeline.tdx_data import VIPDOC, parse_tdx_day  # noqa: E402
import core.pipeline.atomic_json as atomic_json  # noqa: E402

HISTORY_DIR = ROOT / "data" / "history_daily"
OUT_JSON = ROOT / "data" / "audit" / "aa_history_daily_rebuild_20261026.json"
MARKETS = ("sh", "sz", "bj")
EXCLUDED = {"download_errors", "sh_index"}  # 与 factor_ic_132d_refresh._load_universe 同口径


def _serialize_records(records):
    """schema 与 auto_tdx_refresh._serialize_records 逐字段一致 (单一口径声明)"""
    out = []
    for r in records:
        d = r["date"]
        out.append({
            "date": d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "amount": int(r["amount"]),
            "volume": int(r["volume"]),
        })
    out.sort(key=lambda x: x["date"])
    return out


def _one(fp: Path) -> dict:
    code = fp.stem
    if code in EXCLUDED:
        return {"code": code, "status": "excluded"}
    recs = parse_tdx_day(str(fp))
    if not recs:
        return {"code": code, "status": "empty"}
    atomic_json.atomic_dump(
        _serialize_records(recs), str(HISTORY_DIR / f"{code}.json"),
        ensure_ascii=False, indent=2, encoding="utf-8")
    return {"code": code, "status": "ok", "n": len(recs), "last": recs[-1]["date"].isoformat()}


def main() -> int:
    files = []
    for mkt in MARKETS:
        lday = Path(VIPDOC) / mkt / "lday"
        if lday.is_dir():
            files += sorted(p for p in lday.glob("*.day"))
    print(f"[rebuild] TDX .day 文件: {len(files)} (sh/sz/bj lday)")
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    t0 = datetime.now()
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, r in enumerate(pool.map(_one, files), 1):
            results.append(r)
            if i % 1000 == 0:
                print(f"  {i}/{len(files)} ...", flush=True)
    ok = [r for r in results if r["status"] == "ok"]
    empty = [r for r in results if r["status"] == "empty"]
    excluded = [r for r in results if r["status"] == "excluded"]
    last_dates = sorted(r["last"] for r in ok)
    spot = next((r for r in ok if r["code"] == "sh603980"), None)
    report = {
        "task": "t_db07d09b 前置件: TDX->history_daily 重建",
        "incident": "2026-10-26 06:13 data/history_daily 9442 文件离失, 本机 TDX 真源重建",
        "vipdoc": str(VIPDOC),
        "schema": "与 auto_tdx_refresh._serialize_records 逐字段一致",
        "total_day_files": len(files),
        "ok": len(ok),
        "empty_skipped": len(empty),
        "excluded": len(excluded),
        "last_date_min": last_dates[0] if last_dates else None,
        "last_date_max": last_dates[-1] if last_dates else None,
        "spot_sh603980": spot,
        "elapsed_sec": round((datetime.now() - t0).total_seconds(), 1),
        "generated_at": t0.isoformat(timespec="seconds"),
        "engine_commit": None,  # 由调用方回填 git rev-parse --short HEAD
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"[rebuild] ok={len(ok)} empty={len(empty)} excluded={len(excluded)} "
          f"last={report['last_date_max']} elapsed={report['elapsed_sec']}s")
    print(f"[rebuild] 审计 -> {OUT_JSON.relative_to(ROOT)}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
