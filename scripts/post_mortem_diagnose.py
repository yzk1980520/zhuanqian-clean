"""
post_mortem_diagnose.py — 回测 FAIL 自动诊断
触发条件: 回测结果判定 FAIL（由 auto_backtest_pipeline 或人工调用）
输出: data/post_mortem_<ts>.json + stdout 结构化摘要

诊断维度:
1. 因子 IC 排序（找出最弱/翻转因子）
2. 评分分布（头部 vs 尾部区分度）
3. 最近 N 笔交易归因（哪笔拖累了结果）
4. 门禁状态快照（factor_gate 当时状态）
5. 环境门状态（当日环境提示）
"""

import json
import time
import sys
import hashlib
import logging
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJ = Path(__file__).parent.parent
logger = logging.getLogger("post_mortem")


def _load(path: Path, default=None):
    """读取 JSON；文件不存在返回 default，文件损坏记 warning 后返回 default（宪法 VII：不吞异常）。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.warning("post_mortem: %s 损坏，跳过: %s", path.name, e)
        return default


def _factor_ic_diagnosis(ic_data: Optional[dict]) -> dict:
    """分析因子 IC，找出最弱/翻转/缺失因子。"""
    if not ic_data:
        return {"status": "no_data"}

    # ic_data 结构因版本而异，做通用处理
    factors = []
    if isinstance(ic_data, dict):
        # 格式1: {factor_name: {ic_mean, ic_std, ...}}
        for name, info in ic_data.items():
            if isinstance(info, dict):
                factors.append({
                    "name": name,
                    "ic_mean": info.get("ic_mean"),
                    "ic_std": info.get("ic_std"),
                    "direction": info.get("direction"),
                    "status": info.get("status"),
                })
            elif isinstance(info, (int, float)):
                factors.append({"name": name, "ic_mean": info})
    elif isinstance(ic_data, list):
        for item in ic_data:
            if isinstance(item, dict):
                factors.append(item)

    if not factors:
        return {"status": "unparsed", "raw": ic_data}

    valid = [f for f in factors if f.get("ic_mean") is not None]
    reversed_f = [f for f in valid if (f.get("ic_mean") or 0) < -0.01]
    weak_f = [f for f in valid if abs(f.get("ic_mean") or 0) < 0.01]
    top3 = sorted(valid, key=lambda x: x.get("ic_mean") or 0, reverse=True)[:3]
    bottom3 = sorted(valid, key=lambda x: x.get("ic_mean") or 0)[:3]

    return {
        "status": "ok",
        "total_factors": len(factors),
        "valid_factors": len(valid),
        "reversed": [f.get("name") for f in reversed_f],
        "weak": [f.get("name") for f in weak_f],
        "top3_ic": {f.get("name"): f.get("ic_mean") for f in top3},
        "bottom3_ic": {f.get("name"): f.get("ic_mean") for f in bottom3},
    }


def _gate_diagnosis(gate_data: Optional[dict]) -> dict:
    """检查 factor_gate.json 状态。"""
    if not gate_data:
        return {"status": "no_data"}
    return {
        "status": "ok",
        "strict_valid_count": gate_data.get("strict_valid_count"),
        "total_factors": gate_data.get("total_factors"),
        "gate_passed": gate_data.get("passed") or gate_data.get("gate_passed"),
        "blockers": gate_data.get("blockers") or gate_data.get("fail_reasons"),
    }


def _trade_diagnosis(trade_log: Optional[list], n_recent: int = 5) -> dict:
    """取最近 N 笔交易做归因摘要。"""
    if not trade_log:
        return {"status": "no_data"}
    if isinstance(trade_log, dict):
        # 可能是 {"trades": [...]} 格式
        trades = trade_log.get("trades") or trade_log.get("history") or []
    else:
        trades = trade_log
    recent = trades[-n_recent:] if trades else []
    summary = []
    for t in recent:
        if isinstance(t, dict):
            summary.append({
                "ts": t.get("ts") or t.get("date"),
                "symbol": t.get("symbol") or t.get("code"),
                "side": t.get("side") or t.get("direction"),
                "pnl": t.get("pnl") or t.get("return_pct"),
            })
    return {"status": "ok", "recent_trades": summary}


def run_post_mortem(backtest_result: dict, context: dict = None) -> dict:
    """
    执行 post-mortem 诊断。
    
    参数:
      backtest_result: 回测结果 dict（须包含 status="FAIL"）
      context: 可选附加上下文 {factor_ic: ..., gate: ..., trades: ...}
    
    返回: 诊断 dict
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    # 加纳秒尾防同一秒文件名碰撞
    out_file = PROJ / "data" / f"post_mortem_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 10000:04d}.json"

    # 1. 因子 IC
    ic_data = context.get("factor_ic") if context else None
    if ic_data is None:
        ic_data = _load(PROJ / "data" / "factor_ic.json")
    ic_diag = _factor_ic_diagnosis(ic_data)

    # 2. 门禁
    gate_data = context.get("gate") if context else None
    if gate_data is None:
        gate_data = _load(PROJ / "data" / "factor_gate.json")
    gate_diag = _gate_diagnosis(gate_data)

    # 3. 交易归因
    trade_log = context.get("trades") if context else None
    if trade_log is None:
        trade_log = _load(PROJ / "data" / "trade_log.json")
    trade_diag = _trade_diagnosis(trade_log)

    # 4. 门禁状态哈希（防口径漂移）
    gate_hash = ""
    gate_file = PROJ / "data" / "factor_gate.json"
    if gate_file.exists():
        gate_hash = hashlib.sha256(gate_file.read_bytes()).hexdigest()[:16]

    result = {
        "ts": ts,
        "backtest_status": backtest_result.get("status", "FAIL"),
        "backtest_commit": backtest_result.get("commit") or backtest_result.get("engine_commit"),
        "diagnosis": {
            "factor_ic": ic_diag,
            "gate": gate_diag,
            "recent_trades": trade_diag,
        },
        "gate_hash": gate_hash,
        "auto_conclusions": [],
    }

    # 自动结论
    if ic_diag.get("reversed"):
        result["auto_conclusions"].append(
            f"⚠ 因子 {ic_diag['reversed']} IC 翻转（< -0.01），疑似失效"
        )
    if ic_diag.get("weak"):
        result["auto_conclusions"].append(
            f"⚠ 因子 {ic_diag['weak']} IC 接近 0（< 0.01），区分度不足"
        )
    if gate_diag.get("strict_valid_count") is not None and gate_diag["strict_valid_count"] < 8:
        result["auto_conclusions"].append(
            f"⚠ factor_gate strict_valid={gate_diag['strict_valid_count']} < 8，因子层应关闭（fail-close 合规）"
        )

    # 写文件
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 输出摘要
    print(f"=== Post-Mortem {ts} ===")
    print(f"回测状态: {result['backtest_status']}  commit: {result['backtest_commit'] or '(unknown)'}")
    print(f"诊断文件: {out_file}")
    for c in result["auto_conclusions"]:
        print(f"  {c}")
    if not result["auto_conclusions"]:
        print("  未检测到明确异常，建议人工检查因子 IC 分布与交易明细")

    return result


def main():
    # 用法: python scripts/post_mortem_diagnose.py [--result <回测结果json>]
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", default="", help="回测结果 JSON 文件路径")
    args = ap.parse_args()

    if args.result:
        bt_result = _load(Path(args.result), {})
    else:
        bt_result = {"status": "FAIL", "note": "manual post-mortem trigger"}

    run_post_mortem(bt_result)


if __name__ == "__main__":
    main()
