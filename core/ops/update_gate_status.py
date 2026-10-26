#!/usr/bin/env python3
"""
update_gate_status.py — 门禁状态重建工具
==========================================
问题：gate_status.json 无写入代码，门禁状态 stale

用法：
  python update_gate_status.py [--force]
  
逻辑：
  1. 读取最新回测结果 data/rotation_backtest_result.json
  2. 计算门禁指标（win_rate, score_spread, rank_ic 等）
  3. 对比阈值（evaluate.py GATE）
  4. 写 gate_status.json（atomic_json）

退出码：0=PASS, 1=FAIL
"""
import sys
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from datetime import datetime

PROJECT = PROJECT_ROOT
sys.path.insert(0, PROJECT)

import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
from evaluate import GATE

RESULT_FILE = os.path.join(PROJECT, "data", "rotation_backtest_result.json")
GATE_FILE = os.path.join(PROJECT, "data", "gate_status.json")


def load_backtest_result():
    """加载最新回测结果"""
    if not os.path.exists(RESULT_FILE):
        return None
    with open(RESULT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_gate_checks(result):
    """计算门禁指标"""
    checks = {}
    
    # 取最佳变体
    variants = result.get("results", [])
    if not variants:
        return None, "无回测变体"
    
    # 找基准变体（无移动止盈+固定持有）
    base_variant = None
    for v in variants:
        name = v.get("config", {}).get("name", "") if isinstance(v.get("config"), dict) else str(v.get("config", ""))
        if "无移动止盈" in name and "持有" in name:
            base_variant = v
            break
    
    if not base_variant:
        base_variant = variants[0]  # fallback
    
    # 提取指标
    trades = base_variant.get("trades", 0)
    win_rate = base_variant.get("win_rate", 0) / 100  # 转为小数
    max_dd = base_variant.get("max_drawdown_pct", 0) / 100
    excess_5d = base_variant.get("excess_5d", 0) / 100
    
    # 门禁判定
    min_trades_ok = trades >= GATE["min_trades"]
    win_rate_ok = win_rate >= GATE["min_win_rate"]
    dd_ok = max_dd <= GATE["max_drawdown"]
    
    checks = {
        "n_trades": {"value": trades, "threshold": GATE["min_trades"], "pass": min_trades_ok},
        "win_rate": {"value": round(win_rate * 100, 2), "threshold": GATE["min_win_rate"] * 100, "pass": win_rate_ok},
        "max_drawdown": {"value": round(max_dd * 100, 2), "threshold": GATE["max_drawdown"] * 100, "pass": dd_ok},
        "excess_5d": {"value": round(excess_5d * 100, 2), "threshold": 0, "pass": excess_5d >= 0},
    }
    
    all_pass = all(c["pass"] for c in checks.values())
    return checks, "PASS" if all_pass else "FAIL"


def main(force=False):
    """主函数"""
    print("=== 门禁状态重建 ===")
    print(f"回测结果: {RESULT_FILE}")
    print(f"门禁文件: {GATE_FILE}")
    print()
    
    # 加载回测结果
    result = load_backtest_result()
    if not result:
        print("❌ 回测结果文件不存在")
        return 1
    
    # 计算门禁
    checks, status = compute_gate_checks(result)
    if not checks:
        print(f"❌ 门禁计算失败: {status}")
        return 1
    
    # 输出结果
    print("门禁指标:")
    for name, check in checks.items():
        icon = "✅" if check["pass"] else "❌"
        print(f"  {icon} {name}: {check['value']} (阈值={check['threshold']})")
    print()
    print(f"门禁状态: {status}")
    
    # 写入文件
    gate_data = {
        "status": status.lower(),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checks": checks,
        "note": "自动重建 (2026-10-11 审查修复)",
    }
    
    atomic_json.atomic_dump(gate_data, GATE_FILE, ensure_ascii=False, indent=2)
    print(f"\n✅ 已写入 {GATE_FILE}")
    
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="强制重建")
    args = parser.parse_args()
    
    sys.exit(main(force=args.force))
