#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_extended_data.py — 扩展历史库 (data/history_daily) 增量回填
P1#5 重建 (2026-10-23, 老三): 原 8/30 P1-2 脚本从未 commit, 工作区丢失 →
TDX .day 自 10/21 后未再转换入扩展库, 全量 9442 文件止于 10/20。

口径 (以 10/21 07:44 写入侧实测为准, sh603727 三日逐位核对):
  date   = 'YYYY-MM-DD' (str)
  open/high/low/close = TDX .day int / 100 (float)
  volume = TDX .day 成交量字段 (int, 股, 原值)
  amount = TDX .day 成交额字段 (float→int, 元; 该字段为float型, 全int结构体误读见 tdx_data P0修复2026-09-25)

语义: 只追加 (date > 扩展库 max date), 幂等, 不覆盖不删除既有记录。
原子写: 同目录 tmp 文件 + os.replace。扩展库文件不存在则跳过 (不新建,
退市股/新股维持 P1-2 口径)。

用法:
  python scripts/refresh_extended_data.py [--dry-run] [--limit N] [--market sh,sz] [--verbose]
"""
import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline.tdx_data import VIPDOC, parse_tdx_day  # noqa: E402

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "history_daily")
HISTORY_DIR = os.path.normpath(HISTORY_DIR)
STATS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refresh_extended_data_stats.json")


def _parse_tail(data, idx, ext_max_int):
    """从记录 idx 起解析增量 (struct '<IIIIIfII': 第6字段=float成交额, P0修复2026-09-25口径)。
    返回 (records, ordered) — ordered=False 表示尾部乱序, 调用方应退回全量解析。"""
    out, ordered = [], True
    prev = ext_max_int
    for i in range(idx, len(data) // 32):
        vals = struct.unpack_from("<IIIIIfII", data, i * 32)
        d = vals[0]
        if not (19900101 <= d <= 20300000):
            continue
        if d <= prev:
            ordered = False
            break
        prev = d
        s = str(d)
        out.append({
            "date": f"{s[:4]}-{s[4:6]}-{s[6:8]}",
            "open": float(vals[1]) / 100.0,
            "high": float(vals[2]) / 100.0,
            "low": float(vals[3]) / 100.0,
            "close": float(vals[4]) / 100.0,
            "amount": int(vals[5]),
            "volume": int(vals[6]),
        })
    return out, ordered


def process_code(code, day_file, dry_run, verbose):
    """返回 (action, appended_count)。action: updated/skipped_same_fresh/no_ext/skip_noday/skip_unreadable/error"""
    ext_path = os.path.join(HISTORY_DIR, f"{code}.json")
    if not os.path.exists(ext_path):
        return "no_ext", 0
    with open(ext_path, "r", encoding="utf-8") as f:
        ext = json.load(f)
    if not ext:
        return "error", 0  # 空扩展库文件, 不盲写
    ext_max = max(r["date"] for r in ext)
    ext_max_int = int(ext_max.replace("-", ""))

    try:
        with open(day_file, "rb") as f:
            data = f.read()
    except OSError:
        return "skip_unreadable", 0
    n = len(data) // 32
    if n < 1:
        return "skip_noday", 0

    # O(1) 快筛: 最后一记录的日期 (文件=时间序) 不超扩展库 max → 已追平, 免解析
    last = struct.unpack_from("<I", data, (n - 1) * 32)[0]
    if last <= ext_max_int:
        return "skipped_same_fresh", 0

    # 二进制搜索第一条 date > ext_max 的记录位置
    lo, hi = 0, n - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if struct.unpack_from("<I", data, mid * 32)[0] <= ext_max_int:
            lo = mid + 1
        else:
            hi = mid
    inc, ordered = _parse_tail(data, lo, ext_max_int)
    if not ordered:
        # 尾部乱序 → 退回全量解析 (与 tdx_data.parse_tdx_day 同口径)
        recs = parse_tdx_day(day_file)
        if not recs:
            return "skip_noday", 0
        inc = []
        for r in sorted(recs, key=lambda x: x["date"]):
            if int(r["date"].replace("-", "")) > ext_max_int:
                inc.append({
                    "date": r["date"].isoformat(),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "amount": int(r["amount"]),
                    "volume": int(r["volume"]),
                })
    if not inc:
        return "skipped_same_fresh", 0

    new_ext = ext + inc
    if not dry_run:
        tmp_path = ext_path + f".tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(new_ext, f, ensure_ascii=False)
        os.replace(tmp_path, ext_path)
    if verbose:
        print(f"  [更新] {code}: {ext_max} → {inc[-1]['date']} (+{len(inc)})")
    return "updated", len(inc)


def main():
    ap = argparse.ArgumentParser(description="扩展历史库增量回填 (TDX .day → data/history_daily)")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写盘")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 个 .day 文件 (调试)")
    ap.add_argument("--market", default="sh,sz,bj", help="市场列表, 逗号分隔")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    markets = [m.strip() for m in args.market.split(",") if m.strip()]
    t0 = time.time()
    stats = {"run_at": time.strftime("%Y-%m-%d %H:%M:%S"), "dry_run": args.dry_run,
             "markets": markets, "scanned": 0, "updated": [], "appended_total": 0,
             "fresh": 0, "no_ext": 0, "no_day": 0, "errors": []}

    for m in markets:
        lday = os.path.join(VIPDOC, m, "lday")
        if not os.path.isdir(lday):
            continue
        files = sorted(f for f in os.listdir(lday) if f.endswith(".day"))
        if args.limit:
            files = files[:args.limit]
        for fn in files:
            code = fn[:-4]
            action, n = process_code(code, os.path.join(lday, fn), args.dry_run, args.verbose)
            stats["scanned"] += 1
            if action == "updated":
                stats["updated"].append(code)
                stats["appended_total"] += n
            elif action == "skipped_same_fresh":
                stats["fresh"] += 1
            elif action == "no_ext":
                stats["no_ext"] += 1
            elif action == "skip_noday":
                stats["no_day"] += 1
            else:
                stats["errors"].append(f"{code}: {action}")
            if len(files) % 2000 == 0 or len(files) <= 20:
                print(f"  进度 {m} {len(files)}: updated={len(stats['updated'])} appended={stats['appended_total']} ({time.time()-t0:.0f}s)")

    if not args.dry_run:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=1)
        print(f"统计已存: {STATS_FILE}")

    print("=" * 60)
    print(f"扩展库增量回填{' (DRY-RUN)' if args.dry_run else '完成'} 耗时 {time.time()-t0:.0f}s")
    print(f"  扫描 .day: {stats['scanned']}  更新文件: {len(stats['updated'])}  追加记录: {stats['appended_total']}")
    print(f"  已追平: {stats['fresh']}  无扩展库(跳过): {stats['no_ext']}  无.day: {stats['no_day']}  异常: {len(stats['errors'])}")
    for e in stats["errors"][:10]:
        print(f"  ❌ {e}")
    return 0 if not stats["errors"] else 2


if __name__ == "__main__":
    sys.exit(main())
