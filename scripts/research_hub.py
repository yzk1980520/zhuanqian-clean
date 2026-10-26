#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
research_hub.py — 研究域统一入口（Research Domain Hub）
========================================================
老四自审Agent 出品 | 2026-10-14 | 沈砚（研究域架构师）设计
定位
----
把散落在 research_archive/（185个脚本）、research/、docs/、data/ 的研究资产，
收敛成一个**有边界、有规范、可检索、可追溯**的"研究域"。
研究域边界（明确"研究什么 / 不研究什么"）
----------------------------------------
  ✅ 纳入研究域：
     - 因子研究（IC/IR/相关性/衰减/换手）
     - 策略研究（回测参数/止盈止损/轮动规则）
     - 市场状态研究（情绪/主线/板块强度）
     - 复盘结论沉淀（从复盘主理人来的迭代提案）
  ❌ 不纳入研究域（属于工程/运维域）：
     - 交易数据（holdings/trade_log/config）→ 总管独占写
     - 风控真源 risk_rules.py → 只读引用，不改
     - cron 调度、飞书推送 → 总管域
目录规范
--------
    research/
      ├── knowledge-base/          # 已有：知识库
      ├── seven_module_framework.md
      ├── registry.json            # 【本模块维护】研究资产登记表
      ├── topics/                  # 【本模块创建】研究主题（每个主题一个目录）
      │     └── <topic_id>/
      │           ├── README.md    # 主题说明：假设/方法/数据/结论
      │           ├── artifacts/   # 产物：图表/数据/报告
      │           └── meta.json    # 元数据（状态/负责人/时间）
      └── index.md                 # 【本模块生成】研究域总索引
设计原则
--------
1. 只读扫描 + 显式登记：不自动移动/删除任何既有文件（删除保护）。
2. 有据可查：每个主题登记时附来源、时间、负责人。
3. 与复盘主理人对接：topics 可挂接 iteration proposals。
用法
----
    python research_hub.py scan                 # 扫描现有研究资产，生成索引
    python research_hub.py new <topic_id>       # 新建研究主题骨架
    python research_hub.py list                 # 列出已登记主题
    python research_hub.py register <topic_id> --title ... --owner ... --status ...
    python research_hub.py index                # 生成 research/index.md
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception as e:
    print(f"🔴 [research_hub.py:56] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
    pass
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 2026-10-20 P2-1b 归位 scripts/ 后上溯一级
RESEARCH_DIR = os.path.join(PROJECT_ROOT, "research")
TOPICS_DIR = os.path.join(RESEARCH_DIR, "topics")
REGISTRY_PATH = os.path.join(RESEARCH_DIR, "registry.json")
INDEX_PATH = os.path.join(RESEARCH_DIR, "index.md")
# 允许的研究主题状态
TOPIC_STATUS = ("proposed", "active", "concluded", "archived")
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _load_registry() -> Dict[str, Any]:
    if os.path.exists(REGISTRY_PATH):
        try:
            with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and "topics" in d:
                return d
        except Exception as e:
            print(f"🔴 [research_hub.py:74] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
            pass
    return {"_schema_version": "1.0", "updated_at": _now(), "topics": {}}
def _save_registry(reg: Dict[str, Any]) -> None:
    reg["updated_at"] = _now()
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    try:
        sys.path.insert(0, PROJECT_ROOT)
        import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
        atomic_json.atomic_dump(reg, REGISTRY_PATH, ensure_ascii=False, indent=2)
    except Exception:
        with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(reg, f, ensure_ascii=False, indent=2)
# ════════════════════════════════════════════════════════════════
# 命令实现
# ════════════════════════════════════════════════════════════════
def cmd_scan() -> int:
    """扫描现有研究资产（只读），生成索引。"""
    print("=" * 72)
    print("🔬 研究域扫描（只读）")
    print("=" * 72)
    assets = {
        "research/": [],
        "research_archive/": [],
        "docs/": [],
    }
    for rel in assets:
        p = os.path.join(PROJECT_ROOT, rel)
        if os.path.isdir(p):
            items = sorted(os.listdir(p))
            assets[rel] = items
            print(f"\n[{rel}] 共 {len(items)} 项")
            for x in items[:15]:
                print("   ", x)
            if len(items) > 15:
                print(f"    ... 还有 {len(items)-15} 项")
        else:
            print(f"\n[{rel}] 不存在")
    # 统计
    print("\n" + "=" * 72)
    print("📊 研究资产统计")
    print("=" * 72)
    for rel, items in assets.items():
        py = len([x for x in items if x.endswith(".py")])
        md = len([x for x in items if x.endswith(".md")])
        js = len([x for x in items if x.endswith(".json")])
        print(f"  {rel:<22} 总{len(items):>4} | .py {py:>4} | .md {md:>3} | .json {js:>3}")
    print("\n💡 提示：用 `research_hub.py new <topic_id>` 把有价值的研究沉淀为正式主题。")
    return 0
def cmd_new(topic_id: str, title: str = "", owner: str = "老四") -> int:
    """新建研究主题骨架。"""
    if not topic_id or not topic_id.replace("_", "").replace("-", "").isalnum():
        print(f"❌ 非法 topic_id: {topic_id!r}（只允许字母/数字/下划线/连字符）")
        return 1
    tdir = os.path.join(TOPICS_DIR, topic_id)
    if os.path.exists(tdir):
        print(f"⚠️ 主题已存在: {tdir}")
        return 1
    os.makedirs(os.path.join(tdir, "artifacts"), exist_ok=True)
    title = title or topic_id
    # README 模板
    readme = f"""# 研究主题：{title}
- **topic_id**: `{topic_id}`
- **负责人**: {owner}
- **创建时间**: {_now()}
- **状态**: proposed
## 1. 研究假设
> 待填写：本主题要验证/回答什么问题？
## 2. 方法
> 待填写：数据来源、因子/指标、回测区间、评价指标。
## 3. 数据
> 待填写：用到的数据文件与时间范围。
## 4. 结论
> 待填写：结论 + 证据（命令/输出/时间戳）。
## 5. 迭代提案（对接复盘主理人）
> 待填写：若结论支持，提出什么可落地的迭代？若证伪，回退什么？
"""
    with open(os.path.join(tdir, "README.md"), "w", encoding="utf-8") as f:
        f.write(readme)
    meta = {
        "topic_id": topic_id,
        "title": title,
        "owner": owner,
        "status": "proposed",
        "created_at": _now(),
        "updated_at": _now(),
        "artifacts": [],
        "linked_iterations": [],
    }
    with open(os.path.join(tdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    # 登记
    reg = _load_registry()
    reg["topics"][topic_id] = meta
    _save_registry(reg)
    print(f"✅ 已创建研究主题: {tdir}")
    print(f"   README: {os.path.join(tdir, 'README.md')}")
    print(f"   meta:   {os.path.join(tdir, 'meta.json')}")
    return 0
def cmd_register(topic_id: str, title: str, owner: str, status: str) -> int:
    """登记/更新主题元数据。"""
    if status not in TOPIC_STATUS:
        print(f"❌ 非法 status: {status!r}，允许: {TOPIC_STATUS}")
        return 1
    reg = _load_registry()
    if topic_id not in reg["topics"]:
        print(f"⚠️ 主题未登记，先创建: research_hub.py new {topic_id}")
        return 1
    reg["topics"][topic_id].update({
        "title": title or reg["topics"][topic_id].get("title", topic_id),
        "owner": owner or reg["topics"][topic_id].get("owner", "老四"),
        "status": status,
        "updated_at": _now(),
    })
    _save_registry(reg)
    # 同步 meta.json
    tdir = os.path.join(TOPICS_DIR, topic_id)
    mp = os.path.join(tdir, "meta.json")
    if os.path.exists(mp):
        with open(mp, "r", encoding="utf-8") as f:
            m = json.load(f)
        m.update(reg["topics"][topic_id])
        with open(mp, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    print(f"✅ 已更新主题 {topic_id}: status={status}, owner={owner}")
    return 0
def cmd_list() -> int:
    reg = _load_registry()
    topics = reg.get("topics", {})
    print("=" * 72)
    print(f"📚 研究域已登记主题（共 {len(topics)} 个）")
    print("=" * 72)
    if not topics:
        print("  （空）用 `research_hub.py new <topic_id>` 创建第一个主题")
        return 0
    for tid, m in sorted(topics.items()):
        print(f"\n  [{m.get('status','?'):<10}] {tid}")
        print(f"       标题: {m.get('title')}")
        print(f"       负责人: {m.get('owner')}  更新: {m.get('updated_at')}")
    return 0
def cmd_index() -> int:
    """生成 research/index.md 总索引。"""
    reg = _load_registry()
    topics = reg.get("topics", {})
    lines = [
        "# 研究域总索引（Research Domain Index）",
        "",
        f"> 自动生成于 {_now()} ｜ 维护：老四自审Agent（research_hub.py）",
        "",
        "## 研究域边界",
        "",
        "| 纳入 ✅ | 不纳入 ❌ |",
        "|---|---|",
        "| 因子研究 / 策略研究 / 市场状态研究 / 复盘结论沉淀 | 交易数据 / 风控真源 / cron调度 / 飞书推送 |",
        "",
        f"## 已登记主题（{len(topics)}）",
        "",
        "| topic_id | 标题 | 负责人 | 状态 | 更新时间 |",
        "|---|---|---|---|---|",
    ]
    for tid, m in sorted(topics.items()):
        lines.append(f"| `{tid}` | {m.get('title','')} | {m.get('owner','')} | "
                     f"{m.get('status','')} | {m.get('updated_at','')} |")
    if not topics:
        lines.append("| （空） | | | | |")
    lines += [
        "",
        "## 目录规范",
        "",
        "```",
        "research/",
        "  ├── registry.json      # 研究资产登记表（本模块维护）",
        "  ├── index.md           # 本索引",
        "  └── topics/<topic_id>/",
        "        ├── README.md    # 假设/方法/数据/结论/迭代提案",
        "        ├── artifacts/   # 产物",
        "        └── meta.json    # 元数据",
        "```",
        "",
        "## 用法",
        "",
        "```bash",
        "python research_hub.py scan                 # 扫描现有资产",
        "python research_hub.py new <topic_id>       # 新建主题",
        "python research_hub.py register <id> --title T --owner O --status active",
        "python research_hub.py list                 # 列出主题",
        "python research_hub.py index                # 生成本索引",
        "```",
    ]
    os.makedirs(RESEARCH_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 已生成索引: {INDEX_PATH}")
    return 0
def main() -> int:
    ap = argparse.ArgumentParser(description="研究域统一入口")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="扫描现有研究资产")
    p_new = sub.add_parser("new", help="新建研究主题")
    p_new.add_argument("topic_id")
    p_new.add_argument("--title", default="")
    p_new.add_argument("--owner", default="老四")
    p_reg = sub.add_parser("register", help="登记/更新主题")
    p_reg.add_argument("topic_id")
    p_reg.add_argument("--title", default="")
    p_reg.add_argument("--owner", default="")
    p_reg.add_argument("--status", default="active")
    sub.add_parser("list", help="列出主题")
    sub.add_parser("index", help="生成总索引")
    args = ap.parse_args()
    if args.cmd == "scan":
        return cmd_scan()
    if args.cmd == "new":
        return cmd_new(args.topic_id, args.title, args.owner)
    if args.cmd == "register":
        return cmd_register(args.topic_id, args.title, args.owner, args.status)
    if args.cmd == "list":
        return cmd_list()
    if args.cmd == "index":
        return cmd_index()
    return 0
if __name__ == "__main__":
    sys.exit(main())