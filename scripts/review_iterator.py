#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
review_iterator.py — 复盘迭代主理人（Review & Iteration Orchestrator）
======================================================================
老四自审Agent 出品 | 2026-10-14 | 顾澜（复盘迭代主理人）设计
定位
----
把"复盘"与"迭代"从散点变成**闭环**：
    复盘（发生了什么） → 归因（为什么） → 提案（改什么） → 登记（谁跟进） → 验证（改对没）
上游数据源（只读）
------------------
  - trade_log.json                     实盘/推荐记录
  - data/trade_log.json                交易流水
  - data/holdings.json                 持仓
  - data/audit_log.json                self_audit 自省历史
  - data/alert_log.jsonl               自审告警流水
  - data/laosi_audit/*.json            老四自审报告
  - data/review_status.json            老五评审结论
  - data/gate_status.json              门禁结果
  - data/trial_gate_status.json        三重解冻状态
  - data/iteration_log.json            既有迭代日志
下游动作（本模块产出）
----------------------
  - data/review_iteration/review_<date>.json   单次复盘报告
  - data/review_iteration/proposals.json       迭代提案登记表（供研究域/总管消费）
  - data/review_iteration/latest.md            人类可读最新复盘
设计原则
--------
1. 只读上游 + 只写自己的产物目录（data/review_iteration/），绝不写交易数据。
2. 每个提案必须带：来源证据、优先级、建议动作、验证方式、状态。
3. 与 research_hub 对接：提案可转成研究主题（linked_iterations）。
4. fail-safe：上游缺失 → 记 WARN，不编造数据。
用法
----
    python review_iterator.py run                 # 执行一次复盘迭代
    python review_iterator.py run --json          # JSON 输出
    python review_iterator.py proposals           # 查看提案登记表
    python review_iterator.py --help
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
    print(f"🔴 [review_iterator.py:50] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
    pass
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 2026-10-20 P2-1b 归位 scripts/ 后上溯一级
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUT_DIR = os.path.join(DATA_DIR, "review_iteration")
PROPOSALS_PATH = os.path.join(OUT_DIR, "proposals.json")
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def _today() -> str:
    return datetime.now().strftime("%Y%m%d")
def _load_json(path: str, enc: str = "utf-8-sig") -> Optional[Any]:
    try:
        with open(path, "r", encoding=enc) as f:
            return json.load(f)
    except Exception as e:
        print(f"🔴 [review_iterator.py:64] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return None
def _load_jsonl(path: str, tail: int = 200) -> List[Any]:
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception as e:
                    print(f"🔴 [review_iterator.py:76] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
                    continue
    except Exception as e:
        print(f"🔴 [review_iterator.py:78] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return []
    return out[-tail:]
def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        sys.path.insert(0, PROJECT_ROOT)
        import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
        atomic_json.atomic_dump(data, path, ensure_ascii=False, indent=2)
    except Exception:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
# ════════════════════════════════════════════════════════════════
# 阶段 1：复盘（发生了什么）
# ════════════════════════════════════════════════════════════════
def stage_review() -> Dict[str, Any]:
    """收集复盘事实（只读）。"""
    facts: Dict[str, Any] = {"collected_at": _now(), "sources": {}, "warnings": []}
    # 1. 门禁三态
    rg = _load_json(os.path.join(DATA_DIR, "review_status.json"))
    sg = _load_json(os.path.join(DATA_DIR, "sanity_gate_status.json"), enc="utf-8")
    gg = _load_json(os.path.join(DATA_DIR, "gate_status.json"), enc="utf-8")
    tg = _load_json(os.path.join(DATA_DIR, "trial_gate_status.json"), enc="utf-8")
    facts["sources"]["review_status"] = {
        "laowu_approved": rg.get("laowu_approved") if isinstance(rg, dict) else None,
        "final_verdict": rg.get("final_verdict") if isinstance(rg, dict) else None,
        "last_updated": rg.get("last_updated") if isinstance(rg, dict) else None,
    } if isinstance(rg, dict) else None
    if not isinstance(rg, dict):
        facts["warnings"].append("review_status.json 缺失/异常")
    facts["sources"]["sanity_gate"] = sg
    facts["sources"]["gate_status"] = gg
    facts["sources"]["trial_gate"] = {
        "mode": tg.get("mode") if isinstance(tg, dict) else None,
        "verdict": tg.get("verdict") if isinstance(tg, dict) else None,
        "conditions": {k: v.get("pass") for k, v in (tg.get("conditions", {}) or {}).items()}
    } if isinstance(tg, dict) else None
    if not isinstance(tg, dict):
        facts["warnings"].append("trial_gate_status.json 缺失/异常")
    # 2. 自省历史（最近一次）
    al = _load_json(os.path.join(DATA_DIR, "audit_log.json"))
    if isinstance(al, dict) and al.get("history"):
        facts["sources"]["self_audit_latest"] = al["history"][-1]
    else:
        facts["warnings"].append("audit_log.json 无历史")
    # 3. 告警流水（近 20 条）
    alerts = _load_jsonl(os.path.join(DATA_DIR, "alert_log.jsonl"), tail=20)
    facts["sources"]["recent_alerts"] = alerts
    # 4. 老四自审最新报告
    laosi_dir = os.path.join(DATA_DIR, "laosi_audit")
    if os.path.isdir(laosi_dir):
        files = sorted([f for f in os.listdir(laosi_dir) if f.endswith(".json")])
        if files:
            latest = _load_json(os.path.join(laosi_dir, files[-1]))
            facts["sources"]["laosi_latest"] = {
                "file": files[-1],
                "summary": latest.get("summary") if isinstance(latest, dict) else None,
            }
    # 5. 持仓（只读快照，不写）
    hd = _load_json(os.path.join(DATA_DIR, "holdings.json"))
    if isinstance(hd, dict):
        facts["sources"]["holdings_snapshot"] = {
            "total_value": hd.get("total_value"),
            "cash": hd.get("cash"),
            "positions": [k for k in hd.keys() if k.startswith(("sh", "sz"))],
        }
    return facts
# ════════════════════════════════════════════════════════════════
# 阶段 2：归因（为什么）
# ════════════════════════════════════════════════════════════════
def stage_diagnose(facts: Dict[str, Any]) -> List[Dict[str, Any]]:
    """基于事实做规则化归因，产出"发现项"。"""
    findings: List[Dict[str, Any]] = []
    src = facts.get("sources", {})
    # 归因 A：三重门禁未全绿
    tg = src.get("trial_gate")
    if isinstance(tg, dict) and tg.get("mode") not in ("live_trial",):
        conds = tg.get("conditions", {}) or {}
        failed = [k for k, v in conds.items() if v is not True]
        findings.append({
            "id": "F-TRIAL-GATE",
            "severity": "P0",
            "title": "三重解冻条件未全绿，交易处于 dry_run",
            "evidence": f"mode={tg.get('mode')}; verdict={tg.get('verdict')}; 未通过={failed}",
            "root_cause": "条件 " + ",".join(failed) + " 未达标（数据/门禁/评审之一）",
        })
    # 归因 B：sanity gate 连续 SKIP（无新回测 → 策略未验证）
    sg = src.get("sanity_gate")
    if isinstance(sg, dict):
        if sg.get("status") == "FAIL":
            findings.append({
                "id": "F-SANITY-FAIL", "severity": "P0",
                "title": "回测合理性闸 FAIL",
                "evidence": f"gate_id={sg.get('gate_id')}, reason={sg.get('reason')}",
                "root_cause": "回测结果不满足合理性判据",
            })
        elif sg.get("consecutive_skips", 0) >= 3:
            findings.append({
                "id": "F-SANITY-STALE", "severity": "P1",
                "title": f"sanity gate 连续跳过 {sg.get('consecutive_skips')} 次（无新回测）",
                "evidence": f"reason={sg.get('reason')}",
                "root_cause": "回测结果文件长时间未更新，策略有效性未复验",
            })
    # 归因 C：门禁总体 fail
    gg = src.get("gate_status")
    if isinstance(gg, dict) and gg.get("status") == "fail":
        checks = gg.get("checks", {}) or {}
        failed_checks = [k for k, v in checks.items() if isinstance(v, dict) and not v.get("pass")]
        findings.append({
            "id": "F-GATE-FAIL", "severity": "P1",
            "title": "回测门禁整体 fail",
            "evidence": f"未通过项={failed_checks}; generated={gg.get('generated')}",
            "root_cause": "样本数/胜率/回撤等指标未达标",
        })
    # 归因 D：自省告警
    sa = src.get("self_audit_latest")
    if isinstance(sa, dict):
        alerts = sa.get("alerts", []) or []
        patterns = sa.get("error_patterns", []) or []
        hw = sa.get("holding_warnings", []) or []
        if alerts or patterns or hw:
            findings.append({
                "id": "F-SELF-AUDIT", "severity": "P1",
                "title": f"自省告警 {len(alerts)} 项 / 错误模式 {len(patterns)} 项 / 持仓风险 {len(hw)} 项",
                "evidence": f"alerts={[a.get('type') for a in alerts]}; patterns={[p.get('type') for p in patterns]}",
                "root_cause": "策略表现或持仓风险偏离预期",
            })
    # 归因 E：老五评审与门禁矛盾（假绿风险，呼应 self_audit_checkers C-1/C-2）
    rs = src.get("review_status")
    if isinstance(rs, dict):
        fv = rs.get("final_verdict")
        la = rs.get("laowu_approved")
        fv_fail = (fv is False) or (isinstance(fv, str) and fv.strip().upper() == "FAIL")
        if fv_fail and la is True:
            findings.append({
                "id": "F-FALSE-GREEN", "severity": "P0",
                "title": "假绿风险：final_verdict=FAIL 但 laowu_approved=True",
                "evidence": f"final_verdict={fv!r}, laowu_approved={la!r}",
                "root_cause": "评审旗标矛盾，消费方须走 review_gate 统一仲裁",
            })
    if not findings:
        findings.append({
            "id": "F-OK", "severity": "INFO",
            "title": "本轮复盘未发现异常",
            "evidence": "各上游状态正常",
            "root_cause": "-",
        })
    return findings
# ════════════════════════════════════════════════════════════════
# 阶段 3：提案（改什么）
# ════════════════════════════════════════════════════════════════
# 归因 → 提案 映射（规则化，可扩展）
_PROPOSAL_MAP = {
    "F-TRIAL-GATE": {
        "action": "核对未通过条件（数据对齐/门禁/评审），修复后重跑 sync_trial_gate",
        "verify": "python -c \"import sys;sys.path.insert(0,'scripts');import sync_trial_gate;print(sync_trial_gate.check_trial_gate())\"",
        "owner": "总管",
    },
    "F-SANITY-FAIL": {
        "action": "检查回测结果合理性，修复后重跑 sanity gate",
        "verify": "python backtest/check_backtest_sanity.py",
        "owner": "老三",
    },
    "F-SANITY-STALE": {
        "action": "触发一次新回测以刷新 sanity gate（避免长期 SKIP 掩盖策略失效）",
        "verify": "python backtest/backtest_rotation.py  # 或既定回测入口",
        "owner": "老三",
    },
    "F-GATE-FAIL": {
        "action": "针对未通过指标（样本数/胜率/回撤）做参数或因子迭代",
        "verify": "python update_gate_status.py && cat data/gate_status.json",
        "owner": "老三",
    },
    "F-SELF-AUDIT": {
        "action": "复盘自省告警的错误模式，定位评分/策略偏差",
        "verify": "python self_audit.py --report",
        "owner": "老四",
    },
    "F-FALSE-GREEN": {
        "action": "立即核查评审旗标矛盾，统一走 review_gate 仲裁",
        "verify": "python review_gate.py data/review_status.json",
        "owner": "老五",
    },
}
def stage_propose(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把发现项转成迭代提案。"""
    proposals = []
    for f in findings:
        if f["id"] == "F-OK":
            continue
        m = _PROPOSAL_MAP.get(f["id"], {})
        proposals.append({
            "proposal_id": f"P-{f['id']}-{_today()}",
            "from_finding": f["id"],
            "severity": f["severity"],
            "title": f["title"],
            "action": m.get("action", "待补充动作"),
            "verify": m.get("verify", "待补充验证方式"),
            "owner": m.get("owner", "待指派"),
            "evidence": f.get("evidence", ""),
            "status": "proposed",     # proposed → accepted → done → rejected
            "created_at": _now(),
            "linked_topic": None,     # 可挂接 research_hub 主题
        })
    return proposals
# ════════════════════════════════════════════════════════════════
# 阶段 4：登记（谁跟进）
# ════════════════════════════════════════════════════════════════
def stage_register(proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把提案合并进 proposals.json（按 proposal_id 去重）。"""
    reg = _load_json(PROPOSALS_PATH, enc="utf-8") or {
        "_schema_version": "1.0", "updated_at": _now(), "proposals": {}
    }
    if "proposals" not in reg:
        reg["proposals"] = {}
    added, updated = 0, 0
    for p in proposals:
        pid = p["proposal_id"]
        if pid in reg["proposals"]:
            # 保留人工更新的 status，只刷新证据
            old_status = reg["proposals"][pid].get("status", "proposed")
            p["status"] = old_status
            reg["proposals"][pid].update(p)
            updated += 1
        else:
            reg["proposals"][pid] = p
            added += 1
    reg["updated_at"] = _now()
    _save_json(PROPOSALS_PATH, reg)
    return {"added": added, "updated": updated, "total": len(reg["proposals"])}
# ════════════════════════════════════════════════════════════════
# 编排
# ════════════════════════════════════════════════════════════════
def run_once() -> Dict[str, Any]:
    print("=" * 72)
    print("🔁 复盘迭代主理人 — 执行中")
    print(f"   时间: {_now()}")
    print("=" * 72)
    # 1 复盘
    print("\n【阶段1】复盘：收集事实（只读）...")
    facts = stage_review()
    for w in facts.get("warnings", []):
        print(f"   ⚠️ {w}")
    print(f"   ✅ 已采集 {len([k for k,v in facts['sources'].items() if v])} 个数据源")
    # 2 归因
    print("\n【阶段2】归因：规则化诊断...")
    findings = stage_diagnose(facts)
    for f in findings:
        ic = {"P0": "🔴", "P1": "🟡", "P2": "🟢", "INFO": "ℹ️"}.get(f["severity"], "❓")
        print(f"   {ic} [{f['severity']}] {f['title']}")
    # 3 提案
    print("\n【阶段3】提案：生成迭代建议...")
    proposals = stage_propose(findings)
    for p in proposals:
        print(f"   📌 [{p['severity']}] {p['proposal_id']}")
        print(f"        动作: {p['action']}")
        print(f"        负责人: {p['owner']} | 验证: {p['verify'][:60]}")
    # 4 登记
    print("\n【阶段4】登记：写入提案登记表...")
    reg_stat = stage_register(proposals)
    print(f"   ✅ 新增 {reg_stat['added']} / 更新 {reg_stat['updated']} / 累计 {reg_stat['total']}")
    # 产物
    report = {
        "generated_at": _now(),
        "facts": facts,
        "findings": findings,
        "proposals": proposals,
        "register_stats": reg_stat,
    }
    rpath = os.path.join(OUT_DIR, f"review_{_today()}.json")
    _save_json(rpath, report)
    print(f"\n💾 复盘报告: {rpath}")
    print(f"💾 提案登记: {PROPOSALS_PATH}")
    # 人类可读
    md = _render_md(report)
    mpath = os.path.join(OUT_DIR, "latest.md")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"💾 可读报告: {mpath}")
    print("\n" + "=" * 72)
    p0 = len([f for f in findings if f["severity"] == "P0"])
    print(f"🔁 复盘完成：{len(findings)} 发现项（P0={p0}），{len(proposals)} 迭代提案")
    print("=" * 72)
    return report
def _render_md(report: Dict[str, Any]) -> str:
    lines = [
        "# 复盘迭代报告（Review & Iteration）",
        "",
        f"> 生成于 {report['generated_at']} ｜ 主理人：老四自审Agent（review_iterator.py）",
        "",
        "## 一、复盘事实",
        "",
    ]
    src = report["facts"].get("sources", {})
    for k, v in src.items():
        if v is None:
            lines.append(f"- **{k}**: （缺失）")
        elif isinstance(v, dict):
            lines.append(f"- **{k}**: `{json.dumps(v, ensure_ascii=False)[:200]}`")
        else:
            lines.append(f"- **{k}**: {v}")
    lines += ["", "## 二、归因发现", "",
              "| 严重度 | ID | 标题 | 证据 |", "|---|---|---|---|"]
    for f in report["findings"]:
        lines.append(f"| {f['severity']} | {f['id']} | {f['title']} | {f.get('evidence','')[:80]} |")
    lines += ["", "## 三、迭代提案", "",
              "| 严重度 | 提案ID | 动作 | 负责人 | 验证 | 状态 |",
              "|---|---|---|---|---|---|"]
    for p in report["proposals"]:
        lines.append(f"| {p['severity']} | {p['proposal_id']} | {p['action'][:40]} | "
                     f"{p['owner']} | `{p['verify'][:40]}` | {p['status']} |")
    lines += ["", "## 四、闭环说明", "",
              "```",
              "复盘(事实) → 归因(规则诊断) → 提案(动作+验证) → 登记(proposals.json) → 验证(重跑)",
              "```",
              "",
              "> 提案登记表：`data/review_iteration/proposals.json`（供总管/研究域消费）",
              "> 研究域对接：`python research_hub.py new <topic_id>` 把提案转成研究主题"]
    return "\n".join(lines)
def cmd_proposals() -> int:
    reg = _load_json(PROPOSALS_PATH, enc="utf-8")
    if not reg or not reg.get("proposals"):
        print("（提案登记表为空）先运行: python review_iterator.py run")
        return 0
    print("=" * 72)
    print(f"📌 迭代提案登记表（共 {len(reg['proposals'])} 条）")
    print("=" * 72)
    for pid, p in sorted(reg["proposals"].items()):
        ic = {"P0": "🔴", "P1": "🟡", "P2": "🟢"}.get(p.get("severity"), "❓")
        print(f"\n{ic} [{p.get('severity')}] {pid}  ({p.get('status')})")
        print(f"   标题: {p.get('title')}")
        print(f"   动作: {p.get('action')}")
        print(f"   负责人: {p.get('owner')} | 验证: {p.get('verify')}")
    return 0
def main() -> int:
    ap = argparse.ArgumentParser(description="复盘迭代主理人")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="执行一次复盘迭代")
    p_run.add_argument("--json", action="store_true")
    sub.add_parser("proposals", help="查看提案登记表")
    args = ap.parse_args()
    if args.cmd == "run":
        rep = run_once()
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "proposals":
        return cmd_proposals()
    return 0
if __name__ == "__main__":
    sys.exit(main())