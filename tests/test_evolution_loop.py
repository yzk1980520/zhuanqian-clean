# -*- coding: utf-8 -*-
"""test_evolution_loop.py — 策略自动迭代闭环 v1 骨架 TDD（交付物 2）

seam（public interface, 全部纯函数/注入）:
  - redline_check(read_fn, baseline)  红线常量漂移检测（不校验值, 只检测被改没被改）
  - cooldown_active(last_rejections, today, ...)  30d/60d 冷却铁律
  - sharpe_anomaly(baseline, current, ratio)  优秀到反常
  - circuit_interlock(level)  熔断自停映射
  - EvolutionLoop.run_round(...)  五步状态机（PROPOSE→SMOKE→CONFIRM→GATE→MERGE/ROLLBACK）

期望值来源: docs/evolution_loop_v1_schema.md §三/§四/§六 现值 + 手算 worked example。
红线2: dry_run=True 时零实际写口, 用 write_spy 注入断言未被调用。
本轮不接真实回测引擎/gate（留注入 seam, 避免骨架一跑就触发真回测=红线2）。
"""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.ops.evolution_loop as el  # noqa: E402

TODAY = date(2026, 10, 9)


# ── 红线漂移检测（§〇 校准: 动态读真源 + 比对基线, 漂移=冻结） ──────
def test_redline_no_drift_passes():
    baseline = {"fields": {"STOP": 0.10, "CHASE": 4.0}}
    r = el.redline_check(lambda: {"STOP": 0.10, "CHASE": 4.0}, baseline)
    assert r["frozen"] is False
    assert r["changed_fields"] == []


def test_redline_drift_freezes_and_names_field():
    baseline = {"fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}}
    # 有人把止损改成 0.12 → 检测到漂移, 冻结 + 点名该字段
    r = el.redline_check(lambda: {"STOP": 0.12, "CHASE": 4.0, "TIME": 120}, baseline)
    assert r["frozen"] is True
    assert "STOP" in r["changed_fields"]
    assert "CHASE" not in r["changed_fields"]


def test_redline_missing_field_is_drift():
    # 基线里有但真源读不到（常量被删）→ 也算漂移（红线只读, 删=改）
    baseline = {"fields": {"STOP": 0.10}}
    r = el.redline_check(lambda: {}, baseline)
    assert r["frozen"] is True
    assert "STOP" in r["changed_fields"]


# ── 冷却铁律（§三: 30日内被拒2次→冷却, 60日内不得再提案） ─────────
def test_cooldown_active_within_window():
    # 最近 30d 内被拒 2 次（-10d, -5d）→ 冷却中（last=-5d, -5d+60d > today）
    rejs = [TODAY - timedelta(days=10), TODAY - timedelta(days=5)]
    assert el.cooldown_active(rejs, TODAY) is True


def test_cooldown_expired_after_ban_period():
    # 被拒在 100d/95d 前 → 冷却期(last=-95d+60d=-35d)已过期 → 可再提案
    rejs = [TODAY - timedelta(days=100), TODAY - timedelta(days=95)]
    assert el.cooldown_active(rejs, TODAY) is False


def test_cooldown_not_enough_rejections():
    # 30d 内只被拒 1 次 → 不触发冷却（铁律要求 2 次）
    rejs = [TODAY - timedelta(days=3)]
    assert el.cooldown_active(rejs, TODAY) is False


def test_cooldown_spread_over_window():
    # 两次被拒间隔 50d（-50d 与 0d）> 30d 窗 → 窗口内只有 1 次 → 不触发
    rejs = [TODAY - timedelta(days=50), TODAY]
    assert el.cooldown_active(rejs, TODAY) is False


# ── 夏普反常（§三: 合入使夏普 > 2.0× 基线 → 人工评审） ─────────────
def test_sharpe_anomaly_triggered():
    assert el.sharpe_anomaly(1.0, 2.5) is True          # 2.5 > 2.0×1.0


def test_sharpe_anomaly_not_triggered():
    assert el.sharpe_anomaly(1.0, 1.9) is False          # 1.9 < 2.0
    assert el.sharpe_anomaly(1.0, 0.0) is False          # 不升反降


def test_sharpe_anomaly_zero_baseline_guard():
    # 基线=0 时比值无意义 → 保守: 只要当前>0 且基线=0 视为反常（防除零, 保守挂起）
    assert el.sharpe_anomaly(0.0, 0.5) is True


# ── 熔断联挂（§四 E4: L0正常/L1升级等待/L2L3自停+urgent） ──────────
def test_circuit_L0_normal():
    r = el.circuit_interlock("L0")
    assert r["pause"] is False and r["escalate"] is False


def test_circuit_L1_escalate_not_pause():
    r = el.circuit_interlock("L1")
    assert r["pause"] is False and r["escalate"] is True


def test_circuit_L2_L3_pause_and_escalate():
    for lv in ("L2", "L3"):
        r = el.circuit_interlock(lv)
        assert r["pause"] is True and r["escalate"] is True, lv


def test_circuit_default_unknown_is_safe():
    # 未知级别 → 保守: 按最高安全（pause+escalate）, 绝不放行（SOUL#9 不静默吞）
    r = el.circuit_interlock("L99")
    assert r["pause"] is True and r["escalate"] is True


# ── run_round 状态机（§五: 五步 + 红线前置 + 熔断 + 门禁 + 冷却） ─
def _mk_props():
    return [
        {"proposal_id": "P1", "source": "C", "target": "top_n", "desc": "top_n 60→40"},
        {"proposal_id": "P2", "source": "A", "target": "VR5_20", "desc": "翻向重测"},
    ]


def _mk_loop(dry_run=True, gate_pass=True, rejections=None,
             read=None, baseline_sharpe=1.0, current_sharpe=1.1,
             lessons_ref=None, log_path=None):
    write_calls = []
    read_fn = read if read is not None else (lambda: {
        "STOP": 0.10, "CHASE": 4.0, "TIME": 120})
    baseline = {"fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}}

    def gate_fn(prop):
        if gate_pass:
            return {"G1_stat": {"pass": True, "ic": 0.04, "ir": 0.5,
                                "rankic_monotonic": True},
                    "G2_robust": {"pass": True, "sharpe_decay_pct": 10.0},
                    "G3_equiv": {"pass": True, "sanity_exit_code": 0}}
        return {"G1_stat": {"pass": False, "ic": 0.02, "ir": 0.25,
                             "rankic_monotonic": False},
                "G2_robust": {"pass": True, "sharpe_decay_pct": 10.0},
                "G3_equiv": {"pass": True, "sanity_exit_code": 0}}

    # P3v2: lessons_ref 可注入（用于冷却判定测试）；log_path 可注入（用于持久化测试）
    return el.EvolutionLoop(
        dry_run=dry_run,
        read_redline_fn=read_fn,
        redline_baseline=baseline,
        gate_fn=gate_fn,
        rejections_by_target=rejections or {},
        write_spy=write_calls.append,
        lessons_ref=lessons_ref if lessons_ref is not None else el.get_lesson_ref(),
        log_path=log_path,
    ), write_calls


def test_run_round_all_green_merged_dryrun_no_write():
    loop, writes = _mk_loop(dry_run=True, gate_pass=True)
    r = loop.run_round(_mk_props(), TODAY, circuit_level="L0",
                       baseline_sharpe=1.0, current_sharpe=1.1)
    statuses = {res["proposal_id"]: res["status"] for res in r["results"]}
    assert statuses == {"P1": "merged_dryrun", "P2": "merged_dryrun"}
    assert writes == []                      # dry_run 零实际写口（红线2）
    assert r["paused"] is False
    assert r["sharpe_anomaly"] is False


def test_run_round_gate_fail_rolls_back_and_records_lesson():
    loop, writes = _mk_loop(dry_run=True, gate_pass=False)
    r = loop.run_round(_mk_props(), TODAY, circuit_level="L0",
                       baseline_sharpe=1.0, current_sharpe=1.1)
    statuses = {res["proposal_id"]: res["status"] for res in r["results"]}
    assert statuses == {"P1": "rolled_back", "P2": "rolled_back"}
    assert all(res["lesson_recorded"] for res in r["results"])
    assert all(res["failed_gate"] == "G1_stat" for res in r["results"])
    assert writes == []


def test_run_round_circuit_L2_pauses_all_and_escalates():
    loop, writes = _mk_loop(dry_run=True, gate_pass=True)
    r = loop.run_round(_mk_props(), TODAY, circuit_level="L2",
                       baseline_sharpe=1.0, current_sharpe=1.1)
    assert r["paused"] is True
    assert any(e["point"] == "E4" for e in r["escalated"])
    assert all(res["status"] == "skipped_paused" for res in r["results"])
    assert writes == []


def test_run_round_redline_drift_freezes_and_rolls_all_back():
    loop, writes = _mk_loop(
        dry_run=True, gate_pass=True,
        read=lambda: {"STOP": 0.12, "CHASE": 4.0, "TIME": 120},  # 止损被改
    )
    r = loop.run_round(_mk_props(), TODAY, circuit_level="L0",
                       baseline_sharpe=1.0, current_sharpe=1.1)
    assert any(e["point"] == "E1" for e in r["escalated"])
    assert all(res["status"] == "skipped_paused" for res in r["results"])
    assert all(not res["lesson_recorded"] for res in r["results"])  # 非门禁失败, 不记教训
    assert writes == []


def test_run_round_cooldown_skips_rejected_target():
    """P3v2: 冷却判定读 lessons[] 真源（旧 rejections 参数已无效）"""
    import tempfile, os, json as _json
    # 构造 pre-seeded lessons: top_n 近30天内2次被拒 → 冷却中
    lesson1 = {"lesson_id": "L_2026-09-29_0001", "target": "top_n", "status": "rejected",
               "last_rejection": "2026-09-29", "rejection_count": 1}
    lesson2 = {"lesson_id": "L_2026-10-04_0002", "target": "top_n", "status": "rejected",
               "last_rejection": "2026-10-04", "rejection_count": 2}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                     encoding='utf-8') as f:
        _json.dump({"version": "1.1", "redline_baseline": {"fields": {}},
                    "lessons": [lesson1, lesson2]}, f)
        tmp_log = f.name
    try:
        loop, writes = _mk_loop(
            dry_run=True, gate_pass=True,
            log_path=tmp_log,  # P3v2: 读 lessons 真源
        )
        r = loop.run_round(_mk_props(), TODAY, circuit_level="L0",
                           baseline_sharpe=1.0, current_sharpe=1.1)
        statuses = {res["proposal_id"]: res["status"] for res in r["results"]}
        assert statuses["P1"] == "skipped_cooldown"      # top_n 冷却中
        assert statuses["P2"] == "merged_dryrun"         # VR5_20 无冷却, 正常
        assert writes == []
    finally:
        os.unlink(tmp_log)


def test_run_round_sharpe_anomaly_escapes_human_review():
    loop, writes = _mk_loop(dry_run=True, gate_pass=True,
                            baseline_sharpe=1.0, current_sharpe=2.5)
    r = loop.run_round(_mk_props(), TODAY, circuit_level="L0",
                       baseline_sharpe=1.0, current_sharpe=2.5)
    assert r["sharpe_anomaly"] is True
    assert any(e["point"] == "E5" for e in r["escalated"])


def test_run_round_lesson_recorded_uses_injected_ref():
    # 验证教训库走注入的写口（可测, 不真写盘）
    ref = el.get_lesson_ref()
    loop, _ = _mk_loop(dry_run=True, gate_pass=False, lessons_ref=ref)
    loop.run_round(_mk_props(), TODAY, circuit_level="L0",
                   baseline_sharpe=1.0, current_sharpe=1.1)
    assert len(ref) == 2      # 2 个提案各记 1 条教训
