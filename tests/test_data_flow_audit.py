"""RED test: data_flow_audit.py detects orphan producers with >= 95% accuracy.

SC-005: 数据流审计每日运行成功率 >= 99%，孤儿文件检测准确率 >= 95%。
US5 Acceptance Scenario 1: 所有数据文件均有消费方 → status=intact.
US5 Acceptance Scenario 2: 某数据文件无消费方 → orphan_producers 非空，P2 告警。
"""

import pytest
import sys
import json
import tempfile
import shutil
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJ_ROOT / "scripts"


def test_orphan_detection_accuracy():
    """T012 RED: inject an orphan file, run audit, verify it's detected as orphan_producer."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    # Create a temp data dir with one known-orphan JSON file
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create a JSON file that no script references (orphan)
        orphan_file = tmp_path / "orphan_test.json"
        orphan_file.write_text('{"test": true}', encoding="utf-8")

        # Create a normal JSON file that looks referenced
        normal_file = tmp_path / "normal_data.json"
        normal_file.write_text('{"test": false}', encoding="utf-8")

        report = data_flow_audit.run_audit(data_dir=tmp_path)

        # The orphan file should be detected
        orphans = report.get("orphan_producers", [])
        assert orphan_file.name in orphans or any(
            orphan_file.name in str(p) for p in orphans
        ), (
            f"Expected orphan file '{orphan_file.name}' to be detected as orphan_producer. "
            f"Got orphans: {orphans}"
        )


def test_intact_status_when_no_orphans():
    """US5 AS1: all files have consumers → status=intact, orphan_producers=[]."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Create a JSON file and a script that references it
        data_file = tmp_path / "referenced.json"
        data_file.write_text('{"val": 1}', encoding="utf-8")

        script_file = tmp_path / "consumer.py"
        script_file.write_text(f'open("{data_file}")', encoding="utf-8")

        report = data_flow_audit.run_audit(data_dir=tmp_path)
        assert report["status"] == "intact", (
            f"Expected status='intact' when no orphans, got '{report['status']}'"
        )
        assert report["orphan_producers"] == [], (
            f"Expected no orphan producers, got {report['orphan_producers']}"
        )


def test_p0_alert_on_missing_file():
    """T031: audit finds script reading non-existent file → P0 alert."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Script references a file that doesn't exist
        script_file = tmp_path / "broken_consumer.py"
        script_file.write_text('open("/nonexistent/path/data.json")', encoding="utf-8")

        report = data_flow_audit.run_audit(data_dir=tmp_path)
        orphans = report.get("orphan_consumers", [])
        # The missing file should be flagged
        assert any("nonexistent" in str(o) for o in orphans), (
            f"Expected missing file to be flagged as orphan_consumer, got {orphans}"
        )


def test_scan_dirs_default_backward_compatible():
    """附加-2: 未配置 config.json 键、未设环境变量时，扫描目录回退原始默认值。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    import os
    saved = os.environ.pop("DATA_FLOW_SCAN_DIRS", None)
    try:
        proj = Path(__file__).resolve().parent.parent
        assert data_flow_audit.resolve_scan_dirs(proj) == ["scripts", "dashboards"]
    finally:
        if saved is not None:
            os.environ["DATA_FLOW_SCAN_DIRS"] = saved


def test_scan_dirs_env_override(monkeypatch):
    """附加-2: 环境变量 DATA_FLOW_SCAN_DIRS（逗号分隔、容忍空格）覆盖默认。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    monkeypatch.setenv("DATA_FLOW_SCAN_DIRS", "scripts, dashboards , core,backtest,team")
    proj = Path(__file__).resolve().parent.parent
    assert data_flow_audit.resolve_scan_dirs(proj) == [
        "scripts", "dashboards", "core", "backtest", "team"
    ]


def test_scan_dirs_config_json_beats_env(monkeypatch):
    """附加-2 优先级: config.json 的 data_flow_scan_dirs 键 > 环境变量 > 默认值。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    monkeypatch.setenv("DATA_FLOW_SCAN_DIRS", "scripts,dashboards")
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "config.json").write_text(
            json.dumps({"data_flow_scan_dirs": ["scripts", "core/"]}), encoding="utf-8"
        )
        # config.json 优先于环境变量，且去掉尾部斜杠
        assert data_flow_audit.resolve_scan_dirs(proj) == ["scripts", "core"]

    # 配置面非法值（非 list）→ 回退环境变量
    monkeypatch.setenv("DATA_FLOW_SCAN_DIRS", "team")
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "config.json").write_text(json.dumps({"data_flow_scan_dirs": "bad"}), encoding="utf-8")
        assert data_flow_audit.resolve_scan_dirs(proj) == ["team"]


def test_batch_cache_excluded_from_contract_denominator():
    """SC-005 A+C 收口：批量缓存目录文件不入契约资产分母、归 batch_cache 桶。

    - classify_bucket：默认排除目录（history_daily/factors/akshare）命中 → batch_cache；
      日期戳模式命中 → ephemeral；其余 → contract_assets。
    - 报告分桶计数：批量目录文件计入 batch_cache，contract_assets 桶不含批量文件。
    - 排除清单配置面：config.json data_flow_excluded_dirs/patterns 键 > 默认值。
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    dirs = list(data_flow_audit.DEFAULT_EXCLUDED_DIRS)
    pats = list(data_flow_audit.DEFAULT_EXCLUDED_PATTERNS)
    assert data_flow_audit.classify_bucket("data/history_daily/sh600000_20260928.json", dirs, pats) == "batch_cache"
    assert data_flow_audit.classify_bucket("data/factors/ic_v2.json", dirs, pats) == "batch_cache"
    assert data_flow_audit.classify_bucket("data/akshare/finance.json", dirs, pats) == "batch_cache"
    # 嵌套子目录也命中（目录级排除）
    assert data_flow_audit.classify_bucket("data/factors/daily/sh000001.json", dirs, pats) == "batch_cache"
    # 文件名撞目录名不误伤（data/factors.json 根级文件 → 非批量）
    assert data_flow_audit.classify_bucket("data/factors.json", dirs, pats) == "contract_assets"
    # 日期戳/临时件 → ephemeral
    assert data_flow_audit.classify_bucket("data/reports/x_20261025.json", dirs, pats) == "ephemeral"
    assert data_flow_audit.classify_bucket("data/x.bak_20261017.json", dirs, pats) == "ephemeral"
    # 稳定资产 → contract_assets（分母所在桶）
    assert data_flow_audit.classify_bucket("data/holdings.json", dirs, pats) == "contract_assets"

    # 报告分桶计数：批量目录文件只进 batch_cache，不进 contract_assets
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        batch_file = tmp_path / "history_daily" / "sh600000.json"
        batch_file.parent.mkdir(parents=True)
        batch_file.write_text("{}", encoding="utf-8")
        dated_file = tmp_path / "x_20260101.json"
        dated_file.write_text("{}", encoding="utf-8")
        stable_file = tmp_path / "stable_probe_001.json"
        stable_file.write_text("{}", encoding="utf-8")
        report = data_flow_audit.run_audit(data_dir=tmp_path,
                                            ledger_path=tmp_path / "no_such_ledger.json")
        buckets = report["buckets"]
        # 三个文件各自归桶：batch_cache=1, ephemeral=1, contract_assets=1（互不混入）
        assert buckets["batch_cache"]["files"] == 1
        assert buckets["ephemeral"]["files"] == 1
        assert buckets["contract_assets"]["files"] == 1
        assert buckets["contract_assets"]["orphans"] == 1
        # 无台账 → 判据未生效（denominator 为 None，不得用 null 台账顶账）
        assert buckets["judgment"]["denominator"] is None

    # 排除清单配置面：config.json 自定义目录 > 默认值
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "config.json").write_text(json.dumps({
            "data_flow_excluded_dirs": ["custom_batch"],
            "data_flow_excluded_patterns": ["_tmp_"],
        }), encoding="utf-8")
        assert data_flow_audit.resolve_excluded_dirs(proj) == ["custom_batch"]
        assert data_flow_audit.resolve_excluded_patterns(proj) == ["_tmp_"]
        assert data_flow_audit.classify_bucket(
            "data/custom_batch/x.json",
            data_flow_audit.resolve_excluded_dirs(proj),
            data_flow_audit.resolve_excluded_patterns(proj),
        ) == "batch_cache"

    # 默认值（无配置、无环境变量）：三批量目录 + 五日期戳模式随代码入库
    import os
    saved = {k: os.environ.pop(k, None) for k in ("DATA_FLOW_EXCLUDED_DIRS", "DATA_FLOW_EXCLUDED_PATTERNS")}
    try:
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            assert data_flow_audit.resolve_excluded_dirs(proj) == list(data_flow_audit.DEFAULT_EXCLUDED_DIRS)
            assert data_flow_audit.resolve_excluded_patterns(proj) == list(data_flow_audit.DEFAULT_EXCLUDED_PATTERNS)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_injected_orphan_still_detected_no_accuracy_regression():
    """SC-005 准确率不退化：注入假孤儿文件（稳定命名）仍被检出为 orphan_producer，
    且计入 contract_assets 桶孤儿计数——分桶/排除不得掩盖真实孤儿。"""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import data_flow_audit
    except ModuleNotFoundError:
        pytest.skip("data_flow_audit.py not yet implemented (RED phase)")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        fake_orphan = tmp_path / "zz_fake_orphan_probe.json"
        fake_orphan.write_text('{"fake": true}', encoding="utf-8")

        report = data_flow_audit.run_audit(data_dir=tmp_path,
                                           ledger_path=tmp_path / "no_such_ledger.json")
        # 假孤儿必须被检出（准确率不退化的核心断言）
        assert any("zz_fake_orphan_probe.json" in str(p) for p in report["orphan_producers"]), (
            f"注入的假孤儿未被检出: orphans={report['orphan_producers']}"
        )
        # 且归入契约资产桶孤儿计数（稳定命名不被排除清单误伤）
        assert report["buckets"]["contract_assets"]["orphans"] >= 1
        assert report["buckets"]["contract_assets"]["files"] >= 1
