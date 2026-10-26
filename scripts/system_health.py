#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""系统健康检查 — 统一视图 (US2 MVP)

替代分散的 final_health_check.py + alert_engine.py + board_watchdog.py 三源。
写入 data/system/health_snapshot.json (atomic_dump)。

宪法 VII: 无裸 except:，所有异常显式类型。
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT = Path(__file__).resolve().parent.parent
DATA_SYSTEM = PROJECT / "data" / "system"
SNAPSHOT_PATH = DATA_SYSTEM / "health_snapshot.json"

# 宪法 I 引用（只读指针，不硬编码数值）
RISK_RULES_PY = PROJECT / "risk_rules.py"


def run_cmd(cmd: str, timeout: int = 30) -> tuple:
    """运行命令，返回 (stdout, stderr, returncode)。"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=str(PROJECT),
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as e:
        return "", f"timeout: {e}", 1
    except FileNotFoundError as e:
        return "", f"not found: {e}", 1
    except OSError as e:
        return "", f"os error: {e}", 1


def check_cron() -> dict:
    """检查 cron 任务状态。

    2026-10-26 对齐: hermes CLI 的 `cron list` 仅支持 `--all`，无 `--json`；
    旧代码 `hermes cron list --json` 的 `--json` 落入全局解析器 → rc=2 usage error，
    致 cron 板块恒显 error/0。改为解析 `hermes cron list` 文本输出的
    `[<status>]` 标记 (与 board health card 同一读法，22 active 已验证)。
    R1-E: 区分「hermes 命令失败」与「确实无 cron」，不得都静默返回 total=0。
    """
    # 每行 job: `<id> [<status>] <schedule> <name>`; id 可为 8-hex 或 slug (如 dep_graph_qsp_001)
    job_re = re.compile(r"^\s*[A-Za-z0-9_]{4,40}\s+\[(active|paused|disabled|failed|error|completed)\]", re.I)
    try:
        stdout, stderr, rc = run_cmd("hermes cron list")
        # hermes 命令不可用/失败 → 显式标记 error，不得当成「无 cron」
        if rc != 0:
            return {
                "total": 0, "active": 0, "failed": [],
                "error": f"hermes cron list rc={rc}: {stderr.strip()[:120]}",
            }
        if not stdout.strip():
            return {"total": 0, "active": 0, "failed": []}
        job_lines = [ln for ln in stdout.splitlines() if job_re.match(ln)]
        total = len(job_lines)
        active = sum(1 for ln in job_lines if re.search(r"\[active\]", ln, re.I))
        failed = []
        for ln in job_lines:
            if re.search(r"\[(failed|error)\]", ln, re.I):
                m = re.match(r"^\s*([A-Za-z0-9_]{4,40})", ln)
                failed.append(m.group(1) if m else ln.strip())
        return {"total": total, "active": active, "failed": failed}
    except FileNotFoundError as exc:
        return {"total": 0, "active": 0, "failed": [], "error": f"hermes not found: {exc}"}
    except Exception as exc:
        print(f"[WARN] check_cron failed: {exc}", file=sys.stderr)
        return {"total": 0, "active": 0, "failed": [], "error": str(exc)}


def check_tests() -> dict:
    """运行 pytest，返回测试结果。

    宪法 VII: 不丢弃 stderr（旧版 2>/dev/null 丢弃 FAILED 行导致测试失败永不降级）。
    不使用 shell 重定向（POSIX 语法在 cmd/PowerShell 原生下不可移植）。
    """
    import re
    try:
        # 直接调用 python -m pytest，捕获 stdout+stderr，不用 shell 重定向
        stdout, stderr, rc = run_cmd(
            f'"{sys.executable}" -m pytest tests/test_final_health_check.py -q --tb=line',
            timeout=60,
        )
        # pytest -q 的 "FAILED" 摘要行和 "N failed" 计数都在 stdout；
        # 收集 stdout + stderr 一起解析，避免任何一条流丢失
        combined = f"{stdout}\n{stderr}"
        mp = re.search(r"(\d+) passed", combined)
        passed = int(mp.group(1)) if mp else 0
        mf = re.search(r"(\d+) failed", combined)
        failed_count = int(mf.group(1)) if mf else 0
        failed_lines = [
            line.strip() for line in combined.splitlines()
            if line.strip().startswith("FAILED")
        ]
        total = passed + failed_count
        # 无法定位到具体测试文件时（文件缺失等），标记为 FAIL 而非静默 0
        if rc != 0 and total == 0:
            failed_lines.append(f"pytest rc={rc} (no test collected)")
            failed_count = max(failed_count, 1)
        return {
            "total": total,
            "passed": passed,
            "failed": failed_lines,
            "pass_rate": (passed / total) if total > 0 else (0.0 if total == 0 and rc != 0 else 1.0),
        }
    except Exception as exc:
        print(f"[WARN] check_tests failed: {exc}", file=sys.stderr)
        return {"total": 0, "passed": 0, "failed": [str(exc)], "pass_rate": 0.0}


def check_data_freshness() -> dict:
    """检查 data/ 目录下关键文件的新鲜度。"""
    stale_threshold_hours = 24
    try:
        now = datetime.now(timezone.utc)
        key_files = [
            "data/factor_ic/factor_ic_latest.json",
            "data/history_daily/history_daily_latest.json",
            "data/message_queue.json",
        ]
        max_age_hours = 0.0
        for rel in key_files:
            full = PROJECT / rel
            if full.exists():
                mtime = datetime.fromtimestamp(full.stat().st_mtime, tz=timezone.utc)
                age = (now - mtime).total_seconds() / 3600
                max_age_hours = max(max_age_hours, age)
            # 不存在不算 stale，只算已存在的最老文件
        is_stale = max_age_hours > stale_threshold_hours
        return {
            "last_scan_hours": round(max_age_hours, 2),
            "stale_threshold_hours": stale_threshold_hours,
            "is_stale": is_stale,
        }
    except Exception as exc:
        return {"last_scan_hours": 0.0, "stale_threshold_hours": stale_threshold_hours, "is_stale": False, "error": str(exc)}


def build_health_snapshot(
    cron_state: dict | None = None,
    test_result: dict | None = None,
    data_freshness_hours: float | None = None,
) -> dict:
    """构建 SystemHealthSnapshot。

    FR-007: 无快照数据时返回 status='unknown'，不得虚假正常。
    """
    # 检查已有快照
    existed = SNAPSHOT_PATH.exists()
    if not existed:
        return {
            "status": "unknown",
            "message": "等待首个健康检查周期",
            "last_check_at": datetime.now(timezone.utc).isoformat(),
            "response_time_ms": 0,
        }

    # 运行各项检查
    if cron_state is None:
        cron_state = check_cron()
    if test_result is None:
        test_result = check_tests()
    if data_freshness_hours is None:
        freshness = check_data_freshness()
        data_freshness_hours = freshness.get("last_scan_hours", 0.0)

    # 构建 checks
    checks: dict = {}

    # codebase: risk_rules.py 存在且可读
    checks["codebase"] = "PASS" if RISK_RULES_PY.exists() else "FAIL"

    # data_integrity: 关键数据文件存在
    data_keys = ["data/factor_ic/factor_ic_latest.json", "data/message_queue.json"]
    checks["data_integrity"] = "PASS" if all((PROJECT / p).exists() for p in data_keys) else "WARN"

    # scripts_deployed: system_health.py 存在
    checks["scripts_deployed"] = "PASS" if (PROJECT / "scripts" / "system_health.py").exists() else "FAIL"

    # s3_config: config.yaml 存在
    checks["s3_config"] = "PASS" if (PROJECT / "config" / "config.yaml").exists() else "WARN"

    # skills_installed: .hermes/skills/ 非空
    skills_dir = PROJECT / ".hermes" / "skills"
    checks["skills_installed"] = "PASS" if skills_dir.exists() and any(skills_dir.iterdir()) else "WARN"

    # account_status: 检查是否有配置（简化：config 目录存在即 PASS，否则 WARN）
    config_dir = PROJECT / "config"
    checks["account_status"] = "PASS" if config_dir.exists() else "WARN"

    # pending_tasks: 检查 final_health_check 结果是否存在且 score >= 70
    fhc_file = PROJECT / "data" / "final_health_check.json"
    if fhc_file.exists():
        try:
            fhc_data = json.loads(fhc_file.read_text(encoding="utf-8"))
            score = fhc_data.get("score", 0)
            checks["pending_tasks"] = "PASS" if score >= 70 else "FAIL"
        except json.JSONDecodeError as exc:
            print(f"[WARN] final_health_check.json parse failed: {exc}", file=sys.stderr)
            checks["pending_tasks"] = "WARN"
    else:
        checks["pending_tasks"] = "WARN"

    # 判断整体状态
    has_fail = any(v == "FAIL" for v in checks.values())
    has_warn = any(v == "WARN" for v in checks.values())
    has_failed_crons = bool(cron_state.get("failed"))
    has_failed_tests = bool(test_result.get("failed"))
    # T055: cron 探测错误（hermes 不可用/列表解析失败等）不得静默吞没，须参与降级判定
    has_cron_error = bool(cron_state.get("error"))

    if has_fail or has_failed_crons or has_failed_tests or has_cron_error:
        status = "degraded"
    elif has_warn:
        status = "healthy"  # WARN 不降级
    else:
        status = "healthy"

    now_iso = datetime.now(timezone.utc).isoformat()

    snapshot = {
        "status": status,
        "cron": {
            "total": cron_state.get("total", 0),
            "active": cron_state.get("active", 0),
            "failed": cron_state.get("failed", []),
            "error": cron_state.get("error"),  # T055: 非 None 时 status 已降级为 degraded
        },
        "tests": {
            "total": test_result.get("total", 0),
            "passed": test_result.get("passed", 0),
            "failed": test_result.get("failed", []),
            "pass_rate": test_result.get("pass_rate", 0.0),
        },
        "data_freshness": {
            "last_scan_hours": data_freshness_hours,
            "stale_threshold_hours": 24,
            "is_stale": data_freshness_hours > 24,
        },
        "checks": checks,
        "last_check_at": now_iso,
        "response_time_ms": 0,  # filled by caller
    }

    # 原子写入
    try:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(snapshot, str(SNAPSHOT_PATH), ensure_ascii=False, indent=2)
    except ImportError:
        # fallback: 直接写
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return snapshot


def main() -> int:
    """入口：运行健康检查并写入快照。"""
    start = time.time()
    try:
        snapshot = build_health_snapshot()
        elapsed_ms = int((time.time() - start) * 1000)
        snapshot["response_time_ms"] = elapsed_ms
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            from core.pipeline.atomic_json import atomic_dump
            atomic_dump(snapshot, str(SNAPSHOT_PATH), ensure_ascii=False, indent=2)
        except ImportError:
            SNAPSHOT_PATH.write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        # exit 0 = healthy or degraded (still running), exit 1 only on critical error
        return 0
    except Exception as exc:
        print(f"{{\"error\": \"health_check_failed\", \"detail\": {repr(str(exc))}}}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
