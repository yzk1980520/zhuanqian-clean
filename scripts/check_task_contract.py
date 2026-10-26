#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务契约审计 v1.0 — 《多Agent任务契约与自愈规则（元宝对照）》§二 的机器件（读侧消费断言）

立规依据：老大 2026-10-20「优化执行」指示；docs/多Agent任务契约与自愈规则-元宝对照-20261020.md
铁律 §2.9：写侧（派单附【契约块】）必须注册读侧消费断言；本脚本即该断言。

判据（RULE_EPOCH 起创建且处于开放态的任务；epoch 前在途单 → 挂技术债台账，不 FAIL）：
  C1 契约块在位：body 含「【契约块】」
  C2 验收可机判：acceptance_criteria 段 ≥1 条机判行（反引号命令/路径 + PASS/exit/全绿/数值断言）
  C3 输出契约在位：output_contract 段非空
  C4 重试预算显式：retry_budget 声明 N 或 NULL=接受默认
  C5 R0 降级路径：R0 关键词命中 → degradation_path 段非空

只读：sqlite 以 mode=ro 打开 kanban.db（不走 CLI，避开 recompute_ready 写事务/委托栅栏问题）；
不写看板、不碰交易数据。
告警出口：--alert 时写 data/message_queue.json（AGENTS.md 规则 11 唯一投递器 QSP_MsgDrain）。

用法:
  python scripts/check_task_contract.py            # 人读
  python scripts/check_task_contract.py --json     # 机器读
  python scripts/check_task_contract.py --alert    # 违规入队飞书(R0违规→P1, 其余→P2)
"""
import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")

# 立规时刻：规则不溯及既往（此前的在途单挂技术债台账，不在此审计窗口内）
RULE_EPOCH = "2026-10-20T00:00:00+08:00"

OPEN_STATES = ("ready", "running", "blocked", "review", "todo", "scheduled")

# R0 高危关键词（命中任一则 C5 强制降级路径）
R0_KEYWORDS = re.compile(
    r"回测引擎|评分函数|成交模型|数据合并|risk_rules|trade_log|holdings|因子权重|cron巡检")

# 机判行特征：反引号内命令/路径 + 结果断言词
MACHINE_JUDGE = re.compile(
    r"`[^`]*(python|pytest|git |diff |exit=|PASS|FAIL|全绿|assert|\.py|\.json)[^`]*`"
    r"|`[^`]+`\s*→?\s*(PASS|exit=|全绿|== ?\d|≥ ?[12]\s*条|一手证据)", re.I)
# 自然语言数字断言：无需反引号，含 N/N 比例或 exit=N 或中文判定词（D-02 放宽）
NATURAL_JUDGE = re.compile(
    r"(?:\d+/\d+|exit[=:]\d+|全绿|PASS|FAIL|✅|❌|通过|不通过|≥\s*\d+|>\s*\d+)", re.I)

CONTRACT_MARK = "【契约块】"


def find_kanban_db():
    """按序找含任务的主库：env → 桌面端 hermes-home 根 → boards 子目录。"""
    cands = [os.environ.get("HERMES_KANBAN_DB") or ""]
    hh = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
    cands += [os.path.join(hh, "kanban.db"), os.path.join(hh, "kanban", "kanban.db")]
    for c in cands:
        if not c or not os.path.exists(c):
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % c, uri=True, check_same_thread=False)
            n = con.execute("select count(*) from tasks").fetchone()[0]
            con.close()
            if n:
                return c
        except Exception:
            # CR-01 异常响铃化：仅固定标识入 stderr，不泄露路径/异常详情（防 cron 环境信息污染）
            # 原始异常归因见 docs/reviews/t_b07a0064-code-review-20261021.md D-01
            print("🔴 [check_task_contract] CR-01: DB open failed, tried all candidates", file=sys.stderr)
            continue
    return None


def _section(body, key):
    """取契约块内 '- key:' 之后、下一个 '- other_key:' 行之前的文本（含同行冒号后内容）。"""
    lines = (body or "").splitlines()
    key_re = re.compile(r"^\s*[-*]?\s*%s\s*[:：]" % re.escape(key), re.I)
    next_field = re.compile(r"^\s*[-*]\s*[a-z_]+\s*[:：]")
    out, active = [], False
    for ln in lines:
        m = key_re.match(ln)
        if m:
            active = True
            rest = ln[m.end():].strip()
            if rest:
                out.append(rest)
            continue
        if active:
            if next_field.match(ln) and not key_re.match(ln):
                break
            out.append(ln)
    return "\n".join(out).strip()


def is_r0_task(title, body):
    return bool(R0_KEYWORDS.search("%s\n%s" % (title or "", body or "")))


def check_task(body, r0):
    """返回缺失项列表（空=合规）。C1 缺失时整体记 C1，避免连坐。"""
    body = body or ""
    if CONTRACT_MARK not in body:
        return ["C1-契约块"]
    missing = []
    acc = _section(body, "acceptance_criteria")
    if not acc or (not re.search(r"`[^`]+`", acc) and not MACHINE_JUDGE.search(acc) and not NATURAL_JUDGE.search(acc)):
        missing.append("C2-验收机判项")
    oc = _section(body, "output_contract")
    if not oc or oc in ("无", "无。", "-", "—"):
        missing.append("C3-输出契约")
    if not re.search(r"retry_budget\s*[:：]?\s*(\d+|NULL)", body, re.I):
        missing.append("C4-重试预算声明")
    if r0:
        dp = _section(body, "degradation_path")
        if not dp or dp in ("无", "无。", "-", "—"):
            missing.append("C5-R0降级路径")
    return missing


def audit():
    db_path = find_kanban_db()
    if not db_path:
        print("❌ 未找到 kanban.db（试 HERMES_KANBAN_DB 与 hermes-home 默认路径）", file=sys.stderr)
        return None, 2
    con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, check_same_thread=False)
    rows = con.execute(
        "select id, title, body, status, assignee, created_at from tasks "
        "where status in (%s) order by created_at desc" % ",".join("?" * len(OPEN_STATES)),
        OPEN_STATES).fetchall()
    con.close()

    epoch_ts = dt.datetime.fromisoformat(RULE_EPOCH).timestamp()
    violations, debt, compliant, skipped = [], [], [], []
    for tid, title, body, status, assignee, created in rows:
        # 豁免：追溯性 L2 复审挂接卡（结构性占位，非执行派单，无实质 acceptance_criteria）
        # 判据：title 含「L2复审·存量追溯」且 body 以「追溯性 L2 复审挂接卡」开头
        if "L2复审·存量追溯" in (title or "") and (body or "").startswith("追溯性 L2 复审挂接卡"):
            skipped.append({"id": tid, "title": (title or "")[:40], "reason": "L2追溯挂接卡豁免"})
            continue
        r0 = is_r0_task(title, body)
        missing = check_task(body, r0)
        rec = {"id": tid, "status": status, "assignee": assignee,
               "r0": r0, "missing": missing, "title": (title or "")[:40]}
        if created >= epoch_ts:
            (violations if missing else compliant).append(rec)
        elif missing:
            debt.append(rec)

    report = {
        "ok": not violations,
        "db": db_path,
        "rule_epoch": RULE_EPOCH,
        "checked_open": len(rows),
        "in_window": len(violations) + len(compliant),
        "compliant": [c["id"] for c in compliant],
        "violations": violations,
        "debt_no_retro": debt,
        "r0_violations": sum(1 for v in violations if v["r0"]),
        "ts": dt.datetime.now().astimezone().isoformat(),
    }
    return report, (0 if report["ok"] else 1)


def print_human(report):
    print("== 任务契约审计（%s） ==" % report["ts"][:19])
    print("看板库: %s" % report["db"])
    print("开放态在途 %d 单 | 窗口内(≥epoch) %d | 合规 %d | 违规 %d | 挂账(不溯及) %d"
          % (report["checked_open"], report["in_window"], len(report["compliant"]),
             len(report["violations"]), len(report["debt_no_retro"])))
    for v in report["violations"]:
        print("❌ [%s] %s status=%s assignee=%s 缺[%s] %s"
              % ("R0" if v["r0"] else "R1/R2", v["id"], v["status"], v["assignee"],
                 "/".join(v["missing"]), v["title"]))
    for d in report["debt_no_retro"]:
        print("⚖️ 挂账 %s status=%s 缺[%s]（不溯及，验收门前补）"
              % (d["id"], d["status"], "/".join(d["missing"])))
    if report["ok"]:
        print("✅ 窗口内任务全部合规" if report["in_window"] else "ℹ️ 窗口内无受审任务")


def enqueue_alert(report):
    """违规入队（规则 11 唯一出口）。R0 违规 P1，其余 P2。失败不影响退出码语义。"""
    try:
        sys.path.insert(0, PROJECT)
        from core.pipeline.atomic_json import atomic_dump, atomic_load
        q = os.path.join(DATA, "message_queue.json")
        items = atomic_load(q, []) or []
        level = "P1" if report["r0_violations"] else "P2"
        body = "; ".join("%s(%s)缺[%s]" % (v["id"], "R0" if v["r0"] else "R1/R2",
                                             "/".join(v["missing"]))
                         for v in report["violations"][:8])
        items.append({
            "id": "taskcontract_%s_%d" % (level.lower(), int(dt.datetime.now().timestamp())),
            "content": "⚠️ [任务契约审计-%s] %d 个在途单缺契约项：%s（判据见 docs/多Agent任务契约与自愈规则-元宝对照-20261020.md §二）"
                       % (level, len(report["violations"]), body),
            "platform": "feishu",
            "ts": dt.datetime.now().timestamp(),
        })
        atomic_dump(items, q)
        print("已入队 %s ×1 → data/message_queue.json（QSP_MsgDrain 投递）" % level)
        return True
    except Exception as e:
        print("入队失败: %s" % e, file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON（不打印人读报告）")
    ap.add_argument("--alert", action="store_true", help="违规写 data/message_queue.json")
    ap.add_argument("--no-snapshot", action="store_true", help="不写审计快照")
    a = ap.parse_args()

    report, rc = audit()
    if report is None:
        return 2
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        print_human(report)
    if a.alert and report["violations"]:
        enqueue_alert(report)
    if not a.no_snapshot:
        snap_dir = os.path.join(DATA, "logs")
        os.makedirs(snap_dir, exist_ok=True)
        snap = os.path.join(snap_dir, "task_contract_audit_%s.json"
                            % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        with open(snap, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print("审计快照 → %s" % snap)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
