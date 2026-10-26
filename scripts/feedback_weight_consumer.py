#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feedback_weight_consumer.py — feedback_suggestions.json 读侧消费者

职责:
  1. 读取 data/feedback_suggestions.json（只读）
  2. 提取 weight_suggestions 字段 → 生成"权重重估引用清单"
  3. 写入 data/weight_reestimation_refs.json（atomic_json.update_json + read-back断言）

边界:
  - ✅ 只读 suggestions，不修改 factor_weights.json
  - ✅ 不执行权重调整（仅产出引用清单，供老大拍板）
  - ✅ 走 atomic_json.update_json + read-back 断言

用法:
  python scripts/feedback_weight_consumer.py              # 消费全部 suggestions
  python scripts/feedback_weight_consumer.py --dry-run    # 仅检查输入格式
  python scripts/feedback_weight_consumer.py --type weekly_ic  # 只看指定类型
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# 注入项目根到 sys.path
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

from core.pipeline.atomic_json import update_json, atomic_load

SUGGESTIONS_FILE = PROJECT / "data" / "feedback_suggestions.json"
REFS_FILE = PROJECT / "data" / "weight_reestimation_refs.json"

# 支持消费的 review_type
CONSUMABLE_TYPES = ("weekly_ic", "monthly_tune")


def load_suggestions() -> dict:
    """读取 feedback_suggestions.json，不存在则返回空 dict"""
    if not SUGGESTIONS_FILE.exists():
        print(f"[INFO] suggestions 文件不存在，跳过消费: {SUGGESTIONS_FILE}")
        return {}
    try:
        with open(SUGGESTIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] suggestions JSON 解析失败: {e}", file=sys.stderr)
        raise


def extract_refs(data: dict, target_type: str | None = None) -> list[dict]:
    """
    从 suggestions 中提取 weight_suggestions 引用清单。
    每条引用包含: ts, review_type, factor, new_weight, source, confidence, observation
    """
    refs = []
    generated_at = data.get("generated_at", "")

    for rtype in CONSUMABLE_TYPES:
        if target_type and rtype != target_type:
            continue
        section = data.get(rtype, {})
        ws = section.get("weight_suggestions")
        if not ws or not isinstance(ws, dict):
            continue
        for factor, info in ws.items():
            refs.append({
                "ts": info.get("ts", generated_at),
                "review_type": rtype,
                "factor": factor,
                "new_weight": info.get("new_weight"),
                "source": info.get("source", rtype),
                "confidence": info.get("confidence", "low"),
                "observation": info.get("observation", section.get("observation", "")),
                "suggestion_ts": info.get("ts", ""),
            })
    return refs


def build_refs_payload(refs: list[dict], generated_at: str) -> dict:
    """构建 refs JSON payload"""
    return {
        "generated_at": datetime.now().isoformat(),
        "source_suggestions_ts": generated_at,
        "total_refs": len(refs),
        "refs": refs,
        "consumer_version": "1.0.0",
        "note": "仅引用清单，不自动执行权重调整",
    }


def write_refs_atomic(payload: dict) -> dict:
    """用 atomic_json.update_json 写入 refs，并 read-back 断言"""
    def mutator(existing: dict) -> dict:
        # 保留元信息字段，更新内容
        existing["generated_at"] = payload["generated_at"]
        existing["source_suggestions_ts"] = payload["source_suggestions_ts"]
        existing["total_refs"] = payload["total_refs"]
        existing["refs"] = payload["refs"]
        existing["consumer_version"] = payload["consumer_version"]
        existing["note"] = payload["note"]
        return existing

    result = update_json(str(REFS_FILE), mutator, default={})

    # read-back 断言
    readback = atomic_load(str(REFS_FILE), default={})
    assert readback.get("total_refs") == payload["total_refs"], (
        f"read-back 断言失败: 期望 {payload['total_refs']} 条引用，"
        f"实际 {readback.get('total_refs')}"
    )
    assert readback.get("refs") == payload["refs"], "read-back 断言失败: refs 内容不匹配"
    return result


def main():
    parser = argparse.ArgumentParser(
        description="feedback_suggestions 读侧消费者 — 产出权重重估引用清单"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查输入格式，不写 refs 文件",
    )
    parser.add_argument(
        "--type",
        choices=list(CONSUMABLE_TYPES),
        help="指定消费类型，不传则消费全部",
    )
    args = parser.parse_args()

    # 加载
    data = load_suggestions()
    if not data:
        print("[INFO] 无 suggestions 数据，退出")
        return 0

    generated_at = data.get("generated_at", "")
    print(f"[INFO] suggestions generated_at: {generated_at}")

    # 提取引用
    refs = extract_refs(data, target_type=args.type)
    print(f"[INFO] 提取到 {len(refs)} 条权重重估引用")

    # dry-run
    if args.dry_run:
        print("[DRY-RUN] 格式校验通过")
        for r in refs:
            print(f"  {r['review_type']} | {r['factor']} -> {r['new_weight']} "
                  f"(conf={r['confidence']}, ts={r['ts']})")
        return 0

    # 构建 payload 并原子写入
    payload = build_refs_payload(refs, generated_at)
    write_refs_atomic(payload)
    print(f"[OK] refs 已写入: {REFS_FILE} ({len(refs)} 条)")

    # 打印摘要
    by_type: dict[str, int] = {}
    for r in refs:
        by_type[r["review_type"]] = by_type.get(r["review_type"], 0) + 1
    for rtype, count in by_type.items():
        print(f"  [{rtype}] {count} 条引用")

    return 0


if __name__ == "__main__":
    sys.exit(main())
