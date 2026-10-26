#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_holdings.py - 持仓数据同步脚本

功能:
  1. holdings.json (真源) → QSP 系统 real_holdings.json + trade_log.json

约束:
  - 单向同步：holdings.json → QSP，禁止反向
  - 不修改 holdings.json 内容（总管独占写）
  - data/real_holdings.json 已归档至 data/.trash/，本脚本不再写本地派生路径
  - real_holdings.json 的 _schema_version 补写字段由总管执行
  - R-1 修复（2026-10-16 老六L2审查）：save_json 改用 atomic_json 原子写 + read-back 断言 + loud fail

用法:
    python scripts/sync_holdings.py [--dry-run]
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))  # 确保能 import core.pipeline.atomic_json

# 路径配置
ZR_HOLDINGS = ROOT / "data" / "holdings.json"
ZR_TRADE_LOG = ROOT / "data" / "trade_log.json"

QSP_HOLDINGS = Path(r"C:/Users/WIN10/.quant-stock-picker/data/real_holdings.json")
QSP_TRADE_LOG = Path(r"C:/Users/WIN10/.quant-stock-picker/data/real_trade_log.json")

# 已知外部系统白名单（QSP 目录）
QSP_WHITELIST_DIRS = {
    r"C:/Users/WIN10/.quant-stock-picker",
}


def load_json(filepath: Path) -> dict:
    """安全加载JSON文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"⚠️ 文件不存在: {filepath}", file=sys.stderr)
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败 {filepath}: {e}", file=sys.stderr)
        return {}


def save_json(filepath: Path, data: dict, dry_run: bool = False) -> bool:
    """
    原子保存JSON文件（R-1 修复）

    使用 atomic_json.atomic_dump 保证写入原子性，
    写后 read-back 断言关键字段，失败 loud fail。

    Returns:
        True 表示成功，False 表示失败
    """
    if dry_run:
        print(f"[DRY RUN] 将原子写入: {filepath}")
        return True

    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 原子写
    try:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(data, str(filepath), ensure_ascii=False, indent=2, encoding="utf-8")
    except Exception as e:
        print(f"❌ 原子写失败 {filepath}: {e}", file=sys.stderr)
        return False

    # Read-back 断言
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            readback = json.load(f)
    except Exception as e:
        print(f"❌ Read-back 失败 {filepath}: {e}", file=sys.stderr)
        return False

    # 验证关键字段（updated_at / holdings）
    if "updated_at" in data and readback.get("updated_at") != data["updated_at"]:
        print(f"❌ Read-back 断言失败: updated_at 不匹配", file=sys.stderr)
        return False

    if "holdings" in data and readback.get("holdings") != data["holdings"]:
        print(f"❌ Read-back 断言失败: holdings 不匹配", file=sys.stderr)
        return False

    print(f"✅ 已原子写入并验证: {filepath}", file=sys.stderr)
    return True


def sync_qsp_holdings(dry_run: bool = False) -> bool:
    """
    同步 holdings.json → QSP 系统 real_holdings.json（原有逻辑）

    约束: 单向同步，不修改 holdings.json
    """
    src = load_json(ZR_HOLDINGS)
    if not src:
        print("[sync-qsp] ❌ 源文件为空，跳过", file=sys.stderr)
        return False

    dst_data = {
        "holdings": src.get("holdings", []),
        "total_assets": src.get("total_assets", 0),
        "available_cash": src.get("available_cash", 0),
        "position_ratio": src.get("position_ratio", 0),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "synced from holdings.json",
    }

    # 对比现有数据
    if QSP_HOLDINGS.exists():
        existing = load_json(QSP_HOLDINGS)
        src_count = len(src.get("holdings", []))
        dst_count = len(existing.get("holdings", []))
        if src_count != dst_count:
            print(f"[sync-qsp] ⚠️ 持仓数变化: {dst_count} → {src_count}", file=sys.stderr)
        else:
            print(f"[sync-qsp] ℹ️ 持仓数一致: {src_count} 只")
    else:
        print("[sync-qsp] ℹ️ QSP real_holdings.json 不存在，将创建")

    if dry_run:
        print(f"[sync-qsp] 🔍 dry-run 模式，跳过实际写入")
        print(f"[sync-qsp] 目标内容预览:")
        print(json.dumps(dst_data, ensure_ascii=False, indent=2))
        return True

    success = save_json(QSP_HOLDINGS, dst_data, dry_run)
    if not success:
        print(f"❌ 写入 QSP 持仓失败: {QSP_HOLDINGS}", file=sys.stderr)
        return False
    return True


def sync_holdings(dry_run: bool = False):
    """同步持仓数据（QSP 系统）"""

    # 读取源数据
    src_holdings = load_json(ZR_HOLDINGS)
    src_trade_log = load_json(ZR_TRADE_LOG)

    if not src_holdings:
        return False

    # 同步持仓
    qsp_holdings_data = {
        "holdings": src_holdings.get("holdings", []),
        "available_cash": src_holdings.get("available_cash", 0),
        "total_assets": src_holdings.get("total_assets", 0),
        "position_ratio": src_holdings.get("position_ratio", 0),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": f"从zhuanqian同步（原更新: {src_holdings.get('updated_at', 'N/A')}）"
    }

    # 显示同步详情
    print(f"\n源数据（zhuanqian）:")
    print(f"  持仓数: {len(src_holdings.get('holdings', []))}")
    print(f"  总资产: ¥{src_holdings.get('total_assets', 0):,.2f}")
    print(f"  现金: ¥{src_holdings.get('available_cash', 0):,.2f}")

    if src_holdings.get('holdings'):
        for h in src_holdings['holdings']:
            print(f"  - {h['name']}({h['code']}): {h['shares']}股 @ {h['cost_price']}元")

    # 同步交易记录（追加模式）
    qsp_trade_data = {
        "trades": src_trade_log.get("trades", [])
    }

    # 执行同步
    print(f"\n同步到 QSP 系统中...")
    ok1 = save_json(QSP_HOLDINGS, qsp_holdings_data, dry_run)
    ok2 = save_json(QSP_TRADE_LOG, qsp_trade_data, dry_run)
    if not ok1 or not ok2:
        print(f"❌ QSP 同步写入失败", file=sys.stderr)
        return False
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description="持仓数据同步脚本")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    args = parser.parse_args()

    success = True

    print("[sync] 启动 QSP 同步 (dry_run={})".format(args.dry_run))
    success = sync_holdings(dry_run=args.dry_run)

    if success:
        print("\n✅ 同步完成")
    else:
        print("\n❌ 同步失败")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
