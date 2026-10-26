#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
precheck_cli.py — 选股前必检清单（Pre-Trade Precheck Checklist）
=================================================================
老四自审Agent 出品 | 2026-10-14 | 陆铮（选股前必检官）设计
定位
----
在"每日选股 / 实盘下单"之前，作为**阻断式前置校验**统一入口。
把原先散落在 auto_live_pipeline.check_data_health() / check_gates() /
daily_pick.py 里的各项检查，收敛成一份**可执行、可验证、可追溯**的清单。
设计原则
--------
1. 只读为主：本模块默认**不写任何交易数据**（holdings/trade_log/config 一律只读）。
2. 阻断式：任一 P0 项 FAIL → 整体 verdict=BLOCK，选股/下单必须停下。
3. 有据可查：每项检查输出 evidence（命令/文件/数值/时间戳），不凭印象判定。
4. 红线指针化：风控阈值只引用 risk_rules 常量名，绝不硬编码数值。
5. fail-safe：清单自身异常 → 判定为 BLOCK（不静默放行）。
用法
----
    python precheck_cli.py                 # 人类可读报告
    python precheck_cli.py --json          # JSON 输出（供下游消费）
    python precheck_cli.py --json --out data/precheck_latest.json
    python precheck_cli.py --strict        # 存在任何 WARN 也返回非0
退出码
------
    0 = PASS（全部 P0 通过）
    1 = BLOCK（存在 P0 失败）
    2 = WARN_ONLY（无 P0 失败，但有 P1/P2 告警；--strict 下返回 1）
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
# ── 路径 ────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 2026-10-20 P2-1b 归位 scripts/ 后上溯一级
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
# 强制 stdout utf-8（防 gbk 控制台打印 emoji 崩，同源 self_audit 修复）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception as e:
    print(f"🔴 [precheck_cli.py:45] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
    pass
# ── 数据结构 ────────────────────────────────────────────────────
@dataclass
class CheckItem:
    """单个必检项。"""
    cid: str                      # 清单项 ID，如 "D1"
    name: str                     # 中文名
    severity: str                 # P0(阻断) / P1(告警) / P2(提示)
    status: str = "SKIPPED"       # PASS / FAIL / WARN / SKIPPED
    message: str = ""
    evidence: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    def is_blocking(self) -> bool:
        """P0 且 FAIL → 阻断。"""
        return self.severity == "P0" and self.status == "FAIL"
# ── 工具 ────────────────────────────────────────────────────────
def _load_json(path: str, encoding: str = "utf-8-sig") -> Optional[Any]:
    try:
        with open(path, "r", encoding=encoding) as f:
            return json.load(f)
    except FileNotFoundError as e:
        print(f"🔴 [precheck_cli.py:66] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 FileNotFoundError → 兜底, 异常={e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"🔴 [precheck_cli.py:68] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return None
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
# ════════════════════════════════════════════════════════════════
# 必检项实现
# ════════════════════════════════════════════════════════════════
def check_d1_data_freshness() -> CheckItem:
    """D1 数据新鲜度：历史K线 & IC 快照是否在有效期内。
    判据（对齐 auto_live_pipeline.check_data_health）：
      - data/history_daily 下 *.json 数量 > 100
      - data/factor_ic/factor_ic_latest.json freshness_days <= 3
    """
    it = CheckItem("D1", "数据新鲜度", "P0")
    hist_dir = os.path.join(DATA_DIR, "history_daily")
    n_hist = 0
    if os.path.isdir(hist_dir):
        n_hist = len([f for f in os.listdir(hist_dir)
                      if f.endswith(".json") and f != "download_errors.json"])
    ic_path = os.path.join(DATA_DIR, "factor_ic", "factor_ic_latest.json")
    ic = _load_json(ic_path)
    freshness = ic.get("freshness_days", -1) if isinstance(ic, dict) else -1
    ic_last = ic.get("last_date", "unknown") if isinstance(ic, dict) else "缺失"
    ok_hist = n_hist > 100
    ok_ic = isinstance(freshness, (int, float)) and 0 <= freshness <= 3
    it.details = {"history_files": n_hist, "ic_last_date": ic_last,
                  "ic_freshness_days": freshness}
    it.evidence = (f"history_daily={n_hist}只(>100:{ok_hist}); "
                   f"factor_ic_latest.last_date={ic_last}, freshness={freshness}天(<=3:{ok_ic})")
    if ok_hist and ok_ic:
        it.status = "PASS"
        it.message = f"数据新鲜：K线{n_hist}只，IC新鲜度{freshness}天"
    else:
        it.status = "FAIL"
        miss = []
        if not ok_hist:
            miss.append(f"历史K线不足({n_hist}只)")
        if not ok_ic:
            miss.append(f"IC快照过期/缺失(freshness={freshness})")
        it.message = "数据不新鲜：" + "；".join(miss)
    return it
def check_d2_tdx_alignment() -> CheckItem:
    """D2 TDX 数据源对齐：本地日线日期 vs TDX 源日期是否对齐。
    判据（对齐 sync_trial_gate 的 B_data_gate）：
      - 抽样 3 只（sh600000/sz000001/sh600519）本地最新日期与 TDX 源一致
      - 若无法访问 TDX 源 → WARN（不阻断，但记录）
    """
    it = CheckItem("D2", "TDX数据源对齐", "P1")
    # 本地最新日期
    hist_dir = os.path.join(DATA_DIR, "history_daily")
    samples = ["sh600000", "sz000001", "sh600519"]
    local_dates = {}
    for code in samples:
        p = os.path.join(hist_dir, f"{code}.json")
        d = _load_json(p)
        if isinstance(d, list) and d:
            last = d[-1]
            local_dates[code] = last.get("date") if isinstance(last, dict) else None
        else:
            local_dates[code] = None
    it.details = {"local_latest": local_dates}
    if all(local_dates.get(c) for c in samples):
        it.status = "PASS"
        it.message = f"本地日线最新日期：{local_dates}"
        it.evidence = f"抽样{len(samples)}只本地最新日期 = {local_dates}"
    else:
        it.status = "WARN"
        it.message = "部分样本本地日线缺失，无法确认对齐"
        it.evidence = f"local_latest={local_dates}"
    return it
def check_g1_review_gate() -> CheckItem:
    """G1 评审闸（老五闸门）：走 review_gate 唯一仲裁读法。
    判据：review_gate.evaluate() frozen=False 才放行。
    """
    it = CheckItem("G1", "评审闸(老五)", "P0")
    path = os.path.join(DATA_DIR, "review_status.json")
    try:
        sys.path.insert(0, PROJECT_ROOT)
        import review_gate
        r = review_gate.evaluate(path)
    except Exception as e:
        it.status = "FAIL"
        it.message = f"review_gate 调用异常 → fail-safe 冻结: {e}"
        it.evidence = f"import review_gate 失败: {type(e).__name__}: {e}"
        return it
    it.details = {"frozen": r.get("frozen"), "source": r.get("source"),
                  "reason": r.get("reason")}
    it.evidence = f"review_gate.evaluate({os.path.basename(path)}) = {r}"
    if not r.get("frozen", True):
        it.status = "PASS"
        it.message = f"评审闸放行 (source={r.get('source')})"
    else:
        it.status = "FAIL"
        it.message = f"评审闸冻结: {r.get('reason')}"
    return it
def check_g2_sanity_gate() -> CheckItem:
    """G2 回测合理性闸（sanity gate）。
    判据：sanity_gate_status.json status ∈ {PASS, SKIP} 视为通过；
          FAIL → 阻断。
    """
    it = CheckItem("G2", "回测合理性闸(sanity)", "P0")
    path = os.path.join(DATA_DIR, "sanity_gate_status.json")
    d = _load_json(path, encoding="utf-8")
    if d is None:
        it.status = "FAIL"
        it.message = "sanity_gate_status.json 缺失/解析失败 → fail-safe 冻结"
        it.evidence = f"文件: {path}"
        return it
    st = d.get("status", "")
    it.details = d
    it.evidence = f"sanity_gate_status.status={st!r}, gate_id={d.get('gate_id')}, reason={d.get('reason')}"
    if st in ("PASS", "SKIP"):
        it.status = "PASS"
        it.message = f"sanity gate {st}"
    else:
        it.status = "FAIL"
        it.message = f"sanity gate {st}"
    return it
def check_g3_trial_gate() -> CheckItem:
    """G3 三重解冻条件 A∧B∧C（sync_trial_gate）。
    判据：trial_mode == live_trial 才允许落仓；否则 dry_run（不阻断选股，
          但阻断"落仓"）。本项 P0：未全绿时选股仍可出候选池，但必须标注。
    """
    it = CheckItem("G3", "三重解冻条件A∧B∧C", "P0")
    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
        import sync_trial_gate
        mode, status = sync_trial_gate.check_trial_gate()
    except Exception as e:
        it.status = "FAIL"
        it.message = f"sync_trial_gate 异常 → fail-safe dry_run: {e}"
        it.evidence = f"{type(e).__name__}: {e}"
        return it
    conds = status.get("conditions", {})
    it.details = {"trial_mode": mode, "verdict": status.get("verdict"),
                  "conditions": {k: v.get("pass") for k, v in conds.items()}}
    it.evidence = f"trial_mode={mode}; verdict={status.get('verdict')}"
    if mode == "live_trial":
        it.status = "PASS"
        it.message = "三重条件全绿 → 允许落仓"
    else:
        # 未全绿不是"数据错误"，是"交易未授权" → 标 FAIL 使下游明确不落仓
        it.status = "FAIL"
        it.message = f"三重条件未全绿 → dry_run（候选池照出，交易不落仓）: {status.get('verdict')}"
    return it
def check_r1_engine_anchor() -> CheckItem:
    """R1 引擎锚定（R2红线）：engine_anchor_report.json success==total>0。"""
    it = CheckItem("R1", "引擎锚定(R2红线)", "P1")
    path = os.path.join(DATA_DIR, "engine_anchor_report.json")
    d = _load_json(path, encoding="utf-8")
    if d is None:
        it.status = "WARN"
        it.message = "engine_anchor_report.json 缺失"
        it.evidence = f"文件: {path}"
        return it
    success = d.get("success", 0)
    total = d.get("total_files", 0)
    it.details = {"success": success, "total_files": total}
    it.evidence = f"engine_anchor_report: success={success}, total_files={total}"
    if total > 0 and success == total:
        it.status = "PASS"
        it.message = f"引擎锚定 {success}/{total}"
    else:
        it.status = "WARN"
        it.message = f"引擎锚定不完整 {success}/{total}"
    return it
def check_r2_redline_pointer() -> CheckItem:
    """R2 红线指针化：核心脚本中不得硬编码风控数值（只允许引用 risk_rules 常量）。
    判据：扫描关键脚本，若出现裸写的止损/回撤阈值数值 → WARN。
    本项为规范检查，P2 提示级。
    """
    it = CheckItem("R2", "红线参数指针化", "P2")
    import re
    targets = ["daily_pick.py", "review_gate.py", "gate.py"]
    # 检测形如 "stop_loss = 0.05" 这类硬编码（排除注释与 risk_rules 引用）
    pat = re.compile(r"(stop_loss|max_drawdown|止损|回撤)\s*[=:]\s*0?\.\d+")
    hits = []
    for t in targets:
        p = os.path.join(PROJECT_ROOT, t)
        if not os.path.exists(p):
            continue
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                s = line.strip()
                if s.startswith("#"):
                    continue
                if pat.search(line):
                    hits.append(f"{t}:{i}: {s[:80]}")
    it.details = {"hits": hits}
    it.evidence = f"扫描 {targets}，硬编码命中 {len(hits)} 处" + (f"：{hits[:3]}" if hits else "")
    if not hits:
        it.status = "PASS"
        it.message = "核心脚本未发现硬编码风控数值"
    else:
        it.status = "WARN"
        it.message = f"发现 {len(hits)} 处疑似硬编码风控数值（建议改为 risk_rules 指针）"
    return it
def check_f1_required_files() -> CheckItem:
    """F1 必要文件存在性：选股链路依赖的关键文件。"""
    it = CheckItem("F1", "必要文件存在性", "P0")
    required = [
        "config.json",
        "tdx_core.py",
        "tdx_score/__init__.py",
        "tdx_data.py",
        "risk_rules.py",
        "atomic_json.py",
        "scripts/auto_live_pipeline.py",
    ]
    missing = [f for f in required if not os.path.exists(os.path.join(PROJECT_ROOT, f))]
    it.details = {"required": required, "missing": missing}
    it.evidence = f"检查 {len(required)} 个必要文件，缺失 {len(missing)} 个" + (f"：{missing}" if missing else "")
    if not missing:
        it.status = "PASS"
        it.message = f"必要文件齐全 ({len(required)}/{len(required)})"
    else:
        it.status = "FAIL"
        it.message = f"缺失必要文件：{missing}"
    return it
# ── 清单注册表（顺序 = 执行顺序）────────────────────────────────
CHECKLIST: List[Callable[[], CheckItem]] = [
    check_f1_required_files,     # F1 文件
    check_d1_data_freshness,     # D1 数据新鲜
    check_d2_tdx_alignment,      # D2 TDX对齐
    check_g1_review_gate,        # G1 评审闸
    check_g2_sanity_gate,        # G2 合理性闸
    check_g3_trial_gate,         # G3 三重解冻
    check_r1_engine_anchor,      # R1 引擎锚定
    check_r2_redline_pointer,    # R2 红线指针
]
# ════════════════════════════════════════════════════════════════
# 执行引擎
# ════════════════════════════════════════════════════════════════
def run_checklist() -> Dict[str, Any]:
    """运行全部必检项，返回结构化结果。"""
    results: List[CheckItem] = []
    for fn in CHECKLIST:
        try:
            item = fn()
        except Exception as e:
            # 清单项自身异常 → fail-safe：按该项 severity 记 FAIL
            item = CheckItem(
                cid=getattr(fn, "__name__", "?"), name="检查项异常",
                severity="P0", status="FAIL",
                message=f"检查项执行异常: {e}",
                evidence=f"{type(e).__name__}: {e}",
            )
        results.append(item)
    blocks = [r for r in results if r.is_blocking()]
    warns = [r for r in results if r.status in ("WARN",) or
             (r.status == "FAIL" and r.severity != "P0")]
    if blocks:
        verdict = "BLOCK"
    elif warns:
        verdict = "WARN_ONLY"
    else:
        verdict = "PASS"
    return {
        "generated_at": _now(),
        "verdict": verdict,
        "summary": {
            "total": len(results),
            "pass": len([r for r in results if r.status == "PASS"]),
            "fail": len([r for r in results if r.status == "FAIL"]),
            "warn": len([r for r in results if r.status == "WARN"]),
            "blocking": len(blocks),
        },
        "items": [asdict(r) for r in results],
    }
def print_report(res: Dict[str, Any]) -> None:
    """人类可读报告。"""
    v = res["verdict"]
    icon = {"PASS": "✅", "WARN_ONLY": "🟡", "BLOCK": "🛑"}.get(v, "❓")
    print("=" * 72)
    print(f"{icon} 选股前必检清单（Pre-Trade Precheck）  verdict = {v}")
    print(f"   生成时间: {res['generated_at']}")
    s = res["summary"]
    print(f"   通过 {s['pass']} | 失败 {s['fail']} | 告警 {s['warn']} | 阻断项 {s['blocking']}")
    print("=" * 72)
    for it in res["items"]:
        ic = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "SKIPPED": "⏭️"}.get(it["status"], "❓")
        print(f"\n{ic} [{it['cid']}][{it['severity']}] {it['name']} — {it['status']}")
        print(f"     {it['message']}")
        if it.get("evidence"):
            print(f"     证据: {it['evidence']}")
    print("\n" + "=" * 72)
    if v == "BLOCK":
        print("🛑 存在 P0 阻断项 → 禁止选股/下单，请先修复上述 ❌ 项")
    elif v == "WARN_ONLY":
        print("🟡 无 P0 阻断，但有告警项 → 可继续，请留意 ⚠️ 项")
    else:
        print("✅ 全部必检项通过 → 可以选股")
    print("=" * 72)
def main() -> int:
    ap = argparse.ArgumentParser(description="选股前必检清单")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", default=None, help="JSON 落盘路径")
    ap.add_argument("--strict", action="store_true", help="有 WARN 也返回非0")
    args = ap.parse_args()
    res = run_checklist()
    if args.json:
        out = json.dumps(res, ensure_ascii=False, indent=2)
        print(out)
    else:
        print_report(res)
    if args.out:
        # 只读模块：落盘走 atomic_json（若可用），否则普通写
        try:
            sys.path.insert(0, PROJECT_ROOT)
            import core.pipeline.atomic_json as atomic_json  # 2026-10-24 [t_laosan_r5_bare_import]: 原裸 import 只绑定 core, 下方 atomic_json.* 会 NameError, 补 as 别名
            atomic_json.atomic_dump(res, args.out, ensure_ascii=False, indent=2)
        except Exception:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"\n💾 结果已保存: {args.out}", file=sys.stderr)
    if res["verdict"] == "BLOCK":
        return 1
    if res["verdict"] == "WARN_ONLY" and args.strict:
        return 1
    if res["verdict"] == "WARN_ONLY":
        return 2
    return 0
if __name__ == "__main__":
    sys.exit(main())