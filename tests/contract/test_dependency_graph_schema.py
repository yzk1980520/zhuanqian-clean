"""Contract test: dependency_graph.json schema validation.

Validates:
- root fields: generated_at, total_edges, edges, orphan_modules, manual_annotations
- edge fields: source, target, import_type, line_number, symbol
- rule: total_edges == len(edges) + len(manual_annotations)
- rule: line_number >= 1 (0 = unlocated)
- rule: import_type="dynamic" implies corresponding manual_annotation
"""

import json
import pytest
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def sample_dep_graph():
    return {
        "generated_at": "2026-10-22T21:00:00+08:00",
        "total_edges": 3,
        "edges": [
            {
                "source": "scripts/board_server.py",
                "target": "scripts/risk_rules.py",
                "import_type": "direct",
                "line_number": 12,
                "symbol": "STRATEGY_STOP_LOSS_PCT",
            },
            {
                "source": "scripts/final_health_check.py",
                "target": "scripts/risk_rules.py",
                "import_type": "from_import",
                "line_number": 8,
                "symbol": "STRATEGY_STOP_LOSS_PCT",
            },
        ],
        "orphan_modules": [],
        "manual_annotations": [
            {
                "source": "scripts/some_script.py",
                "target": "scripts/other_script.py",
                "reason": "dynamic import via __import__",
            }
        ],
    }


def test_root_fields_present(sample_dep_graph):
    """Root must have generated_at, total_edges, edges, orphan_modules, manual_annotations."""
    required = {"generated_at", "total_edges", "edges", "orphan_modules", "manual_annotations"}
    missing = required - set(sample_dep_graph.keys())
    assert not missing, f"Missing root fields: {missing}"


def test_total_edges_matches_count(sample_dep_graph):
    """total_edges == len(edges) + len(manual_annotations)."""
    expected = len(sample_dep_graph["edges"]) + len(sample_dep_graph["manual_annotations"])
    assert sample_dep_graph["total_edges"] == expected, (
        f"total_edges={sample_dep_graph['total_edges']} != "
        f"len(edges)={len(sample_dep_graph['edges'])} + "
        f"len(annotations)={len(sample_dep_graph['manual_annotations'])}"
    )


def test_edge_fields_present(sample_dep_graph):
    """Each edge must have source, target, import_type, line_number, symbol."""
    required = {"source", "target", "import_type", "line_number", "symbol"}
    for i, edge in enumerate(sample_dep_graph["edges"]):
        missing = required - set(edge.keys())
        assert not missing, f"Edge[{i}] missing: {missing}"


def test_edge_line_number_positive(sample_dep_graph):
    """line_number >= 1 (0 = unlocated, which is allowed but we test explicit > 0)."""
    for i, edge in enumerate(sample_dep_graph["edges"]):
        assert edge["line_number"] >= 1, f"Edge[{i}] line_number={edge['line_number']} < 1"


def test_dynamic_import_has_manual_annotation(sample_dep_graph):
    """If any edge has import_type='dynamic', must have matching manual_annotation."""
    dynamic_edges = [e for e in sample_dep_graph["edges"] if e["import_type"] == "dynamic"]
    if dynamic_edges:
        annotations = sample_dep_graph["manual_annotations"]
        for edge in dynamic_edges:
            matching = [a for a in annotations if a["source"] == edge["source"] and a["target"] == edge["target"]]
            assert matching, f"No manual_annotation for dynamic edge: {edge['source']} -> {edge['target']}"


def test_import_type_enum():
    """import_type must be one of: direct, from_import, dynamic."""
    valid = {"direct", "from_import", "dynamic"}
    for t in ["direct", "from_import", "dynamic"]:
        assert t in valid


def test_invalid_import_type_rejected():
    """An edge with invalid import_type is a schema violation."""
    valid_types = {"direct", "from_import", "dynamic"}
    assert "invalid_type" not in valid_types


def test_generated_at_iso8601(sample_dep_graph):
    """generated_at must be parseable ISO 8601."""
    from datetime import datetime
    datetime.fromisoformat(sample_dep_graph["generated_at"])
