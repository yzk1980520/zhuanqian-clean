# -*- coding: utf-8 -*-
"""R1-P5 t_45357e19: M-3 探针 state 再冻结加固（self_audit_checkers）

AC 覆盖:
  1. SKIPPED 路径也写 state（last_run 推进 + skipped_reason 枚举），不得冻结
     —— 冻结态是 10-19 型「次日误升级 P0」的复发条件
  2. skipped_reason 三类枚举: parse_fail / timeout / no_data；
     实测轮（PASS/FAIL）skipped_reason=None；非法枚举/非 int 实测值拒绝写入（响铃不静默）
  3. consecutive 死字段消费方断言: state 从未写入该键（M-3 写回仅 4 字段），
     遗留键不再影响判定；SKIPPED 态 violations_count=null 断连续链 → 不触发 P0 误升级
     （2 个相邻实测违规日 → P0 的节奏不变）

运行: 仓根 pytest tests/test_m3_probe_state.py -q（QSP 门禁口径 scripts/test_*.py 之外）
"""
import json
import os
import subprocess
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import core.ops.self_audit_checkers as shc


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def tmp_state(monkeypatch):
    """把探针 state 路径指到临时文件，隔离 live data/dispatch_audit_state.json"""
    fd, path = tempfile.mkstemp(prefix="m3_probe_state_", suffix=".json")
    os.close(fd)
    monkeypatch.setattr(shc, "_DISPATCH_AUDIT_STATE_PATH", path)
    yield path
    try:
        os.unlink(path)
    except OSError as e:
        print("🔴 [t_45357e19] tmp_state 清理失败(响铃不静默): %s" % e, flush=True)


@pytest.fixture(autouse=True)
def _restore_queue():
    """FAIL 路径会追加 dispatchaudit_* 到 live message_queue.json —— 收走后清掉，防跨测试污染"""
    yield
    from core.pipeline import atomic_json
    qpath = os.path.join(shc.DATA_DIR, "message_queue.json")
    try:
        items = atomic_json.atomic_load(qpath, []) or []
        items = [m for m in items if not str(m.get("id", "")).startswith("dispatchaudit_")]
        atomic_json.atomic_dump(items, qpath)
    except Exception as e:
        print("🔴 [t_45357e19] 队列清理失败(响铃不静默): %s" % e, flush=True)


def _fail_rep(n=1):
    return {
        "ok": False, "checked": 3, "scope_since": "2026-10-16T20:16:00",
        "violations": [{"id": "t_%d" % i, "rule": "C1", "detail": "d"} for i in range(n)],
    }


def _seed_state(path, **kw):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kw, f, ensure_ascii=False)


def _run_m3(trigger):
    """按 trigger 触发 check_m3_dispatch_audit 一条路径，返回 AuditResult"""
    if trigger == "timeout":
        with patch("subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60)):
            return shc.check_m3_dispatch_audit()
    if trigger == "call_error":
        with patch("subprocess.run", side_effect=OSError("call boom")):
            return shc.check_m3_dispatch_audit()
    if trigger == "parse_fail":
        m = MagicMock(returncode=0, stdout="not json {{{", stderr="")
        with patch("subprocess.run", return_value=m):
            return shc.check_m3_dispatch_audit()
    if trigger == "missing_script":
        monkey_root = "/nonexistent_root_xyz_45357e19"
        with patch.object(shc, "ROOT", monkey_root):
            return shc.check_m3_dispatch_audit()
    if trigger == "fail":
        m = MagicMock(returncode=1, stdout=json.dumps(_fail_rep(1), ensure_ascii=False), stderr="")
        with patch("subprocess.run", return_value=m):
            return shc.check_m3_dispatch_audit()
    if trigger == "pass":
        rep = {"ok": True, "checked": 5, "scope_since": "2026-10-26T08:00:00", "violations": []}
        m = MagicMock(returncode=0, stdout=json.dumps(rep, ensure_ascii=False), stderr="")
        with patch("subprocess.run", return_value=m):
            return shc.check_m3_dispatch_audit()
    raise ValueError("unknown trigger: %s" % trigger)


# ---------------------------------------------------------------- AC2/3: SKIPPED 不冻结

@pytest.mark.parametrize("trigger,expected_reason", [
    ("timeout", "timeout"),
    ("parse_fail", "parse_fail"),
    ("call_error", "no_data"),
    ("missing_script", "no_data"),
])
def test_m3_skipped_writes_state_no_freeze(tmp_state, trigger, expected_reason):
    """AC2: 每条 SKIPPED 路径 state 都写（last_run 推进 + skipped_reason + violations_count=null）"""
    t0 = datetime.now().isoformat(timespec="seconds")
    r = _run_m3(trigger)
    assert r.status == "SKIPPED", "%s 应 SKIPPED: %s" % (trigger, r.message)
    st = json.load(open(tmp_state, encoding="utf-8"))
    assert st["skipped_reason"] == expected_reason, st
    assert st["violations_count"] is None, "SKIPPED 轮不得伪造实测值(防假绿): %s" % st
    assert st["last_run"] >= t0, "last_run 必须推进(不冻结): %s" % st


# ---------------------------------------------------------------- AC1: skipped_reason 枚举

def test_m3_skipped_reason_enum_values():
    assert tuple(shc._M3_SKIP_REASONS) == ("parse_fail", "timeout", "no_data")


def test_m3_write_state_rejects_bad_enum(tmp_state):
    """非法枚举 → ValueError 响铃（编程错误必须 loud），state 不落盘"""
    with pytest.raises(ValueError):
        shc._m3_write_state(skipped_reason="weird_reason")
    assert not os.path.exists(tmp_state) or os.path.getsize(tmp_state) == 0


def test_m3_write_state_rejects_non_int_measured(tmp_state):
    """实测轮 violations_count 必须是 int（防字符串/None 伪实测）"""
    with pytest.raises(ValueError):
        shc._m3_write_state(violations_count="19")
    with pytest.raises(ValueError):
        shc._m3_write_state(violations_count=None)


def test_m3_measured_run_writes_skipped_reason_none(tmp_state):
    """AC1 对偶面: 实测轮（PASS）state 写 skipped_reason=None + violations_count 实测 0 + checked 实测"""
    r = _run_m3("pass")
    assert r.status == "PASS", r.message
    st = json.load(open(tmp_state, encoding="utf-8"))
    assert st["skipped_reason"] is None
    assert st["violations_count"] == 0
    assert st["checked"] == 5
    assert "scope_since" in st


# ---------------------------------------------------------------- AC3: 死字段消费方断言

@pytest.mark.parametrize("prev_state,exp_sev,exp_consec", [
    # 遗留 state 带死字段 consecutive=1: 新判定不消费该键 → consecutive 收敛 2（旧逻辑同 P0，数值收敛）
    ({"violations_count": 1, "consecutive": 1}, "P0", 2),
    # 死字段大值不再放大: 旧逻辑会算 consecutive=5，新逻辑只看 violations_count → 2
    ({"violations_count": 1, "consecutive": 3}, "P0", 2),
    # SKIPPED 态（violations_count=null）→ 连续链断开 → P1，不得误升级 P0（10-19 型防复发）
    ({"violations_count": None, "skipped_reason": "timeout"}, "P1", 1),
    # 上轮实测 0 违规 → 链条未起 → P1
    ({"violations_count": 0}, "P1", 1),
    # 上轮实测 19 违规（无死字段，live 态形状）→ 连续 2 日 → P0（2日 P1→P0 节奏不变）
    ({"violations_count": 19, "checked": 5}, "P0", 2),
])
def test_m3_consecutive_dead_field_removed(tmp_state, prev_state, exp_sev, exp_consec):
    """AC3: 判定面唯一消费 violations_count 实测值；consecutive 死键删除后行为等价/收敛"""
    _seed_state(tmp_state, last_run="2026-10-25T20:00:00", **prev_state)
    r = _run_m3("fail")
    assert r.status == "FAIL", r.message
    assert r.severity == exp_sev, "prev=%s 期望 %s: %s" % (prev_state, exp_sev, r.evidence)
    assert r.details["consecutive"] == exp_consec
    st = json.load(open(tmp_state, encoding="utf-8"))
    assert "consecutive" not in st, "死字段不得再落 state: %s" % st
    assert st["skipped_reason"] is None and st["violations_count"] == 1, st
