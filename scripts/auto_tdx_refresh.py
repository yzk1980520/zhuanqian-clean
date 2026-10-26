#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""auto_tdx_refresh.py — TDX核心股日线每日刷新 (2026-10-24 C3-2 R0裁定重建 [t_laosan_c3_ops])

cron job 3498d272 'TDX数据每日刷新(核心+新鲜度)' 目标脚本, 10/23大归档归档至
archive/scripts-20261023/ 后从未入库 → job FATAL '目标脚本不存在'。本次重建:
  - 薄驱动: 不复制归档版的 TDX 二进制解析逻辑, 全部复用活跃真源
    core.pipeline.tdx_data (S4基地化模块: parse_tdx_day/get_tdx_data/get_latest_tdx_date)
    + core.pipeline.atomic_json (写JSON统一原子入口)
  - venv自举: numpy 缺失时自动重跑到项目venv (TDX解析走NumPy向量化)
  - 数据不离开本机 (AGENTS.md 铁律7)

job备注口径: 核心7股+sh603727 每日刷新 history_daily (修 10-09/10-11 断供事故)。
M-7数据化 (2026-10-24 R0裁定 [t_laosan_m1_m7_data_supply_tests]): 有效股列表 =
固定6只核心 (CORE_STOCKS_FIXED) ∪ data/holdings.json 持仓码 (运行时读, 持仓轮出自动跟随);
holdings.json 缺失/损坏 → fallback 原7只硬编码 (CORE_STOCKS_FALLBACK, 含 sh603727) + WARN,
禁静默吞。当前持仓=sh603727 时, 有效列表与原7只硬编码完全等价 (顺序/成员)。

用法:
  python scripts/auto_tdx_refresh.py            # 检查新鲜度, 滞后>3日则刷新
  python scripts/auto_tdx_refresh.py --force    # 强制刷新全部核心股
  python scripts/auto_tdx_refresh.py --dry-run  # 只查新鲜度, 不写文件 (烟测, exit 0)
  python scripts/auto_tdx_refresh.py --help     # 帮助
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ============================================================================
# VENV自举：缺numpy时自动重跑到项目venv (沿用归档版口径, 已验证路径)
# ============================================================================
_VENV_PYTHON = r"C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe"
_BOOTSTRAP_DONE = os.environ.get("_ZQ_VENV_BOOTSTRAP")


def _try_reexec_venv():
    """缺numpy时, 用项目venv重跑当前脚本 (显式异常类型捕获, 宪法VII禁裸except)"""
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
    import numpy  # noqa: F401  (core.pipeline.tdx_data.parse_tdx_day 依赖NumPy向量化)
except ImportError:
    if not _try_reexec_venv():
        print("ERROR: numpy缺失且venv不可用, 请激活项目venv后运行", file=sys.stderr)
        sys.exit(1)

# ============================================================================
# 项目根锚定 + 真源导入 (薄驱动: 只调 core.pipeline 现成函数, 不重造解析逻辑)
# ============================================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.pipeline.tdx_data import VIPDOC, get_tdx_data, get_latest_tdx_date  # noqa: E402
import core.pipeline.atomic_json as atomic_json  # noqa: E402  (写JSON统一原子入口)

# M-7数据化 (2026-10-24 R0裁定 [t_laosan_m1_m7_data_supply_tests]):
# 有效股列表 = 固定6只核心 ∪ data/holdings.json 持仓码 (运行时读取, 持仓轮出自动跟随,
# 修 sh603727 硬编码=现行持仓→轮出后数据缺口)。
# holdings.json 缺失/损坏 → fallback 原7只硬编码 + WARN (禁静默吞)。
CORE_STOCKS_FIXED = ["sh600519", "sh600000", "sz000858", "sh601318", "sz000001", "sh600036"]
CORE_STOCKS_FALLBACK = CORE_STOCKS_FIXED + ["sh603727"]  # 原7只硬编码 (含现行持仓 sh603727, 与job _note 对齐)
HOLDINGS_FILE = PROJECT_ROOT / "data" / "holdings.json"
DATA_DIR = PROJECT_ROOT / "data" / "history_daily"
LOGS_DIR = PROJECT_ROOT / "logs"
FRESHNESS_MAX_LAG_DAYS = 3  # 滞后>3日判需刷新


def _setup_logger():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("auto_tdx_refresh")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(logging.FileHandler(LOGS_DIR / "data_refresh.log", encoding="utf-8"))
        logger.addHandler(logging.StreamHandler())
    return logger


logger = _setup_logger()


def _serialize_records(records):
    """core.pipeline 真源记录(date对象) → 落盘JSON schema (date字符串, 升序, 与既有文件口径一致)"""
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
    out.sort(key=lambda x: x["date"])  # 升序=旧惯例 (2026-10-15归一化)
    return out


def refresh_stock_data(code):
    """刷新单只股票: 经 core.pipeline 真源读TDX全量日线 → atomic_json 原子写 history_daily"""
    try:
        records = get_tdx_data(code, days=1_000_000)  # 全量(>现有条数时返回全部)
    except (OSError, ValueError) as e:
        logger.error("%s: TDX读取失败(%s): %s", code, type(e).__name__, e)
        return False

    if not records:
        logger.warning("%s: TDX文件缺失或无有效记录 (VIPDOC=%s)", code, VIPDOC)
        return False

    out_records = _serialize_records(records)
    output_path = DATA_DIR / f"{code}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json.atomic_dump(out_records, str(output_path), ensure_ascii=False, indent=2, encoding="utf-8")
    logger.info("%s: ✅ 刷新成功 (%d条, 最新=%s)", code, len(out_records), out_records[-1]["date"])
    return True


def _read_holding_codes():
    """读 data/holdings.json 持仓码 (只读, holdings.json 写口归总管 — AGENTS.md §6.1)。

    返回持仓码集合; 文件缺失/损坏/结构异常(holdings非列表) → 返回 None
    (调用方 fallback 原7只硬编码+WARN, 禁静默吞)。
    """
    try:
        doc = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None
    holdings = doc.get("holdings", []) if isinstance(doc, dict) else []
    if not isinstance(holdings, list):
        return None  # 结构损坏 (holdings非列表) → 同缺失, 调用方 fallback + WARN, 禁静默收窄
    codes = set()
    for h in holdings:
        if isinstance(h, str) and h:
            codes.add(h)  # 容忍裸字符串码 (主形态是 dict, 键为 symbol/code)
        elif isinstance(h, dict):
            c = h.get("symbol") or h.get("code")
            if isinstance(c, str) and c:
                codes.add(c)
    return codes


def resolve_core_stocks():
    """M-7: 有效股列表 = 固定6只核心 ∪ holdings.json 持仓码 (顺序: 固定6只在前, 持仓码字典序追加, 去重)。

    holdings.json 缺失/损坏 → fallback 原7只硬编码 + WARN (禁静默吞)。
    """
    codes = _read_holding_codes()
    if codes is None:
        logger.warning("holdings.json 缺失/损坏 → fallback 原%d只硬编码核心列表: %s",
                       len(CORE_STOCKS_FALLBACK), CORE_STOCKS_FALLBACK)
        return list(CORE_STOCKS_FALLBACK)
    out = list(CORE_STOCKS_FIXED)
    for c in sorted(codes):
        if c not in out:
            out.append(c)
    return out


def check_data_freshness(stocks=None):
    """检查数据新鲜度: 读既有json末尾日期 vs 今天, 滞后>3日判需刷新。

    stocks=None 时运行时解析 (M-7 数据化: 固定核心 ∪ 持仓)。
    """
    if stocks is None:
        stocks = resolve_core_stocks()
    issues = []
    for code in stocks:
        data_path = DATA_DIR / f"{code}.json"
        if not data_path.exists():
            issues.append(f"{code}: 文件缺失")
            continue
        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            issues.append(f"{code}: 解析错误({type(e).__name__}: {e})")
            continue
        if not data:
            issues.append(f"{code}: 空数据")
            continue
        latest_date = data[-1]["date"]  # 升序存储, 最新在末尾
        latest_dt = datetime.strptime(latest_date, "%Y-%m-%d")
        days_lag = (datetime.now() - latest_dt).days
        if days_lag > FRESHNESS_MAX_LAG_DAYS:
            issues.append(f"{code}: 滞后{days_lag}天 (最新={latest_date})")
        else:
            logger.info("%s: ✅ 数据新鲜 (滞后%d天, 最新=%s)", code, days_lag, latest_date)
    return issues


def main(argv=None):
    parser = argparse.ArgumentParser(description="TDX核心股日线每日刷新 (薄驱动→core.pipeline真源)")
    parser.add_argument("--force", action="store_true", help="强制刷新全部核心股(不论新鲜度)")
    parser.add_argument("--dry-run", action="store_true", help="只检查新鲜度, 不写文件(烟测)")
    args = parser.parse_args(argv)

    # M-7: 运行时解析有效股列表 (固定核心 ∪ holdings.json 持仓; 缺失/损坏→fallback原7只+WARN)
    stocks = resolve_core_stocks()
    logger.info("=" * 60)
    logger.info("🔄 TDX数据自动刷新启动 (核心%d只, 薄驱动→core.pipeline, 股列表=%s)", len(stocks), stocks)
    logger.info("=" * 60)

    issues = check_data_freshness(stocks)
    if args.dry_run:
        logger.info("--dry-run: 仅检查新鲜度, 不写文件")
        if issues:
            logger.warning("发现%d个需刷新项:", len(issues))
            for issue in issues:
                logger.warning("  - %s", issue)
        else:
            logger.info("✅ 数据新鲜, 无需刷新")
        return 0

    if not issues and not args.force:
        logger.info("✅ 数据新鲜, 无需刷新")
        return 0

    logger.info("开始刷新 (%d个待处理项%s)", len(issues) or len(stocks),
                ", --force" if args.force else "")
    success_count = 0
    for code in stocks:
        if refresh_stock_data(code):
            success_count += 1
    logger.info("刷新完成: %d/%d只成功", success_count, len(stocks))

    # 验证: 刷新后新鲜度复检 (TDX源本身滞后属上游行情问题, 不算脚本失败)
    final_issues = check_data_freshness(stocks)
    if final_issues and success_count == 0:
        logger.warning("刷新未生效, 仍存在数据问题:")
        for issue in final_issues:
            logger.warning("  - %s", issue)
        return 1
    if success_count == len(stocks):
        logger.info("✅ 全部核心股刷新完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
