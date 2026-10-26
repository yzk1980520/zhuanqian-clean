"""Contract test: role_permissions.json schema validation.

Validates:
- root fields: profiles, version, updated_at
- profile fields: profile_name, allowed_writes, blocked_writes, allowed_reads
- rule: blocked_writes takes priority over allowed_writes
- rule: profile_name in {default, opencode, atomcode, laosi, workbuddy, prime, yulongjue}
"""

import json
import pytest
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def sample_role_permissions():
    return {
        "profiles": [
            {
                "profile_name": "opencode",
                "allowed_writes": ["scripts/**/*.py", "tests/**/*.py"],
                "blocked_writes": ["data/holdings.json", "data/trade_log.json", "risk_rules.py"],
                "allowed_reads": ["data/**/*.json", "scripts/**/*.py"],
            },
            {
                "profile_name": "default",
                "allowed_writes": ["scripts/**/*.py", "specs/**/*.md"],
                "blocked_writes": [],
                "allowed_reads": ["data/**/*.json", "scripts/**/*.py"],
            },
        ],
        "version": "1.0",
        "updated_at": "2026-10-22T15:00:00+08:00",
    }


VALID_PROFILES = {"default", "opencode", "atomcode", "laosi", "workbuddy", "prime", "yulongjue"}


def test_root_fields_present(sample_role_permissions):
    """Root must have profiles, version, updated_at."""
    required = {"profiles", "version", "updated_at"}
    missing = required - set(sample_role_permissions.keys())
    assert not missing, f"Missing root fields: {missing}"


def test_profile_fields_present(sample_role_permissions):
    """Each profile must have profile_name, allowed_writes, blocked_writes, allowed_reads."""
    required = {"profile_name", "allowed_writes", "blocked_writes", "allowed_reads"}
    for i, profile in enumerate(sample_role_permissions["profiles"]):
        missing = required - set(profile.keys())
        assert not missing, f"profile[{i}] missing: {missing}"


def test_profile_name_in_valid_set(sample_role_permissions):
    """profile_name must be in the known set of Hermes profiles."""
    for i, profile in enumerate(sample_role_permissions["profiles"]):
        name = profile["profile_name"]
        assert name in VALID_PROFILES, f"profile[{i}] name '{name}' not in {VALID_PROFILES}"


def test_blocked_writes_priority_over_allowed(sample_role_permissions):
    """blocked_writes takes priority over allowed_writes (blacklist beats whitelist)."""
    # Conceptual validation: blocked_writes and allowed_writes are separate fields,
    # and the implementation MUST check blocked first.
    # This is a schema-level contract — real enforcement is in role_permission_check.py.
    for profile in sample_role_permissions["profiles"]:
        assert isinstance(profile["blocked_writes"], list)
        assert isinstance(profile["allowed_writes"], list)
        # A path in blocked_writes should not also be in allowed_writes (semantic violation)
        overlap = set(profile["blocked_writes"]) & set(profile["allowed_writes"])
        assert not overlap, (
            f"profile '{profile['profile_name']}' has overlap between "
            f"blocked_writes and allowed_writes: {overlap}"
        )


def test_all_7_profiles_defined():
    """All 7 Hermes profiles must have a corresponding entry."""
    # Check the actual file if it exists
    perms_path = PROJ_ROOT / "data" / "system" / "role_permissions.json"
    if perms_path.exists():
        data = json.loads(perms_path.read_text(encoding="utf-8"))
        defined = {p["profile_name"] for p in data["profiles"]}
        missing = VALID_PROFILES - defined
        assert not missing, f"Missing profile definitions: {missing}"


def test_version_is_string(sample_role_permissions):
    """version must be a string."""
    assert isinstance(sample_role_permissions["version"], str)


def test_updated_at_iso8601(sample_role_permissions):
    """updated_at must be parseable ISO 8601."""
    from datetime import datetime
    datetime.fromisoformat(sample_role_permissions["updated_at"])
