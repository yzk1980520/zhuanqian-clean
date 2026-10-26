"""RED test: role_permission_check.py blocks opencode from writing holdings.json.

FR-004: 每次 git commit 时验证提交者角色与其操作权限匹配，越界操作写 P1 告警。
SC-004: 角色权限校验拦截率 100%。
"""

import pytest
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJ_ROOT / "scripts"
MSG_QUEUE = PROJ_ROOT / "data" / "message_queue.json"


def test_opencode_blocked_write_to_holdings():
    """T010 RED: opencode profile writing data/holdings.json → exit=1 + P1 alert."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import role_permission_check
    except ModuleNotFoundError:
        pytest.skip("role_permission_check.py not yet implemented (RED phase)")

    # Simulate opencode profile trying to write holdings.json
    result = role_permission_check.check_permission(
        profile_name="opencode",
        action="write",
        target_path="data/holdings.json",
    )
    assert result["allowed"] is False, (
        "opencode should be blocked from writing data/holdings.json"
    )
    assert result["level"] == "P1", (
        f"Expected P1 alert level, got {result.get('level')}"
    )
    assert result["type"] == "permission_violation", (
        f"Expected type='permission_violation', got {result.get('type')}"
    )


def test_default_profile_allowed_write_scripts():
    """T026: default (总管) profile writing scripts/xxx.py → allowed."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import role_permission_check
    except ModuleNotFoundError:
        pytest.skip("role_permission_check.py not yet implemented (RED phase)")

    result = role_permission_check.check_permission(
        profile_name="default",
        action="write",
        target_path="scripts/test_script.py",
    )
    assert result["allowed"] is True, (
        f"default profile should be allowed to write scripts/*.py, got: {result}"
    )


def test_atomcode_blocked_write_risk_rules():
    """T028: atomcode (老五) profile writing risk_rules.py → blocked."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import role_permission_check
    except ModuleNotFoundError:
        pytest.skip("role_permission_check.py not yet implemented (RED phase)")

    result = role_permission_check.check_permission(
        profile_name="atomcode",
        action="write",
        target_path="risk_rules.py",
    )
    assert result["allowed"] is False, (
        "atomcode should be blocked from writing risk_rules.py"
    )
    assert result["level"] == "P1", (
        f"Expected P1 alert level, got {result.get('level')}"
    )
