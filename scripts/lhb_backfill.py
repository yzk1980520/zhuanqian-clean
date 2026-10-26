#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lhb_backfill.py — 龙虎榜历史数据回填 (2026-10-24 C3-2 R0裁定重建 [t_laosan_c3_ops])

cron job c7e3f9a2b104 'LHB每日拉取器(收盘后)' 目标脚本, 10/23大归档归档至
archive/scripts-20261023/ 后从未入库 → job FATAL '目标脚本不存在'。本次重建。

职责:
  遍历交易日(周一至周五), 通过 akshare stock_lhb_detail_em (公开龙虎榜数据,
  本机拉取不离开机器) 拉取当日明细, 写入 data/akshare/get_lhb_detail_YYYYMMDD.json
  (走 core.pipeline.atomic_json 原子写; 存在则跳过不覆盖)。
  接口不可达/返回空 → 跳过(不写文件), 记录日志; 部分失败仍 exit 0
  (接口限制造成的失败是已知行为, 非脚本 bug — 与归档版口径一致)。

数据源: akshare 公开龙虎榜 (Wind 禁止条款不适用)。
活数据在 data/akshare/ (get_lhb_detail_*.json + backup_20261015/)。

用法:
  python scripts/lhb_backfill.py            # 全量回填 2026-05-01 → 今日 (跳过已有)
  python scripts/lhb_backfill.py --dry-run  # 只枚举缺失日, 不拉取 (烟测, exit 0)
  python scripts/lhb_backfill.py --limit 5  # 只补前5个缺失日 (限量烟测)
  python scripts/lhb_backfill.py --help     # 帮助
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import subprocess
import time
from datetime import date, datetime, timedelta, timezone

# ============================================================================
# VENV自举：缺akshare时自动重跑到项目venv
# ============================================================================
_VENV_PYTHON = r"C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe"
_BOOTSTRAP_DONE = os.environ.get("_ZQ_VENV_BOOTSTRAP")


def _try_reexec_venv():
    """缺akshare时, 用项目venv重跑当前脚本 (显式异常类型捕获, 宪法VII禁裸except)"""
    if _BOOTSTRAP_DONE:
        return False
    if not os.path.exists(_VENV_PYTHON):
        return False
    try:
        env = os.environ.copy()
        env["_ZQ_VENV_BOOTSTRAP"] = "1"
        result = subprocess.run(
            [_VENV_PYTHON, os.path.abspath(__file__)] + sys.argv[1:],
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        sys.exit(result.returncode)
    except OSError as e:
        print(f"ERROR: venv重跑失败(OSError): {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR: venv重跑失败({type(e).__name__}): {e}", file=sys.stderr)
        return False
    return True


try:
    import akshare as ak  # noqa: F401
except ImportError:
    if not _try_reexec_venv():
        print("ERROR: akshare缺失且venv不可用, 请激活项目venv后运行", file=sys.stderr)
        sys.exit(1)

# ============================================================================
# 项目根锚定 + 原子写真源
# ============================================================================
def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


if str(_project_root()) not in sys.path:
    sys.path.insert(0, str(_project_root()))

import core.pipeline.atomic_json as atomic_json  # noqa: E402  (写JSON统一原子入口, S4基地化真源)

TZ8 = timezone(timedelta(hours=8))
PROJECT = _project_root()
AKSHARE_DIR = os.path.join(PROJECT, "data", "akshare")
os.makedirs(AKSHARE_DIR, exist_ok=True)

START_DATE = date(2026, 5, 1)
LOG_FILE = os.path.join(AKSHARE_DIR, "lhb_backfill.log")


def log(msg: str, *, end: str = "\n", flush: bool = False):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, end=end, flush=flush)
    if "\n" in end or not flush:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print(f"WARNING: 日志写入失败({type(e).__name__}): {e}", file=sys.stderr)


def try_pull(day: date):
    """拉取单日 LHB 数据, 成功返回 payload dict, 失败返回 None (显式异常捕获+响铃)"""
    ys = day.strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=ys, end_date=ys)
        if df is None or len(df) == 0:
            return None
        # 归一化为纯 Python 类型 (避免 numpy 类型 json.dump 崩)
        payload = {"data": json.loads(df.to_json(orient="records", force_ascii=False))}
        return payload
    except Exception as e:
        log(f"  ⚠️ {ys} 拉取异常({type(e).__name__}): {str(e)[:100]}")
        return None


def _write_hmac(out_path: str):
    """同步写 .hmac (与 akshare_daily_pull.py / data_quality_daily 兼容)"""
    key = os.environ.get("DATA_QUALITY_HMAC_KEY", "")
    key_bytes = key.encode() if key else b""
    try:
        with open(out_path, "rb") as fb:
            sig = hmac.new(key_bytes, fb.read(), hashlib.sha256).hexdigest()
        with open(out_path + ".hmac", "w", encoding="utf-8") as fh:
            fh.write(sig)
    except OSError as e:
        log(f"  ⚠️ {out_path}.hmac 写入失败({type(e).__name__}): {e}")


def atomic_write(path: str, data: dict):
    """原子写JSON: 走 core.pipeline.atomic_json 真源 (临时文件+os.replace)"""
    atomic_json.atomic_dump(data, path, ensure_ascii=False, indent=2, encoding="utf-8")


def existing_lhb_days():
    existing = set()
    for fn in os.listdir(AKSHARE_DIR):
        m = re.match(r"get_lhb_detail_(\d{8})\.json$", fn)
        if m:
            existing.add(m.group(1))
    return existing


def main(argv=None):
    parser = argparse.ArgumentParser(description="龙虎榜历史数据回填 (akshare公开数据→data/akshare/)")
    parser.add_argument("--start", default=None, help="起始日 YYYYMMDD (默认 20260501)")
    parser.add_argument("--limit", type=int, default=None, help="只补前N个缺失日 (烟测)")
    parser.add_argument("--dry-run", action="store_true", help="只枚举缺失日, 不拉取不写文件")
    args = parser.parse_args(argv)

    start = START_DATE
    if args.start:
        try:
            start = date(int(args.start[:4]), int(args.start[4:6]), int(args.start[6:8]))
        except (ValueError, IndexError):
            print(f"ERROR: --start 格式应为 YYYYMMDD, 实际 {args.start}", file=sys.stderr)
            return 2
    end = date.today()

    log("=" * 60)
    log(f"LHB 历史回填开始: {start} → {end}" + (" [--dry-run]" if args.dry_run else ""))
    log(f"数据目录: {AKSHARE_DIR}")

    existing = existing_lhb_days()
    log(f"已有文件: {len(existing)} 个" + (f" (范围 {min(existing)}~{max(existing)})" if existing else ""))

    # 枚举缺失工作日
    missing = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            ys = d.strftime("%Y%m%d")
            if ys not in existing:
                missing.append(d)
        d += timedelta(days=1)

    if args.limit:
        missing = missing[: args.limit]

    if args.dry_run:
        log(f"缺失交易日: {len(missing)} 个 → {([m.strftime('%Y%m%d') for m in missing[:20]] or '无')}"
            f"{' ...' if len(missing) > 20 else ''}")
        log("--dry-run 完成: 不拉取不写文件")
        return 0

    ok_days, err_days = [], []
    for day in missing:
        ys = day.strftime("%Y%m%d")
        log(f"  📥 {ys} ...", end=" ", flush=True)
        payload = try_pull(day)
        if payload is not None:
            out_path = os.path.join(AKSHARE_DIR, f"get_lhb_detail_{ys}.json")
            try:
                atomic_write(out_path, payload)
                _write_hmac(out_path)
                ok_days.append(ys)
                log(f"✅ {len(payload['data'])} rows")
            except (OSError, ValueError, TypeError) as e:
                err_days.append(ys)
                log(f"❌ 写入失败({type(e).__name__}): {e}")
        else:
            err_days.append(ys)
            log("⚠️ 无数据/接口异常")
        time.sleep(1.0)  # 限速防东财接口拒绝

    log("-" * 60)
    log(f"回填完成: ✅ {len(ok_days)} 成功 | ⚠️ {len(err_days)} 失败/无数据 | ⏭ {len(existing)} 已有跳过")
    if ok_days:
        log(f"成功日期范围: {min(ok_days)} ~ {max(ok_days)}")
    if err_days:
        log(f"失败日期(前20): {err_days[:20]}")
    log("=" * 60)

    # 写汇总报告到 .scratch
    report = {
        "task": "lhb_backfill",
        "start_date": str(start),
        "end_date": str(end),
        "ok_count": len(ok_days),
        "err_count": len(err_days),
        "skip_count": len(existing),
        "ok_days": ok_days,
        "err_days": err_days,
        "timestamp": datetime.now(TZ8).isoformat(),
    }
    report_path = os.path.join(PROJECT, ".scratch", "lhb_backfill_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    try:
        atomic_write(report_path, report)
        log(f"报告已写: {report_path}")
    except (OSError, ValueError, TypeError) as e:
        log(f"⚠️ 报告写入失败({type(e).__name__}): {e}")

    # 部分失败也 exit 0 (接口限制造成的失败是已知行为, 非脚本 bug — 归档版口径)
    return 0


if __name__ == "__main__":
    sys.exit(main())
