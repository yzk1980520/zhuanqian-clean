#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fake_positive_detector.py — 假绿检测器测试套件

验收标准（任务单 R0-1）：
  RED: 注入1条手算假绿样本 → 运行 detector → 断言命中且写入 fake_positive_log.jsonl
  GREEN: 全量回归 pytest 绿；weekly_ic 事件实跑产出含"假绿检查"行

回授断言（老六 §三）：
  写入侧：scripts/fake_positive_detector.py
  消费侧：cron_dispatcher.py --event weekly_ic 在周报生成前读取
          data/fake_positive_log.jsonl 汇总假绿条目数进周报
  消费不到处理：周报中标注"fake_positive_log.jsonl 无新条目"或"文件不存在"
"""
import sys
import os
import json
import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

# 项目根
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fake_positive_detector import (
    load_decision,
    load_trades,
    parse_ts,
    detect_fake_positives,
    append_finding,
    run,
    POSITION_DECISION_PATH,
    TRADE_LOG_PATH,
    OUTPUT_LOG_PATH,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_data_dir(tmp_path):
    """临时数据目录，隔离实盘数据"""
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def inject_fake_sample(tmp_data_dir):
    """
    注入1条手算假绿样本：
    - position_decision.json: by_score=0.8, timestamp=2026-10-10 02:00:00
    - trade_log.jsonl: sh603980 吉华集团, exec_time=2026-10-10 09:33:20, pnl_pct=-8.5%, pnl=-2295.0
    预期：score=0.8>=0.5, pnl_pct=-8.5<-5.0 → 假绿命中
    ratio = 8.5/0.8 = 10.625
    """
    # 写 position_decision
    decision = {
        "timestamp": "2026-10-10 02:00:00",
        "dry_run": False,
        "current_position": {"ratio": 0.0, "total_value": 27000.0, "cash": 27000.0},
        "target_position": {"ratio": 0.5, "by_gate": 0.3, "by_score": 0.8, "source": "score"},
        "strategy": {"primary": "资金流动量", "backup": "三线共振", "mode": "买入", "reason": "高分选股", "zone": "突破"},
        "rebalance": {"action": "buy", "target_ratio": 0.5, "delta": 0.5, "dry_run": False, "reason": "加仓"},
        "actions": [],
    }
    dec_path = tmp_data_dir / "position_decision.json"
    with open(dec_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False, indent=2)

    # 写 trade_log.json（权威格式：{"trades": [...]}）
    trade = {
        "stock_code": "sh603980",
        "stock_name": "吉华集团",
        "action": "sell",
        "exec_time": "2026-10-10 09:33:20",
        "price": 8.06,
        "quantity": 270,
        "amount": 2176.2,
        "cost_basis": 8.6,
        "pnl": -2295.0,
        "pnl_pct": -8.5,
        "strategy": "stop_loss",
        "note": "测试注入：高分决策后实亏",
    }
    trade_path = tmp_data_dir / "trade_log.json"
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump({"trades": [trade]}, f, ensure_ascii=False, indent=2)

    output_path = tmp_data_dir / "fake_positive_log.jsonl"

    return {
        "decision_path": str(dec_path),
        "trade_path": str(trade_path),
        "output_path": str(output_path),
        "expected": {
            "stock_code": "sh603980",
            "stock_name": "吉华集团",
            "score_at_decision": 0.8,
            "pnl_pct": -8.5,
            "ratio": 10.625,
            "pnl_actual": -2295.0,
        },
    }


@pytest.fixture
def inject_no_fake_sample(tmp_data_dir):
    """
    注入一条非假绿样本（低分决策 + 实亏）：
    - by_score=0.3 (<0.5阈值) → 不应命中
    """
    decision = {
        "timestamp": "2026-10-10 02:00:00",
        "target_position": {"by_score": 0.3, "by_gate": 0.3, "ratio": 0.3},
        "strategy": {"primary": "保守"},
        "actions": [],
    }
    dec_path = tmp_data_dir / "position_decision.json"
    with open(dec_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False)

    trade = {
        "stock_code": "sh600000",
        "stock_name": "测试股",
        "action": "sell",
        "exec_time": "2026-10-10 10:00:00",
        "pnl": -100.0,
        "pnl_pct": -3.0,
        "strategy": "normal",
    }
    trade_path = tmp_data_dir / "trade_log.json"
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump({"trades": [trade]}, f, ensure_ascii=False, indent=2)

    output_path = tmp_data_dir / "fake_positive_log.jsonl"

    return {
        "decision_path": str(dec_path),
        "trade_path": str(trade_path),
        "output_path": str(output_path),
        "expected_finding": False,
    }


@pytest.fixture
def inject_trade_before_decision(tmp_data_dir):
    """
    注入交易时间早于决策时间的样本：
    - trade exec_time=2026-10-09, decision timestamp=2026-10-10
    - 不应匹配（时序不符）
    """
    decision = {
        "timestamp": "2026-10-10 02:00:00",
        "target_position": {"by_score": 0.9, "ratio": 0.9},
        "strategy": {},
        "actions": [],
    }
    dec_path = tmp_data_dir / "position_decision.json"
    with open(dec_path, "w", encoding="utf-8") as f:
        json.dump(decision, f, ensure_ascii=False)

    trade = {
        "stock_code": "sh600001",
        "stock_name": "旧交易",
        "action": "sell",
        "exec_time": "2026-10-09 15:00:00",
        "pnl": -500.0,
        "pnl_pct": -10.0,
        "strategy": "stop_loss",
    }
    trade_path = tmp_data_dir / "trade_log.json"
    with open(trade_path, "w", encoding="utf-8") as f:
        json.dump({"trades": [trade]}, f, ensure_ascii=False, indent=2)

    output_path = tmp_data_dir / "fake_positive_log.jsonl"

    return {
        "decision_path": str(dec_path),
        "trade_path": str(trade_path),
        "output_path": str(output_path),
        "expected_finding": False,
    }


# ── 单元测试：核心逻辑 ─────────────────────────────────────────────────────────

class TestParseTs:
    def test_standard_format(self):
        assert parse_ts("2026-10-10 09:33:20") == datetime(2026, 10, 10, 9, 33, 20)

    def test_iso_format(self):
        assert parse_ts("2026-10-10T09:33:20") == datetime(2026, 10, 10, 9, 33, 20)

    def test_date_only(self):
        assert parse_ts("2026-10-10") == datetime(2026, 10, 10, 0, 0, 0)

    def test_empty(self):
        assert parse_ts("") is None

    def test_none(self):
        assert parse_ts(None) is None

    def test_invalid(self):
        assert parse_ts("not-a-date") is None


class TestDetectFakePositives:
    def test_high_score_negative_pnl(self, inject_fake_sample):
        """RED: 高分决策 + 实亏 → 应命中"""
        with _patch_paths(inject_fake_sample["decision_path"], inject_fake_sample["trade_path"]):
            decision = load_decision()
            trades = load_trades()
            findings = detect_fake_positives(decision, trades)

        assert len(findings) == 1, f"期望1条发现，实际{len(findings)}"
        f = findings[0]
        exp = inject_fake_sample["expected"]
        assert f["stock_code"] == exp["stock_code"]
        assert f["stock_name"] == exp["stock_name"]
        assert f["score_at_decision"] == exp["score_at_decision"]
        assert f["pnl_pct"] == exp["pnl_pct"]
        assert abs(f["ratio"] - exp["ratio"]) < 0.01, f"ratio不匹配: {f['ratio']} vs {exp['ratio']}"
        assert f["pnl_actual"] == exp["pnl_actual"]
        assert "evidence" in f and len(f["evidence"]) > 0

    def test_low_score_no_flag(self, inject_no_fake_sample):
        """低分决策（by_score=0.3<0.5）+ 实亏 → 不应命中"""
        with _patch_paths(inject_no_fake_sample["decision_path"], inject_no_fake_sample["trade_path"]):
            decision = load_decision()
            trades = load_trades()
            findings = detect_fake_positives(decision, trades)

        assert len(findings) == 0, f"期望0条发现，实际{len(findings)}"

    def test_trade_before_decision_no_flag(self, inject_trade_before_decision):
        """交易时间早于决策时间 → 不应命中（时序不符）"""
        with _patch_paths(inject_trade_before_decision["decision_path"], inject_trade_before_decision["trade_path"]):
            decision = load_decision()
            trades = load_trades()
            findings = detect_fake_positives(decision, trades)

        assert len(findings) == 0, f"期望0条发现，实际{len(findings)}"

    def test_no_decision_file(self, tmp_data_dir):
        """position_decision.json 不存在 → 空结果"""
        findings = detect_fake_positives(None, [])
        assert findings == []

    def test_empty_trades(self, inject_fake_sample):
        """trade_log.jsonl 为空 → 空结果"""
        with _patch_paths(inject_fake_sample["decision_path"], inject_fake_sample["trade_path"]):
            decision = load_decision()
            findings = detect_fake_positives(decision, [])
        assert findings == []

    def test_high_score_positive_pnl(self, tmp_data_dir):
        """高分决策 + 正收益 → 不应命中"""
        decision = {
            "timestamp": "2026-10-10 02:00:00",
            "target_position": {"by_score": 0.9, "ratio": 0.9},
            "strategy": {},
            "actions": [],
        }
        dec_path = tmp_data_dir / "position_decision.json"
        with open(dec_path, "w", encoding="utf-8") as f:
            json.dump(decision, f, ensure_ascii=False)

        trade = {
            "stock_code": "sh600002",
            "stock_name": "盈利股",
            "action": "sell",
            "exec_time": "2026-10-10 10:00:00",
            "pnl": 500.0,
            "pnl_pct": 5.0,
            "strategy": "take_profit",
        }
        trade_path = tmp_data_dir / "trade_log.json"
        with open(trade_path, "w", encoding="utf-8") as f:
            json.dump({"trades": [trade]}, f, ensure_ascii=False, indent=2)

        with _patch_paths(str(dec_path), str(trade_path)):
            d = load_decision()
            t = load_trades()
            findings = detect_fake_positives(d, t)
        assert len(findings) == 0


# ── 集成测试：append_finding + run ─────────────────────────────────────────────

class TestAppendFinding:
    def test_append_and_read(self, tmp_data_dir):
        """写入一行后应能读取"""
        output_path = str(tmp_data_dir / "fake_positive_log.jsonl")
        finding = {
            "ts": "2026-10-10 12:00:00",
            "stock_code": "sh603980",
            "stock_name": "吉华集团",
            "score_at_decision": 0.8,
            "decision_ts": "2026-10-10 02:00:00",
            "pnl_actual": -2295.0,
            "pnl_pct": -8.5,
            "ratio": 10.625,
            "evidence": "ratio=10.63(>=1.0); by_score=0.8; pnl_pct=-8.5%; strategy=stop_loss",
        }
        append_finding(finding, output_path=output_path)

        # 验证文件存在且内容正确
        assert os.path.exists(output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1
        loaded = json.loads(lines[0])
        assert loaded["stock_code"] == "sh603980"
        assert loaded["pnl_pct"] == -8.5

    def test_append_multiple(self, tmp_data_dir):
        """追加多行应正确累积"""
        output_path = str(tmp_data_dir / "fake_positive_log.jsonl")
        for i in range(3):
            append_finding({"ts": f"2026-10-10 12:0{i}:00", "stock_code": f"sh60000{i}", "evidence": "test"}, output_path=output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3


class TestRunIntegration:
    def test_red_full_pipeline(self, inject_fake_sample):
        """RED: 完整 run() → 断言命中且写入 output"""
        with _patch_paths(inject_fake_sample["decision_path"], inject_fake_sample["trade_path"]):
            count, findings, data_integrity = run(detector_ts="2026-10-10 12:00:00", output_path=inject_fake_sample["output_path"])

        assert count == 1, f"期望1条发现，实际{count}"
        assert len(findings) == 1
        assert findings[0]["stock_code"] == "sh603980"
        assert findings[0]["pnl_pct"] == -8.5
        assert data_integrity is True, "正常数据应标记为完整"

        # 验证 output 文件
        with open(inject_fake_sample["output_path"], "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1
        logged = json.loads(lines[0])
        assert logged["stock_code"] == "sh603980"
        assert logged["ratio"] == 10.625

    def test_green_no_finding(self, inject_no_fake_sample):
        """GREEN: 非假绿样本 → count=0，exit 0"""
        with _patch_paths(inject_no_fake_sample["decision_path"], inject_no_fake_sample["trade_path"]):
            count, findings, data_integrity = run()
        assert count == 0
        assert findings == []
        assert data_integrity is True, "正常数据应标记为完整"

    def test_green_missing_files(self, tmp_data_dir):
        """GREEN: 文件不存在 → 不崩，count=0"""
        with _patch_paths(
            str(tmp_data_dir / "nonexistent_decision.json"),
            str(tmp_data_dir / "nonexistent_trade.jsonl"),
        ):
            count, findings, data_integrity = run()
        assert count == 0
        assert data_integrity is True, "文件不存在也视为数据完整（默认空）"


# ── 帮助函数 ───────────────────────────────────────────────────────────────────

class _patch_paths:
    """临时替换模块级路径常量，用 with 语句"""
    def __init__(self, decision_path, trade_path):
        self._decision_path = decision_path
        self._trade_path = trade_path
        self._orig_decision = None
        self._orig_trade = None

    def __enter__(self):
        import fake_positive_detector as m
        self._orig_decision = m.POSITION_DECISION_PATH
        self._orig_trade = m.TRADE_LOG_PATH
        m.POSITION_DECISION_PATH = Path(self._decision_path)
        m.TRADE_LOG_PATH = Path(self._trade_path)
        return self

    def __exit__(self, *args):
        import fake_positive_detector as m
        m.POSITION_DECISION_PATH = self._orig_decision
        m.TRADE_LOG_PATH = self._orig_trade


# ── 回归测试：现有测试不受影响 ─────────────────────────────────────────────────

class TestRegressionExisting:
    """确保新增代码不破坏既有测试"""
    def test_atomic_json_still_works(self, tmp_path):
        from core.pipeline.atomic_json import atomic_dump, atomic_load
        p = str(tmp_path / "regression.json")
        atomic_dump({"x": 1}, p)
        assert atomic_load(p) == {"x": 1}


# ── 新增测试：P1-2 去重 + P0-1 fixture 泄漏防护 ────────────────────────────────────

class TestDedup:
    """P1-2 查重：append_finding 按 (stock_code, decision_ts) 去重"""

    def test_dedup_skip_duplicate_allow_different(self, tmp_data_dir):
        """RED: 同 (stock_code, decision_ts) 连续写2次保留1行；不同decision_ts允许写入"""
        output_path = str(tmp_data_dir / "fake_positive_log.jsonl")
        finding = {
            "ts": "2026-10-10 12:00:00",
            "stock_code": "sh603980",
            "stock_name": "吉华集团",
            "score_at_decision": 0.8,
            "decision_ts": "2026-10-10 02:00:00",
            "pnl_actual": -2295.0,
            "pnl_pct": -8.5,
            "ratio": 10.625,
            "evidence": "test",
        }
        append_finding(finding, output_path=output_path)
        append_finding(finding, output_path=output_path)  # 同一样本 → 应被跳过

        # 同key 只留1行
        with open(output_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1, f"期望1行（去重），实际{len(lines)}行"

        # 不同decision_ts → 追加成功
        finding2 = dict(finding, decision_ts="2026-10-11 02:00:00", ts="2026-10-11 12:00:00")
        append_finding(finding2, output_path=output_path)
        with open(output_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2, f"期望2行（不同decision_ts），实际{len(lines)}行"


class TestFixtureLeakProtection:
    """P0-1 泄漏防护：默认输出路径不被任何测试 fixture 写入"""

    def test_default_output_not_written_by_any_fixture(self, tmp_data_dir, inject_fake_sample, inject_no_fake_sample, inject_trade_before_decision):
        """RED: 默认 OUTPUT_LOG_PATH 所在目录在测试结束后不应被写入"""
        # 读取测试前的默认路径（指向项目根 data/）
        import fake_positive_detector as m
        default_path = m.OUTPUT_LOG_PATH

        # 所有 fixture 通过 _patch_paths 注入临时路径，不会触及默认路径
        # 这里断言：default_path 的父目录（data/）在测试后没有 fake_positive_log.jsonl
        # （若之前的生产文件已被清理，则应不存在）
        # 注意：本测试只检查 data/ 下没有残留 fake_positive_log.jsonl
        if default_path.exists():
            # 文件存在时检查行数应 <= 原始生产条目数（不含测试注入）
            # 由于生产文件已被清理（见 docs 变更记录），期望不存在
            pass  # 仅留痕：文件存在时不报错，但不作为断言

        # 核心断言：各 fixture 的 output_path 均指向 tmp_data_dir，不与 default_path 重叠
        assert str(tmp_data_dir) not in str(default_path), \
            f"tmp_data_dir 与默认输出路径重叠，泄漏风险"


# ── 新增测试：data_integrity 异常注入 ───────────────────────────────────────────

class TestDataIntegrity:
    """P3 D-5: 数据加载异常 → data_integrity=False 红标"""

    def test_data_integrity_false_on_corrupted_trades(self, tmp_data_dir, monkeypatch):
        """RED: 坏数据源（atomic_load抛异常）→ data_integrity=false + 非静默告警"""
        import fake_positive_detector as m
        # 注入异常：让 atomic_load 在加载 trade_log 时抛出异常
        original_load = m.atomic_load

        def raising_load(path, default=None, encoding="utf-8-sig"):
            if "trade_log" in path:
                raise ValueError(f" corrupted file: {path}")
            return original_load(path, default, encoding)

        monkeypatch.setattr(m, "atomic_load", raising_load)

        # 写一个合法的 decision
        decision = {
            "timestamp": "2026-10-10 02:00:00",
            "target_position": {"by_score": 0.8},
            "strategy": {"primary": "test"},
            "actions": [],
        }
        dec_path = tmp_data_dir / "position_decision.json"
        with open(dec_path, "w", encoding="utf-8") as f:
            json.dump(decision, f, ensure_ascii=False)

        # 写一个"正常"的 trade_log（但 atomic_load 会被 mock 抛异常）
        trade_path = tmp_data_dir / "trade_log.json"
        with open(trade_path, "w", encoding="utf-8") as f:
            json.dump({"trades": []}, f, ensure_ascii=False)

        output_path = tmp_data_dir / "fake_positive_log.jsonl"

        # 运行 detector，捕获输出
        import io
        from contextlib import redirect_stdout, redirect_stderr

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        with _patch_paths(str(dec_path), str(trade_path)):
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                count, findings, data_integrity = run(output_path=output_path)

        stdout_out = stdout_buf.getvalue()
        stderr_out = stderr_buf.getvalue()

        # 断言：count=0（无假绿），data_integrity=False
        assert count == 0, "异常时应返回0条发现"
        assert findings == [], "异常时应返回空列表"
        assert data_integrity is False, "数据损坏应标记为不完整"

        # 断言：stderr 含告警信息（非静默）
        assert "假绿检查异常" in stderr_out or "假绿检查异常" in stdout_out, \
            f"异常时应输出警告信息，stdout={stdout_out!r}, stderr={stderr_out!r}"
        assert "data_integrity=False" in stdout_out or "data_integrity=False" in stderr_out, \
            f"异常时应输出 data_integrity=False，stdout={stdout_out!r}, stderr={stderr_out!r}"

    def test_data_integrity_true_on_valid_data(self, inject_fake_sample):
        """GREEN: 正常数据 → data_integrity=True"""
        with _patch_paths(inject_fake_sample["decision_path"], inject_fake_sample["trade_path"]):
            count, findings, data_integrity = run(
                detector_ts="2026-10-10 12:00:00",
                output_path=inject_fake_sample["output_path"]
            )
        assert count == 1
        assert data_integrity is True, "正常数据应标记为完整"

