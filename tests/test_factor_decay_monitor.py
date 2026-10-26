# -*- coding: utf-8 -*-
"""test_factor_decay_monitor.py — 因子衰减监控挂表测试 (P2-O3, 2026-10-20 老三)

覆盖 scripts/factor_decay_monitor.py 纯核（evaluate / trading_days_between /
状态机）+ IO 封装（子进程 e2e，tmp-repo 隔离，不碰生产 data/）+
self_audit_checkers.check_m4_factor_decay 复检器。

反例（任务单要求）：
  - IR 稳定（全活跃因子 ICIR>=0.3 → R3 连击 0，不触发）
  - 衰减未触发（条件真但连击未达阈值 / 保留率 42.4%≥40% 不满足）
  - 触发窗口未到（第 N-1 日不触发，第 N 日才触发）

口径：只在数据 as-of 日推进时计数（合成日历同构 trading_calendar.json，区间 (a,b]）；
同 as-of 日重跑幂等；假→真保守记 1；数据回退保留计数器。
"""
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"

ACTIVE = ["chg10", "overnight_sum20", "chg5", "momentum_20"]
TODAY_OBS = "2026-10-20"   # 周二（合成日历内）

ICIR_STABLE = {f: 0.4 for f in ACTIVE}          # 反例：IR 稳定（全部 >=0.3 达标）
ICIR_LOW = {f: 0.2 for f in ACTIVE}             # 全 <0.3（R3 条件真）


def _load_monitor():
    """从仓库 scripts/ 直接加载监控器模块（不经过包路径）。"""
    spec = importlib.util.spec_from_file_location(
        "factor_decay_monitor_under_test", ROOT / "scripts" / "factor_decay_monitor.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fdm():
    return _load_monitor()


@pytest.fixture(scope="module")
def CAL():
    """合成交易日历：2026-09-01..2026-12-31 工作日 Mon-Fri（与生产 trading_calendar.json 同构，测试确定性）"""
    out, d = [], date(2026, 9, 1)
    while d <= date(2026, 12, 31):
        if d.isoweekday() < 6:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def obs_day(CAL, n):
    """TODAY_OBS 起第 n 个交易日（1-indexed）。"""
    i = CAL.index(TODAY_OBS)
    return CAL[i + n - 1]


def make_gate(computed_at, flipped=("chg10", "momentum_20"), chg5_retained=42.4):
    comparison = {}
    for f in ACTIVE:
        if f == "chg5":
            lo = chg5_retained < 40.0
            comparison[f] = {"baseline_ic": 0.0397, "recent_ic_20d": 0.016841,
                             "direction_match": True, "ic_retained_pct": chg5_retained,
                             "gate_pass": not lo, "status": "CONFLICT" if lo else "PASS"}
        else:
            is_flip = f in flipped
            comparison[f] = {"baseline_ic": 0.05, "recent_ic_20d": -0.03 if is_flip else 0.04,
                             "direction_match": not is_flip,
                             "ic_retained_pct": 69.3 if is_flip else 94.5,
                             "gate_pass": not is_flip, "status": "CONFLICT" if is_flip else "PASS"}
    return {
        "computed_at": f"{computed_at}T05:57:34" if len(computed_at) == 10 else computed_at,
        "version": "2.6", "active_factors": list(ACTIVE),
        "baseline_ic": {f: {"ic_mean": 0.05, "icir": 0.21, "sample_size": 85} for f in ACTIVE},
        "recent_ic_20d": {f: {"ic_20d_mean": -0.03, "ic_20d_std": 0.1, "n_days": 27} for f in ACTIVE},
        "comparison": comparison,
    }


def make_latest(icirs, last_date="2026-10-16"):
    return {"last_date": last_date, "source": "test-synthetic",
            "factors": [{"name": f, "ic": 0.04, "status": "valid"} for f in ACTIVE],
            "diagnostics": {f: {"icir": icirs.get(f), "ic_std": 0.1, "n_dates": 132}
                            for f in ACTIVE}}


def walk(fdm, CAL, days):
    """days: 逐日 (gate_obs, latest_obs, flipped, retained, icirs) 列表 → (state, fired, cleared, warnings)"""
    state = fdm.fresh_state()
    fired_all, cleared_all, warn_all = [], [], []
    for gate_obs, lat_obs, flipped, retained, icirs in days:
        gate = make_gate(gate_obs, flipped=flipped, chg5_retained=retained)
        latest = make_latest(icirs, last_date=lat_obs)
        res = fdm.evaluate(latest, gate, CAL, state, now_iso=f"{gate_obs} 15:35:00")
        fired_all.extend(res["fired"])
        cleared_all.extend(res["cleared"])
        warn_all.extend(res["warnings"])
    return state, fired_all, cleared_all, warn_all


# ====================================================================
# 交易日计数
# ====================================================================

class TestTradingDays:
    def test_interval_weekend_gap(self, fdm, CAL):
        # 10-16(五) → 10-20(二)：区间 (10-16,10-20] = {10-19(一), 10-20(二)} = 2 个交易日
        assert fdm.trading_days_between(CAL, "2026-10-16", "2026-10-20") == 2

    def test_interval_week(self, fdm, CAL):
        # 10-20(二) → 10-23(五)：区间 (10-20,10-23] = {10-21, 10-22, 10-23} = 3
        assert fdm.trading_days_between(CAL, "2026-10-20", "2026-10-23") == 3

    def test_regression_returns_zero(self, fdm, CAL):
        assert fdm.trading_days_between(CAL, "2026-10-23", "2026-10-20") == 0

    def test_date_not_in_calendar_positional(self, fdm, CAL):
        # 非日历日（周六 10-17）也按区间位置计数，不报错 → {10-19, 10-20} = 2
        assert fdm.trading_days_between(CAL, "2026-10-17", "2026-10-20") == 2


# ====================================================================
# 纯核状态机
# ====================================================================

class TestStateMachine:
    def test_first_obs_init_cond_true(self, fdm, CAL):
        state, fired, _, _ = walk(fdm, CAL,
                                   [(TODAY_OBS, TODAY_OBS, ("chg10", "momentum_20"), 94.5, ICIR_STABLE)])
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == 1
        assert state["counters"]["flip_persist:chg10"]["first_cond_date"] == TODAY_OBS
        assert state["counters"]["flip_persist:momentum_20"]["streak_days"] == 1
        assert fired == []

    def test_first_obs_init_cond_false(self, fdm, CAL):
        state, _, _, _ = walk(fdm, CAL, [(TODAY_OBS, TODAY_OBS, (), 94.5, ICIR_STABLE)])
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == 0
        assert state["counters"]["low_retention:chg5"]["streak_days"] == 0
        assert state["counters"]["ir_all_low:ALL"]["streak_days"] == 0

    def test_idempotent_same_obs_date(self, fdm, CAL):
        """同 as-of 日重跑 N 次：不连击、不重复告警。"""
        days = [(TODAY_OBS, TODAY_OBS, ("chg10",), 94.5, ICIR_STABLE)] * 3
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == 1
        assert fired == []

    def test_flip_trigger_at_20d(self, fdm, CAL):
        days = [(obs_day(CAL, n), obs_day(CAL, n), ("chg10", "momentum_20"), 94.5, ICIR_STABLE)
                for n in range(1, 21)]
        state, fired, _, _ = walk(fdm, CAL, days)
        keys = sorted(s["key"] for s in fired)
        assert keys == ["flip_persist:chg10", "flip_persist:momentum_20"]
        for s in fired:
            assert s["severity"] == "P1"
            assert "v2.7" in s["recommendation"]
            assert s["streak_days"] == 20
            assert s["threshold_days"] == 20
        # 同日重跑幂等：无新信号（防重复告警）
        gate = make_gate(obs_day(CAL, 20), flipped=("chg10", "momentum_20"), chg5_retained=94.5)
        latest = make_latest(ICIR_STABLE, last_date=obs_day(CAL, 20))
        res = fdm.evaluate(latest, gate, CAL, state, now_iso=f"{obs_day(CAL, 20)} 15:35:00")
        assert res["fired"] == []

    def test_flip_window_not_reached_19d(self, fdm, CAL):
        """反例：触发窗口未到 — 第 19 日连击=19 < 20，不触发。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), ("chg10",), 94.5, ICIR_STABLE)
                for n in range(1, 20)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == 19
        assert fired == []

    def test_flip_clear_resets_and_closes_signal(self, fdm, CAL):
        """触发后翻转消失：连击清零 + 信号 closed + cleared 事件（不重报）。"""
        days20 = [(obs_day(CAL, n), obs_day(CAL, n), ("chg10",), 94.5, ICIR_STABLE)
                  for n in range(1, 21)]
        state, fired, _, _ = walk(fdm, CAL, days20)
        assert len(fired) == 1 and fired[0]["status"] == "active"
        gate = make_gate(obs_day(CAL, 21), flipped=(), chg5_retained=94.5)
        latest = make_latest(ICIR_STABLE, last_date=obs_day(CAL, 21))
        res = fdm.evaluate(latest, gate, CAL, state, now_iso=f"{obs_day(CAL, 21)} 15:35:00")
        assert res["fired"] == []
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == 0
        sig = state["signals"][0]
        assert sig["status"] == "cleared"
        assert len(state["cleared_events"]) == 1
        assert state["cleared_events"][0]["key"] == "flip_persist:chg10"

    def test_false_to_true_transition_conservative(self, fdm, CAL):
        """假→真：中间不可证区间不外推，连击记 1（非 delta）。"""
        d5, d6 = obs_day(CAL, 5), obs_day(CAL, 6)
        days = [(d5, d5, (), 94.5, ICIR_STABLE), (d6, d6, ("chg10",), 94.5, ICIR_STABLE)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == 1
        assert state["counters"]["flip_persist:chg10"]["first_cond_date"] == d6
        assert fired == []

    def test_low_retention_trigger_at_10d(self, fdm, CAL):
        """chg5 保留率 <40% 连续 2 周（10 交易日）→ P1 重裁 v2.7。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 35.0, ICIR_STABLE) for n in range(1, 11)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert [s["key"] for s in fired] == ["low_retention:chg5"]
        assert fired[0]["severity"] == "P1"
        assert fired[0]["streak_days"] == 10

    def test_low_retention_window_not_reached_9d(self, fdm, CAL):
        """反例：9 日未达 2 周（10 交易日），不触发。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 35.0, ICIR_STABLE) for n in range(1, 10)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["low_retention:chg5"]["streak_days"] == 9
        assert fired == []

    def test_low_retention_42p4_no_signal(self, fdm, CAL):
        """反例：衰减未触发 — 现值 42.4%（≥40%）不满足 <40%，连击保持 0。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 42.4, ICIR_STABLE) for n in range(1, 11)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["low_retention:chg5"]["streak_days"] == 0
        assert fired == []

    def test_ir_stable_no_signal(self, fdm, CAL):
        """反例：IR 稳定 — 全活跃因子 ICIR≥0.3，R3 连击 0（跑满 40 日也不触发）。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 94.5, ICIR_STABLE) for n in range(1, 41)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["ir_all_low:ALL"]["streak_days"] == 0
        assert fired == []

    def test_ir_all_low_trigger_at_30d(self, fdm, CAL):
        """全活跃因子 ICIR<0.3 持续 ≥30 交易日 → P2 重标 v2.8。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 94.5, ICIR_LOW) for n in range(1, 31)]
        state, fired, _, _ = walk(fdm, CAL, days)
        ir_fired = [s for s in fired if s["key"] == "ir_all_low:ALL"]
        assert len(ir_fired) == 1
        assert ir_fired[0]["severity"] == "P2"
        assert "v2.8" in ir_fired[0]["recommendation"]
        assert ir_fired[0]["streak_days"] == 30
        assert ir_fired[0]["evidence"]["icir"] == ICIR_LOW

    def test_ir_all_low_window_not_reached_29d(self, fdm, CAL):
        """反例：触发窗口未到 — 第 29 日不触发。"""
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 94.5, ICIR_LOW) for n in range(1, 30)]
        state, fired, _, _ = walk(fdm, CAL, days)
        assert state["counters"]["ir_all_low:ALL"]["streak_days"] == 29
        assert [s["key"] for s in fired] == []

    def test_data_regressed_keeps_counter(self, fdm, CAL):
        """数据回退（新 as-of 更早）：计数器保留不动，记警告。"""
        state, _, _, _ = walk(fdm, CAL,
            [(obs_day(CAL, 5), obs_day(CAL, 5), ("chg10",), 94.5, ICIR_STABLE),
             (obs_day(CAL, 6), obs_day(CAL, 6), ("chg10",), 94.5, ICIR_STABLE)])
        streak_after_2 = state["counters"]["flip_persist:chg10"]["streak_days"]
        gate = make_gate(obs_day(CAL, 4), flipped=("chg10",), chg5_retained=94.5)
        latest = make_latest(ICIR_STABLE, last_date=obs_day(CAL, 4))
        res = fdm.evaluate(latest, gate, CAL, state, now_iso=f"{obs_day(CAL, 4)} 15:35:00")
        assert state["counters"]["flip_persist:chg10"]["streak_days"] == streak_after_2
        assert any("data_regressed" in w for w in res["warnings"])


# ====================================================================
# 数据契约（loud fail，非静默吞）
# ====================================================================

class TestDataContractLoud:
    def test_latest_missing_factor_icir_raises(self, fdm, CAL):
        state = fdm.fresh_state()
        bad = make_latest(ICIR_STABLE)
        del bad["diagnostics"]["chg5"]
        with pytest.raises(fdm.DataContractError):
            fdm.evaluate(bad, make_gate(TODAY_OBS, flipped=()), CAL, state, now_iso="x")

    def test_gate_missing_comparison_raises(self, fdm, CAL):
        state = fdm.fresh_state()
        gate = make_gate(TODAY_OBS)
        del gate["comparison"]["momentum_20"]
        with pytest.raises(fdm.DataContractError):
            fdm.evaluate(make_latest(ICIR_STABLE), gate, CAL, state, now_iso="x")

    def test_gate_missing_computed_at_raises(self, fdm, CAL):
        state = fdm.fresh_state()
        gate = make_gate(TODAY_OBS)
        del gate["computed_at"]
        with pytest.raises(fdm.DataContractError):
            fdm.evaluate(make_latest(ICIR_STABLE), gate, CAL, state, now_iso="x")

    def test_empty_active_factors_raises(self, fdm, CAL):
        state = fdm.fresh_state()
        gate = make_gate(TODAY_OBS)
        gate["active_factors"] = []
        with pytest.raises(fdm.DataContractError):
            fdm.evaluate(make_latest(ICIR_STABLE), gate, CAL, state, now_iso="x")


# ====================================================================
# 队列写口（message_queue.json 唯一出口；tmp 隔离）
# ====================================================================

class TestQueueWrites:
    def test_queue_on_fire_and_no_duplicate(self, fdm, CAL, tmp_path, monkeypatch):
        """触发→入队 1 条；pending 为空时重入队→队列不变（防重复告警）。"""
        import core.ops.message_queue as mq
        qfile = tmp_path / "message_queue.json"
        qfile.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(mq, "QUEUE_FILE", str(qfile))

        days = [(obs_day(CAL, n), obs_day(CAL, n), ("chg10",), 94.5, ICIR_STABLE)
                for n in range(1, 21)]
        _, fired_all, _, _ = walk(fdm, CAL, days)
        assert len(fired_all) == 1

        queued, failures = fdm.queue_signals(fired_all, project_root=str(ROOT))
        assert len(queued) == 1 and not failures
        queue = json.loads(qfile.read_text(encoding="utf-8"))
        assert len(queue) == 1
        assert queue[0]["sender"] == "factor_decay_monitor"
        assert queue[0]["priority"] == "critical"
        assert fired_all[0]["queued"] is True

        queued2, _ = fdm.queue_signals([], project_root=str(ROOT))
        assert queued2 == []
        assert len(json.loads(qfile.read_text(encoding="utf-8"))) == 1  # 不重复

    def test_p2_signal_priority_normal(self, fdm, CAL, tmp_path, monkeypatch):
        """P2 信号入队 priority=normal（P1=critical，drain 排序口径）。"""
        import core.ops.message_queue as mq
        qfile = tmp_path / "message_queue.json"
        qfile.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(mq, "QUEUE_FILE", str(qfile))
        days = [(obs_day(CAL, n), obs_day(CAL, n), (), 94.5, ICIR_LOW) for n in range(1, 31)]
        _, fired_all, _, _ = walk(fdm, CAL, days)
        ir = [s for s in fired_all if s["key"] == "ir_all_low:ALL"]
        assert len(ir) == 1
        queued, _ = fdm.queue_signals(ir, project_root=str(ROOT))
        assert len(queued) == 1
        assert json.loads(qfile.read_text(encoding="utf-8"))[0]["priority"] == "normal"

    @pytest.mark.slow  # P3 2026-10-26 (t_81fad29b): 实测 15.07s(写失败重试路径) → 门禁快档排除
    def test_queue_write_failure_loud(self, fdm, tmp_path, monkeypatch):
        """add_message 返回 None（写失败）→ queue_signals 如实上报 failure，不静默；
        queued 保持 False → 下轮重试，防告警丢失。"""
        import core.ops.message_queue as mq
        bad = tmp_path / "no_dir" / "q.json"  # 目录不存在 → 写必失败
        monkeypatch.setattr(mq, "QUEUE_FILE", str(bad))
        sig = {"id": "DEC-x", "key": "flip_persist:chg10", "rule": "flip_persist",
               "factor": "chg10", "severity": "P1", "recommendation": "v2.7 重裁",
               "streak_days": 20, "threshold_days": 20, "first_cond_date": "2026-09-01",
               "data_asof": "2026-10-20", "evidence": {}, "triggered_at": "x",
               "status": "active", "queued": False}
        queued, failures = fdm.queue_signals([sig], project_root=str(ROOT))
        assert queued == [] and failures == ["DEC-x"]
        assert sig["queued"] is False


# ====================================================================
# 子进程 e2e（tmp-repo 隔离；不碰生产 data/）
# ====================================================================

def _build_tmp_repo(tmp_path, CAL):
    """tmp 仓库布局：拷贝监控器 + core/ 真源最小树（atomic_json/message_queue），
    core/ops/message_queue.py 的两个硬编码队列路径改指 tmp（防子进程写穿生产队列）。

    [t_laosan_c1_test_alignment] 2026-10-24: S4/S6 基地化对齐 —— 活跃
    scripts/factor_decay_monitor.py 导入 core.pipeline.atomic_json (L57/L423) +
    core.ops.message_queue (L355)（根侧 atomic_json.py/message_queue.py 已迁 core/,
    不再是消费方）；原根侧拷贝布局对齐归档后真源改为最小 core/ 树拷贝。"""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "data" / "factor_ic").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "factor_decay_monitor.py",
                repo / "scripts" / "factor_decay_monitor.py")
    for rel in ("core/__init__.py", "core/pipeline/__init__.py",
                "core/pipeline/atomic_json.py", "core/ops/__init__.py",
                "core/ops/message_queue.py"):
        src = ROOT / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
    mq = (repo / "core" / "ops" / "message_queue.py").read_text(encoding="utf-8")
    mq = mq.replace(r"D:\open code\zhuanqian\data\message_queue.json",
                    str(repo / "data" / "message_queue.json"))
    mq = mq.replace(r"D:\open code\zhuanqian\data\message_sent_log.json",
                    str(repo / "data" / "message_sent_log.json"))
    (repo / "core" / "ops" / "message_queue.py").write_text(mq, encoding="utf-8")
    cal = {"data": [{"date": d} for d in CAL], "pulled_at": "test", "source": "synthetic"}
    (repo / "data" / "trading_calendar.json").write_text(
        json.dumps(cal, ensure_ascii=False), encoding="utf-8")
    return repo


def _seed_inputs(repo, CAL, day, flipped, retained, icirs):
    obs = obs_day(CAL, day)
    gate = make_gate(obs, flipped=flipped, chg5_retained=retained)
    latest = make_latest(icirs, last_date=obs)
    (repo / "data" / "factor_ic" / "t2b_gate_20d_check.json").write_text(
        json.dumps(gate, ensure_ascii=False, indent=1), encoding="utf-8")
    (repo / "data" / "factor_ic" / "factor_ic_latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")


def _run_monitor(repo, CAL, expect_rc=0):
    r = subprocess.run(
        [str(VENV_PY), str(repo / "scripts" / "factor_decay_monitor.py"), "--json"],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    report = json.loads(r.stdout)
    if r.returncode != expect_rc:
        raise AssertionError(
            f"rc={r.returncode} expect {expect_rc}: stderr={r.stderr[-400:]}\nstdout={r.stdout[-400:]}")
    return r.returncode, report


class TestSubprocessE2E:
    def test_fresh_init_no_fire(self, tmp_path, CAL):
        """首跑（今日实态：2 翻转 + 保留率 42.4 + 全 IR<0.3）：计数器初始化，未达阈值 → 无触发。"""
        repo = _build_tmp_repo(tmp_path, CAL)
        _seed_inputs(repo, CAL, 1, ("chg10", "momentum_20"), 42.4, ICIR_LOW)
        rc, report = _run_monitor(repo, CAL)
        assert rc == 0 and report["status"] == "ok"
        assert report["fired"] == []
        c = report["counters"]
        assert c["flip_persist:chg10"]["streak_days"] == 1
        assert c["flip_persist:momentum_20"]["streak_days"] == 1
        assert c["low_retention:chg5"]["streak_days"] == 0      # 42.4 ≥ 40 不满足
        assert c["ir_all_low:ALL"]["streak_days"] == 1
        sig_path = repo / "data" / "decay_signals.json"
        assert sig_path.exists()
        st = json.loads(sig_path.read_text(encoding="utf-8"))
        assert st["signals"] == [] and st["counters"] == c
        q = repo / "data" / "message_queue.json"
        assert not q.exists() or json.loads(q.read_text(encoding="utf-8")) == []

    def test_fire_writes_queue_once(self, tmp_path, CAL):
        """逐日推进到第 20 日触发 2×P1 → 队列恰 2 条；同日重跑幂等不重复。"""
        repo = _build_tmp_repo(tmp_path, CAL)
        rep = {}
        for n in range(1, 21):
            _seed_inputs(repo, CAL, n, ("chg10", "momentum_20"), 94.5, ICIR_STABLE)
            rc, rep = _run_monitor(repo, CAL)
            if n < 20:
                assert rep["fired"] == []
        assert sorted(s["key"] for s in rep["fired"]) == ["flip_persist:chg10", "flip_persist:momentum_20"]
        q = repo / "data" / "message_queue.json"
        msgs = json.loads(q.read_text(encoding="utf-8"))
        assert len(msgs) == 2
        assert all(m["sender"] == "factor_decay_monitor" and m["priority"] == "critical" for m in msgs)
        st = json.loads((repo / "data" / "decay_signals.json").read_text(encoding="utf-8"))
        assert all(s["queued"] is True for s in st["signals"])
        # 同日重跑：幂等，不重复入队
        rc, rep2 = _run_monitor(repo, CAL)
        assert rc == 0 and rep2["fired"] == []
        assert len(json.loads(q.read_text(encoding="utf-8"))) == 2

    def test_preseed_state_load_and_continue(self, tmp_path, CAL):
        """预置第 19 日状态文件 → 第 20 日直接触发（load_state 路径）。"""
        repo = _build_tmp_repo(tmp_path, CAL)
        _seed_inputs(repo, CAL, 1, ("chg10",), 94.5, ICIR_STABLE)
        _run_monitor(repo, CAL)
        sig = repo / "data" / "decay_signals.json"
        st = json.loads(sig.read_text(encoding="utf-8"))
        st["counters"]["flip_persist:chg10"] = {
            "streak_days": 19, "first_cond_date": obs_day(CAL, 1),
            "last_obs_date": obs_day(CAL, 19), "condition": True}
        sig.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        _seed_inputs(repo, CAL, 20, ("chg10",), 94.5, ICIR_STABLE)
        rc, rep = _run_monitor(repo, CAL)
        assert rc == 0
        assert [s["key"] for s in rep["fired"]] == ["flip_persist:chg10"]
        assert rep["fired"][0]["streak_days"] == 20  # 19 + 区间 1 交易日

    def test_missing_input_rc2_loud(self, tmp_path, CAL):
        """权威表缺失 → rc=2 + error JSON（loud，非静默）。"""
        repo = _build_tmp_repo(tmp_path, CAL)
        _seed_inputs(repo, CAL, 1, (), 94.5, ICIR_STABLE)
        (repo / "data" / "factor_ic" / "factor_ic_latest.json").unlink()
        r = subprocess.run(
            [str(VENV_PY), str(repo / "scripts" / "factor_decay_monitor.py"), "--json"],
            cwd=str(repo), capture_output=True, text=True, encoding="utf-8", timeout=90)
        report = json.loads(r.stdout)
        assert r.returncode == 2
        assert report["status"] == "error"
        assert "factor_ic_latest.json" in report["error"]


# ====================================================================
# M-4 复检器（self_audit_checkers.check_m4_factor_decay）
# ====================================================================

def _self_checker():
    import core.ops.self_audit_checkers as m
    return m


class TestM4Checker:
    def test_pass_when_no_fired(self, tmp_path, CAL, monkeypatch):
        repo = _build_tmp_repo(tmp_path, CAL)
        _seed_inputs(repo, CAL, 1, ("chg10", "momentum_20"), 42.4, ICIR_LOW)
        m = _self_checker()
        monkeypatch.setattr(m, "ROOT", str(repo))
        r = m.check_m4_factor_decay()
        assert r.status == "PASS" and r.checker == "m4_factor_decay"
        assert r.details["streaks"]["flip_persist:chg10"] == 1

    def test_fail_when_fired(self, tmp_path, CAL, monkeypatch):
        """预置第 19 日状态 → M-4 复检触发第 20 日 → FAIL P1（队列已由监控器写入）。"""
        repo = _build_tmp_repo(tmp_path, CAL)
        _seed_inputs(repo, CAL, 1, ("chg10",), 94.5, ICIR_STABLE)
        subprocess.run([str(VENV_PY), str(repo / "scripts" / "factor_decay_monitor.py"), "--json"],
                       cwd=str(repo), capture_output=True, text=True, encoding="utf-8", timeout=90)
        sig = repo / "data" / "decay_signals.json"
        st = json.loads(sig.read_text(encoding="utf-8"))
        st["counters"]["flip_persist:chg10"] = {
            "streak_days": 19, "first_cond_date": obs_day(CAL, 1),
            "last_obs_date": obs_day(CAL, 19), "condition": True}
        sig.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        _seed_inputs(repo, CAL, 20, ("chg10",), 94.5, ICIR_STABLE)
        m = _self_checker()
        monkeypatch.setattr(m, "ROOT", str(repo))
        r = m.check_m4_factor_decay()
        assert r.status == "FAIL" and r.severity == "P1"
        assert len(r.details["fired"]) == 1
        assert r.details["fired"][0]["key"] == "flip_persist:chg10"
        q = repo / "data" / "message_queue.json"
        assert len(json.loads(q.read_text(encoding="utf-8"))) == 1  # 监控器唯一写口已入队

    def test_skipped_when_script_missing(self, tmp_path, monkeypatch):
        repo = tmp_path / "empty_repo"
        (repo / "scripts").mkdir(parents=True)
        m = _self_checker()
        monkeypatch.setattr(m, "ROOT", str(repo))
        r = m.check_m4_factor_decay()
        assert r.status == "SKIPPED" and "缺失" in r.message

    def test_skipped_when_data_contract_broken(self, tmp_path, CAL, monkeypatch):
        repo = _build_tmp_repo(tmp_path, CAL)
        _seed_inputs(repo, CAL, 1, (), 94.5, ICIR_STABLE)
        (repo / "data" / "factor_ic" / "t2b_gate_20d_check.json").unlink()
        m = _self_checker()
        monkeypatch.setattr(m, "ROOT", str(repo))
        r = m.check_m4_factor_decay()
        assert r.status == "SKIPPED" and r.severity == "P1"
        assert "loud fail" in r.message
