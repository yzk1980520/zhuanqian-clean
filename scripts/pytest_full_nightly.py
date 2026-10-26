#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pytest_full_nightly.py — 夜间全量 pytest 档（薄驱动）
=====================================================
P3 2026-10-26 (t_81fad29b)：pytest 门禁快档落地件。

背景（docs/pytest_timeout_investigation_20261025.md §5.1/§5.2）：
- 门禁快档 = `pytest tests/ -q -m "not slow and not backtest"`（≈110-170s, 稳进 180s 预算）,
  由外部 harness / scripts/daily_monitor.py 调用。
- 重件（97项, 已挂 @pytest.mark.slow / @pytest.mark.backtest）走本夜间全量档,
  无预算约束, 顺带产出 --durations 漂移监控（快档墙钟若劣化, 由本档 top-slowest 定位）。

Hermes cron 入口：hermes-home/scripts/pytest_full_nightly.py（zq_shim 转发器）→ 本文件唯一真源。

退出码契约（区别于业务红）：
- 0 = 套件完整跑完（无论红绿, 结果写 JSON + stdout 仅在有 baseline 漂移时出声）
- 2 = 运维性失败（venv 缺失 / pytest 崩溃 / 收集错误无 summary 行）

stdout 语义（no_agent 投递面, watchdog 模式）：
- 失败集 == KNOWN_FAILS 基线 → 空输出（不刷屏）
- 有新增失败 或 既有失败复绿 → 一行摘要（低频事件, 供人工更新基线）

已知失败基线（10-26, 14项环境/数据陈旧类, 单独立件处理中, 勿随手删）：
- DL/torch 降级 ×2, L1缓存契约 ×4, model_config ×2, dashboard health_status,
  factor_ic missing_config, feishu 双向通道, trade_log 新鲜度,
  weekly_report 假阳性, no_bare_core_imports（全仓AST扫描）
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ZQ_ROOT = Path(os.environ.get("ZQ_ROOT", r"D:\open code\zhuanqian"))
VENV_PY = r"C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe"
OUT_JSON = ZQ_ROOT / "data" / "audit" / "pytest_full_nightly_last.json"
TIMEOUT_S = 2400  # 全量实测 ~880s, 留 2.7 倍余量; 夜间档无预算约束

# 既有失败基线（docs/pytest_timeout_investigation_20261025.md §2 14 项, 环境/数据陈旧类,
# 单独立件处理。失败集与基线不一致时本脚本出声, 人工同步此处）。
# 10-26 02:06 全量档实跑复绿 2 项（test_health_status_exists / test_message_id_tracking）
# → 基线 14→12；若复红, 夜间档会再出声, 届时重加回。14 项立件收口时以该件为准重标定。
KNOWN_FAILS = frozenset({
    "tests/test_dl_import_degradation.py::test_torch_missing_degrades_with_root_cause_not_misleading",
    "tests/test_dl_import_degradation.py::test_dl_still_active_when_torch_present",
    "tests/test_factor_ic.py::TestFactorFunctions::test_missing_config_factors",
    "tests/test_layers_contract.py::TestL1FinancialCacheContract::test_exists",
    "tests/test_layers_contract.py::TestL1FinancialCacheContract::test_top_schema",
    "tests/test_layers_contract.py::TestL1FinancialCacheContract::test_stock_schema",
    "tests/test_layers_contract.py::TestL1FinancialCacheContract::test_indicators_sample",
    "tests/test_model_config.py::test_fallback_differs_from_main",
    "tests/test_model_config.py::test_all_provider_env_keys_exist",
    "tests/test_no_bare_core_imports.py::test_no_bare_core_imports_in_repo",
    "tests/test_system.py::TestDataFreshness::test_trade_log_freshness",
    "tests/test_weekly_report_fake_positive.py::TestFakePositiveThreeStates::test_state_no_new_entries",
})

SUMMARY_RE = re.compile(r"^(?:(\d+) (failed|passed|skipped|xfailed|deselected|errors?) ?[, ]*)+in \d+m?\d*\.?\d*s")


def parse_failures(stdout: str):
    """从 -q 输出提取 FAILED 行（完整节点 id, 去重保序: 进度区+summary 区会各印一遍）"""
    fails = []
    seen = set()
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("FAILED "):
            node = line[len("FAILED "):].split(" - ")[0].strip()
            if node not in seen:
                seen.add(node)
                fails.append(node)
    return fails


def parse_durations(stdout: str, top: int = 15):
    out = []
    in_sec = False
    for line in stdout.splitlines():
        if "slowest" in line and "durations" in line:
            in_sec = True
            continue
        if in_sec:
            m = re.match(r"^(\d+\.\d+)s (setup|call|teardown)\s+(\S+)", line.strip())
            if m:
                out.append({"seconds": float(m.group(1)), "phase": m.group(2), "node": m.group(3)})
            elif line.startswith("=") or line.startswith("-"):
                if out:
                    break
            if len(out) >= top:
                break
    return out


def parse_counts(stdout: str):
    counts = {}
    m = re.search(r"=+ short test summary info =+", stdout)
    tail = stdout[m.end():] if m else stdout[-2000:]
    for num, label in re.findall(r"(\d+) (failed|passed|skipped|xfailed|deselected)", tail):
        counts[label] = int(num)
    wall = re.search(r"in (\d+(?::\d+)?\.\d+)s", tail)
    if wall:
        s = wall.group(1)
        if ":" in s:
            mm, ss = s.split(":")
            counts["wall_seconds"] = int(mm) * 60 + float(ss)
        else:
            counts["wall_seconds"] = float(s)
    return counts


def main():
    if not VENV_PY or not Path(VENV_PY).exists():
        print(f"[pytest_full_nightly] FATAL: venv python 不存在: {VENV_PY}", file=sys.stderr)
        sys.exit(2)

    ts = datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    cmd = [
        VENV_PY, "-m", "pytest", "tests/", "-q", "--tb=line",
        "-p", "no:cacheprovider", "--durations=15",
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(ZQ_ROOT), capture_output=True, text=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        print(f"[pytest_full_nightly] FATAL: pytest 超时 >{TIMEOUT_S}s（夜间档异常, 检查机器负载/死锁）", file=sys.stderr)
        sys.exit(2)

    wall = round(time.time() - t0, 1)
    fails = parse_failures(proc.stdout)
    counts = parse_counts(proc.stdout)
    durations = parse_durations(proc.stdout)

    # 运维性失败守卫（异常吞噬=埋雷, 09-25 纪律）：收集错误/崩溃/无 summary 行 → 响亮 exit 2
    if proc.returncode == 2:
        print(f"[pytest_full_nightly] FATAL: pytest 收集/内部错误 (rc=2)\n"
              f"stdout tail:\n{proc.stdout[-2000:]}\nstderr tail:\n{proc.stderr[-2000:]}", file=sys.stderr)
        sys.exit(2)
    if "passed" not in counts and "failed" not in counts:
        print(f"[pytest_full_nightly] FATAL: 未解析到测试 summary（rc={proc.returncode}, "
              f"套件未完整跑完, 不写静默结论）\n"
              f"stdout tail:\n{proc.stdout[-2000:]}", file=sys.stderr)
        sys.exit(2)

    payload = {
        "ts": ts,
        "total_wall_seconds": wall,
        "pytest_exit_code": proc.returncode,
        "counts": counts,
        "failures": fails,
        "top_slowest": durations,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    fail_set = set(fails)
    new_fails = sorted(fail_set - set(KNOWN_FAILS))
    recovered = sorted(set(KNOWN_FAILS) - fail_set)

    # watchdog：基线严格一致 → 静默；任何漂移（新增/复绿）→ 一行摘要
    if new_fails or recovered:
        parts = []
        if new_fails:
            parts.append(f"新增失败 {len(new_fails)}: " + "; ".join(new_fails[:5]) + (" …" if len(new_fails) > 5 else ""))
        if recovered:
            parts.append(f"复绿 {len(recovered)}: " + "; ".join(recovered[:5]) + (" …" if len(recovered) > 5 else ""))
        print(f"[pytest_full_nightly] 基线漂移: {' | '.join(parts)}; "
              f"结果 {json.dumps(payload['counts'], ensure_ascii=False)}; 详见 {OUT_JSON}")
    elif proc.returncode == 0:
        # 全绿且基线已空 → 罕见, 报一声
        print(f"[pytest_full_nightly] 全量 {counts.get('passed', '?')}P/0F, wall={wall}s（全绿!）")
    # 其余情况（红但全在基线内）：静默, 结果已在 JSON


if __name__ == "__main__":
    main()
