# -*- coding: utf-8 -*-
"""T012: DL 重训流水线 Phase 2 集成测试 (003-pretraining-automation)

Mock 回测引擎 (_load_engine_bundle / _run_engine_for_weight) 与 kanban 创建
(_kanban_create_review_card), 不实际执行 132日回测、不实际创建任务卡。

覆盖 spec FR-005 (效果对比), FR-006 (季度预算), Edge Case 72h 超时, T011 原子切换。
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import dl_retrain_pipeline as pl  # noqa: E402

TZ8 = timezone(timedelta(hours=8))


# ── T012-1: 季度预算超限 → P1 阻断 ──────────────────────────

def test_quarter_budget_exceeded_blocks(tmp_path, monkeypatch):
    """manual_count=1 + ic_count=1 → total≥limit(1) → 阻断 + P1 告警, 计数器不变"""
    count_file = tmp_path / "quarter_retrain_count.json"
    count_file.write_text(json.dumps({
        "quarter": pl._current_quarter(),
        "manual_count": 1, "ic_count": 1, "total_count": 2, "limit": 1,
    }), encoding="utf-8")
    mq = tmp_path / "message_queue.json"
    monkeypatch.setattr(pl, "QUARTER_COUNT_FILE", count_file)
    monkeypatch.setattr(pl, "MESSAGE_QUEUE_FILE", mq)

    allowed, data = pl.enforce_quarter_budget("ic_flip")

    assert allowed is False, "预算已耗尽必须阻断"
    assert data["total_count"] == 2
    # 阻断 ≠ 消耗: 计数器文件未被改动
    assert json.loads(count_file.read_text(encoding="utf-8"))["total_count"] == 2
    # P1 告警已写入 message_queue
    queue = json.loads(mq.read_text(encoding="utf-8"))
    assert queue and queue[-1]["severity"] == "P1"
    assert "阻断" in queue[-1]["message"]


# ── T012-2: 效果对比判据 (mock 引擎) ─────────────────────────

def test_effect_comparison_pass_criteria(tmp_path, monkeypatch):
    """命中率↑ + 回撤Δ≤2pp → verdict=pass; 回撤Δ>2pp → fail (同窗口对照组)"""
    old_w = tmp_path / "dl_predictor.pkl"
    new_w = tmp_path / "dl_predictor_new.pkl"
    old_w.write_bytes(b"old")
    new_w.write_bytes(b"new")
    report_path = tmp_path / "dl_retrain_report.json"

    bundle = {"br": MagicMock(), "orig_window": ("2021-01-04", "2026-09-18"),
              "window": ("2026-07-01", "2026-10-24")}
    metrics = {
        str(old_w): {"top1_hit_rate": 62.0, "annualized_return": 8.0,
                     "max_drawdown": 20.0, "trades": 10},
        str(new_w): {"top1_hit_rate": 70.0, "annualized_return": 11.0,
                     "max_drawdown": 21.5, "trades": 10},
    }

    def fake_run(weight, bundle_):
        return dict(metrics[str(Path(weight))])

    monkeypatch.setattr(pl, "_load_engine_bundle", lambda trading_days=132: bundle)
    monkeypatch.setattr(pl, "_run_engine_for_weight", fake_run)

    # pass 判据: 70 ≥ 62 且 21.5-20=1.5pp ≤ 2pp
    report = pl.run_backtest_comparison(old_w, new_w, report_path)
    assert report["verdict"] == "pass"
    assert report["status"] == "pending_review"
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    for k in ("top1_hit_rate", "annualized_return", "max_drawdown"):
        assert k in saved["old_metrics"] and k in saved["new_metrics"], f"FR-005 缺指标 {k}"
    assert saved["verdict"] == "pass"
    assert saved["engine_commit"], "准则7: 回测数字必须可溯源到引擎 commit"

    # 对照组口径: 命中率同样↑, 但回撤Δ=4pp>2pp → fail
    metrics[str(new_w)] = {"top1_hit_rate": 70.0, "annualized_return": 11.0,
                           "max_drawdown": 24.0, "trades": 10}
    report2 = pl.run_backtest_comparison(old_w, new_w, tmp_path / "r2.json")
    assert report2["verdict"] == "fail" and report2["status"] == "rejected"
    # 命中率不升同样 fail
    metrics[str(new_w)] = {"top1_hit_rate": 55.0, "annualized_return": 5.0,
                           "max_drawdown": 19.0, "trades": 10}
    report3 = pl.run_backtest_comparison(old_w, new_w, tmp_path / "r3.json")
    assert report3["verdict"] == "fail"

    # 权重文件缺失 → 显式异常 (宪法 VII, 不静默)
    with pytest.raises(FileNotFoundError):
        pl.run_backtest_comparison(old_w, tmp_path / "missing.pkl", tmp_path / "r4.json")


# ── T012-2b: 零成交守卫 (A10 修正) ───────────────────────────
def test_insufficient_data_guard_zero_trades(tmp_path, monkeypatch):
    """A10: trades=0 -> verdict=insufficient_data, status=aborted, P1 告警, 不创建评审卡"""
    old_w = tmp_path / "dl_predictor.pkl"
    new_w = tmp_path / "dl_predictor_new.pkl"
    old_w.write_bytes(b"old")
    new_w.write_bytes(b"new")
    report_path = tmp_path / "dl_retrain_report.json"
    mq = tmp_path / "message_queue.json"
    mq.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(pl, "MESSAGE_QUEUE_FILE", mq)

    bundle = {"br": MagicMock(), "orig_window": ("2021-01-04", "2026-09-18"),
              "window": ("2026-07-01", "2026-10-24")}
    zero_metrics = {"top1_hit_rate": 0.0, "annualized_return": 0.0,
                    "max_drawdown": 0.0, "trades": 0}
    monkeypatch.setattr(pl, "_load_engine_bundle", lambda trading_days=132: bundle)
    monkeypatch.setattr(pl, "_run_engine_for_weight", lambda w, b: zero_metrics)

    report = pl.run_backtest_comparison(old_w, new_w, report_path)

    assert report["verdict"] == "insufficient_data", "零成交必须判 insufficient_data"
    assert report["status"] == "aborted", "状态必须为 aborted (不触发评审)"
    assert report["dl_lookahead"] is True, "前视偏差披露必须存在"
    # P1 告警写入
    queue = json.loads(mq.read_text(encoding="utf-8"))
    assert queue and queue[-1]["severity"] == "P1" and "零成交" in queue[-1]["message"]


def test_trigger_review_insufficient_data_no_side_effects(tmp_path, monkeypatch):
    """A10 闭环 (c16f8feb 补全): trigger_review(insufficient_data) 必须短路 —
    不覆盖 status=aborted / 不标队列 / 不发 P2 / 不建评审卡 (守卫侧 P1 已发)"""
    report_path = tmp_path / "r.json"
    report_path.write_text(json.dumps({
        "verdict": "insufficient_data", "status": "aborted",
        "old_weight": "models/dl_predictor.pkl", "new_weight": "models/dl_predictor_new.pkl",
        "old_metrics": {"trades": 0}, "new_metrics": {"trades": 0},
    }), encoding="utf-8")
    queue_file = tmp_path / "retrain_queue.json"
    queue_file.write_text(json.dumps({"tasks": [{"task_id": "rt_1", "status": "pending"}],
                                      "updated_at": None}), encoding="utf-8")
    mq = tmp_path / "message_queue.json"
    mq.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(pl, "RETRAIN_QUEUE_FILE", queue_file)
    monkeypatch.setattr(pl, "MESSAGE_QUEUE_FILE", mq)
    kanban_mock = MagicMock()
    monkeypatch.setattr(pl, "_kanban_create_review_card", kanban_mock)

    res = pl.trigger_review("insufficient_data", report_path)

    assert res["status"] == "aborted"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "aborted", \
        "status 不得被 fail 分支覆盖为 rejected"
    q = json.loads(queue_file.read_text(encoding="utf-8"))
    assert q["tasks"][0]["status"] == "pending", "队列任务不得标 rejected (旧权重继续, 非效果未达标)"
    assert json.loads(mq.read_text(encoding="utf-8")) == [], "不得发 P2 未达标告警 (P1 已在守卫侧发出)"
    kanban_mock.assert_not_called()  # 不创建评审卡


def test_cleanup_stale_json_tmp(tmp_path, monkeypatch):
    """⑥(a) P2: _save_json 崩溃残留清理 — 陈旧 tmp (>24h) 清除, fresh tmp 保留"""
    import time
    stale = tmp_path / "message_queue.json.tmp"
    fresh = tmp_path / "weight_status.json.tmp"
    stale.write_text("{}", encoding="utf-8")
    fresh.write_text("{}", encoding="utf-8")
    old = time.time() - 48 * 3600
    import os as _os
    _os.utime(stale, (old, old))
    monkeypatch.setattr(pl, "DATA_DIR", tmp_path)

    assert pl._cleanup_stale_json_tmp() == 1, "仅清 1 个陈旧件"
    assert not stale.exists(), "陈旧 tmp 必须清除"
    assert fresh.exists(), "并行在跑任务的 fresh tmp 不得误删"
    # DATA_DIR 缺失 → 0 件不报错
    monkeypatch.setattr(pl, "DATA_DIR", tmp_path / "ghost")
    assert pl._cleanup_stale_json_tmp() == 0


# ── T012-3: 72h 超时 → 旧权重续期 extended + P2 ──────────────

def _write_report(report_path, hours_ago: float, status):
    report_path.write_text(json.dumps({
        "created_at": (datetime.now(TZ8) - timedelta(hours=hours_ago)).isoformat(),
        "status": status,
        "old_weight": "models/dl_predictor.pkl",
        "new_weight": "models/dl_predictor_new.pkl",
        "old_metrics": {}, "new_metrics": {}, "verdict": "pass",
    }), encoding="utf-8")


def test_72h_timeout_extends_old_weight(tmp_path, monkeypatch):
    old_w = tmp_path / "dl_predictor.pkl"
    old_w.write_bytes(b"old")
    meta_path = old_w.with_suffix(".pkl.metadata.json")
    meta_path.write_text(json.dumps({
        "trained_at": (datetime.now(TZ8) - timedelta(days=95)).isoformat(),
        "data_window": "20260501-20261024", "ic_baseline": 0.032,
        "status": "needs_retrain", "model_type": "dl_predictor",
    }), encoding="utf-8")
    report_path = tmp_path / "dl_retrain_report.json"
    _write_report(report_path, hours_ago=73, status="pending_review")
    report_path = report_path
    # 报告里 old_weight 指向 tmp (供 metadata 定位)
    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    report_data["old_weight"] = str(old_w)
    report_path.write_text(json.dumps(report_data), encoding="utf-8")

    mq = tmp_path / "message_queue.json"
    monkeypatch.setattr(pl, "REPORT_FILE", report_path)
    monkeypatch.setattr(pl, "MESSAGE_QUEUE_FILE", mq)

    assert pl.check_review_timeout() is True, "73h > 72h 必须触发续期"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["status"] == "extended", "旧权重 metadata 必须改 extended"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "extended"
    queue = json.loads(mq.read_text(encoding="utf-8"))
    assert queue and queue[-1]["severity"] == "P2", "72h 超时必须发 P2 提醒"

    # 对照组: 60h 内不触发
    _write_report(report_path, hours_ago=60, status="pending_review")
    assert pl.check_review_timeout() is False

    # 非 pending_review 状态不触发
    _write_report(report_path, hours_ago=96, status="approved")
    assert pl.check_review_timeout() is False


# ── T012-4: 评审通过 → 原子切换 (rename + 归档 + metadata) ───

def test_atomic_switch_on_approval(tmp_path):
    old = tmp_path / "dl_predictor.pkl"
    new = tmp_path / "dl_predictor_new.pkl"
    old.write_bytes(b"old-weights")
    new.write_bytes(b"new-weights")
    meta = old.with_suffix(".pkl.metadata.json")
    meta.write_text(json.dumps({
        "trained_at": (datetime.now(TZ8) - timedelta(days=95)).isoformat(),
        "data_window": "20260501-20261024", "ic_baseline": 0.032,
        "status": "needs_retrain", "model_type": "dl_predictor",
    }), encoding="utf-8")
    # 新权重自带元数据 (train 时写入) → 切换后 metadata 血缘承接自它
    new_meta = new.with_suffix(".pkl.metadata.json")
    new_meta.write_text(json.dumps({
        "trained_at": (datetime.now(TZ8) - timedelta(days=2)).isoformat(),
        "data_window": "20260701-20261024", "ic_baseline": 0.035,
        "status": "needs_review", "model_type": "dl_predictor",
    }), encoding="utf-8")

    res = pl.atomic_weight_switch(new, old)

    today = datetime.now(TZ8).strftime("%Y%m%d")
    archive = tmp_path / f"dl_predictor_archive_{today}.pkl"
    # 1) 新权重已升级为规范名, 临时名消失
    assert old.exists() and old.read_bytes() == b"new-weights"
    assert not new.exists(), "临时名必须被 rename 走"
    # 2) 旧权重已归档
    assert archive.exists() and archive.read_bytes() == b"old-weights"
    assert res["archived"] == str(archive) and res["active"] == str(old)
    # 3) metadata: trained_at=今天, status=valid, 血缘承接自新权重自带 metadata
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m["status"] == "valid"
    assert datetime.fromisoformat(m["trained_at"]).date() == datetime.now(TZ8).date()
    assert m["source_weight"] == "dl_predictor_new.pkl"
    assert m["archived_as"] == archive.name
    assert m["data_window"] == "20260701-20261024"  # 承接新权重元数据
    assert m["ic_baseline"] == 0.035
    # 4) 旧权重 metadata 跟随归档件; 新权重临时 metadata 已并入并移除 (防孤儿)
    arch_meta = archive.with_suffix(archive.suffix + ".metadata.json")
    assert arch_meta.exists() and \
        json.loads(arch_meta.read_text(encoding="utf-8"))["data_window"] == "20260501-20261024"
    assert not new_meta.exists()

    # 缺文件 → 显式异常
    with pytest.raises(FileNotFoundError):
        pl.atomic_weight_switch(tmp_path / "ghost.pkl", old)


def test_atomic_switch_rollback_on_metadata_failure(tmp_path, monkeypatch):
    """T011 回滚: metadata 写失败 → 新权重恢复临时名, 旧权重不变"""
    old = tmp_path / "dl_predictor.pkl"
    new = tmp_path / "dl_predictor_new.pkl"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    meta = old.with_suffix(".pkl.metadata.json")
    assert not meta.exists()  # 前置: 无 metadata 文件

    def boom(path, data):
        raise OSError("disk full (模拟)")

    monkeypatch.setattr(pl, "_atomic_write_json", boom)
    with pytest.raises(RuntimeError, match="已回滚"):
        pl.atomic_weight_switch(new, old)

    assert old.exists() and old.read_bytes() == b"old", "旧权重必须恢复原内容"
    assert new.exists() and new.read_bytes() == b"new", "新权重必须恢复临时名"
    assert not meta.exists(), "回滚后不得残留半写 metadata"


# ── T010 补充: 评审触发 pass/fail 两条路径 ───────────────────

def test_trigger_review_pass_creates_review_card(tmp_path, monkeypatch):
    report_path = tmp_path / "r.json"
    report_path.write_text(json.dumps({
        "verdict": "pass", "status": "pending_review",
        "old_weight": "models/dl_predictor.pkl", "new_weight": "models/dl_predictor_new.pkl",
        "old_metrics": {"top1_hit_rate": 62.0, "annualized_return": 8.0, "max_drawdown": 20.0},
        "new_metrics": {"top1_hit_rate": 70.0, "annualized_return": 11.0, "max_drawdown": 21.5},
        "engine_commit": "abc123",
    }), encoding="utf-8")
    mock_create = MagicMock(return_value="t_mock0001")
    monkeypatch.setattr(pl, "_kanban_create_review_card", mock_create)

    res = pl.trigger_review("pass", report_path)

    assert res == {"status": "pending_review", "review_task_id": "t_mock0001"}
    assert json.loads(report_path.read_text(encoding="utf-8"))["review_task_id"] == "t_mock0001"
    # 卡 body 含报告路径 + 指标对比表 (laowu 评审依据)
    body = mock_create.call_args[0][0]
    assert str(report_path) in body
    assert "TOP1命中率" in body and "70.0" in body and "62.0" in body
    assert mock_create.call_args.kwargs.get("assignee", "laowu") == "laowu"


def test_trigger_review_fail_marks_rejected(tmp_path, monkeypatch):
    report_path = tmp_path / "r.json"
    report_path.write_text(json.dumps({
        "verdict": "fail", "status": "rejected",
        "old_weight": "models/dl_predictor.pkl", "new_weight": "models/dl_predictor_new.pkl",
        "old_metrics": {}, "new_metrics": {},
    }), encoding="utf-8")
    queue_file = tmp_path / "retrain_queue.json"
    queue_file.write_text(json.dumps({"tasks": [
        {"task_id": "rt_1", "status": "deployed"},
        {"task_id": "rt_2", "status": "pending"},
    ], "updated_at": None}), encoding="utf-8")
    mq = tmp_path / "message_queue.json"
    monkeypatch.setattr(pl, "RETRAIN_QUEUE_FILE", queue_file)
    monkeypatch.setattr(pl, "MESSAGE_QUEUE_FILE", mq)

    res = pl.trigger_review("fail", report_path)

    assert res["status"] == "rejected"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "rejected"
    # 队列最近 pending 任务标 rejected, 旧权重继续服役 (metadata 不动 = 无切换)
    q = json.loads(queue_file.read_text(encoding="utf-8"))
    assert q["tasks"][1]["status"] == "rejected" and q["tasks"][0]["status"] == "deployed"
    # P2 告警 (spec User Story 3: 未达标告警写 message_queue P2)
    queue = json.loads(mq.read_text(encoding="utf-8"))
    assert queue and queue[-1]["severity"] == "P2"


# ── M3: trigger_review 报告文件不存在 → FileNotFoundError ───────────
def test_trigger_review_missing_report(tmp_path):
    """M3 (宪法 VII): 报告文件不存在 → FileNotFoundError, 不静默吞异常"""
    with pytest.raises(FileNotFoundError, match="报告不存在"):
        pl.trigger_review("pass", tmp_path / "ghost_report.json")


# ── M1+M2: _make_dl_scorer 分支隔离 (c16f8feb 补全) ─────────────────
def test_dl_scorer_factor_exception_branch():
    """M1: 因子评分异常 → factor_fail++, DL fail 计数不受影响"""
    from unittest.mock import MagicMock, patch
    bundle = {"br": MagicMock(), "strategy": "S3", "stocks_data": {}}
    mock_engine = MagicMock()

    with patch("core.pipeline.tdx_core.score_stock") as mock_factor:
        mock_factor.side_effect = RuntimeError("factor_error")
        scorer, state = pl._make_dl_scorer(bundle, mock_engine)
        # 调用一次 (stocks_data 空 → recs 空 → DL 分支跳过)
        scorer("TEST001", {}, [], 0.5, {})
        assert state == {"fail": 0, "factor_fail": 1}, "因子异常必须计数 factor_fail, 不污染 DL fail"
        assert mock_engine.predict_single_stock.call_count == 0


def test_dl_scorer_dl_exception_branch():
    """M2: DL 评分异常 → fail++, factor_fail 计数不受影响"""
    from unittest.mock import MagicMock, patch
    bundle = {"br": MagicMock(), "strategy": "S3",
              "stocks_data": {"TEST002": [{"date": "2026-01-01"}]}}
    mock_engine = MagicMock()
    mock_engine.predict_single_stock.side_effect = RuntimeError("dl_error")

    with patch("core.pipeline.tdx_core.score_stock", return_value=(1.0, 0, 0)):
        scorer, state = pl._make_dl_scorer(bundle, mock_engine)
        scorer("TEST002", {}, [], 0.5, {})
        assert state == {"fail": 1, "factor_fail": 0}, "DL 异常必须计数 fail, 不污染 factor_fail"
