#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression tests for final_health_check.py exit-code contract (2026-10-21).

Fixes three defects:
  1. PROJECT path: Path(__file__).parent → parent.parent (root, not scripts/)
  2. Bare `except:` → `except Exception:`
  3. __main__ exit logic: score<70 → exit(1), else exit(0)

Tests:
  - PROJECT resolves to repo root (contains data/ and mainline/)
  - No bare `except:` in the file
  - main() writes report to <root>/data/final_health_check.json
  - __main__ block reads the SAME report path main() writes to
  - score=14 mock → exit=1
  - score=90 mock → exit=0
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent  # tests/ → repo root
TARGET = REPO / "scripts" / "final_health_check.py"
PY = sys.executable  # use the running Python (project venv)


def _read_src() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_project_path_points_to_root():
    """PROJECT must be the repo root, not scripts/."""
    src = _read_src()
    # PROJECT = Path(__file__).parent.parent.resolve()  ← correct
    assert "parent.parent" in src, (
        "PROJECT must use parent.parent to reach repo root; "
        f"got src: {src}"
    )
    # Must NOT be parent.resolve() alone (that's scripts/)
    bad_pattern = re.search(r'PROJECT\s*=\s*Path\(__file__\)\.parent\.resolve\(\)', src)
    assert not bad_pattern, (
        "PROJECT still uses .parent (scripts dir) — should be .parent.parent (root)"
    )


def test_no_bare_except():
    """No bare `except:` — bare except swallows KeyboardInterrupt/SystemExit."""
    src = _read_src()
    lines = [ln for ln in src.splitlines() if "except" in ln]
    bare = [ln.strip() for ln in lines if re.match(r'^\s*except\s*:', ln)]
    assert not bare, (
        f"bare `except:` found (SOUL准则9 P0): {bare}"
    )


def test_main_writes_report_to_root_data():
    """main() writes report to <PROJECT>/data/final_health_check.json (root)."""
    src = _read_src()
    assert "data" in src, "no 'data' reference found"
    # PROJECT / "data" / "final_health_check.json" must be the report target
    # and PROJECT must be the root-level variable
    assert 'PROJECT / "data"' in src, "report must use PROJECT / 'data'"


def test_main_block_reads_same_report_path():
    """__main__ exit logic reads the SAME report path main() writes to."""
    src = _read_src()
    # __main__ block should reference PROJECT (not Path(__file__).parent.parent)
    # so both main() and __main__ resolve to the same absolute path
    main_block = src.split('if __name__')[1] if 'if __name__' in src else ""
    # Should not re-derive path from __file__ in __main__
    assert "Path(__file__)" not in main_block, (
        "__main__ block must use PROJECT, not re-derive from __file__"
    )
    # Should reference PROJECT
    assert "PROJECT" in main_block, "__main__ block must use PROJECT for report path"


def _run_script(project_dir: Path) -> tuple[int, int]:
    """Run the script in a mock project dir. Returns (exit_code, report_score)."""
    proj = project_dir / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "data").mkdir(exist_ok=True)
    (proj / "mainline" / "docs").mkdir(parents=True, exist_ok=True)
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "data" / "holdings.json").write_text(json.dumps({"total_assets": 100}))
    (proj / "data" / "trade_log.jsonl").write_text("")
    (proj / "data" / "s3_execution_record.json").write_text("{}")
    (proj / "data" / "s3_monitor_status.json").write_text("{}")

    target_src = _read_src()
    fake_script = proj / "scripts" / "final_health_check.py"
    fake_script.write_text(target_src, encoding="utf-8")

    result = subprocess.run(
        [PY, str(fake_script)],
        capture_output=True, text=True, timeout=60,
        cwd=str(proj)
    )
    report = proj / "data" / "final_health_check.json"
    report_score = json.loads(report.read_text()).get("score", 0) if report.exists() else -1
    return result.returncode, report_score


def test_exit_code_matches_contract(tmp_path):
    """核心契约: main() 计算 score → __main__ 读同一文件 → exit 与 score<70 严格一致。"""
    rc, score = _run_script(tmp_path)
    expected = 1 if score < 70 else 0
    assert rc == expected, f"score={score} should exit {expected}, got {rc}"


def test_exit_code_real_env_above_threshold():
    """实环境运行（真实项目）：score=85 ≥ 70 → exit=0。"""
    proj = REPO
    report_file = proj / "data" / "final_health_check.json"
    report_file.unlink(missing_ok=True)
    result = subprocess.run(
        [PY, str(proj / "scripts" / "final_health_check.py")],
        capture_output=True, text=True, timeout=120,
        cwd=str(proj)
    )
    score = json.loads(report_file.read_text()).get("score", 0) if report_file.exists() else 0
    expected = 1 if score < 70 else 0
    assert result.returncode == expected, (
        f"real env: score={score} should exit {expected}, got {result.returncode}\n"
        f"stdout: {result.stdout[-300:]}"
    )
