"""RED test: dependency_graph_generator.py finds >= 10 referents for risk_rules.py.

SC-003: 依赖图覆盖 >= 95% 的 Python 导入关系。
US3 Acceptance Scenario 1: risk_rules.py 引用方 >= 10 个。
"""

import pytest
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJ_ROOT / "scripts"


def test_risk_rules_has_10_referents():
    """T011 RED: dependency graph scan must find >= 10 scripts referencing risk_rules.py."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import dependency_graph_generator
    except ModuleNotFoundError:
        pytest.skip("dependency_graph_generator.py not yet implemented (RED phase)")

    graph = dependency_graph_generator.generate_dependency_graph(
        root_dir=PROJ_ROOT,
        scan_dirs=["scripts", "tests", "dashboards"],
    )

    # Find all edges targeting risk_rules.py
    risk_rules_referents = [
        e for e in graph["edges"]
        if "risk_rules.py" in e["target"]
    ]

    assert len(risk_rules_referents) >= 10, (
        f"Expected >= 10 referents for risk_rules.py, found {len(risk_rules_referents)}: "
        f"{[e['source'] for e in risk_rules_referents]}"
    )


def test_dependency_graph_total_edges_positive():
    """T021 prereq: dependency graph must have total_edges > 0."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import dependency_graph_generator
    except ModuleNotFoundError:
        pytest.skip("dependency_graph_generator.py not yet implemented (RED phase)")

    graph = dependency_graph_generator.generate_dependency_graph(
        root_dir=PROJ_ROOT,
        scan_dirs=["scripts", "tests", "dashboards"],
    )

    assert graph["total_edges"] > 0, (
        f"Expected total_edges > 0, got {graph['total_edges']}"
    )


def test_dynamic_import_manual_annotation():
    """T022: any dynamic import edge must have corresponding manual_annotation."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import dependency_graph_generator
    except ModuleNotFoundError:
        pytest.skip("dependency_graph_generator.py not yet implemented (RED phase)")

    graph = dependency_graph_generator.generate_dependency_graph(
        root_dir=PROJ_ROOT,
        scan_dirs=["scripts", "tests", "dashboards"],
    )

    dynamic_edges = [e for e in graph["edges"] if e["import_type"] == "dynamic"]
    annotations = graph.get("manual_annotations", [])

    for edge in dynamic_edges:
        matching = [
            a for a in annotations
            if a["source"] == edge["source"] and a["target"] == edge["target"]
        ]
        assert matching, (
            f"Dynamic import edge at {edge['source']} -> {edge['target']} "
            f"has no manual annotation"
        )
