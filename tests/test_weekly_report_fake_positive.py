#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_weekly_report_fake_positive.py — 周报假绿检查消费侧测试

验收标准（老六 R0-1c 硬要求）:
  1. 有假绿样本 → 周报出现"假绿检查: N 条"
  2. 无新条目 → 周报出现"假绿检查: 无新项目"
  3. 文件缺失 → 周报出现"假绿检查: 文件不存在"

回授断言 (§2.9):
  - 写侧: fake_positive_detector.py 写 fake_positive_log.jsonl
  - 读侧: weekly_report_generator.py 消费
  - 消费不到 = 周报失败告警段
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [tests\test_weekly_report_fake_positive.py] CR-01: except Exception:", file=sys.stderr)
# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.weekly_report_generator import (
    collect_fake_positive_data,
    render_report,
    get_week_range,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_entries():
    """生成3条假绿样本，时间在本周内"""
    today = datetime.now()
    week_start, week_end = get_week_range(
        f"{today.year}-W{today.isocalendar()[1]:02d}"
    )
    entries = []
    for i in range(3):
        entries.append({
            "ts": f"{week_start} 10:{i:02d}:00",
            "stock_code": f"60000{i + 1}",
            "stock_name": f"测试股票{i + 1}",
            "score_at_decision": 0.85,
            "decision_ts": week_start,
            "pnl_actual": -5000.0,
            "pnl_pct": -8.5,
            "ratio": 10.0,
            "evidence": "ratio=10.0(>=1.0); by_score=0.85; pnl_pct=-8.5%; strategy=s3",
        })
    return entries


@pytest.fixture
def empty_file(tmp_path):
    """创建空文件"""
    f = tmp_path / "fake_positive_log.jsonl"
    f.write_text("", encoding="utf-8")
    return f


@pytest.fixture
def file_with_old_entries(tmp_path, sample_entries):
    """创建有历史条目（上周）的文件"""
    f = tmp_path / "fake_positive_log.jsonl"
    # 写入上周的条目
    last_week = datetime.now() - timedelta(days=14)
    content = []
    for i in range(2):
        content.append(json.dumps({
            "ts": last_week.strftime("%Y-%m-%d") + " 10:00:00",
            "stock_code": f"60099{i}",
            "stock_name": f"历史股票{i}",
            "score_at_decision": 0.9,
            "decision_ts": last_week.strftime("%Y-%m-%d"),
            "pnl_actual": -3000.0,
            "pnl_pct": -5.0,
            "ratio": 5.5,
            "evidence": "test",
        }))
    f.write_text("\n".join(content) + "\n", encoding="utf-8")
    return f


# ── 三态测试 ─────────────────────────────────────────────────────────────────

class TestFakePositiveThreeStates:
    """假绿检查三态验收"""

    def test_state_file_missing(self, tmp_path):
        """状态1: 文件不存在 → '假绿检查: 文件不存在'"""
        # 确保路径不存在
        log_path = tmp_path / "nonexistent" / "fake_positive_log.jsonl"
        
        with patch(
            "scripts.weekly_report_generator.PROJECT_ROOT", tmp_path
        ):
            result = collect_fake_positive_data("2026-W42")
        
        assert result["status"] == "FILE_MISSING"
        assert "文件不存在" in result["section"]
        assert result["count"] == 0
        print(f"✅ 状态1通过: {result['section']}")

    def test_state_no_new_entries(self, tmp_path):
        """状态2: 文件有历史但本周无新增 → '假绿检查: 无新项目'"""
        # 创建完整目录结构
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"

        # 写入上周的条目
        last_week = datetime.now() - timedelta(days=14)
        content = []
        for i in range(2):
            content.append(json.dumps({
                "ts": last_week.strftime("%Y-%m-%d") + " 10:00:00",
                "stock_code": f"60099{i}",
                "stock_name": f"历史股票{i}",
                "score_at_decision": 0.9,
                "decision_ts": last_week.strftime("%Y-%m-%d"),
                "pnl_actual": -3000.0,
                "pnl_pct": -5.0,
                "ratio": 5.5,
                "evidence": "test",
            }))
        log_path.write_text("\n".join(content) + "\n", encoding="utf-8")

        # [t_039f1e18 2026-10-26 分诊] 原硬编码 "2026-W42": 当前 ISO 周越过 W42 两周后
        # (W44 起), now-14d 的"上周条目"落入 W42 窗口 → 误判 FOUND (时间敏感失效)。
        # 改请求当前 ISO 周: now-14d 恒在当前周起点前 8~14 天 (W-2/W-1 区间),
        # 永不落入当前周 → NO_NEW 稳定成立。
        today = datetime.now()
        with patch(
            "scripts.weekly_report_generator.PROJECT_ROOT", tmp_path
        ):
            result = collect_fake_positive_data(
                f"{today.year}-W{today.isocalendar()[1]:02d}"
            )

        assert result["status"] == "NO_NEW"
        assert "无新项目" in result["section"]
        assert result["count"] == 0
        print(f"✅ 状态2通过: {result['section']}")

    def test_state_found_entries(self, tmp_path):
        """状态3: 本周有新条目 → '假绿检查: N 条'"""
        # 创建完整目录结构
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"

        # 生成本周条目
        today = datetime.now()
        week_start, _ = get_week_range(
            f"{today.year}-W{today.isocalendar()[1]:02d}"
        )
        entries = []
        for i in range(3):
            entries.append({
                "ts": f"{week_start} 10:{i:02d}:00",
                "stock_code": f"60000{i + 1}",
                "stock_name": f"测试股票{i + 1}",
                "score_at_decision": 0.85,
                "decision_ts": week_start,
                "pnl_actual": -5000.0,
                "pnl_pct": -8.5,
                "ratio": 10.0,
                "evidence": "test",
            })
        log_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8"
        )

        with patch(
            "scripts.weekly_report_generator.PROJECT_ROOT", tmp_path
        ):
            result = collect_fake_positive_data(
                f"{today.year}-W{today.isocalendar()[1]:02d}"
            )

        assert result["status"] == "FOUND"
        assert result["count"] == 3
        assert "3 条" in result["section"]
        assert "600001" in result["detail"]
        print(f"✅ 状态3通过: {result['section']}")


class TestReportIntegration:
    """周报集成测试"""

    def test_render_with_file_missing(self, tmp_path):
        """渲染周报时文件缺失 → 报告含告警"""
        # 不创建 data 目录，确保文件不存在
        with patch(
            "scripts.weekly_report_generator.PROJECT_ROOT", tmp_path
        ):
            fake_pos = collect_fake_positive_data("2026-W42")
            # 构造完整数据结构
            health = {
                "score": 85, "status": "OK",
                "gateway_status": "OK", "gateway_detail": "pid=1234",
                "cron_status": "OK", "cron_detail": "总=5, 活跃=3",
                "gate_status": "OPEN", "gate_detail": "模式=soft",
                "data_status": "OK", "data_detail": "文件=3492",
                "ic_status": "OK", "ic_detail": "有效=18",
                "source_file": "health.json"
            }
            ic = {
                "valid_factors": 18, "total_factors": 20,
                "alert_count": 0, "worst_factor": "chg5",
                "worst_ic": "-0.3100", "table_rows": "",
                "trend_analysis": "正常", "source_file": "ic.json",
                "data_date": "2026-10-15", "alerts": [],
                "all_factors": {}
            }
            bt = {
                "win_rate": "64.9", "win_rate_comp": "+16.3pp vs 基准",
                "max_dd": "37.0", "dd_comp": "达标",
                "sharpe": "2.58", "sharpe_comp": "达标",
                "trade_count": 120, "avg_hold": "5.2",
                "gates_passed": 5, "gates_total": 5, "gates_failed": 0,
                "verdict": "✅ 通过", "benchmark": {}, "source": "bt.json"
            }
            events = {"p0": [], "p1": [], "p2": [], "resolved": []}
            plan = []
            report = render_report(
                "2026-W42", health, ic, bt, events, plan, fake_pos
            )

        assert "假绿检查: 文件不存在" in report
        print(f"✅ 报告集成测试通过: 文件缺失场景")

    def test_render_with_entries(self, tmp_path):
        """渲染周报时有样本 → 报告含明细"""
        # 创建完整目录结构
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"

        today = datetime.now()
        week_start, _ = get_week_range(
            f"{today.year}-W{today.isocalendar()[1]:02d}"
        )
        entries = []
        for i in range(2):
            entries.append({
                "ts": f"{week_start} 10:{i:02d}:00",
                "stock_code": f"60000{i + 1}",
                "stock_name": f"测试股票{i + 1}",
                "score_at_decision": 0.85,
                "decision_ts": week_start,
                "pnl_actual": -5000.0,
                "pnl_pct": -8.5,
                "ratio": 10.0,
                "evidence": "test",
            })
        log_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8"
        )

        with patch(
            "scripts.weekly_report_generator.PROJECT_ROOT", tmp_path
        ):
            fake_pos = collect_fake_positive_data(
                f"{today.year}-W{today.isocalendar()[1]:02d}"
            )
            health = {
                "score": 85, "status": "OK",
                "gateway_status": "OK", "gateway_detail": "pid=1234",
                "cron_status": "OK", "cron_detail": "总=5, 活跃=3",
                "gate_status": "OPEN", "gate_detail": "模式=soft",
                "data_status": "OK", "data_detail": "文件=3492",
                "ic_status": "OK", "ic_detail": "有效=18",
                "source_file": "health.json"
            }
            ic = {
                "valid_factors": 18, "total_factors": 20,
                "alert_count": 0, "worst_factor": "chg5",
                "worst_ic": "-0.3100", "table_rows": "",
                "trend_analysis": "正常", "source_file": "ic.json",
                "data_date": "2026-10-15", "alerts": [],
                "all_factors": {}
            }
            bt = {
                "win_rate": "64.9", "win_rate_comp": "+16.3pp vs 基准",
                "max_dd": "37.0", "dd_comp": "达标",
                "sharpe": "2.58", "sharpe_comp": "达标",
                "trade_count": 120, "avg_hold": "5.2",
                "gates_passed": 5, "gates_total": 5, "gates_failed": 0,
                "verdict": "✅ 通过", "benchmark": {}, "source": "bt.json"
            }
            events = {"p0": [], "p1": [], "p2": [], "resolved": []}
            plan = []
            report = render_report(
                f"{today.year}-W{today.isocalendar()[1]:02d}",
                health, ic, bt, events, plan, fake_pos
            )

        assert "假绿检查: 2 条" in report
        assert "600001" in report
        assert "测试股票1" in report
        print(f"✅ 报告集成测试通过: 有样本场景")

    def test_render_without_fake_pos(self):
        """不带 fake_pos 参数 → 降级为默认值"""
        health = {
            "score": 85, "status": "OK",
            "gateway_status": "OK", "gateway_detail": "pid=1234",
            "cron_status": "OK", "cron_detail": "总=5, 活跃=3",
            "gate_status": "OPEN", "gate_detail": "模式=soft",
            "data_status": "OK", "data_detail": "文件=3492",
            "ic_status": "OK", "ic_detail": "有效=18",
            "source_file": "health.json"
        }
        ic = {
            "valid_factors": 18, "total_factors": 20,
            "alert_count": 0, "worst_factor": "chg5",
            "worst_ic": "-0.3100", "table_rows": "",
            "trend_analysis": "正常", "source_file": "ic.json",
            "data_date": "2026-10-15", "alerts": [],
            "all_factors": {}
        }
        bt = {
            "win_rate": "64.9", "win_rate_comp": "+16.3pp vs 基准",
            "max_dd": "37.0", "dd_comp": "达标",
            "sharpe": "2.58", "sharpe_comp": "达标",
            "trade_count": 120, "avg_hold": "5.2",
            "gates_passed": 5, "gates_total": 5, "gates_failed": 0,
            "verdict": "✅ 通过", "benchmark": {}, "source": "bt.json"
        }
        events = {"p0": [], "p1": [], "p2": [], "resolved": []}
        plan = []
        report = render_report(
            "2026-W42", health, ic, bt, events, plan, None
        )

        assert "假绿检查: 无数据" in report
        print(f"✅ 降级测试通过: 无参数场景")


class TestWeekFiltering:
    """周过滤逻辑测试"""

    def test_filter_by_week(self, tmp_path):
        """测试跨周过滤：只有本周条目应被计入"""
        # 创建完整目录结构
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"

        today = datetime.now()
        week_start, week_end = get_week_range(
            f"{today.year}-W{today.isocalendar()[1]:02d}"
        )

        entries = []

        # 本周条目（在周范围内）
        entries.append({
            "ts": f"{week_start} 10:00:00",
            "stock_code": "600001",
            "stock_name": "本周股票",
            "score_at_decision": 0.8,
            "decision_ts": week_start,
            "pnl_actual": -4000.0,
            "pnl_pct": -6.0,
            "ratio": 7.5,
            "evidence": "test",
        })

        # 上周条目（不在周范围内）
        last_week_start = (today - timedelta(days=14)).strftime("%Y-%m-%d")
        entries.append({
            "ts": f"{last_week_start} 10:00:00",
            "stock_code": "600002",
            "stock_name": "上周股票",
            "score_at_decision": 0.7,
            "decision_ts": last_week_start,
            "pnl_actual": -3000.0,
            "pnl_pct": -5.0,
            "ratio": 7.1,
            "evidence": "test",
        })

        log_path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n",
            encoding="utf-8"
        )

        with patch(
            "scripts.weekly_report_generator.PROJECT_ROOT", tmp_path
        ):
            result = collect_fake_positive_data(
                f"{today.year}-W{today.isocalendar()[1]:02d}"
            )

        assert result["count"] == 1  # 只计入本周
        assert "600001" in result["detail"]
        assert "600002" not in result["detail"]
        print(f"✅ 周过滤测试通过: 本周1条，上周1条")


class TestWeekBoundaryCases:
    """P1-1 周过滤边界用例：周六23:59:59计入 / 周日00:00:00计入 / 周日23:59:59计入 / 下周一00:00:00排除"""

    def test_saturday_2359_included(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"
        entries = [{
            "ts": "2026-10-17 23:59:59",
            "stock_code": "600001",
            "stock_name": "周六最后一条",
            "score_at_decision": 0.85,
            "decision_ts": "2026-10-17",
            "pnl_actual": -4000.0,
            "pnl_pct": -6.0,
            "ratio": 8.0,
            "evidence": "test",
        }]
        log_path.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
        with patch("scripts.weekly_report_generator.PROJECT_ROOT", tmp_path):
            result = collect_fake_positive_data("2026-W42")
        assert result["status"] == "FOUND"
        assert result["count"] == 1
        assert "600001" in result["detail"]

    def test_sunday_000000_included(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"
        entries = [{
            "ts": "2026-10-18 00:00:00",
            "stock_code": "600002",
            "stock_name": "周日零点",
            "score_at_decision": 0.8,
            "decision_ts": "2026-10-18",
            "pnl_actual": -3000.0,
            "pnl_pct": -5.0,
            "ratio": 7.0,
            "evidence": "test",
        }]
        log_path.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
        with patch("scripts.weekly_report_generator.PROJECT_ROOT", tmp_path):
            result = collect_fake_positive_data("2026-W42")
        assert result["status"] == "FOUND"
        assert result["count"] == 1
        assert "600002" in result["detail"]

    def test_sunday_235959_included(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"
        entries = [{
            "ts": "2026-10-18 23:59:59",
            "stock_code": "600003",
            "stock_name": "周日最后时刻",
            "score_at_decision": 0.9,
            "decision_ts": "2026-10-18",
            "pnl_actual": -6000.0,
            "pnl_pct": -9.0,
            "ratio": 11.0,
            "evidence": "test",
        }]
        log_path.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
        with patch("scripts.weekly_report_generator.PROJECT_ROOT", tmp_path):
            result = collect_fake_positive_data("2026-W42")
        assert result["status"] == "FOUND"
        assert result["count"] == 1
        assert "600003" in result["detail"]

    def test_monday_000000_next_excluded(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"
        entries = [{
            "ts": "2026-10-19 00:00:00",
            "stock_code": "600004",
            "stock_name": "下周一",
            "score_at_decision": 0.7,
            "decision_ts": "2026-10-19",
            "pnl_actual": -2000.0,
            "pnl_pct": -3.0,
            "ratio": 5.0,
            "evidence": "test",
        }]
        log_path.write_text(json.dumps(entries[0]) + "\n", encoding="utf-8")
        with patch("scripts.weekly_report_generator.PROJECT_ROOT", tmp_path):
            result = collect_fake_positive_data("2026-W42")
        assert result["status"] == "NO_NEW"
        assert result["count"] == 0
        assert "600004" not in result.get("detail", "")


class TestBadLineAlert:
    """P2-1 坏行告警：有效+半截JSON → count正确 + stderr有警告"""

    def test_bad_json_line_stderr_alert(self, tmp_path, capsys):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / "fake_positive_log.jsonl"
        valid = {
            "ts": "2026-10-15 10:00:00",
            "stock_code": "600001",
            "stock_name": "有效股票",
            "score_at_decision": 0.85,
            "decision_ts": "2026-10-15",
            "pnl_actual": -4000.0,
            "pnl_pct": -6.0,
            "ratio": 8.0,
            "evidence": "test",
        }
        bad_line = '{"ts": "2026-10-15 11:00:00", "stock_code": "600002", TRUNCATED'
        content = json.dumps(valid) + "\n" + bad_line + "\n"
        log_path.write_text(content, encoding="utf-8")
        with patch("scripts.weekly_report_generator.PROJECT_ROOT", tmp_path):
            result = collect_fake_positive_data("2026-W42")
        assert result["status"] == "FOUND"
        assert result["count"] == 1
        assert "600001" in result["detail"]
        captured = capsys.readouterr()
        assert "跳过坏行" in captured.err
        assert "600002" not in result.get("detail", "")


# ── 运行入口 ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
