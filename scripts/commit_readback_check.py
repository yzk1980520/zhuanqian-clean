#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""commit_readback_check.py — 闭环资产 commit 固化 read-back 断言 (P-B2, 自愈引擎 v1.0 件, 只读)
双向断言:
  P1: 应-track 的闭环 metadata/脚本/载体缺失或未 git 跟踪 (归档轮丢失风险, P1#3/P1#5 同根因)
  P0: 应-untrack 的 raw 交易数据被 git 跟踪 (25cf6b47 安全红线: 数据不出本机,
      AGNES key 泄露事故后的刻意政策) — 违反 = 红线事件
设计: 清单配置驱动, 与 .gitignore L98 `data/` 政策一致 — metadata 定向 -f 入库,
raw trading data 永远本地留存。
输出: {pass, p0, p1, detail} 与 carrier_check 同构; exit 0/1。
--selftest: 合成故障自检 (P-C2 对照组形态 b, 12/12 覆盖件): 5 例注入走同一
run_checks 核心, 验证断言非空转; 无 git 副作用、不写盘、不动主仓。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 应-track (闭环 metadata / 脚本 / 任务载体 / 台账 schema)
SHOULD_TRACK = [
    "data/factor_ic/factor_gate.json",
    "data/factor_ic/forward_prob_cards/sh600312.json",   # 老五组件3 600312 概率卡 (872aed76 R8 件核销, @laowu 裁定补清单 2026-10-24)
    "data/factor_ic/factor_ic_hybrid_20261024.json",     # C→A 混合卡 (3ab0ec2f, 晋升权威源后转快照件, @laowu 裁定补清单 2026-10-24)
    "data/factor_ic/zcheck_20261024.json",                # C→A 序列② z 检数据件 (4fd4a8e0 @laosan 件, @opencode 10/24 晚随行核销)
    "data/review_status.json",
    "data/jev_f2_ruling.json",
    "data/jev_p4_ruling.json",
    "data/jev_s310_ruling.json",
    "data/history_refresh.log",
    "data/holdings_sync.log",
    "data/known_gaps.json",  # R8: dev 通道写面 (GAP-005 台账)
    "data/stale_alive_21.json",  # R8: dev 通道写面 (21 件明细)
    "data/system/role_permissions.json",  # R8: dev 通道写面 (权限治理 metadata)
    "mainline/docs/selfheal/ledger_schema_v1.json",
    "scripts/carrier_check.py",
    "scripts/fixguard_check.py",
    "scripts/refdrift_check.py",
    "scripts/ic_blind_window_check.py",
    "scripts/config_drift_check.py",
    "scripts/risk_redline_check.py",
    "scripts/task_selfcheck.py",
    "scripts/refresh_extended_data.py",
    "scripts/sync_holdings.py",
    "scripts/Zhuanqian_HistoryRefresh.bat",
    "scripts/Zhuanqian_HoldingsSync.bat",
    "scripts/pr2_tencent_price_recipe.json",
    "scripts/pr2_tencent_price_refresh.py",
    "scripts/install_readback_hook.py",
    "dashboards/buy_signal_panel.py",          # 买入信号面板模块 (10/24 @user 扩围件)
    "data/board_signal_ledger.jsonl",          # 面板亮/灭翻转台账 (R8 台账模式, @老六 readback +1 件)
    "data/board_signal_ledger.state.json",     # 面板翻转 state 件 (运行时生成, @老三 挂账 P1 核销)
    "data/audit/sc005_orphan_ledger.json",     # SC-005 契约资产孤儿台账 (T054 A+C 判据改口径, laowu_countersigned, 2026-10-26)
    "scripts/selfheal_recipes.json",
    "scripts/ic_pollution_check.py",
    "scripts/numeric_conservation_check.py",
    "data/rulings/ic_strict_gate_ruling.json",
    "scripts/drill_gov_metadata_wipe.py",
    "tests/test_carrier_check.py",
    # R8 核销 (t_db07d09b, 老三): RESID_MOM 变体复测证据件 — 只读取证产物,
    # 非 raw 交易数据, 入 readback 清单防归档轮丢失
    "data/audit/aa_resid_mom_variant_scan_20261026.json",
    "data/audit/aa_resid_mom_variant_retest_t_db07d09b.md",
    "data/audit/aa_history_daily_rebuild_20261026.json",
]

# 必须-untrack (raw 交易数据, 25cf6b47 安全红线)
MUST_NOT_TRACK = [
    "data/holdings.json",
    "data/trade_log.json",
    "data/trade_log.jsonl",  # R8 dev 通道写面: raw 交易日志
    "data/daily_stock_selection.json",  # R8 dev 通道写面: 每日选股 raw 输出
    "data/real_holdings.json",  # 已退役本地派生路径 (sync_holdings L12), 更不该入库
]


def run_checks(tracked, exists, should_track=None, must_not_track=None):
    """核心断言 (可注入): tracked=已跟踪集, exists(rel)->bool。返回 (p0, p1, detail)。"""
    st = should_track if should_track is not None else SHOULD_TRACK
    mn = must_not_track if must_not_track is not None else MUST_NOT_TRACK
    p0, p1, detail = [], [], []
    for rel in st:
        if not exists(rel):
            p1.append(f"P1: 闭环资产缺失: {rel}")
        elif rel not in tracked:
            p1.append(f"P1: 闭环资产未 git 跟踪: {rel} (归档轮丢失风险)")
        else:
            detail.append({"file": rel, "status": "tracked"})
    for rel in mn:
        if rel in tracked:
            p0.append(f"P0: 安全红线: raw 交易数据 {rel} 被 git 跟踪 (25cf6b47 政策, 需 git rm --cached)")
        else:
            detail.append({"file": rel, "status": "untracked_ok"})
    return p0, p1, detail


def r8_check(root, tracked, log_text=None):
    """R8 不可信作者位登记 (台账 rules R8, @laoliu 07:0x 补充件):
    dev@zhuanqian.local 通道对 data/ 面的 commit 必须被 readback 清单 (SHOULD_TRACK)
    或 raw 豁免面 (MUST_NOT_TRACK/history_daily) 覆盖方可核销, 未覆盖=P1 待核销。
    返回 (p1, detail)。log_text 可注入 (selftest 合成故障, 零 git 副作用)。
    口径: SHOULD_TRACK=已核销 / MUST_NOT_TRACK+history_daily=raw 豁免 / HEAD 已删=归档注记 /
    其余在库=未覆盖 P1 (待 @laowu 裁定补清单)。"""
    injected = log_text is not None
    if not injected:
        out = subprocess.run(
            ["git", "log", "--author=dev@zhuanqian.local", "-n", "30",
             "--name-only", "--pretty=format:@@%H", "--", "data/"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        log_text = out.stdout
    if injected:  # 合成注入面: 无 HEAD 依赖 (archived 分支不触发, 注入面文件均按在库处理)
        head_files = None
    else:
        head_files = set(subprocess.run(
            ["git", "ls-tree", "-r", "HEAD", "--name-only"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout.splitlines())
    commits, p1, detail = {}, [], []
    for line in log_text.splitlines():
        if line.startswith("@@"):
            cur = line[2:]
            commits[cur] = []
        elif line.strip() and not line.startswith("@@"):
            commits.setdefault(cur, []).append(line.strip())
    for sha, files in commits.items():
        for f in files:
            if f in SHOULD_TRACK:
                detail.append({"commit": sha, "file": f, "status": "r8_covered_readback"})
            elif f in MUST_NOT_TRACK or f.startswith("data/history_daily/"):
                detail.append({"commit": sha, "file": f, "status": "r8_exempt_raw"})
            elif head_files is not None and f not in head_files and not (root / f).exists():
                detail.append({"commit": sha, "file": f, "status": "r8_archived_gone (HEAD 已删, 无需核销)"})
            else:
                p1.append(f"P1: R8 不可信作者位写面未覆盖: dev 通道 commit {sha[:8]} 触碰 {f} "
                          f"(未入 readback 清单, 待核销或 @laowu 裁定补清单)")
    return p1, detail


def main():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    tracked = set(filter(None, out.stdout.split("\0")))
    p0, p1, detail = run_checks(tracked, lambda rel: (ROOT / rel).exists())
    p1r8, d8 = r8_check(ROOT, tracked)
    p1.extend(p1r8)
    detail.extend(d8)
    result = {"pass": not p0 and not p1, "p0": p0, "p1": p1, "detail": detail,
              "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n[P-B2 read-back] 应track {len(SHOULD_TRACK)} / 红线 {len(MUST_NOT_TRACK)} | P0={len(p0)} P1={len(p1)}",
          file=sys.stderr)
    return 0 if result["pass"] else 1


def selftest():
    """P-C2 对照组形态 b: 5 例合成故障注入, 断言命中即 pass。零 git 副作用。"""
    T = set(SHOULD_TRACK)
    all_exist = lambda rel: True
    cases = [
        ("A 健康基线: 全在库无红线", T, all_exist, 0, 0),
        ("B 红线: holdings 被跟踪", T | {"data/holdings.json"}, all_exist, 1, 0),
        ("C 断链: 载体未入库", T - {"scripts/Zhuanqian_HistoryRefresh.bat"}, all_exist, 0, 1),
        ("D 缺失: 资产文件不在", T, lambda rel: rel != "data/review_status.json", 0, 1),
        ("E 复合: 红线+断链+缺失", (T - {"scripts/selfheal_recipes.json"}) | {"data/trade_log.json"},
         lambda rel: rel != "data/jev_f2_ruling.json", 1, 2),
        ("F R8: dev 通道未覆盖写面", None, all_exist, 0, 1),
    ]
    fails = 0
    for name, tracked, exists, exp_p0, exp_p1 in cases:
        if tracked is None:  # R8 注入例: dev 通道 commit 触碰未入清单的 data/ 文件
            fake_log = "@@f001\n" + "data/rulings/ic_strict_gate_ruling.json\n" + "data/uncovered_new.json\n"
            p1r8, _d = r8_check(ROOT, set(), log_text=fake_log)
            p0, p1 = [], p1r8
        else:
            p0, p1, _ = run_checks(tracked, exists)
        ok = len(p0) == exp_p0 and len(p1) == exp_p1
        fails += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: P0={len(p0)}/{exp_p0} P1={len(p1)}/{exp_p1}")
    print(f"[selftest] {len(cases) - fails}/{len(cases)} 合成故障命中", file=sys.stderr)
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
