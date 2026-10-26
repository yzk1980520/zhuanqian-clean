#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_message_template.py — 飞书消息模板生成器（强制规范）

为什么要有这个脚本（2026-10-20 总管立规）：
  今日审查发现3类问题：
  1) 证据链缺失 — 裁定类未附命令+输出（违反准则5）
  2) P0预警未验证 — 假阳性消耗信噪比
  3) 修正未闭环 — 原行动项状态未说明

本脚本强制：
- 字符数校验（P0<200, P1/P2<400）
- 字段完整性检查（等级前缀+证据+行动项）
- 模板化输出（进度/裁定/修正）

用法：
  python scripts/feishu_message_template.py --type progress --level P1 --title "执行进度" --content "..."
  python scripts/feishu_message_template.py --type ruling --evidence "$ grep ..." --action "① @laosi 截止18:00"
  python scripts/feishu_message_template.py --dry-run --file message.md
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# 等级字符限制
LEVEL_LIMITS = {
    "P0": 200,
    "P1": 400,
    "P2": 400,
    "P3": None,
}

# 强制字段模式
REQUIRED_PATTERNS = {
    "progress": re.compile(r"▶|【|进度|任务|commit"),
    "ruling": re.compile(r"✅|❌|⚠️|\$ |command|证据"),
    "correction": re.compile(r"原|修正|作废|继续|更新"),
}


def check_character_limit(text: str, level: str) -> tuple[bool, int | None]:
    """检查字符数限制"""
    limit = LEVEL_LIMITS.get(level)
    if limit is None:
        return True, None
    return len(text) <= limit, limit


def check_required_fields(text: str, msg_type: str) -> tuple[bool, list[str]]:
    """检查强制字段"""
    patterns = REQUIRED_PATTERNS.get(msg_type, [])
    issues = []

    if not isinstance(patterns, list):
        patterns = [patterns]

    for pattern in patterns:
        if not pattern.search(text):
            issues.append(f"缺少{pattern.pattern}字段")

    return len(issues) == 0, issues


def generate_progress(level: str, title: str, content: str) -> str:
    """生成进度类消息"""
    ts = datetime.now().strftime("%H:%M")
    body = f"【{title} · {ts}】\n\n{content}"

    ok, limit = check_character_limit(body, level)
    if not ok and limit:
        print(f"⚠️  字符数{len(body)}超限制{limit}", file=sys.stderr)

    return body


def generate_ruling(level: str, title: str, evidence: str, action: str) -> str:
    """生成裁定类消息"""
    ts = datetime.now().strftime("%H:%M")
    body = f"【{title} · {ts}】\n\n"
    body += f"## 结论\n{evidence}\n\n"
    body += f"## 行动项\n{action}"

    ok, _ = check_required_fields(body, "ruling")
    if not ok:
        print("⚠️  缺少强制字段（证据/行动项）", file=sys.stderr)

    return body


def generate_correction(level: str, title: str, original_ts: str, changes: str, original_actions: str) -> str:
    """生成修正类消息"""
    ts = datetime.now().strftime("%H:%M")
    body = f"【{title} · {ts}】\n\n"
    body += f"原{original_ts}裁定更新：\n{changes}\n\n"
    body += f"原行动项状态：\n{original_actions}"

    return body


def main() -> int:
    ap = argparse.ArgumentParser(description="飞书消息模板生成器")
    ap.add_argument("--type", choices=["progress", "ruling", "correction"], required=True, help="消息类型")
    ap.add_argument("--level", choices=["P0", "P1", "P2", "P3"], default="P1", help="等级")
    ap.add_argument("--title", required=True, help="标题")
    ap.add_argument("--content", help="进度类内容")
    ap.add_argument("--evidence", help="裁定类证据（命令+输出）")
    ap.add_argument("--action", help="裁定类行动项")
    ap.add_argument("--original-ts", help="修正类原消息时间")
    ap.add_argument("--changes", help="修正类变更内容")
    ap.add_argument("--original-actions", help="修正类原行动项状态")
    ap.add_argument("--file", help="从文件读取正文（长文本）")
    ap.add_argument("--dry-run", action="store_true", help="只校验不输出")

    args = ap.parse_args()

    # 从文件读取
    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    elif args.type == "progress":
        content = args.content or ""
    elif args.type == "ruling":
        content = generate_ruling(args.level, args.title, args.evidence or "", args.action or "")
    elif args.type == "correction":
        content = generate_correction(args.level, args.title, args.original_ts or "", args.changes or "", args.original_actions or "")
    else:
        print(f"❌ 未知类型: {args.type}", file=sys.stderr)
        return 2

    # 字符数校验
    ok, limit = check_character_limit(content, args.level)
    if not ok and limit:
        print(f"❌ 字符数{len(content)}超限制{limit}", file=sys.stderr)
        return 1

    # 强制字段校验
    if args.type != "progress":
        field_ok, issues = check_required_fields(content, args.type)
        if not field_ok:
            print(f"⚠️  缺少字段: {', '.join(issues)}", file=sys.stderr)

    if args.dry_run:
        print(f"✅ dry-run通过，字符数={len(content)}")
        return 0

    print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
