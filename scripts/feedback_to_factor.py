#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feedback_to_factor.py — 复盘反馈→因子权重建议生成器

职责:
  1. 读取 data/feedback_log.jsonl（append-only）
  2. 按 review_type 分组分析
  3. 生成因子权重调整建议（仅输出，不执行）
  4. 输出到 stdout + data/feedback_suggestions.json

边界:
  - ❌ 不修改 factor_registry
  - ❌ 不修改 STRATEGIES
  - ❌ 不修改 factor_weights.json
  - ✅ 只生成建议，等待老大拍板→总管合入

用法:
  python scripts/feedback_to_factor.py                    # 分析所有反馈
  python scripts/feedback_to_factor.py --type after_close # 只看after_close
  python scripts/feedback_to_factor.py --type weekly_ic   # 只看weekly_ic
  python scripts/feedback_to_factor.py --type monthly_tune # 只看monthly_tune
  python scripts/feedback_to_factor.py --dry-run          # 仅检查格式，不输出建议
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Any

PROJECT = Path(__file__).parent.parent
FEEDBACK_LOG = PROJECT / "data" / "feedback_log.jsonl"
SUGGESTIONS_FILE = PROJECT / "data" / "feedback_suggestions.json"

# 置信度权重：用于汇总多条反馈的权重建议
CONFIDENCE_WEIGHT = {"low": 0.3, "medium": 0.6, "high": 1.0}


def load_feedback_log() -> List[Dict]:
    """读取 feedback_log.jsonl，跳过空行和无效JSON"""
    if not FEEDBACK_LOG.exists():
        print(f"[INFO] feedback_log 不存在: {FEEDBACK_LOG}")
        return []
    records = []
    with open(FEEDBACK_LOG, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] 第{lineno}行JSON解析失败: {e}", file=sys.stderr)
    return records


def filter_by_type(records: List[Dict], review_type: Optional[str] = None) -> List[Dict]:
    """按 review_type 过滤"""
    if not review_type:
        return records
    return [r for r in records if r.get("review_type") == review_type]


def aggregate_weight_suggestions(
    records: List[Dict],
) -> Dict[str, Dict[str, Any]]:
    """
    汇总所有非null的weight_suggestion：
    - 同因子多条记录：取最新一条（按ts排序）
    - 输出结构: {因子名: {new_weight, source, ts, confidence}}
    """
    factor_updates: Dict[str, Dict[str, Any]] = {}
    for rec in sorted(records, key=lambda x: x.get("ts", ""), reverse=True):
        ws = rec.get("weight_suggestion")
        if not ws or not isinstance(ws, dict):
            continue
        for factor, weight in ws.items():
            if factor not in factor_updates:
                factor_updates[factor] = {
                    "new_weight": weight,
                    "source": rec.get("observer", "unknown"),
                    "ts": rec.get("ts", ""),
                    "confidence": rec.get("confidence", "low"),
                    "observation": rec.get("observation", ""),
                }
    return factor_updates


def generate_after_close_advice(records: List[Dict]) -> Dict[str, Any]:
    """生成after_close复盘建议"""
    if not records:
        return {"review_type": "after_close", "advice": "无反馈记录", "factors": []}

    latest = max(records, key=lambda x: x.get("ts", ""))
    advice = {
        "review_type": "after_close",
        "date": latest.get("date", ""),
        "observation": latest.get("observation", ""),
        "suggested_action": latest.get("suggested_action", ""),
        "related_factors": latest.get("related_factors", []),
        "confidence": latest.get("confidence", "low"),
        "all_observations": [
            {"date": r.get("date"), "obs": r.get("observation")} for r in records
        ],
    }
    return advice


def generate_weekly_ic_advice(records: List[Dict]) -> Dict[str, Any]:
    """生成weekly_ic监控建议"""
    if not records:
        return {"review_type": "weekly_ic", "advice": "无反馈记录", "factors": []}

    latest = max(records, key=lambda x: x.get("ts", ""))
    factor_updates = aggregate_weight_suggestions(records)

    advice = {
        "review_type": "weekly_ic",
        "date": latest.get("date", ""),
        "observation": latest.get("observation", ""),
        "suggested_action": latest.get("suggested_action", ""),
        "weight_suggestions": factor_updates,
        "related_factors": latest.get("related_factors", []),
        "confidence": latest.get("confidence", "low"),
    }
    return advice


def generate_monthly_tune_advice(records: List[Dict]) -> Dict[str, Any]:
    """生成monthly_tune月度调优建议（接口层，不自动执行）"""
    if not records:
        return {
            "review_type": "monthly_tune",
            "advice": "无反馈记录",
            "weight_suggestions": {},
        }

    latest = max(records, key=lambda x: x.get("ts", ""))
    factor_updates = aggregate_weight_suggestions(records)

    advice = {
        "review_type": "monthly_tune",
        "date": latest.get("date", ""),
        "observation": latest.get("observation", ""),
        "suggested_action": latest.get("suggested_action", ""),
        "weight_suggestions": factor_updates,
        "related_factors": latest.get("related_factors", []),
        "confidence": latest.get("confidence", "low"),
        "note": "此建议需经老大拍板→总管合入，本脚本不自动执行",
    }
    return advice


def print_report(advice: Dict[str, Any]) -> None:
    """格式化输出建议报告"""
    print("=" * 60)
    print(f"📊 复盘反馈 → 因子建议报告")
    print(f"   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    rtype = advice.get("review_type", "unknown")
    print(f"\n【复盘类型】{rtype}")
    print(f"【日期】{advice.get('date', 'N/A')}")
    print(f"【观察】{advice.get('observation', 'N/A')}")
    print(f"【建议动作】{advice.get('suggested_action', 'N/A')}")
    print(f"【置信度】{advice.get('confidence', 'N/A')}")

    factors = advice.get("related_factors", [])
    if factors:
        print(f"【关联因子】{', '.join(factors)}")

    ws = advice.get("weight_suggestions")
    if ws:
        print("\n【因子权重调整建议】（仅供参考，不自动执行）")
        for factor, info in ws.items():
            print(
                f"  {factor}: {info['new_weight']} "
                f"(来源: {info['source']}, 置信度: {info['confidence']})"
            )
        print("\n⚠️  以上建议需经老大拍板→总管合入STRATEGIES")

    action = advice.get("suggested_action")
    if action and rtype == "after_close":
        print(f"\n【次日行动】{action}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="复盘反馈→因子权重建议生成器（只读，不执行）"
    )
    parser.add_argument(
        "--type",
        choices=["after_close", "weekly_ic", "monthly_tune"],
        help="指定复盘类型，不传则分析全部",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查feedback_log格式，不输出建议",
    )
    args = parser.parse_args()

    # 加载反馈日志
    records = load_feedback_log()
    if not records:
        print("[INFO] feedback_log 无记录，退出")
        return 0

    # 过滤
    filtered = filter_by_type(records, args.type)
    if args.type and not filtered:
        print(f"[INFO] 无 {args.type} 类型反馈记录")
        return 0

    # dry-run: 仅验证格式
    if args.dry_run:
        print(f"[DRY-RUN] 共 {len(records)} 条记录，格式校验通过")
        for i, r in enumerate(records[-3:], len(records) - 2):
            fields = list(r.keys())
            print(f"  行{i}: type={r.get('review_type')}, fields={fields}")
        return 0

    # 生成建议
    if args.type == "after_close" or not args.type:
        advice = generate_after_close_advice(
            [r for r in filtered if r.get("review_type") == "after_close"]
            if args.type
            else filter_by_type(records, "after_close")
        )
        print_report(advice)

    if args.type == "weekly_ic" or not args.type:
        advice = generate_weekly_ic_advice(
            [r for r in filtered if r.get("review_type") == "weekly_ic"]
            if args.type
            else filter_by_type(records, "weekly_ic")
        )
        print_report(advice)

    if args.type == "monthly_tune" or not args.type:
        advice = generate_monthly_tune_advice(
            [r for r in filtered if r.get("review_type") == "monthly_tune"]
            if args.type
            else filter_by_type(records, "monthly_tune")
        )
        print_report(advice)

    # 写 suggestions 文件（只写建议，不改registry）
    output = {
        "generated_at": datetime.now().isoformat(),
        "total_records": len(records),
        "after_close": generate_after_close_advice(
            filter_by_type(records, "after_close")
        ),
        "weekly_ic": generate_weekly_ic_advice(filter_by_type(records, "weekly_ic")),
        "monthly_tune": generate_monthly_tune_advice(
            filter_by_type(records, "monthly_tune")
        ),
    }
    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✅ 建议已写入: {SUGGESTIONS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
