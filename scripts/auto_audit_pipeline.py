#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_audit_pipeline.py v0.1 — 散报告收割流水线（P0-3 交付件, 2026-10-26 t_3bd7c2b8）
================================================================================
契约来源:
  - mainline/docs/AUTO-REVIEW-ITERATION-MECHANISM.md §1.1/§2（散报告收割→指纹去重→台账写入）
  - 机制文档 §四分工: 老三件①「先 1 票 1 天最小样本验证再放量（rollout_scope 留痕）」
  - .agent/skills/backtest-data-integrity/references/audit-pipeline-and-sched-reconcile.md（CLI 口径）

职责（只读收割 + 提案写入，**不写 defect_ledger.json**——台账写权归总管独占，机制 §2 规则4）:
  1. 散报告收割: 扫描报告文件, 提取 P0/P1/P2 候选项（只提候选+原文定位, 不自定 severity, §2 规则3）
  2. 指纹去重: sha1(报告路径|P级|症状去空白) —— 与台账 fingerprint 同算法同长度(40 hex);
     去重对象: defect_ledger.json 存量 + data/audit/ledger_proposals/ 历史提案 +
     data/anti_patterns.json（指纹字段缺失时降级为留痕, 不报"去重干净", 假绿守卫）
  3. 台账写入: 新候选逐件写 data/audit/ledger_proposals/DEF-proposal-<ts>-<fp8>.json
     （总管道: 脚本出提案 → 总管审核开单并入台账）
  4. 留痕: data/audit/harvest_log.jsonl 每轮 1 行（含 no_change / fingerprint_guard）

用法（.venv 解释器, 项目根执行）:
  .venv\\Scripts\\python.exe scripts/auto_audit_pipeline.py --scope single --source "data/audit/pipeline_status_20261026.md" --stock sh600519
  .venv\\Scripts\\python.exe scripts/auto_audit_pipeline.py --scope batch --days 14
  .venv\\Scripts\\python.exe scripts/auto_audit_pipeline.py --scope single --source "..." --json

退出码: 0=正常（含 no_change）; 2=输入缺失/不可读（显式报, 不静默空转, 供 cron 前置断言消费）。

rollout_scope 留痕（机制 §2 schema 必填）:
  single → "1票1天最小样本(single=<rel>, stock=<code|未指定>, day=<date|filedate>)"
  batch  → "batch_<N>d"
放量须待总管验收后改 --scope batch, 本脚本不自放量。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AUDIT_DIR = PROJECT / "data" / "audit"
PROPOSAL_DIR = AUDIT_DIR / "ledger_proposals"
HARVEST_LOG = AUDIT_DIR / "harvest_log.jsonl"
LEDGER_FILE = AUDIT_DIR / "defect_ledger.json"
ANTIPATTERNS_FILE = PROJECT / "data" / "anti_patterns.json"

PIPELINE_VERSION = "v0.1"
RUNNER = "laosan"

# P级只提候选, 台账 schema 只收 P0/P1/P2; P3+ 记 out_of_set 统计不入提案
# 表格严重度: 首个数据格恰为 P0/P1/P2 整格（严重度列）; P3+ 整格 → out_of_set
TABLE_SEV_RE = re.compile(r"^\|\s*P([0-9])\s*\|")
# 正文独立 P[0-2] 提及: 后面不得紧跟数字或 "-数字"（P0-3/P1-2 是任务ID不是严重度, 防误提）
PROSE_SEV_RE = re.compile(r"(?:^|[\s|（(【])P([0-3])(?!\d)(?!\-\d)")
# 阴性结论/已闭环标记（机制 §1.1 + cron prompt: 阴性结论/已闭环项不入台账）
# 正则而非子串: "无需 P0 处置"(阴性) 不匹配子串 "无 P0"（隔了"需"字）→ 首版缺陷, 2026-10-26 修
NEGATIVE_RE = re.compile(
    r"无\s*(?:需|要)?\s*P[0-2]|已修复|已解决|已闭环|已完成|已关闭|不重开|已销项|superseded"
)


def _now_local_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha1_fp(canonical: str) -> str:
    """与台账 fingerprint 同源同算法: sha1(normalized), 40 hex（机制 §2 指纹定义）"""
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _rel_posix(p: Path) -> str:
    """Windows 混合斜杠 relative_to 陷阱 → try/except 降级文件名（reference doc 陷阱3）"""
    try:
        return p.resolve().relative_to(PROJECT.resolve()).as_posix()
    except (ValueError, OSError):
        return p.name


def _atomic_write_text(path: Path, text: str) -> None:
    """atomic_dump 语义（tmp+os.replace）。core.pipeline.atomic_json 仅收 JSON,
    此处写原始文本（提案=json 字符串, harvest_log=单行追加另走 append）"""
    d = path.parent
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_ledger_fingerprints() -> tuple[dict[str, str], bool]:
    """读台账存量指纹（只读）。返回 {fp: entry_id}, ok=False 时不可用于去重判定"""
    if not LEDGER_FILE.is_file():
        return {}, True  # 台账未建（建账归总管首次建账动作）, 无存量可比 → 非失败
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise SystemExit(f"[ERROR] 台账不可读, 拒绝收割(去重前置件缺失): {LEDGER_FILE} ({e})")
    fps = {}
    for ent in data.get("entries", []):
        fp = ent.get("fingerprint")
        if fp:
            fps[fp] = ent.get("id", "?")
    return fps, True


def load_prior_proposal_fps() -> set[str]:
    """历史提案指纹（防重复提案, 10-18 批次 12/12 去重的同款口径）"""
    out: set[str] = set()
    if not PROPOSAL_DIR.is_dir():
        return out
    for pf in sorted(PROPOSAL_DIR.glob("DEF-proposal-*.json")):
        try:
            with open(pf, "r", encoding="utf-8") as f:
                pdata = json.load(f)
            for prop in pdata.get("proposals", []):
                if prop.get("fingerprint"):
                    out.add(prop["fingerprint"])
        except (json.JSONDecodeError, OSError) as e:
            raise SystemExit(f"[ERROR] 历史提案不可读, 拒绝收割(去重不可信): {pf.name} ({e})")
    return out


def load_antipattern_fingerprint_guard() -> str:
    """anti_patterns 指纹守卫（假绿守卫: 指纹未补齐时不得报'去重干净'）"""
    if not ANTIPATTERNS_FILE.is_file():
        return "anti_patterns.json 缺失, 反例库去重不可用, 去重仅按台账/历史提案指纹精确比对"
    try:
        with open(ANTIPATTERNS_FILE, "r", encoding="utf-8") as f:
            ap = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return f"anti_patterns.json 不可读({e}), 反例库去重不可用, 去重仅按台账/历史提案指纹精确比对"
    patterns = ap.get("patterns", [])
    missing = sum(1 for p in patterns if not p.get("fingerprint"))
    if missing:
        return (f"anti_patterns.json {missing}/{len(patterns)} 指纹未补齐, 反例库去重不可信, "
                f"去重仅按台账/历史提案指纹精确比对(留痕), 不报'对账/去重干净'")
    return f"anti_patterns.json {len(patterns)}/{len(patterns)} 指纹已补齐, 反例库去重可用"


def extract_candidates(rel_source: str, text: str) -> tuple[list[dict], list[dict], int]:
    """提取 P0-P2 候选 + 阴性过滤 + P3 统计。
    规则: 表格行看首格整格严重度; 正文看独立 P 提及（P0-3 型任务ID 不提, 防误报）。
    返回 (candidates, filtered_negative, out_of_set_count)"""
    lines = text.splitlines()
    candidates: list[dict] = []
    filtered: list[dict] = []
    out_of_set = 0
    for i, raw in enumerate(lines, start=1):
        s = raw.rstrip().strip()
        if not s:
            continue
        sev: str | None = None
        is_table = s.startswith("|")
        if is_table:
            tm = TABLE_SEV_RE.match(s)
            if tm:
                d = tm.group(1)
                if d in ("0", "1", "2"):
                    sev = f"P{d}"
                else:
                    out_of_set += 1
                    continue
        if sev is None:
            pm = PROSE_SEV_RE.search(s)
            if pm:
                d = pm.group(1)
                if d in ("0", "1", "2"):
                    sev = f"P{d}"
                else:
                    out_of_set += 1
                    continue
        if sev is None:
            continue
        # 阴性结论/已闭环行: 不入台账（cron prompt 同口径）
        if NEGATIVE_RE.search(s):
            filtered.append({"line": i, "sev_mention": sev, "text": s[:200],
                             "reason": "negative_or_closed_marker"})
            continue
        desc = s if is_table else s
        desc_norm = " ".join(desc.split())
        cand = {
            "line": i,
            "sev_mention": sev,
            "text": desc[:300],
            "fingerprint": _sha1_fp(f"{rel_source}|{sev}|{desc_norm}"),
        }
        candidates.append(cand)
    return candidates, filtered, out_of_set


def resolve_sources(args) -> list[tuple[Path, str]]:
    if args.scope == "single":
        if not args.source:
            raise SystemExit("[ERROR] --scope single 须配 --source <报告路径>")
        p = (PROJECT / args.source).resolve() if not os.path.isabs(args.source) else Path(args.source)
        if not p.is_file():
            raise SystemExit(f"[ERROR] 源文件不存在(exit 2): {args.source}")
        return [(p, _rel_posix(p))]
    # batch
    days = args.days
    cutoff = datetime.now().timestamp() - days * 86400
    found: list[tuple[Path, str]] = []
    patterns = {
        "data/audit": [AUDIT_DIR.glob("*.md")],
        "mainline/docs": [
            (PROJECT / "mainline" / "docs").glob("audit_report_*.md"),
            (PROJECT / "mainline" / "docs").glob("AUDIT-REPORT*.md"),
            (PROJECT / "mainline" / "docs").glob("review-*.md"),
        ],
    }
    for globs in patterns.values():
        for g in globs:
            for p in sorted(g):
                try:
                    if p.stat().st_mtime >= cutoff:
                        found.append((p, _rel_posix(p)))
                except OSError as e:
                    raise SystemExit(f"[ERROR] stat 失败, 拒绝批量收割: {p} ({e})")
    # 去重保序
    seen, deduped = set(), []
    for p, rel in found:
        if p not in seen:
            seen.add(p)
            deduped.append((p, rel))
    if len(deduped) > 200:
        print(f"[WARN] batch 源文件 {len(deduped)} > 200, 截断至 200（先窄后宽）")
        deduped = deduped[:200]
    return deduped


def file_date_hint(p: Path) -> str:
    m = re.search(r"(20\d{2})([01]\d)([0-3]\d)", p.name)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y%m%d")


def main() -> int:
    ap = argparse.ArgumentParser(description="散报告收割→指纹去重→提案（P0-3 流水线 v0.1）")
    ap.add_argument("--scope", choices=["single", "batch"], default="single")
    ap.add_argument("--source", help="single 模式源报告路径")
    ap.add_argument("--days", type=int, default=14, help="batch 模式 mtime 窗口（天）")
    ap.add_argument("--stock", help="最小样本票代码（rollout_scope 留痕, 1票1天）")
    ap.add_argument("--day", help="最小样本日 YYYYMMDD（缺省取文件名日期）")
    ap.add_argument("--json", action="store_true", help="stdout 输出 JSON 摘要")
    args = ap.parse_args()

    sources = resolve_sources(args)
    ledger_fps, _ = load_ledger_fingerprints()
    prior_fps = load_prior_proposal_fps()
    guard = load_antipattern_fingerprint_guard()

    if args.scope == "single":
        rollout_scope = (f"1票1天最小样本(single={args.source}, "
                         f"stock={args.stock or '未指定'}, day={args.day or file_date_hint(sources[0][0])})")
        scope_tag = "single_sample"
    else:
        rollout_scope = f"batch_{args.days}d"
        scope_tag = f"batch_{args.days}d"

    ts_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_id = f"BATCH-{ts_tag}"
    all_new: list[dict] = []
    dup_ledger = 0
    dup_prior = 0
    total_candidates = 0
    total_filtered = 0
    total_out_of_set = 0
    source_files_ok: list[str] = []
    per_source_files: list[dict] = []

    for p, rel in sources:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            raise SystemExit(f"[ERROR] 源报告不可读, 拒绝收割: {rel} ({e})")
        cands, filtered, oos = extract_candidates(rel, text)
        total_candidates += len(cands)
        total_filtered += len(filtered)
        total_out_of_set += oos
        source_files_ok.append(rel)
        new_for_source: list[dict] = []
        for c in cands:
            if c["fingerprint"] in ledger_fps:
                dup_ledger += 1
                continue
            if c["fingerprint"] in prior_fps:
                dup_prior += 1
                continue
            rec = {
                "proposal_id": f"DEF-proposal-{ts_tag}-{c['fingerprint'][:8]}",
                "created_at": _now_local_iso(),
                "source_report": rel,
                "line": c["line"],
                "fingerprint": c["fingerprint"],
                "is_duplicate": False,
                "duplicate_reason": "",
                "severity_mention": c["sev_mention"],
                "description": c["text"],
                "evidence_chain": [f"来源: {rel}:{c['line']}"],
                "rollout_scope": rollout_scope,
                "status": "proposal",
                "notes": "本脚本只提候选项+原文定位, 不自定 severity（机制 §2 规则3）; P 级由老五/总管开单时定级",
            }
            new_for_source.append(rec)
        per_source_files.append({
            "source_report": rel,
            "issues_found": len(cands),
            "filtered_negative_or_closed": len(filtered),
            "out_of_sev_set": oos,
            "new_candidates": len(new_for_source),
        })
        # 逐件写提案文件（一候选一文件, 对齐 10-11 批次格式）
        for rec in new_for_source:
            doc = {
                "proposal_batch_id": batch_id,
                "created_at": rec["created_at"],
                "harvest_meta": {
                    "scope": scope_tag,
                    "report_file": rel,
                    "issues_found": len(cands),
                    "runner": f"{RUNNER}_pipeline_{PIPELINE_VERSION}",
                    "fingerprint_guard": guard,
                },
                "total_candidates": 1,
                "filtered_negative_or_closed": [x["text"][:120] for x in filtered[:5]],
                "duplicates_found": 0,
                "proposals": [rec],
            }
            fname = f"DEF-proposal-{ts_tag}-{rec['fingerprint'][:8]}.json"
            _atomic_write_text(PROPOSAL_DIR / fname, json.dumps(doc, ensure_ascii=False, indent=2))
            all_new.append({"proposal_id": rec["proposal_id"], "file": f"data/audit/ledger_proposals/{fname}",
                            "fingerprint": rec["fingerprint"], "sev_mention": rec["severity_mention"],
                            "source_report": rel})

    no_change = not all_new
    log_line = {
        "ts": _now_local_iso(),
        "event": "harvest" if not no_change else "harvest_no_change",
        "by": f"{RUNNER}_pipeline_{PIPELINE_VERSION}",
        "scope": scope_tag,
        "source_files": source_files_ok,
        "issues_found": total_candidates,
        "filtered_negative_or_closed": total_filtered,
        "out_of_sev_set": total_out_of_set,
        "duplicates_of_ledger": dup_ledger,
        "duplicates_of_prior_proposals": dup_prior,
        "new_proposals": len(all_new),
        "new_candidate_ids": [x["proposal_id"] for x in all_new],
        "rollout_scope": rollout_scope,
        "fingerprint_guard": guard,
        "note": "脚本只出提案; 台账 defect_ledger.json 写权归总管（机制 §2 规则4）",
    }
    with open(HARVEST_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_line, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())

    summary = {
        "pipeline": PIPELINE_VERSION,
        "scope": scope_tag,
        "rollout_scope": rollout_scope,
        "sources": per_source_files,
        "issues_found": total_candidates,
        "duplicates_of_ledger": dup_ledger,
        "duplicates_of_prior_proposals": dup_prior,
        "new_proposals": all_new,
        "fingerprint_guard": guard,
        "no_change": no_change,
        "harvest_log_line": log_line,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"[{PIPELINE_VERSION}] scope={scope_tag} rollout_scope={rollout_scope}")
        print(f"  源文件={len(source_files_ok)} 候选={total_candidates} 阴性过滤={total_filtered} "
              f"台账重复={dup_ledger} 历史提案重复={dup_prior} 新提案={len(all_new)}")
        for x in all_new:
            print(f"  NEW {x['proposal_id']} [{x['sev_mention']}] {x['source_report']} :: {x['fingerprint'][:8]}")
        print(f"  指纹守卫: {guard}")
        print(f"  harvest_log: data/audit/harvest_log.jsonl (+1行)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
