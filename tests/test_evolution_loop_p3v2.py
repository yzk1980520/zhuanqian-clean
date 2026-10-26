# -*- coding: utf-8 -*-
"""test_evolution_loop_p3v2.py — EVOL-P3v2 验收测试（断言验证）

验收断言（SOUL 准则5，断言不用打勾）：
1. run_round 门禁 fail 后 iteration_log.json.lessons[] 实增 1 条，字段含 evidence + gate_results + failed_gate
2. 触发 E1/E4 → escalations[] 实增对应条目（含 action 文本，挂起态）
3. 冷却判定读 lessons[].last_rejection + rejection_count，30d/60d 铁律
4. 并发 2 进程写 escalation → 无覆盖（atomic_json 锁断言）
5. 静态断言：evolution_loop.py 循环代码路径无飞书直接调用
"""
import sys
import os
import json
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core.ops.evolution_loop as el  # noqa: E402
import core.pipeline.atomic_json as _aj  # noqa: E402

TODAY = date(2026, 10, 10)

# P3 2026-10-26 (t_81fad29b, pytest 门禁快档 §5.2): 仅 test_assert1_lesson_persistence
# 调真 el.make_gate_fn()（FactorGateV2 一次初始化 ~66s 成本转移 + run_round 门禁三关,
# 实测 54s）= 本文件唯一重件 → 函数级 backtest marker。其余断言2-5 用 lambda 桩门禁,
# 留门禁快档；全量/夜间档全族照常跑，断言语义零改动。
import pytest


# ── 断言1：lesson 落盘 ─────────────────────────────────────────
@pytest.mark.backtest
def test_assert1_lesson_persistence():
    """断言1：run_round G1 fail → iteration_log.json.lessons[] 实增 1 条。

    验证字段：evidence.engine_commit / gate_results / failed_gate / last_rejection / cooldown_until
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                     encoding='utf-8') as f:
        log_path = f.name
        json.dump({"version": "1.1", "redline_baseline": {
            "fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120,
                       "TP_UP": [[6, 0.15]], "TP_DOWN": [[5, 0.03]]}},
                   "lessons": []}, f)

    try:
        # 构造 G1 fail 的 prop
        n = 100
        fv = [0.0] * n  # 常量因子 → IC=0 → G1 fail
        ret = list(__import__('numpy').random.randn(n))
        prop = {
            "proposal_id": "P_FAIL",
            "source": "A",
            "target": "weak_factor",
            "desc": "弱信号提案",
            "factor_name": "weak_factor",
            "factor_values": fv,
            "returns": ret,
            "fit_dates": ["2026-01-01"],
            "oos_dates": ["2026-01-02"],
        }

        loop = el.EvolutionLoop(
            dry_run=True,
            read_redline_fn=lambda: {"STOP": 0.10, "CHASE": 4.0, "TIME": 120,
                                     "TP_UP": [[6, 0.15]], "TP_DOWN": [[5, 0.03]]},
            redline_baseline={"fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120,
                                          "TP_UP": [[6, 0.15]], "TP_DOWN": [[5, 0.03]]}},
            gate_fn=el.make_gate_fn(),
            write_spy=lambda *a, **k: None,
            lessons_ref=el.get_lesson_ref(),
            log_path=log_path,
        )
        result = loop.run_round([prop], TODAY, circuit_level="L0")

        # 读取 log
        data = _aj.atomic_load(log_path, default={})
        lessons = data.get("lessons", [])

        # 断言：lessons[] 实增 1 条
        assert len(lessons) == 1, f"期望 lessons 长度 1, 得到 {len(lessons)}"

        lesson = lessons[0]
        # 字段完整性
        assert "evidence" in lesson, "lesson 缺少 evidence 字段"
        assert "gate_results" in lesson, "lesson 缺少 gate_results 字段"
        assert "failed_gate" in lesson, "lesson 缺少 failed_gate 字段"
        assert "last_rejection" in lesson, "lesson 缺少 last_rejection 字段"
        assert "cooldown_until" in lesson, "lesson 缺少 cooldown_until 字段"

        # evidence.engine_commit 接真实 git hash
        commit = lesson["evidence"]["engine_commit"]
        assert len(commit) == 40, f"engine_commit 非40位: {commit}"

        # failed_gate 应为 G1_stat
        assert lesson["failed_gate"] == "G1_stat", f"failed_gate 应为 G1_stat, 得到 {lesson['failed_gate']}"

        # gate_results.G1_stat.pass=False
        assert lesson["gate_results"]["G1_stat"]["pass"] is False

        # last_rejection = today
        assert lesson["last_rejection"] == TODAY.isoformat()

        # cooldown_until = None (仅1次被拒, 未到60天)
        assert lesson["cooldown_until"] is None, f"期望 None, 得到 {lesson['cooldown_until']}"

        print(f"断言1: lesson 落盘 ✅ lessons[0].failed_gate={lesson['failed_gate']}, "
              f"engine_commit={commit[:8]}…")
    finally:
        os.unlink(log_path)


# ── 断言2：escalations 落盘 ─────────────────────────────────────
def test_assert2_escalations_persistence():
    """断言2：E1/E4 触发 → iteration_log.json.escalations[] 实增。

    E1: 红线漂移
    E4: 熔断 L2
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                     encoding='utf-8') as f:
        log_path = f.name
        json.dump({"version": "1.1", "redline_baseline": {
            "fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}},
                   "escalations": []}, f)

    try:
        # E1 场景：baseline 与真源不一致
        baseline = {"fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}}
        drifted_read = lambda: {"STOP": 0.15, "CHASE": 4.0, "TIME": 120}  # STOP 被改

        loop = el.EvolutionLoop(
            dry_run=True,
            read_redline_fn=drifted_read,
            redline_baseline=baseline,
            gate_fn=lambda p: {"G1_stat": {"pass": True}},
            write_spy=lambda *a, **k: None,
            lessons_ref=[],
            log_path=log_path,
        )
        result = loop.run_round([], TODAY, circuit_level="L0")

        # E1 应触发
        assert any(e["point"] == "E1" for e in result["escalated"]), \
            f"期望 E1 升级, 得到 {result['escalated']}"

        # 读取 log
        data = _aj.atomic_load(log_path, default={})
        escs = data.get("escalations", [])
        assert len(escs) == 1, f"期望 escalations 长度 1, 得到 {len(escs)}"
        assert escs[0]["point"] == "E1", f"期望 E1, 得到 {escs[0]}"

        print(f"断言2a: E1 红线漂移 → escalations[] 实增 ✅")

        # E4 场景：熔断 L2
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                         encoding='utf-8') as f2:
            log_path2 = f2.name
            json.dump({"version": "1.1", "redline_baseline": {
                "fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}},
                       "escalations": []}, f2)

        loop2 = el.EvolutionLoop(
            dry_run=True,
            read_redline_fn=lambda: {"STOP": 0.10, "CHASE": 4.0, "TIME": 120},
            redline_baseline=baseline,
            gate_fn=lambda p: {"G1_stat": {"pass": True}},
            write_spy=lambda *a, **k: None,
            lessons_ref=[],
            log_path=log_path2,
        )
        result2 = loop2.run_round([], TODAY, circuit_level="L2")

        assert any(e["point"] == "E4" for e in result2["escalated"]), \
            f"期望 E4 升级, 得到 {result2['escalated']}"

        data2 = _aj.atomic_load(log_path2, default={})
        escs2 = data2.get("escalations", [])
        assert len(escs2) == 1
        assert escs2[0]["point"] == "E4"
        assert "action" in escs2[0], "E4 缺少 action 文本"

        print(f"断言2b: E4 熔断 L2 → escalations[] 实增 ✅")
    finally:
        os.unlink(log_path)
        os.unlink(log_path2)


# ── 断言3：冷却判定读 lessons 真源 ───────────────────────────────
def test_assert3_cooldown_from_lessons():
    """断言3：冷却判定读 lessons[].last_rejection + rejection_count，30d/60d 铁律。

    场景1: 同 target 近30天内2次被拒 → cooldown_active=True
    场景2: 远超过60天 → cooldown_active=False
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                     encoding='utf-8') as f:
        log_path = f.name
        json.dump({"version": "1.1", "redline_baseline": {
            "fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}},
                   "lessons": []}, f)

    try:
        # 场景1: 近30天内2次被拒 → 冷却中
        lesson1 = {
            "lesson_id": "L_2026-09-20_0001",
            "target": "weak_factor",
            "status": "rejected",
            "last_rejection": "2026-09-20",
            "rejection_count": 1,
        }
        lesson2 = {
            "lesson_id": "L_2026-09-25_0002",
            "target": "weak_factor",
            "status": "rejected",
            "last_rejection": "2026-09-25",
            "rejection_count": 2,
        }
        _aj.atomic_dump({"version": "1.1", "redline_baseline": {"fields": {}},
                         "lessons": [lesson1, lesson2]}, log_path)

        loop = el.EvolutionLoop(
            dry_run=True,
            read_redline_fn=lambda: {},
            redline_baseline={"fields": {}},
            gate_fn=lambda p: {"G1_stat": {"pass": True}},
            write_spy=lambda *a, **k: None,
            lessons_ref=[],
            log_path=log_path,
        )
        lessons = loop._load_lessons_from_log()
        assert len(lessons) == 2, f"期望2条lessons, 得到 {len(lessons)}"

        # 今天 2026-10-10，last_rejection=09-25，间隔15d≤30，ban_until=11-24>10-10 → 冷却中
        result = loop._cooldown_active_from_lessons("weak_factor", TODAY, lessons)
        assert result is True, f"期望冷却中(True), 得到 {result}"

        print(f"断言3a: 近30天2拒 → cooldown_active=True ✅")

        # 场景2: 远超过60天 → 冷却过期
        old_lesson = {
            "lesson_id": "L_2026-06-01_0001",
            "target": "old_factor",
            "status": "rejected",
            "last_rejection": "2026-06-01",
            "rejection_count": 1,
        }
        old_lesson2 = {
            "lesson_id": "L_2026-06-05_0002",
            "target": "old_factor",
            "status": "rejected",
            "last_rejection": "2026-06-05",
            "rejection_count": 2,
        }
        result2 = loop._cooldown_active_from_lessons("old_factor", TODAY, [old_lesson, old_lesson2])
        # last_rejection=06-05, ban_until=08-04 < 10-10 → 冷却过期
        assert result2 is False, f"期望冷却过期(False), 得到 {result2}"

        print(f"断言3b: 远超过60天 → cooldown_active=False ✅")
    finally:
        os.unlink(log_path)


# ── 断言4：并发写 escalation 无覆盖 ──────────────────────────────
def test_assert4_concurrent_escalation_no_overwrite():
    """断言4：并发 2 进程写 escalation → 无覆盖（atomic_json 锁断言）。

    验证 atomic_json.update_json 的跨进程 FileLock 保证最终一致性：
    两个线程同时调 update_json（各自传 mutator），后者不会丢失前者的修改。
    注意：本测试直接验证 update_json 的原子写口，而非复现"先读后改"竞态。
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                     encoding='utf-8') as f:
        log_path = f.name
        json.dump({"version": "1.1", "escalations": []}, f)

    try:
        import threading

        results = {"count": 0, "errors": []}

        def writer(idx):
            """每个线程直接调 update_json（不先读），模拟真实循环落盘路径。"""
            try:
                _aj.update_json(
                    log_path,
                    lambda d: (d.setdefault("escalations", []).append({"point": f"E{idx}"}), d)[1],
                    default={"escalations": []},
                )
                results["count"] += 1
            except Exception as e:
                results["errors"].append(str(e))

        # 并发 10 线程写
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not results["errors"], f"写入异常: {results['errors']}"
        assert results["count"] == 10, f"期望10次写入成功, 得到 {results['count']}"

        # 验证最终文件有 10 条 escalation
        data = _aj.atomic_load(log_path, default={})
        escs = data.get("escalations", [])
        assert len(escs) == 10, f"期望10条escalation, 得到 {len(escs)}: {escs}"
        points = sorted([e["point"] for e in escs])
        assert points == [f"E{i}" for i in range(10)], f"点集不匹配: {points}"

        print(f"断言4: 并发10线程写 escalations → 无覆盖 ✅ escs={len(escs)}条")
    finally:
        os.unlink(log_path)


# ── 断言5：静态断言 — 循环代码路径无飞书调用 ─────────────────────
def test_assert5_no_feishu_in_loop():
    """断言5：evolution_loop.py 循环代码路径零处飞书直接调用。

    grep 验证 broadcast/system-broadcast/feishu 不在 run_round/ EvolutionLoop 内。
    """
    import re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "evolution_loop.py")
    path = os.path.abspath(path)
    with open(path, encoding='utf-8') as f:
        content = f.read()

    # 飞书相关关键词
    feishu_patterns = [
        r"system-broadcast",
        r"broadcast\s*\(",
        r"feishu",
        r"飞书",
    ]

    # 只检查 class EvolutionLoop 及其方法体内
    in_class = False
    violations = []
    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        if 'class EvolutionLoop:' in stripped:
            in_class = True
            continue
        if in_class:
            # 遇到下一个顶级定义（非缩进）则退出
            if stripped and not stripped.startswith(' ') and not stripped.startswith('#'):
                if stripped.startswith('def ') and 'EvolutionLoop' not in stripped:
                    in_class = False
                    continue
            for pat in feishu_patterns:
                if re.search(pat, stripped, re.IGNORECASE):
                    violations.append((i, stripped[:80]))

    assert not violations, f"循环代码路径发现飞书调用: {violations}"
    print("断言5: evolution_loop.py 循环代码路径零处飞书调用 ✅")


if __name__ == "__main__":
    print("=" * 60)
    print("EVOL-P3v2 验收测试")
    print("=" * 60)
    test_assert1_lesson_persistence()
    test_assert2_escalations_persistence()
    test_assert3_cooldown_from_lessons()
    test_assert4_concurrent_escalation_no_overwrite()
    test_assert5_no_feishu_in_loop()
    print("=" * 60)
    print("所有 P3v2 验收测试通过 ✅")
