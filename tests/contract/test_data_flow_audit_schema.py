"""Contract test: data_flow_report.json schema validation.

Validates:
- root fields: scanned_at, status, orphan_producers, orphan_consumers
- node fields: file_path, producer_script, consumer_scripts, created_at, last_accessed_at, status
- status enum: intact, orphan_producer, orphan_consumer
"""

import json
import pytest
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def sample_data_flow_report():
    return {
        "scanned_at": "2026-10-22T21:00:00+08:00",
        "status": "intact",
        "orphan_producers": [],
        "orphan_consumers": [],
        "nodes": [
            {
                "file_path": "data/factor_ic/factor_ic_latest.json",
                "producer_script": "scripts/factor_ic_scan.py",
                "consumer_scripts": ["scripts/board_server.py"],
                "created_at": "2026-10-22T09:30:00+08:00",
                "last_accessed_at": "2026-10-22T15:25:00+08:00",
                "status": "intact",
            }
        ],
    }


VALID_STATUS = {"intact", "orphan_producer", "orphan_consumer"}


def test_root_fields_present(sample_data_flow_report):
    """Root must have scanned_at, status, orphan_producers, orphan_consumers."""
    required = {"scanned_at", "status", "orphan_producers", "orphan_consumers"}
    missing = required - set(sample_data_flow_report.keys())
    assert not missing, f"Missing root fields: {missing}"


def test_root_status_enum(sample_data_flow_report):
    """Root status must be in {intact, orphan_producer, orphan_consumer}."""
    assert sample_data_flow_report["status"] in VALID_STATUS


def test_orphan_lists_are_lists(sample_data_flow_report):
    """orphan_producers and orphan_consumers must be lists."""
    assert isinstance(sample_data_flow_report["orphan_producers"], list)
    assert isinstance(sample_data_flow_report["orphan_consumers"], list)


def test_node_fields_present(sample_data_flow_report):
    """Each node must have all required fields."""
    required = {
        "file_path", "producer_script", "consumer_scripts",
        "created_at", "last_accessed_at", "status",
    }
    for i, node in enumerate(sample_data_flow_report["nodes"]):
        missing = required - set(node.keys())
        assert not missing, f"node[{i}] missing: {missing}"


def test_node_status_enum(sample_data_flow_report):
    """Each node status must be in {intact, orphan_producer, orphan_consumer}."""
    for i, node in enumerate(sample_data_flow_report["nodes"]):
        assert node["status"] in VALID_STATUS, (
            f"node[{i}] status='{node['status']}' not in {VALID_STATUS}"
        )


def test_node_file_path_is_string(sample_data_flow_report):
    """file_path must be a non-empty string."""
    for i, node in enumerate(sample_data_flow_report["nodes"]):
        assert isinstance(node["file_path"], str) and node["file_path"], (
            f"node[{i}] file_path is empty"
        )


def test_orphan_producer_consistency(sample_data_flow_report):
    """If a node is orphan_producer, it must appear in orphan_producers list."""
    report = sample_data_flow_report
    orphan_files = {n["file_path"] for n in report["nodes"] if n["status"] == "orphan_producer"}
    reported_orphans = set(report["orphan_producers"])
    assert orphan_files == reported_orphans, (
        f"Node orphan_producers {orphan_files} != root orphan_producers {reported_orphans}"
    )


def test_orphan_consumer_consistency(sample_data_flow_report):
    """If a node is orphan_consumer, it must appear in orphan_consumers list."""
    report = sample_data_flow_report
    orphan_files = {n["file_path"] for n in report["nodes"] if n["status"] == "orphan_consumer"}
    reported_orphans = set(report["orphan_consumers"])
    assert orphan_files == reported_orphans, (
        f"Node orphan_consumers {orphan_files} != root orphan_consumers {reported_orphans}"
    )


def test_iso8601_timestamps(sample_data_flow_report):
    """All timestamp fields must be parseable ISO 8601."""
    from datetime import datetime
    ts_fields = ["scanned_at"]
    for node in sample_data_flow_report["nodes"]:
        ts_fields.extend(["created_at", "last_accessed_at"])
    for field in ts_fields:
        if field in sample_data_flow_report:
            datetime.fromisoformat(sample_data_flow_report[field])
        for node in sample_data_flow_report["nodes"]:
            if field in node:
                datetime.fromisoformat(node[field])
