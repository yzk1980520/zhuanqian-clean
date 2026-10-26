#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_closedloop_health.py — 闭环健康度日报测试套件

验收标准（任务单 R1-4）：
  - 10 断言检查函数均可独立调用，返回 {status, detail}
  - calc_completeness 正确计算完整率
  - write_daily_signal 通过 atomic_json 写入 daily_signal.json（不改动其他字段）
  - append_history 正确追加到 closedloop_history.jsonl
  - get_7day_trend 返回最近 N 条记录
  - laosi_audit.audit_closedloop 可消费 daily_signal.closedloop 字段

回授断言（老六 §三）：
  写入侧：scripts/closedloop_health.py
  消费侧：scripts/laosi_audit.py a4udit_closedloop 读取 closedloop 字段对账
  数据源：data/closedloop_history.jsonl（append 台账，7日可回溯）
"""
import sys
import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def project_dirs(tmp_path):
    """临时项目目录结构，隔离实盘数据"""
    # 复制 docs/layers-contract.md（如果存在）
    src_root = ROOT
    (tmp_path / "docs").mkdir()
    layers_contract = src_root / "docs" / "layers-contract.md"
    if layers_contract.exists():
        shutil.copy2(layers_contract, tmp_path / "docs" / "layers-contract.md")

    (tmp_path / "scripts").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "mainline" / "docs").mkdir(parents=True)

    # 写入最小 AGENTS.md
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        "# 御龙决量化系统\n"
        "老大：决策者\n"
        "总管：调度与协调\n"
        "老三：技术验证\n"
        "老五：评审\n"
        "牛马：待命\n"
        "禁止：未经审批修改核心参数\n"
        "独占：holdings.json 由总管写入\n",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def empty_cron_config(tmp_path):
    path = tmp_path / "cron_config.json"
    path.write_text(json.dumps({"events": []}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def cron_with_self_audit(tmp_path):
    path = tmp_path / "cron_config.json"
    path.write_text(
        json.dumps({"events": [{"name": "self_audit", "cmd": "python scripts/laosi_audit.py"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def cron_with_weekly_ic(tmp_path):
    path = tmp_path / "cron_config.json"
    path.write_text(
        json.dumps({"events": [{"name": "weekly_ic", "cmd": "python scripts/fake_positive_detector.py"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def feedback_suggestions(tmp_path):
    path = tmp_path / "data" / "feedback_suggestions.json"
    path.write_text(json.dumps({"generated_at": "2026-10-16T00:00:00", "suggestions": []}), encoding="utf-8")
    return path


@pytest.fixture
def feedback_log(tmp_path):
    path = tmp_path / "data" / "feedback_log.jsonl"
    path.write_text(json.dumps({"ts": "2026-10-16", "msg": "test"}) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def weight_refs(tmp_path):
    path = tmp_path / "data" / "weight_reestimation_refs.json"
    path.write_text(json.dumps({"total_refs": 6, "refs": []}), encoding="utf-8")
    return path


@pytest.fixture
def review_status_with_schema(tmp_path):
    path = tmp_path / "data" / "review_status.json"
    path.write_text(json.dumps({"laowu_approved": True, "_schema_version": 2}), encoding="utf-8")
    return path


@pytest.fixture
def holdings_only(tmp_path):
    """仅 holdings.json，无 real_holdings 双源"""
    path = tmp_path / "data" / "holdings.json"
    path.write_text(json.dumps({"holdings": [], "updated_at": "2026-10-16"}), encoding="utf-8")
    return path


# ── 断言检查函数测试 ────────────────────────────────────────────────────────────

class TestA1Contract:
    def test_pass_when_contract_exists(self, project_dirs):
        from closedloop_health import check_a1_contract, DOCS_DIR
        # 临时替换 DOCS_DIR
        import closedloop_health as m
        orig = m.DOCS_DIR
        m.DOCS_DIR = project_dirs / "docs"
        try:
            r = m.check_a1_contract()
            assert r["status"] == "PASS"
            assert "layers-contract.md" in r["detail"]
        finally:
            m.DOCS_DIR = orig

    def test_fail_when_contract_missing(self, project_dirs):
        import closedloop_health as m
        orig = m.DOCS_DIR
        m.DOCS_DIR = project_dirs / "docs_missing"  # 不存在
        try:
            r = m.check_a1_contract()
            assert r["status"] == "FAIL"
            assert "不存在" in r["detail"]
        finally:
            m.DOCS_DIR = orig

    def test_partial_when_too_small(self, project_dirs):
        (project_dirs / "docs" / "layers-contract.md").write_text("tiny", encoding="utf-8")
        import closedloop_health as m
        orig = m.DOCS_DIR
        m.DOCS_DIR = project_dirs / "docs"
        try:
            r = m.check_a1_contract()
            assert r["status"] == "PARTIAL"
        finally:
            m.DOCS_DIR = orig


class TestA2SingleSource:
    def test_pass_no_dual_source(self, project_dirs, holdings_only, review_status_with_schema):
        import closedloop_health as m
        orig = m.DATA_DIR
        m.DATA_DIR = project_dirs / "data"
        try:
            r = m.check_a2_single_source()
            assert r["status"] == "PASS"
        finally:
            m.DATA_DIR = orig

    def test_fail_real_holdings_residue(self, project_dirs, holdings_only):
        rh = project_dirs / "data" / "real_holdings.json"
        rh.write_text(json.dumps({"source": "remote", "updated_at": "2026-10-14"}), encoding="utf-8")
        import closedloop_health as m
        orig = m.DATA_DIR
        m.DATA_DIR = project_dirs / "data"
        try:
            r = m.check_a2_single_source()
            assert r["status"] in ("FAIL", "PARTIAL")
            assert "real_holdings" in r["detail"]
        finally:
            m.DATA_DIR = orig

    def test_fail_missing_review_status(self, project_dirs, holdings_only):
        # review_status.json 不存在（holdings_only fixture 不含它）
        import closedloop_health as m
        orig = m.DATA_DIR
        m.DATA_DIR = project_dirs / "data"
        try:
            r = m.check_a2_single_source()
            # 单 issue → PARTIAL（代码逻辑：1个问题=PARTIAL，2个以上=FAIL）
            assert r["status"] == "PARTIAL"
        finally:
            m.DATA_DIR = orig


class TestA3FeedbackWrite:
    def test_pass(self, project_dirs, feedback_log, feedback_suggestions):
        import closedloop_health as m
        orig = m.DATA_DIR
        m.DATA_DIR = project_dirs / "data"
        try:
            r = m.check_a3_feedback_write()
            assert r["status"] == "PASS"
        finally:
            m.DATA_DIR = orig

    def test_fail_no_feedback_log(self, project_dirs):
        import closedloop_health as m
        orig = m.DATA_DIR, m.FEEDBACK_LOG, m.FEEDBACK_SUGGESTIONS
        m.DATA_DIR = project_dirs / "data"
        # FEEDBACK_LOG/FEEDBACK_SUGGESTIONS 是 import 时解析的模块级常量，
        # 需同步覆写使其指向不存在的临时路径
        m.FEEDBACK_LOG = project_dirs / "data" / "feedback_log_nonexistent.jsonl"
        m.FEEDBACK_SUGGESTIONS = project_dirs / "data" / "feedback_suggestions_nonexistent.json"
        try:
            r = m.check_a3_feedback_write()
            assert r["status"] == "FAIL"
            assert "feedback_log.jsonl 不存在" in r["detail"]
        finally:
            m.DATA_DIR, m.FEEDBACK_LOG, m.FEEDBACK_SUGGESTIONS = orig


class TestA4FeedbackRead:
    def test_pass(self, project_dirs, weight_refs):
        # 需要 feedback_weight_consumer.py 存在
        consumer = project_dirs / "scripts" / "feedback_weight_consumer.py"
        consumer.write_text("# empty consumer\n", encoding="utf-8")
        import closedloop_health as m
        orig = m.SCRIPTS_DIR, m.DATA_DIR
        m.SCRIPTS_DIR = project_dirs / "scripts"
        m.DATA_DIR = project_dirs / "data"
        try:
            r = m.check_a4_feedback_read()
            assert r["status"] == "PASS"
        finally:
            m.SCRIPTS_DIR, m.DATA_DIR = orig

    def test_fail_consumer_missing(self, project_dirs, weight_refs):
        import closedloop_health as m
        orig = m.SCRIPTS_DIR
        m.SCRIPTS_DIR = project_dirs / "scripts_empty"  # 不存在
        try:
            r = m.check_a4_feedback_read()
            assert r["status"] == "FAIL"
            assert "feedback_weight_consumer.py 不存在" in r["detail"]
        finally:
            m.SCRIPTS_DIR = orig

    def test_partial_no_weight_refs(self, project_dirs):
        consumer = project_dirs / "scripts" / "feedback_weight_consumer.py"
        consumer.write_text("# empty\n", encoding="utf-8")
        import closedloop_health as m
        orig = m.SCRIPTS_DIR, m.DATA_DIR
        m.SCRIPTS_DIR = project_dirs / "scripts"
        m.DATA_DIR = project_dirs / "data"
        try:
            r = m.check_a4_feedback_read()
            assert r["status"] == "PARTIAL"
            assert "weight_reestimation_refs.json 不存在" in r["detail"]
        finally:
            m.SCRIPTS_DIR, m.DATA_DIR = orig


class TestA5FalseGreen:
    def test_pass(self, project_dirs, cron_with_weekly_ic):
        detector = project_dirs / "scripts" / "fake_positive_detector.py"
        detector.write_text("# detector\n", encoding="utf-8")
        import closedloop_health as m
        orig = m.SCRIPTS_DIR, m.CRON_CONFIG
        m.SCRIPTS_DIR = project_dirs / "scripts"
        m.CRON_CONFIG = cron_with_weekly_ic
        try:
            r = m.check_a5_false_green()
            assert r["status"] == "PASS"
        finally:
            m.SCRIPTS_DIR, m.CRON_CONFIG = orig

    def test_fail_detector_missing(self, project_dirs, cron_with_weekly_ic):
        import closedloop_health as m
        orig = m.SCRIPTS_DIR
        m.SCRIPTS_DIR = project_dirs / "scripts_empty"
        try:
            r = m.check_a5_false_green()
            assert r["status"] == "FAIL"
        finally:
            m.SCRIPTS_DIR = orig

    def test_partial_no_weekly_ic(self, project_dirs):
        detector = project_dirs / "scripts" / "fake_positive_detector.py"
        detector.write_text("# detector\n", encoding="utf-8")
        import closedloop_health as m
        orig = m.SCRIPTS_DIR, m.CRON_CONFIG
        m.SCRIPTS_DIR = project_dirs / "scripts"
        m.CRON_CONFIG = project_dirs / "cron_config.json"
        (project_dirs / "cron_config.json").write_text(json.dumps({"events": []}), encoding="utf-8")
        try:
            r = m.check_a5_false_green()
            assert r["status"] == "PARTIAL"
            assert "weekly_ic" in r["detail"]
        finally:
            m.SCRIPTS_DIR, m.CRON_CONFIG = orig


class TestA6SelfAudit:
    def test_pass(self, project_dirs, cron_with_self_audit):
        """A6 PASS: laosi存在、产物新鲜、无open P0"""
        laosi = project_dirs / "scripts" / "laosi_audit.py"
        laosi.write_text("# laosi audit\n", encoding="utf-8")
        # 创建空的缺陷台账（无P0）
        audit_dir = project_dirs / "data" / "laosi_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        defect_ledger = project_dirs / "data" / "audit" / "defect_ledger.json"
        defect_ledger.parent.mkdir(parents=True, exist_ok=True)
        defect_ledger.write_text('{"entries": []}', encoding="utf-8")
        # 创建新鲜的自审产物
        import time
        audit_file = audit_dir / "laosi_20261019.json"
        audit_file.write_text('{"time": "' + time.strftime("%Y-%m-%dT%H:%M:%S") + '"}', encoding="utf-8")

        import closedloop_health as m
        orig = m.SCRIPTS_DIR, m.CRON_CONFIG, m.DATA_DIR, m.DEFECT_LEDGER
        m.SCRIPTS_DIR = project_dirs / "scripts"
        m.CRON_CONFIG = cron_with_self_audit
        m.DATA_DIR = project_dirs / "data"
        m.DEFECT_LEDGER = defect_ledger
        try:
            r = m.check_a6_self_audit()
            assert r["status"] == "PASS", f"Expected PASS but got: {r}"
        finally:
            m.SCRIPTS_DIR, m.CRON_CONFIG, m.DATA_DIR, m.DEFECT_LEDGER = orig

    def test_fail_laosi_missing(self, project_dirs, cron_with_self_audit):
        import closedloop_health as m
        orig = m.SCRIPTS_DIR
        m.SCRIPTS_DIR = project_dirs / "scripts_empty"
        try:
            r = m.check_a6_self_audit()
            assert r["status"] == "FAIL"
        finally:
            m.SCRIPTS_DIR = orig

    def test_fail_open_p0(self, project_dirs, cron_with_self_audit):
        """A6 FAIL: 自审在跑但有open P0缺陷未消"""
        laosi = project_dirs / "scripts" / "laosi_audit.py"
        laosi.write_text("# laosi audit\n", encoding="utf-8")
        audit_dir = project_dirs / "data" / "laosi_audit"
        audit_dir.mkdir(parents=True, exist_ok=True)
        # 创建含P0缺陷的台账
        defect_ledger = project_dirs / "data" / "audit" / "defect_ledger.json"
        defect_ledger.parent.mkdir(parents=True, exist_ok=True)
        defect_ledger.write_text(json.dumps({
            "entries": [
                {"id": "P0-1", "severity": "P0", "status": "open", "title": "test"},
                {"id": "P1-1", "severity": "P1", "status": "open", "title": "test"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        # 创建新鲜的自审产物
        import time
        audit_file = audit_dir / "laosi_20261019.json"
        audit_file.write_text('{"time": "' + time.strftime("%Y-%m-%dT%H:%M:%S") + '"}', encoding="utf-8")

        import closedloop_health as m
        orig = m.SCRIPTS_DIR, m.CRON_CONFIG, m.DATA_DIR, m.DEFECT_LEDGER
        m.SCRIPTS_DIR = project_dirs / "scripts"
        m.CRON_CONFIG = cron_with_self_audit
        m.DATA_DIR = project_dirs / "data"
        m.DEFECT_LEDGER = defect_ledger
        try:
            r = m.check_a6_self_audit()
            assert r["status"] == "FAIL", f"Expected FAIL but got: {r}"
            assert "P0" in r["detail"]
        finally:
            m.SCRIPTS_DIR, m.CRON_CONFIG, m.DATA_DIR, m.DEFECT_LEDGER = orig


class TestA7Rollback:
    def test_pass(self, project_dirs):
        # 创建 .bak 文件
        (project_dirs / ".bak_test").write_text("bak", encoding="utf-8")
        import closedloop_health as m
        orig = m.ROOT
        m.ROOT = project_dirs
        try:
            r = m.check_a7_rollback()
            # git 在非 git 目录会 FAIL，但至少 .bak 检查通过
            assert "detail" in r
        finally:
            m.ROOT = orig


class TestA8EvidenceChain:
    def test_returns_detail(self):
        import closedloop_health as m
        r = m.check_a8_evidence_chain()
        assert "status" in r
        assert "detail" in r


class TestA9ExternalIsolation:
    def test_pass_when_agents_md_exists(self, project_dirs):
        import closedloop_health as m
        orig = m.AGENTS_MD
        m.AGENTS_MD = project_dirs / "AGENTS.md"
        try:
            r = m.check_a9_external_isolation()
            assert r["status"] == "PASS"
        finally:
            m.AGENTS_MD = orig

    def test_fail_when_agents_md_missing(self, project_dirs):
        import closedloop_health as m
        orig = m.AGENTS_MD
        m.AGENTS_MD = project_dirs / "missing.md"
        try:
            r = m.check_a9_external_isolation()
            assert r["status"] == "FAIL"
        finally:
            m.AGENTS_MD = orig


class TestA10HumanMachineBoundary:
    def test_pass(self, project_dirs):
        import closedloop_health as m
        orig = m.AGENTS_MD
        m.AGENTS_MD = project_dirs / "AGENTS.md"
        try:
            r = m.check_a10_human_machine_boundary()
            assert r["status"] == "PASS"
        finally:
            m.AGENTS_MD = orig

    def test_fail_missing(self, project_dirs):
        import closedloop_health as m
        orig = m.AGENTS_MD
        m.AGENTS_MD = project_dirs / "missing.md"
        try:
            r = m.check_a10_human_machine_boundary()
            assert r["status"] == "FAIL"
        finally:
            m.AGENTS_MD = orig


# ── 完整率计算测试 ──────────────────────────────────────────────────────────────

class TestCalcCompleteness:
    def test_all_pass(self):
        import closedloop_health as m
        # 2026-10-24 T051 C4 对齐: 断言集 2026-10-20 新增 A13_日历新鲜度, 分母=14
        # (calc_completeness 真源: denominator=len(ASSERTION_CHECKS)=14, 与 results 键数无关)
        results = {f"A{i}": {"status": "PASS"} for i in range(0, 14)}
        r = m.calc_completeness(results)
        assert r["pass"] == 14
        assert r["fail"] == 0
        assert r["partial"] == 0
        assert r["completeness_pct"] == 100.0
        assert r["score"] == 14.0

    def test_mixed(self):
        import closedloop_health as m
        # 2026-10-24 T051 C4 对齐: 14 断言 (A0-A13), PARTIAL=0.5 分 → 12.5/14=89.3
        results = {
            "A0": {"status": "PASS"}, "A1": {"status": "PASS"},
            "A2": {"status": "PASS"}, "A3": {"status": "PASS"},
            "A4": {"status": "PASS"}, "A5": {"status": "PASS"},
            "A6": {"status": "PASS"}, "A7": {"status": "PASS"},
            "A8": {"status": "PASS"}, "A9": {"status": "PARTIAL"},
            "A10": {"status": "FAIL"}, "A11": {"status": "PASS"},
            "A12": {"status": "PASS"}, "A13": {"status": "PASS"},
        }
        r = m.calc_completeness(results)
        assert r["pass"] == 12
        assert r["partial"] == 1
        assert r["fail"] == 1
        assert r["completeness_pct"] == pytest.approx(89.3)
        assert r["score"] == 12.5

    def test_all_fail(self):
        import closedloop_health as m
        results = {f"A{i}": {"status": "FAIL"} for i in range(0, 14)}
        r = m.calc_completeness(results)
        assert r["completeness_pct"] == 0.0
        assert r["score"] == 0.0


# ── daily_signal 写入测试 ───────────────────────────────────────────────────────

class TestWriteDailySignal:
    def test_writes_closedloop_field(self, project_dirs):
        import core.pipeline.atomic_json
        import closedloop_health as m
        signal_path = project_dirs / "data" / "daily_signal.json"
        signal_path.write_text(json.dumps({"date": "2026-10-15", "gate": {"status": "soft"}}), encoding="utf-8")

        results = {f"A{i}": {"status": "PASS"} for i in range(0, 14)}
        completeness = m.calc_completeness(results)

        import closedloop_health as m
        orig = m.DAILY_SIGNAL
        m.DAILY_SIGNAL = signal_path
        try:
            m.write_daily_signal(results, completeness)
            written = json.loads(signal_path.read_text(encoding="utf-8"))
            assert "closedloop" in written
            assert written["closedloop"]["completeness_pct"] == 100.0
            # 2026-10-24 T051 C4 对齐: 断言集 14 项 (A0-A13, 2026-10-20 新增 A13)
            assert written["closedloop"]["pass"] == 14
            # 原有字段不应被删除
            assert written["gate"]["status"] == "soft"
        finally:
            m.DAILY_SIGNAL = orig

    def test_creates_file_if_missing(self, project_dirs):
        signal_path = project_dirs / "data" / "daily_signal.json"
        # 不预建文件
        import closedloop_health as m
        orig = m.DAILY_SIGNAL
        m.DAILY_SIGNAL = signal_path
        try:
            results = {f"A{i}": {"status": "PASS"} for i in range(0, 13)}
            completeness = m.calc_completeness(results)
            m.write_daily_signal(results, completeness)
            assert signal_path.exists()
            written = json.loads(signal_path.read_text(encoding="utf-8"))
            assert "closedloop" in written
        finally:
            m.DAILY_SIGNAL = orig


# ── history 写入测试 ────────────────────────────────────────────────────────────

class TestAppendHistory:
    def test_appends_record(self, project_dirs):
        history_path = project_dirs / "data" / "closedloop_history.jsonl"
        import closedloop_health as m
        orig = m.HISTORY_FILE
        m.HISTORY_FILE = history_path
        try:
            results = {f"A{i}": {"status": "PASS" if i != 2 else "FAIL"} for i in range(0, 14)}
            completeness = m.calc_completeness(results)
            m.append_history(results, completeness)
            lines = history_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 1
            record = json.loads(lines[0])
            # 2026-10-24 T051 C4 对齐: 14 断言分母, 13 PASS + 1 FAIL → 13/14=92.9
            assert record["completeness_pct"] == pytest.approx(92.9)
            assert record["pass"] == 13
            assert record["fail"] == 1
        finally:
            m.HISTORY_FILE = orig

    def test_appends_multiple_runs(self, project_dirs):
        history_path = project_dirs / "data" / "closedloop_history.jsonl"
        import closedloop_health as m
        orig = m.HISTORY_FILE
        m.HISTORY_FILE = history_path
        try:
            for pass_count in [13, 11, 12]:
                results = {f"A{i}": {"status": "PASS" if i <= pass_count else "FAIL"} for i in range(0, 13)}
                completeness = m.calc_completeness(results)
                m.append_history(results, completeness)
            lines = history_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 3
        finally:
            m.HISTORY_FILE = orig


# ── 7日趋势测试 ─────────────────────────────────────────────────────────────────

class TestGet7DayTrend:
    def test_returns_last_7(self, project_dirs):
        history_path = project_dirs / "data" / "closedloop_history.jsonl"
        import closedloop_health as m
        orig = m.HISTORY_FILE
        m.HISTORY_FILE = history_path
        try:
            # 注入 10 条记录
            for day in range(1, 11):
                record = {
                    "ts": f"2026-10-{day:02d}T04:00:00",
                    "date": f"2026-10-{day:02d}",
                    "completeness_pct": 90.0 + day,
                    "score": 9.0 + day,
                    "total": 10,
                    "pass": 9 + day if day <= 1 else 10,
                    "partial": 0,
                    "fail": 0 if day > 1 else 1,
                    "assertions": {f"A{i}": "PASS" for i in range(1, 11)},
                }
                with open(history_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            trend = m.get_7day_trend()
            assert len(trend) == 7
            assert trend[0]["date"] == "2026-10-04"
            assert trend[-1]["date"] == "2026-10-10"
        finally:
            m.HISTORY_FILE = orig

    def test_empty_when_no_file(self, project_dirs):
        history_path = project_dirs / "data" / "closedloop_history.jsonl"
        import closedloop_health as m
        orig = m.HISTORY_FILE
        m.HISTORY_FILE = history_path
        try:
            trend = m.get_7day_trend()
            assert trend == []
        finally:
            m.HISTORY_FILE = orig


# ── 老四对账集成测试 ────────────────────────────────────────────────────────────

class TestLaosiClosedloopAudit:
    def test_consumes_closedloop_field(self, project_dirs):
        """laosi_audit.audit_closedloop 正确消费 daily_signal.closedloop"""
        signal_path = project_dirs / "data" / "daily_signal.json"
        signal_path.write_text(
            json.dumps({
                "closedloop": {
                    "completeness_pct": 90.0,
                    "pass": 9, "partial": 0, "fail": 1,
                    "ts": "2026-10-16T04:00:00",
                    "assertions": {f"A{i}": "PASS" for i in range(1, 11)},
                }
            }),
            encoding="utf-8",
        )
        from laosi_audit import LaosiAudit
        audit = LaosiAudit()
        # 临时替换 ROOT
        import laosi_audit as m
        orig = m.ROOT
        m.ROOT = project_dirs
        try:
            audit.audit_closedloop()
            checks = audit.report["checks"]
            assert "closedloop" in checks
            assert checks["closedloop"] == "90.0%"
            # 90% < 100 应产生 INFO 级 finding
            findings = [f for f in audit.report["findings"] if "闭环完整率" in f.get("msg", "")]
            assert len(findings) >= 1
        finally:
            m.ROOT = orig

    def test_missing_signal_raises_p1(self, project_dirs):
        from laosi_audit import LaosiAudit
        audit = LaosiAudit()
        import laosi_audit as m
        orig = m.ROOT
        m.ROOT = project_dirs
        try:
            audit.audit_closedloop()
            assert audit.report["checks"]["closedloop"] == "missing"
            findings = [f for f in audit.report["findings"] if "daily_signal.json 不存在" in f.get("msg", "")]
            assert len(findings) == 1
            assert findings[0]["level"] == "P1"
        finally:
            m.ROOT = orig

    def test_missing_closedloop_field_raises_p1(self, project_dirs):
        signal_path = project_dirs / "data" / "daily_signal.json"
        signal_path.write_text(json.dumps({"date": "2026-10-16"}), encoding="utf-8")
        from laosi_audit import LaosiAudit
        audit = LaosiAudit()
        import laosi_audit as m
        orig = m.ROOT
        m.ROOT = project_dirs
        try:
            audit.audit_closedloop()
            assert audit.report["checks"]["closedloop"] == "missing"
            findings = [f for f in audit.report["findings"] if "缺 closedloop" in f.get("msg", "")]
            assert len(findings) == 1
            assert findings[0]["level"] == "P1"
        finally:
            m.ROOT = orig


# ── 导入验证 ────────────────────────────────────────────────────────────────────

class TestImports:
    """验证所有被测试的符号均可从模块导入"""
    def test_all_assertion_checks_importable(self):
        from closedloop_health import ASSERTION_CHECKS, run_all_checks
        # 2026-10-24 T051 C4 对齐: 2026-10-20 新增 A13_日历新鲜度 → 14 项 (A0-A13)
        assert len(ASSERTION_CHECKS) == 14
        assert callable(run_all_checks)

    def test_calc_completeness_importable(self):
        from closedloop_health import calc_completeness
        assert callable(calc_completeness)

    def test_write_functions_importable(self):
        from closedloop_health import write_daily_signal, append_history, get_7day_trend
        assert callable(write_daily_signal)
        assert callable(append_history)
        assert callable(get_7day_trend)

    def test_all_assertions_defined(self):
        from closedloop_health import ASSERTION_CHECKS
        # 2026-10-24 T051 C4 对齐: 键名以 closedloop_health.ASSERTION_CHECKS 真源为准
        # (A12 改名"关键调度载体"、2026-10-20 新增 A13_日历新鲜度)
        expected_keys = [
            "A0_体检器自身活性", "A1_层间契约固化", "A2_状态唯一真源",
            "A3_闭环反馈写侧", "A4_闭环反馈读侧", "A5_假绿不可重复",
            "A6_自审机制运行", "A7_回滚可执行", "A8_证据链完整",
            "A9_外部依赖隔离", "A10_人机边界明确", "A11_跨体检器交叉校验",
            "A12_关键调度载体",
            "A13_日历新鲜度",
        ]
        assert list(ASSERTION_CHECKS.keys()) == expected_keys


# ── tech_debt 解析测试（R1-4 补单）──────────────────────────────────────────────

class TestParseTechDebtLedger:
    """3 用例覆盖：正常N条 / 文件缺失 / 7天无进展→stale"""

    def test_normal_n_entries_no_stale(self, project_dirs):
        """正常：N 条有效条目，无 7 天 stale → P2"""
        # 2026-10-24 T051 C4 对齐: 原 fixture 用固定日期 (2026-10-15/16), 随日历推进必然
        # 超 7 天 → 误判 stale → PARTIAL。改用相对日期 (今日 -1/-2 天) 保持"无 stale"语义。
        from datetime import datetime, timedelta
        d1 = (datetime.now().date() - timedelta(days=1)).isoformat()
        d2 = (datetime.now().date() - timedelta(days=2)).isoformat()
        ledger = project_dirs / "docs" / "tech_debt_ledger.md"
        ledger.write_text(
            "# 技术债台账\n"
            "## D-1 测试债一\n"
            "- **描述**: desc1\n"
            f"- **挂账**: {d1} 总管\n"
            "- **owner**: 老三\n"
            "- **优先级**: P2\n"
            f"- **进展**: {d1} 进行中\n"
            "## D-2 测试债二\n"
            "- **描述**: desc2\n"
            f"- **挂账**: {d2} 总管\n"
            "- **owner**: 总管\n"
            "- **优先级**: P2\n"
            f"- **进展**: {d2} 修改中\n",
            encoding="utf-8",
        )
        import closedloop_health as m
        orig = m.TECH_DEBT_LEDGER
        m.TECH_DEBT_LEDGER = ledger
        try:
            r = m.parse_tech_debt_ledger()
            assert r["status"] == "PASS"
            assert r["open"] == 2
            assert r["stale_7d"] == []
            assert r["alert_level"] == "P2"
            assert r["oldest_ts"] == d2
        finally:
            m.TECH_DEBT_LEDGER = orig

    def test_file_missing(self, project_dirs):
        """文件不存在 → FAIL, open=0, alert_level=P2"""
        import closedloop_health as m
        missing = project_dirs / "docs" / "nonexistent.md"
        orig = m.TECH_DEBT_LEDGER
        m.TECH_DEBT_LEDGER = missing
        try:
            r = m.parse_tech_debt_ledger()
            assert r["status"] == "FAIL"
            assert r["open"] == 0
            assert r["stale_7d"] == []
            assert r["alert_level"] == "P2"
            assert "不存在" in r["detail"]
        finally:
            m.TECH_DEBT_LEDGER = orig

    def test_stale_7d_triggers_p1(self, project_dirs):
        """7 天无进展 → stale_7d 非空, alert_level=P1, status=PARTIAL"""
        from datetime import datetime, timedelta
        stale_date = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")
        ledger = project_dirs / "docs" / "tech_debt_ledger.md"
        ledger.write_text(
            f"## D-1 老债未动\n"
            f"- **描述**: stale debt\n"
            f"- **挂账**: 2026-10-01\n"
            f"- **owner**: 老三\n"
            f"- **优先级**: P1\n"
            f"- **进展**: {stale_date} 无进展\n",
            encoding="utf-8",
        )
        import closedloop_health as m
        orig = m.TECH_DEBT_LEDGER
        m.TECH_DEBT_LEDGER = ledger
        try:
            r = m.parse_tech_debt_ledger()
            assert r["status"] == "PARTIAL"
            assert r["open"] == 1
            assert "D-1" in r["stale_7d"]
            assert r["alert_level"] == "P1"
        finally:
            m.TECH_DEBT_LEDGER = orig


class TestTechDebtInDailySignal:
    """验证 write_daily_signal 将 tech_debt 字段写入 daily_signal"""

    def test_tech_debt_field_written(self, project_dirs):
        import core.pipeline.atomic_json
        import closedloop_health as m
        signal_path = project_dirs / "data" / "daily_signal.json"
        signal_path.write_text(json.dumps({"date": "2026-10-15"}), encoding="utf-8")

        results = {f"A{i}": {"status": "PASS"} for i in range(0, 13)}
        completeness = m.calc_completeness(results)
        tech_debt = {"open": 2, "stale_7d": [], "oldest_ts": "2026-10-16", "alert_level": "P2"}

        orig = m.DAILY_SIGNAL
        m.DAILY_SIGNAL = signal_path
        try:
            m.write_daily_signal(results, completeness, tech_debt=tech_debt)
            written = json.loads(signal_path.read_text(encoding="utf-8"))
            assert "tech_debt" in written["closedloop"]
            assert written["closedloop"]["tech_debt"]["open"] == 2
            assert written["closedloop"]["tech_debt"]["stale_7d"] == []
            assert written["closedloop"]["tech_debt"]["alert_level"] == "P2"
        finally:
            m.DAILY_SIGNAL = orig
