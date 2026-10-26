#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A12 / A0 / A3 判据的「降级自证」回归测试（2026-10-21 立）

为什么要有这个文件：
  升级判据会让健康度**由绿转红**（本次 89.3% → 75.0%）。看到红色的人最省事的
  "修复"就是把判据改回宽松。光在文件头写"严禁"不够 —— 必须能**证明**判据真的能
  分辨好坏，并且让"改回宽松"这个动作立刻产生失败。
  本文件是三道防误操作里的第 1 道（第 2 道 = guard G17~G20，第 3 道 = 头部严禁清单）。

三档结构（只跑绿不算证明，必须红绿都能跑出来）：
  PASS 档  正常态                       ⇒ 判据必须判 PASS
  FAIL 档  人为制造违规（不碰生产数据） ⇒ 判据必须判 FAIL，且**点名**具体原因
  BOUNDARY 刚好卡在阈值上的值           ⇒ 判定符合预期（恰好等于阈值 ⇒ 不判红）

⚠️ 铁律: 全部场景用 tmp_path / monkeypatch 构造，**绝不读写生产 data/**。
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "closedloop_health_under_test", ROOT / "scripts" / "closedloop_health.py")
cl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cl)


# ── 工具：构造与生产完全隔离的假环境 ────────────────────────────────────────

def _task(hidden, command, args="", triggers=("CalendarTrigger@2026-10-21T07:30:00",)):
    """模拟 _load_scheduled_tasks 返回的单条记录形态。"""
    return {"hidden": hidden, "command": command, "arguments": args,
            "triggers": list(triggers), "state": "Ready"}


@pytest.fixture
def fake_scripts(tmp_path):
    """临时 scripts/ 目录，含 A12 所需的静默 runner 与 A3 所需的脚本。"""
    s = tmp_path / "scripts"
    s.mkdir()
    (s / "run_path_hidden.vbs").write_text("' stub\n", encoding="utf-8")
    (s / "feedback_to_factor.py").write_text("# stub\n", encoding="utf-8")
    return s


def _setup_a12(fake_scripts, monkeypatch, tasks):
    monkeypatch.setattr(cl, "SCRIPTS_DIR", fake_scripts)
    monkeypatch.setattr(cl, "CARRIER_SPECS", [
        ("A", "载体A", "A.bat"), ("B", "载体B", "B.bat"), ("C", "载体C", "C.bat"),
    ])
    for n in ("A", "B", "C"):
        (fake_scripts / f"{n}.bat").write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(cl, "_load_scheduled_tasks", lambda **k: tasks)


# ════════════════════════════════════════════════════════════════════════════
# PASS 档
# ════════════════════════════════════════════════════════════════════════════

def test_pass_tier_a12_all_compliant(fake_scripts, monkeypatch):
    """PASS 档: 全部载体 Hidden=true 且宿主 ∈ SILENT_HOSTS ⇒ A12 判 PASS。"""
    _setup_a12(fake_scripts, monkeypatch, {
        "A": _task(True, "wscript.exe"),
        "B": _task(True, r"C:\WINDOWS\System32\wscript.exe"),
        "C": _task(True, r"D:\x\.venv\Scripts\pythonw.exe"),
    })
    r = cl.check_a12_schedule_carrier()
    assert r["status"] == "PASS", r["detail"]
    assert "3/3" in r["detail"]
    assert r["extra_lines"], "合规清单表必须输出"


def test_pass_tier_a0_fresh_heartbeat(tmp_path, monkeypatch):
    """PASS 档: history 存在且心跳新鲜 ⇒ A0 判 PASS。"""
    p = tmp_path / "closedloop_history.jsonl"
    p.write_text(json.dumps({"ts": datetime.now().isoformat()}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cl, "HISTORY_FILE", p)
    r = cl.check_a0_meta_selfcheck()
    assert r["status"] == "PASS", r["detail"]


# ════════════════════════════════════════════════════════════════════════════
# FAIL 档
# ════════════════════════════════════════════════════════════════════════════

def test_fail_tier_a12_hidden_not_set(fake_scripts, monkeypatch):
    """FAIL 档: 撤掉某个载体的 Hidden ⇒ A12 判 FAIL 且点名 Hidden。"""
    _setup_a12(fake_scripts, monkeypatch, {
        "A": _task(None, "wscript.exe"),          # Hidden 未设置
        "B": _task(True, "wscript.exe"),
        "C": _task(True, "pythonw.exe"),
    })
    r = cl.check_a12_schedule_carrier()
    assert r["status"] == "FAIL", r["detail"]
    assert "Hidden" in r["detail"]
    assert "载体A" in r["detail"], "必须点名具体载体"


def test_fail_tier_a12_command_points_to_bat(fake_scripts, monkeypatch):
    """FAIL 档: Command 直指 .bat ⇒ A12 判 FAIL 且点名 Command 宿主。"""
    _setup_a12(fake_scripts, monkeypatch, {
        "A": _task(True, r"D:\x\daily_auto.bat"),   # 直指 bat
        "B": _task(True, "wscript.exe"),
        "C": _task(True, "pythonw.exe"),
    })
    r = cl.check_a12_schedule_carrier()
    assert r["status"] == "FAIL", r["detail"]
    assert "宿主非静默" in r["detail"]
    assert "载体A" in r["detail"]


def test_fail_tier_a12_cmd_exe_host(fake_scripts, monkeypatch):
    """FAIL 档: Command = cmd.exe（Zhuanqian_DailyAuto 的真实形态）⇒ FAIL。"""
    _setup_a12(fake_scripts, monkeypatch, {
        "A": _task(None, "cmd", '/c "D:\\x\\daily_auto.bat"',
                   triggers=("CalendarTrigger@2026-08-19T20:00:00",)),
        "B": _task(True, "wscript.exe"),
        "C": _task(True, "wscript.exe"),
    })
    r = cl.check_a12_schedule_carrier()
    assert r["status"] == "FAIL", r["detail"]
    assert "cmd" in r["detail"]
    # cmd /c 直跑 bat 应同时触发 Hidden 与宿主两条违规
    assert r["detail"].count("载体A") >= 1


def test_fail_tier_a0_history_missing(tmp_path, monkeypatch):
    """FAIL 档: 心跳文件被挪走 ⇒ A0 判 FAIL 且点名文件路径。"""
    gone = tmp_path / "closedloop_history.jsonl"
    monkeypatch.setattr(cl, "HISTORY_FILE", gone)     # 仅指向临时路径，不动生产
    assert not gone.exists()
    r = cl.check_a0_meta_selfcheck()
    assert r["status"] == "FAIL", r["detail"]
    assert "closedloop_history.jsonl" in r["detail"], "必须点名具体文件"


def test_fail_tier_a0_history_unparsable(tmp_path, monkeypatch):
    """FAIL 档: 心跳文件全部行不可解析 ⇒ A0 判 FAIL（旧版此处兜底 PASS）。"""
    p = tmp_path / "closedloop_history.jsonl"
    p.write_text("{not json at all}\n<<<garbage>>>\n", encoding="utf-8")
    monkeypatch.setattr(cl, "HISTORY_FILE", p)
    r = cl.check_a0_meta_selfcheck()
    assert r["status"] == "FAIL", r["detail"]
    assert "解析失败" in r["detail"]


def test_fail_tier_a0_missing_ts(tmp_path, monkeypatch):
    """FAIL 档: 末条记录缺 ts 字段 ⇒ A0 判 FAIL（旧版此处兜底 PASS）。"""
    p = tmp_path / "closedloop_history.jsonl"
    p.write_text(json.dumps({"score": 1.0}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cl, "HISTORY_FILE", p)
    r = cl.check_a0_meta_selfcheck()
    assert r["status"] == "FAIL", r["detail"]
    assert "ts" in r["detail"]


def test_fail_tier_a3_stale_feedback(tmp_path, monkeypatch):
    """FAIL 档: feedback_log 末条为 10 天前 ⇒ A3 判 FAIL 且点名末条时间。

    对照: 旧判据用「近 48h 新增条数」，实测 45.4h 无新增仍报 PASS（假绿）。
    """
    p = tmp_path / "feedback_log.jsonl"
    old = (datetime.now() - timedelta(days=10)).isoformat()
    p.write_text(json.dumps({"ts": old, "v": 1}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cl, "FEEDBACK_LOG", p)
    monkeypatch.setattr(cl, "FEEDBACK_SUGGESTIONS", tmp_path / "nope.json")
    r = cl.check_a3_feedback_write()
    assert r["status"] == "FAIL", r["detail"]
    assert "停摆" in r["detail"]
    assert old[:10] in r["detail"], "必须点名末条时间戳"


# ════════════════════════════════════════════════════════════════════════════
# BOUNDARY 档
# ════════════════════════════════════════════════════════════════════════════

def test_boundary_business_hours_exactly_24h():
    """边界档: 工作日小时恰好 = soft(24h) ⇒ 不判超期（判据是 `>` 而非 `>=`）。"""
    mon = datetime(2026, 10, 19, 9, 0, 0)    # 周一
    tue = datetime(2026, 10, 20, 9, 0, 0)     # 周二
    assert cl._business_hours_between(mon, tue) == pytest.approx(24.0)


def test_boundary_weekend_excluded():
    """边界档: 周五 18:00 → 下周三 18:00，工作日口径恰好 72h ⇒ 不判停摆。

    这条同时证明「周末豁免」生效: 自然时间跨度是 120h(5 天)，
    若按自然小时算会被误判为停摆，扣除 48h 周末后恰好 72h，不判红。
    """
    fri = datetime(2026, 10, 16, 18, 0, 0)   # 周五
    wed = datetime(2026, 10, 21, 18, 0, 0)   # 下周三
    hours = cl._business_hours_between(fri, wed)
    assert hours == pytest.approx(72.0)
    assert not (hours > cl.A3_HARD_H)


def test_boundary_a3_just_below_soft(tmp_path, monkeypatch):
    """边界档: 末条 23h 前（工作日口径 ≤ 23h < soft 24h）⇒ A3 判 PASS。"""
    p = tmp_path / "feedback_log.jsonl"
    ts = (datetime.now() - timedelta(hours=23)).isoformat()
    p.write_text(json.dumps({"ts": ts, "v": 1}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cl, "FEEDBACK_LOG", p)
    monkeypatch.setattr(cl, "FEEDBACK_SUGGESTIONS", tmp_path / "nope.json")
    r = cl.check_a3_feedback_write()
    assert r["status"] == "PASS", r["detail"]


def test_boundary_a12_hidden_string_variants(fake_scripts, monkeypatch):
    """边界档: Hidden 为布尔 True ⇒ 合规；为 'false' ⇒ 不合规。"""
    _setup_a12(fake_scripts, monkeypatch, {
        "A": _task(True, "wscript.exe"),
        "B": _task(False, "wscript.exe"),          # XML 显式 false
        "C": _task(True, "pythonw.exe"),
    })
    r = cl.check_a12_schedule_carrier()
    assert r["status"] == "FAIL", r["detail"]
    assert "载体B" in r["detail"]


def test_boundary_a3_stale_is_not_pass(tmp_path, monkeypatch):
    """边界档: 末条 26h 前 ⇒ 工作日口径 > soft(24h) 时不得为 PASS。

    只在未跨周末时严格断言；跨周末时允许 PASS(周末豁免本就应该让它绿)。
    """
    p = tmp_path / "feedback_log.jsonl"
    ts = (datetime.now() - timedelta(hours=26)).isoformat()
    p.write_text(json.dumps({"ts": ts, "v": 1}) + "\n", encoding="utf-8")
    monkeypatch.setattr(cl, "FEEDBACK_LOG", p)
    monkeypatch.setattr(cl, "FEEDBACK_SUGGESTIONS", tmp_path / "nope.json")
    r = cl.check_a3_feedback_write()
    # 2026-10-24 T051 C4 对齐: 周末豁免取决于区间任一端是否落周末 (原判据只看 ts 端:
    # 周六运行 + ts=周五 时 26h 窗口已含周六 → 豁免生效 → PASS 是脚本正确行为, 原误红)。
    spans_weekend = (datetime.now() - timedelta(hours=26)).weekday() >= 5 or datetime.now().weekday() >= 5
    if not spans_weekend:
        assert r["status"] != "PASS", r["detail"]
    assert r["status"] in ("PASS", "PARTIAL", "FAIL")


# ════════════════════════════════════════════════════════════════════════════
# 守卫自身有效性：证明「改回宽松」会被抓住
# ════════════════════════════════════════════════════════════════════════════

def _guard_module():
    spec = importlib.util.spec_from_file_location(
        "guard_under_test", ROOT / "scripts" / "guard_assertion_effectiveness.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


def test_guard_g17_detects_hidden_check_removal(monkeypatch):
    """反向自证: 若有人删掉 `if hidden is not True:` ⇒ G17 必须报 FAIL。"""
    g = _guard_module()
    src = Path(cl.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "if hidden is not True:" in src, "前置条件: 生产代码应含 Hidden 判定"

    degraded = src.replace("if hidden is not True:", "pass  # 降级: 不再校验 Hidden\n    if False:")
    monkeypatch.setattr(g, "_read", lambda p: degraded)
    ok, detail = g.check_g17()
    assert not ok, f"G17 未能识别 Hidden 判定被删: {detail}"
    print(f"    [G17 捕获降级] {detail}")


def test_guard_g17_detects_host_check_removal(monkeypatch):
    """反向自证: 若有人把宿主白名单判定改成恒真 ⇒ G17 报 FAIL。"""
    g = _guard_module()
    src = Path(cl.__file__).read_text(encoding="utf-8", errors="ignore")
    degraded = src.replace("if host not in SILENT_HOSTS:", "if False:")
    monkeypatch.setattr(g, "_read", lambda p: degraded)
    ok, detail = g.check_g17()
    assert not ok, f"G17 未能识别宿主白名单判定被删: {detail}"
    print(f"    [G17 捕获降级] {detail}")


def test_guard_g18_detects_fallback_pass_restored(monkeypatch):
    """反向自证: 若有人把 A0 改回 `if HISTORY_FILE.exists():` 包裹 ⇒ G18 报 FAIL。"""
    g = _guard_module()
    src = Path(cl.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "if not HISTORY_FILE.exists():" in src

    degraded = src.replace("if not HISTORY_FILE.exists():", "if HISTORY_FILE.exists():")
    monkeypatch.setattr(g, "_read", lambda p: degraded)
    ok, detail = g.check_g18()
    assert not ok, f"G18 未能识别兜底 PASS 复辟: {detail}"
    print(f"    [G18 捕获降级] {detail}")


def test_guard_g19_detects_freshness_removed(monkeypatch):
    """反向自证: 若有人把 A3 降回只查存在性 ⇒ G19 报 FAIL。"""
    g = _guard_module()
    src = Path(cl.__file__).read_text(encoding="utf-8", errors="ignore")
    degraded = src.replace("_business_hours_between(", "_removed_business_hours(")
    monkeypatch.setattr(g, "_read", lambda p: degraded)
    ok, detail = g.check_g19()
    assert not ok, f"G19 未能识别新鲜度判据被删: {detail}"
    print(f"    [G19 捕获降级] {detail}")


def test_guard_g20_detects_specs_shrunk(monkeypatch):
    """反向自证: 若有人把 CARRIER_SPECS 从 28 条瘦身到 4 条 ⇒ G20 报 FAIL。"""
    g = _guard_module()
    src = Path(cl.__file__).read_text(encoding="utf-8", errors="ignore")

    import re as _re
    m = _re.search(r"(CARRIER_SPECS\s*=\s*\[)(.*?)(\n\])", src, _re.S)
    assert m, "前置条件: 应能定位 CARRIER_SPECS 块"
    entries = _re.findall(r'^\s*\(\s*"([^"]+)"', m.group(2), _re.M)
    assert len(entries) >= 28, f"前置条件: 现有 {len(entries)} 条"

    kept = m.group(2).split("\n")[:5]
    degraded = src[:m.start(2)] + "\n".join(kept) + src[m.end(2):]
    monkeypatch.setattr(g, "_read", lambda p: degraded)
    ok, detail = g.check_g20()
    assert not ok, f"G20 未能识别清单被瘦身: {detail}"
    print(f"    [G20 捕获降级] {detail}")
