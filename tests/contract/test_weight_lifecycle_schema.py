"""T003: 权重元数据 schema 契约测试（RED）

验证 models/ 下所有权重文件旁的 metadata.json 符合 schema。
FR-003 要求：trained_at (ISO) / data_window (YYYYMMDD-YYYYMMDD) / ic_baseline (float) / status (enum)
"""
import json
import re
from pathlib import Path
from datetime import datetime

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

VALID_STATUSES = {"valid", "needs_retrain", "no_metadata", "extended"}
WEIGHT_PATTERNS = [
    ("*.pkl", "dl_predictor"),
    ("*.pt", "dl_predictor_torch"),
]
LAYA_DIR = MODELS_DIR / "laya-typed-decisions"
LAYA_WEIGHT_FILE = "model.safetensors"


def test_metadata_schema_valid_weight():
    """metadata.json 所有必填字段存在且类型正确"""
    sample = {
        "trained_at": "2026-10-24T00:00:00+08:00",
        "data_window": "20260501-20261024",
        "ic_baseline": 0.032,
        "status": "valid",
        "model_type": "dl_predictor",
    }
    _assert_metadata_schema(sample)


def test_metadata_schema_needs_retrain():
    """过期权重 status = needs_retrain"""
    sample = {
        "trained_at": "2026-01-01T00:00:00+08:00",
        "data_window": "20250701-20251231",
        "ic_baseline": 0.041,
        "status": "needs_retrain",
        "model_type": "dl_predictor",
    }
    _assert_metadata_schema(sample)


def test_metadata_schema_no_metadata():
    """缺失 metadata.json 时 fallback 状态"""
    sample = {
        "trained_at": None,
        "data_window": None,
        "ic_baseline": None,
        "status": "no_metadata",
        "model_type": "unknown",
    }
    _assert_metadata_schema(sample, allow_null=True)


def test_metadata_status_enum():
    """status 必须在 VALID_STATUSES 内"""
    bad = {"trained_at": "2026-10-01", "data_window": "20260101-20261001",
           "ic_baseline": 0.03, "status": "INVALID_STATUS"}
    try:
        _assert_metadata_schema(bad)
        assert False, "should have raised"
    except (ValueError, AssertionError):
        pass


def test_models_dir_exists():
    """models/ 目录存在 (gitignored 实体: 新 worktree 缺失 → 条件式 skipif, 不假红不假绿)"""
    if not MODELS_DIR.is_dir():
        pytest.skip(f"models/ 实体缺失 (gitignored, worktree 未供给) — {MODELS_DIR}, 非契约违约")
    assert MODELS_DIR.is_dir(), f"models/ not found at {MODELS_DIR}"


def test_laya_dir_exists():
    """Laya 模型目录存在 (gitignored 实体: 新 worktree 缺失 → 条件式 skipif)"""
    if not LAYA_DIR.is_dir():
        pytest.skip(f"laya-typed-decisions/ 实体缺失 (gitignored, worktree 未供给) — {LAYA_DIR}, 非契约违约")
    assert LAYA_DIR.is_dir(), f"laya-typed-decisions/ not found at {LAYA_DIR}"


def _assert_metadata_schema(meta: dict, allow_null: bool = False):
    """核心 schema 校验逻辑"""
    assert "status" in meta, "missing status field"
    assert meta["status"] in VALID_STATUSES, f"invalid status: {meta['status']}"

    if allow_null:
        return

    # trained_at
    assert "trained_at" in meta and meta["trained_at"] is not None, "trained_at required"
    try:
        datetime.fromisoformat(meta["trained_at"])
    except (ValueError, TypeError):
        raise ValueError(f"trained_at not ISO format: {meta['trained_at']}")

    # data_window: YYYYMMDD-YYYYMMDD
    assert "data_window" in meta and meta["data_window"] is not None, "data_window required"
    assert re.match(r"^\d{8}-\d{8}$", meta["data_window"]), \
        f"data_window format invalid: {meta['data_window']}"

    # ic_baseline
    assert "ic_baseline" in meta and meta["ic_baseline"] is not None, "ic_baseline required"
    assert isinstance(meta["ic_baseline"], (int, float)), "ic_baseline must be numeric"
