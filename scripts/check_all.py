#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_all.py — 单一权威门禁入口（D-7 P2①；2026-10-18 老三补全脚本映射版；2026-10-20 剔除已隔离幽灵映射后 51 个；2026-10-21 接入 O-3 数据不出本机红线守卫后 52 个；2026-10-21 再接入 4 个孤立行为级守卫后 56 个；2026-10-21 任务契约审计(规则14)接入 dispatch 域后 57 个）

用法:
  python scripts/check_all.py <subcommand>
  python scripts/check_all.py all

子命令（12 域；逐条映射表见 docs/D7-P2-三方纪要-20261017.md §六。20261023 P1#2 裁定后: 归档轮断链33处 → 除名30/改路径1/恢复3, 映射 57→28；20261023夜 自愈引擎 P-B1: +carriers (28→29)；20261024 P-C1/P-C3: +fixguard/refdrift (29→31)；20261024夜 P-F/P-R/P-T 集成批: +ic/config/redline/selfcheck (31→35)）:
  data-quality   4 脚本（自动执行 3: data_flow_checker / data_quality_checker / factor_health_check）
  backtest-gate  5 脚本（自动执行 2: gate_check / walk_forward_gate）
  contract       8 脚本（自动执行 3: check_protocol_mount / pre_pick_gate / verify_config
                 + 5 个 pytest 守卫: test_no_remote_egress / test_factor_weights_loud_fail /
                 test_trading_hours_fail_close / test_suppress_priority_layering / test_factor_gate_blocking）
  health         6 脚本（自动执行 2: chain_health_check / final_health_check）
  dispatch       5 脚本（自动执行 3: dispatch_audit_check / drain_meta_check / check_task_contract）
  carriers       1 脚本（自动执行 1: carrier_check — P-B1 计划任务载体断言, 只读）
  fixguard       1 脚本（自动执行 1: fixguard_check — P-C1 未固化修复守卫, 只读）
  refdrift       1 脚本（自动执行 1: refdrift_check — P-C3 分支/ref 漂移自检, 只读本地 ref 无网络）
  repair_class   1 脚本（自动执行 1: repair_class_check — P-C4 repair_class 四态标注审计, 只读注册表）
  ic             1 脚本（自动执行 1: ic_blind_window_check — P-F2 IC 监控盲窗断言, 只读）
  config         1 脚本（自动执行 1: config_drift_check — P-F3 三方会签 config 漂移守卫, 只读）
  redline        1 脚本（自动执行 1: risk_redline_check — P-R1 红线状态一致性三查, 只读）
  selfcheck      1 脚本（自动执行 1: task_selfcheck — P-T1 连接层任务自检, 只读）
  readback       1 脚本（自动执行 1: commit_readback_check — P-B2 闭环资产固化 read-back + raw 数据红线负断言, 只读）
  ic_pollution   1 脚本（自动执行 1: ic_pollution_check — P-F1 IC 权威源污染检测, quarantine 只告警不修, 只读）
  numeric_conservation 1 脚本（自动执行 1: numeric_conservation_check — P-F4 回测结论数字守恒三要素校验, 只读）
  control_gate   1 脚本（自动执行 1: control_gate_check — P-C2 对照组门禁: 自愈断言件对照组证据覆盖审计, 缺对照组=P1 auto-clear 拦截, 只读）
  all            顺序跑上述全部，输出统一 JSON 结果到 stdout

设计原则:
  - 不修改门禁阈值（K45 D1-D6 口径冻结），check_all.py 是调用入口，不重实现门禁逻辑
  - 旧脚本保留（cron 兼容），仅加 DEPRECATED 头注释
  - 20 个自动执行脚本实际调用，各自 exit code 原样入 JSON（0=PASS，非 0=FAIL，口径随旧脚本）
  - 37 个 list-only 脚本只登记映射（一次性验证/副作用/死循环监控/参数依赖/网络依赖等，
    理由逐条见 LIST_ONLY_NOTES + 纪要 §六映射表）：executed=false / status=NOT_RUN，
    **不算通过也不算失败**，不参与域 pass 判定（2026-10-21 修正：旧实现给 list-only 记
    pass:true 混进汇总，duration_s=0 的"没跑项"被当成绿，属假绿）
  - 结果 JSON schema: {"subcmd": ..., "pass": bool, "details": [...], "summary": {...}, "exit": int}
    每条 details 含 status ∈ {PASS, FAIL, NOT_RUN, ERROR}；status 是唯一权威口径，
    pass 字段仅对 executed=true 的项有意义（NOT_RUN 项 pass=null，不是 true）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_TIMEOUT_S = 120

# ---------------------------------------------------------------------------
# 子命令 → 旧脚本映射（收编关系，51 个，按 5 域归类）
# ---------------------------------------------------------------------------
SUBCOMMANDS: dict[str, list[str]] = {
    "data-quality": [
        "scripts/data_flow_checker.py",
        "scripts/data_quality_checker.py",
        "scripts/factor_health_check.py",
        "scripts/audit_delisted_coverage.py",
    ],
    "backtest-gate": [
        "scripts/gate_check.py",
        "scripts/walk_forward_gate.py",
        "scripts/check_backtest_result_fresh.py",
        "scripts/update_gate_index.py",
        "scripts/sync_trial_gate.py",
    ],
    "contract": [
        "scripts/check_protocol_mount.py",
        "scripts/pre_pick_gate.py",
        "scripts/verify_config.py",
        "tests/test_no_remote_egress.py",
        "tests/test_factor_weights_loud_fail.py",
        "tests/test_trading_hours_fail_close.py",
        "tests/test_suppress_priority_layering.py",
        "tests/test_factor_gate_blocking.py",
    ],
    "health": [
        "scripts/chain_health_check.py",
        "scripts/final_health_check.py",
        "scripts/fallback_health_check.py",
        "scripts/system_audit_checker.py",
        "scripts/check_remote_main_freshness.py",
        "self_heal_check.py",
    ],
    "dispatch": [
        "scripts/dispatch_audit_check.py",
        "scripts/drain_meta_check.py",
        "scripts/check_task_contract.py",
        "scripts/laosi_audit.py",
        "scripts/aoci_daily_check.py",
    ],
    "carriers": [
        "scripts/carrier_check.py",
    ],
    # 20261024 自愈引擎 v1.0 老三认领件 (P-C1/P-C3 只读断言版, 10/24 落地提前于批次):
    # 输出与 carrier_check 同构 JSON {pass,p0,p1,detail}, 老六台账 schema 直接消费
    "fixguard": [
        "scripts/fixguard_check.py",
    ],
    "refdrift": [
        "scripts/refdrift_check.py",
    ],
    "ic": [
        "scripts/ic_blind_window_check.py",
    ],
    "config": [
        "scripts/config_drift_check.py",
    ],
    "redline": [
        "scripts/risk_redline_check.py",
    ],
    "selfcheck": [
        "scripts/task_selfcheck.py",
    ],
    "readback": [
        "scripts/commit_readback_check.py",
    ],
    "ic_pollution": [
        "scripts/ic_pollution_check.py",
    ],
    "numeric_conservation": [
        "scripts/numeric_conservation_check.py",
    ],
    # 20261024 P-C4 老三件 (d9477868 破圈虚报后真实落地): repair_class 四态标注审计
    # (对 P-B4 注册表只读), 机器化防洗白总则: 非fixable件enabled=true=P0, 开闸件缺见证=P1
    "repair_class": [
        "scripts/repair_class_check.py",
    ],
    # 20261024 P-C2 老三件 (对照组门禁总则机器件): 自愈断言件入自动清账前必须挂
    # 对照组证据(测试件在库≥2用例 或 --selftest 合成故障), 缺证据=P1 auto-clear 拦截, 只读
    "control_gate": [
        "scripts/control_gate_check.py",
    ],
}

# 自动执行集（20 个）：check_all 实际 subprocess 调用并参与 pass/fail 判定。
# 键=脚本相对路径，值=超时秒数。依据 2026-10-18 冒烟实测（.venv, PYTHONPATH 已清）:
#   factor_health_check 196s / dispatch_audit_check 104s → 300s 留余量。
AUTO_RUN: dict[str, int] = {
    "scripts/data_flow_checker.py": DEFAULT_TIMEOUT_S,
    "scripts/data_quality_checker.py": DEFAULT_TIMEOUT_S,
    "scripts/factor_health_check.py": 300,
    "scripts/gate_check.py": DEFAULT_TIMEOUT_S,
    "scripts/walk_forward_gate.py": DEFAULT_TIMEOUT_S,
    "scripts/check_protocol_mount.py": DEFAULT_TIMEOUT_S,
    "scripts/pre_pick_gate.py": DEFAULT_TIMEOUT_S,
    "scripts/verify_config.py": DEFAULT_TIMEOUT_S,
    # P-B1 载体存在性断言（2026-10-23 自愈引擎 v1.0 件）: 计划任务 State/bat 入库/脚本存活/写侧新鲜度
    "scripts/carrier_check.py": 180,
    # 20261024 P-C1/P-C3 老三件 (自愈引擎 v1.0): 未固化修复守卫 + ref 漂移自检, 纯 git 只读, 120s 内
    "scripts/fixguard_check.py": 120,
    "scripts/refdrift_check.py": 120,
    # 20261024夜 P-F/P-R/P-T 件 (自愈引擎 v1.0, @opencode 集成批次): IC 盲窗/会签漂移/风控红线/连接层任务自检, 只读断言
    "scripts/ic_blind_window_check.py": 120,
    "scripts/config_drift_check.py": 120,
    "scripts/risk_redline_check.py": 120,
    "scripts/task_selfcheck.py": 180,
    # 20261024夜 P-B2 (自愈引擎 v1.0): 闭环资产 commit 固化 read-back + raw 交易数据红线负断言, 纯 git 只读
    "scripts/commit_readback_check.py": 60,
    # 20261024夜 P-F1/P-F4 老五件 (自愈引擎 v1.0): IC 污染检测(quarantine 只告警) + 回测数字守恒三要素, 纯 JSON 只读
    "scripts/ic_pollution_check.py": 60,
    "scripts/numeric_conservation_check.py": 60,
    # 20261024 P-C4 老三件: repair_class 四态标注审计, 纯读注册表 JSON, 60s 内
    "scripts/repair_class_check.py": 60,
    # 20261024 P-C2 老三件: 对照组门禁 (自愈断言件对照组覆盖审计, 纯文件系统只读, 60s 内)
    "scripts/control_gate_check.py": 60,
    # O-3 数据不出本机红线守卫（2026-10-21 接入）：曾红 16 小时无人发现，
    # 因不在任何必跑门禁里；pytest 用例经 _run_script 的 -m pytest 分支驱动
    "tests/test_no_remote_egress.py": DEFAULT_TIMEOUT_S,
    # 以下 4 个行为级守卫（2026-10-21 接入）此前是"孤立守卫"：既不在 check_all
    # AUTO_RUN，也不在回归套件 .agent/regression/__init__.py，不在任何 bat/xml/yml
    # 定时任务里，只能人工手动 pytest 才跑。同 O-3 教训，一并接进必跑门禁。
    "tests/test_factor_weights_loud_fail.py": DEFAULT_TIMEOUT_S,
    "tests/test_trading_hours_fail_close.py": DEFAULT_TIMEOUT_S,
    "tests/test_suppress_priority_layering.py": DEFAULT_TIMEOUT_S,
    "tests/test_factor_gate_blocking.py": DEFAULT_TIMEOUT_S,
    "scripts/chain_health_check.py": DEFAULT_TIMEOUT_S,
    "scripts/final_health_check.py": DEFAULT_TIMEOUT_S,
    "scripts/dispatch_audit_check.py": 300,
    "scripts/drain_meta_check.py": DEFAULT_TIMEOUT_S,
    # 规则14 任务契约审计（t_330700bd 2026-10-21 老四接入，先例 dispatch_audit_check 同 300s 预算）：
    # 只读 sqlite(mode=ro) 开 kanban.db，窗口内缺契约块 → exit 1；无参数运行=仅审计+写快照
    # （data/logs/），不入队 message_queue（--alert 出口归 09:30 QSP_TaskContractCheck 独占）
    "scripts/check_task_contract.py": 300,
}

# list-only（10 个）：只登记映射 + DEPRECATED 注释，check_all 不执行。
# P1裁定(20261023, 老三, P1#2 21件断链→实测33处): 10/23 S5-ops归档轮后, 清单引用脚本全部失实。
# 引用扫描裁定: 30 件一次性验证/已被等价件取代者 → 除名(等价覆盖: backtest/check_backtest_sanity.py +
# gate_check.py + system_audit_checker.py + core/ops/health_check.py + sync_trial_gate 132d链);
# self_heal_check.py 实物在仓库根(self_heal_task.cmd 专用, 92f96864) → 更正登记路径;
# data-quality 自动执行三件(data_flow_checker/data_quality_checker/factor_health_check)已从
# archive/scripts-20261023 恢复入库(sha256 逐件核对, 77d90332"真冗余"判定对 check_all 硬依赖误伤)。
LIST_ONLY_NOTES: dict[str, str] = {
    # data-quality (1)
    "scripts/audit_delisted_coverage.py": "退市股覆盖审计（132d 作业链经 bat 执行，cron 引用，QSP 任务优先）",
    # backtest-gate (3)
    "scripts/check_backtest_result_fresh.py": "需 --since 参数（bat 链传本轮回测开始时刻；入口无上下文，避免改口径）",
    "scripts/update_gate_index.py": "环境门指数数据补全工具（写 daily_signal.json；cron 引用，QSP 任务优先）",
    "scripts/sync_trial_gate.py": "三重解冻条件 A∧B∧C 门禁（cron 巡检统一入口，QSP 任务优先）",
    # health (4)
    "scripts/fallback_health_check.py": "fallback 端点可达性探测（网络 + P1 告警写 alert_log.jsonl 副作用）",
    "scripts/system_audit_checker.py": "回归触发工具（subprocess 跑 pytest，重；cron 承接）",
    "scripts/check_remote_main_freshness.py": "git ls-remote 网络操作（老六 cron 承接）",
    "self_heal_check.py": "主动自愈引擎（仓库根实物, self_heal_task.cmd 专用; 探测→修复动作副作用，门禁入口禁止）",
    # dispatch (2)
    "scripts/laosi_audit.py": "老四每日巡检（飞书 P0/P1 告警副作用，每日 20:00 cron 执行）",
    "scripts/aoci_daily_check.py": "AOCI 每日检查（飞书通知副作用，cron 承接）",
}

# 自检：全部映射必须被完整覆盖（20261024夜 P-B2 read-back 入列后 = 26 自动 + 10 list-only = 36），一个不多一个不少
# 20261023夜 P-B1 carriers 件入列: carrier_check.py 计入 AUTO_RUN
# 20261024 P-C1/P-C3 老三件入列: fixguard_check.py + refdrift_check.py 计入 AUTO_RUN
_ALL_MAPPED: list[str] = [s for lst in SUBCOMMANDS.values() for s in lst]
assert len(_ALL_MAPPED) == 40, f"SUBCOMMANDS 应含 40 个映射，实际 {len(_ALL_MAPPED)}"
assert len(set(_ALL_MAPPED)) == 40, "SUBCOMMANDS 出现重复条目"
assert set(AUTO_RUN) | set(LIST_ONLY_NOTES) == set(_ALL_MAPPED), "AUTO_RUN + LIST_ONLY 未完整覆盖 40 映射"
assert not (set(AUTO_RUN) & set(LIST_ONLY_NOTES)), "同一脚本不可既自动执行又 list-only"


def _project_root() -> str:
    """项目根目录（从 scripts/ 向上一级）。"""
    return str(Path(__file__).resolve().parent.parent)


def _run_script(script_rel: str, root: str) -> dict:
    """Run or record a single gate script, return result dict."""
    script_path = os.path.join(root, script_rel)
    exists = os.path.isfile(script_path)
    if not exists:
        return {"script": script_rel,
                "mode": "auto" if script_rel in AUTO_RUN else "list-only",
                "executed": False, "pass": False, "exit": None, "status": "ERROR",
                "error": f"script not found: {script_rel}", "duration_s": 0.0}
    if script_rel not in AUTO_RUN:
        # list-only：只登记映射（保留 cron 兼容），不执行 ⇒ NOT_RUN。
        # ⛔ 2026-10-21：这里曾写 pass=True，导致"根本没跑（duration_s=0）"的项被算进
        #    通过数、给域贡献绿。没跑就是没跑，pass 只能是 None（未判定），不是 True。
        return {"script": script_rel, "mode": "list-only", "executed": False,
                "pass": None, "status": "NOT_RUN", "exit": None, "error": None,
                "note": LIST_ONLY_NOTES.get(script_rel, "未列入自动执行集"),
                "duration_s": 0.0}
    timeout = AUTO_RUN[script_rel]
    t0 = time.monotonic()
    result = {"script": script_rel, "mode": "auto", "executed": True,
              "pass": False, "status": "ERROR", "exit": -1, "error": None,
              "duration_s": 0.0}
    try:
        # pytest 用例（tests/test_*.py）必须经 -m pytest 驱动：直接 python <文件>
        # 只会定义测试类、不执行任何用例，exit 0 即假绿——红线守卫绝不能这样接入。
        # 同时显式 PYTHONPATH=项目根：用例内含 import supabase_data，缺了收集阶段就报错。
        norm = script_rel.replace("\\", "/")
        if norm.startswith("tests/") and os.path.basename(norm).startswith("test_") \
                and norm.endswith(".py"):
            env = dict(os.environ)
            env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
            cmd = [sys.executable, "-m", "pytest", script_rel,
                   "-q", "--no-header", "-p", "no:cacheprovider"]
        else:
            env = None
            cmd = [sys.executable, script_path]
        _flags = 0
        if os.name == "nt":
            _flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            creationflags=_flags,
        )
        result["exit"] = proc.returncode
        result["pass"] = proc.returncode == 0
        result["status"] = "PASS" if proc.returncode == 0 else "FAIL"
        if proc.stderr and not result["pass"]:
            result["error"] = proc.stderr.strip()[:500]
    except subprocess.TimeoutExpired:
        result["error"] = f"timeout after {timeout}s"
    except Exception as exc:
        result["error"] = str(exc)
    result["duration_s"] = round(time.monotonic() - t0, 2)
    return result


def _summarize(details: list) -> dict:
    """按 status 汇总明细。NOT_RUN（list-only 未执行项）单独计数，
    既不计入 passed 也不计入 failed —— 没跑的项不许给域贡献绿。"""
    s = {"total": len(details), "executed": 0, "passed": 0,
         "failed": 0, "not_run": 0, "error": 0}
    for d in details:
        st = d.get("status")
        if st == "NOT_RUN":
            s["not_run"] += 1
        elif st == "PASS":
            s["passed"] += 1
        elif st == "ERROR":
            s["error"] += 1
        else:  # FAIL / 未知 ⇒ 一律按失败算（fail-close）
            s["failed"] += 1
    s["executed"] = s["total"] - s["not_run"]
    # 域 pass 只看真跑过的项：list-only 未执行 ≠ 通过；
    # 一条都没跑 ⇒ 零证据，同样不许报绿（fail-close）
    s["pass"] = (s["failed"] == 0 and s["error"] == 0 and s["executed"] > 0)
    return s


SUMMARY_NUM_KEYS = ("total", "executed", "passed", "failed", "not_run", "error")


def run_subcommand(subcmd: str, root: str) -> dict:
    """Run auto scripts in a subcommand (list-only entries recorded), return aggregated result."""
    scripts = SUBCOMMANDS.get(subcmd, [])
    if not scripts:
        return {"subcmd": subcmd, "pass": False, "details": [], "exit": 1,
                "summary": _summarize([]),
                "error": f"unknown subcommand: {subcmd}"}
    details = []
    for script_rel in scripts:
        details.append(_run_script(script_rel, root))
    summary = _summarize(details)
    return {"subcmd": subcmd, "pass": summary["pass"], "details": details,
            "summary": summary, "exit": 0 if summary["pass"] else 1}


def run_all(root: str) -> dict:
    """Run all subcommands sequentially."""
    results = []
    for subcmd in SUBCOMMANDS:
        results.append(run_subcommand(subcmd, root))
    all_pass = all(r["pass"] for r in results)
    agg = {"total": 0, "executed": 0, "passed": 0, "failed": 0, "not_run": 0, "error": 0}
    for r in results:
        for k in SUMMARY_NUM_KEYS:
            agg[k] += r["summary"].get(k, 0)
    agg["pass"] = all_pass
    return {"all": True, "pass": all_pass, "results": results,
            "summary": agg, "exit": 0 if all_pass else 1}


def main():
    root = _project_root()
    args = sys.argv[1:]
    if not args or args[0] in ("help", "--help", "-h"):
        print(__doc__)
        print("Available subcommands:", ", ".join(SUBCOMMANDS.keys()))
        sys.exit(0)

    subcmd = args[0]
    if subcmd == "all":
        result = run_all(root)
    elif subcmd in SUBCOMMANDS:
        result = run_subcommand(subcmd, root)
    else:
        print(f"error: unknown subcommand '{subcmd}'", file=sys.stderr)
        print("Available:", ", ".join(SUBCOMMANDS.keys()), file=sys.stderr)
        sys.exit(1)

    # 统一 JSON 输出到 stdout（Drain 消费侧读 JSON）
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(result.get("exit", 1))


if __name__ == "__main__":
    main()
