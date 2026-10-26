"""RED test: system_health.py returns unknown when no health_snapshot.json exists.

FR-007: Health endpoint MUST return status=unknown when data/system/health_snapshot.json
does not exist — never return healthy with missing data.
"""

import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJ_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJ_ROOT / "scripts"
SYSTEM_DIR = PROJ_ROOT / "data" / "system"
SNAPSHOT_PATH = SYSTEM_DIR / "health_snapshot.json"


def _import_system_health():
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import system_health
    except ModuleNotFoundError:
        pytest.skip("system_health.py not yet implemented (RED phase)")
        return None
    return system_health


@pytest.fixture
def mock_hermes_cron():
    """Mock hermes cron list to return healthy state."""
    return {
        "total": 67,
        "active": 67,
        "failed": [],
    }


@pytest.fixture
def mock_pytest_result():
    """Mock pytest result to return all passing."""
    return {"total": 17, "passed": 17, "failed": [], "pass_rate": 1.0}


def test_health_returns_unknown_when_no_snapshot():
    """T009 RED: without health_snapshot.json, system_health() must return status='unknown'."""
    # Import after setting up paths
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import system_health
    except ModuleNotFoundError:
        pytest.skip("system_health.py not yet implemented (RED phase)")

    # Remove snapshot if it exists
    snapshot_path = SYSTEM_DIR / "health_snapshot.json"
    existed = snapshot_path.exists()
    if existed:
        snapshot_path.unlink()

    try:
        result = system_health.build_health_snapshot(
            cron_state={"total": 67, "active": 67, "failed": []},
            test_result={"total": 17, "passed": 17, "failed": [], "pass_rate": 1.0},
            data_freshness_hours=0.5,
        )
        assert result["status"] == "unknown", (
            f"Expected status='unknown' when no snapshot exists, got '{result['status']}'"
        )
    finally:
        # Restore snapshot if it existed
        if existed:
            import json
            snapshot_path.write_text(json.dumps({
                "status": "healthy",
                "cron": {"total": 67, "active": 67, "failed": []},
                "tests": {"total": 17, "passed": 17, "failed": [], "pass_rate": 1.0},
                "data_freshness": {"last_scan_hours": 0.5, "stale_threshold_hours": 24, "is_stale": False},
                "checks": {k: "PASS" for k in [
                    "codebase", "data_integrity", "scripts_deployed",
                    "s3_config", "skills_installed", "account_status", "pending_tasks"
                ]},
                "last_check_at": "2026-10-22T15:00:00+08:00",
                "response_time_ms": 0,
            }), encoding="utf-8")


def test_health_degraded_on_cron_error():
    """T055: cron_state 含 error 字段（hermes cron 探测失败）时 status 必须 != 'healthy'。

    回归点：旧实现静默吞没 cron.error，status 仍 healthy。
    验收对应：python scripts/system_health.py 输出中 cron.error 非空时 status != 'healthy'。
    """
    sh = _import_system_health()
    assert sh is not None

    snapshot_path = SNAPSHOT_PATH
    existed = snapshot_path.exists()
    if not existed:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps({
            "status": "healthy",
            "cron": {"total": 67, "active": 67, "failed": []},
        }), encoding="utf-8")

    try:
        result = sh.build_health_snapshot(
            cron_state={"total": 5, "active": 4, "failed": [], "error": "hermes cron list rc=1: boom"},
            test_result={"total": 17, "passed": 17, "failed": [], "pass_rate": 1.0},
            data_freshness_hours=0.5,
        )
        assert result["status"] != "healthy", (
            f"T055: cron.error 非空时 status 不得为 healthy, got '{result['status']}'"
        )
        assert result["status"] == "degraded"
        assert result["cron"]["error"]  # error 必须透出到快照

        # 对照：无 error 且各项 PASS 时仍为 healthy（向后兼容，不误伤正常路径）
        ok = sh.build_health_snapshot(
            cron_state={"total": 5, "active": 4, "failed": [], "error": None},
            test_result={"total": 17, "passed": 17, "failed": [], "pass_rate": 1.0},
            data_freshness_hours=0.5,
        )
        assert ok["status"] in ("healthy", "degraded")  # 树状态决定，不得为 unknown
        assert ok["cron"]["error"] is None
    finally:
        if not existed:
            snapshot_path.unlink(missing_ok=True)
