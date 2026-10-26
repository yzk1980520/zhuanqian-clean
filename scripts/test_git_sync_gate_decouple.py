# -*- coding: utf-8 -*-
"""test_git_sync_gate_decouple.py -- P1-D 门禁单点解耦 回归断言(区分"既存红/新红")

背景(派单 P1-D, 老六 2026-10-16 §二): git_sync_task 门禁是全局单点, scripts/test_*.py
任一红即"不绿不推", 一条与推送无关的红测试就静默冻结整条推送链 16.8h / 积压 60 提交。
修复(保留强度, 只修"冻结不可见"):
  (a) 区分红来源: 基线 gate_red_baseline(钉在上次成功同步) 内=既存红→放行+P1 告警+台账;
      基线外=新红(改动引入)→一律阻断(强度不变);
  (b) 冻结可见: 判红落 frozen_since/frozen_reason 到 git_sync_state.json + 经唯一投递器
      入 message_queue.json; 连续 2 轮或 >2h 升 P0;
  (c) 兜底通道: --force-with-reason 人工审计强推(who/why/what 留痕)。

假覆盖防护(AGENTS 规则14 / 老六硬要求②): 本文件一律 import 生产模块 git_sync_task 并
调用其真实函数 (classify_reds / decide_gate / parse_failing_nodes / run_pytest_gate),
绝不在 temp 里重实现门禁逻辑。生产代码真被改的证据 = `git diff --stat scripts/git_sync_task.py` 非空。

fork 弹防护(老六护栏): 本文件在 scripts/ 下会被门禁 glob。故:
  - 纯函数测试 (parse/classify/decide/shape): 无子进程, 无递归, <1s。
  - 唯一真派生测试 test_run_gate_captures_real_failing_nodes: @skipif(ZQ_PYTEST_GATE==1),
    仅在独立运行(非门禁上下文)时跑; 且 monkeypatch PROJECT→临时 fixture, 其子进程只跑
    fixture 文件(不含本文件), 无自递归。门禁运行时该测试自动跳过 ⇒ 本文件 <2s 跑完。
"""
import os
import sys
import shutil
import tempfile
import datetime as _dt

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import git_sync_task as gst  # noqa: E402  生产模块(本文件即测它, 非 temp 重实现)


def _gate(failing, ok=False, rc=0, timed_out=False, note=None):
    """构造 run_pytest_gate 形状的 gate 结果(喂给 decide_gate)。"""
    return {"ok": ok, "passed": 10, "failed": len(failing),
            "rc": rc, "timed_out": timed_out, "failing_nodes": failing,
            "note": note}


# ---------------------------------------------------------------- 纯函数: parse/classify
def test_parse_failing_nodes():
    out = ("==== short test summary info ====\n"
           "FAILED scripts/test_x.py::test_a - AssertionError: x\n"
           "FAILED scripts/test_y.py::test_b\n")
    assert gst.parse_failing_nodes(out) == [
        "scripts/test_x.py::test_a", "scripts/test_y.py::test_b"]
    assert gst.parse_failing_nodes("no failures here") == []
    assert gst.parse_failing_nodes("") == []


def test_classify_new_vs_preexisting():
    r = gst.classify_reds(["a", "b", "c"], ["a"])
    assert r["new"] == ["b", "c"]
    assert r["preexisting"] == ["a"]
    # 幂等/首跑: prev 空/None → 全部视为新红(保守阻断)
    assert gst.classify_reds(["z"], None)["new"] == ["z"]
    assert gst.classify_reds(["z"], ["z"])["new"] == []


# ---------------------------------------------------------------- 验收① 两组场景
def test_scenario_a_preexisting_red_proceeds_with_p1():
    """场景A「无关既有红测试」→ 不阻断且出 P1 告警 + 台账(带着 N 条既存红推送)。"""
    d = gst.decide_gate(_gate(["tests/contract_docs.py::test_stale"], ok=False, rc=1),
                        {"gate_red_baseline": ["tests/contract_docs.py::test_stale"]})
    assert d["proceed"] is True, "既存红应放行, got=%r" % d
    assert d["alert_priority"] == "P1"
    assert "既存红" in d["ledger"], d.get("ledger")
    assert d["new_red"] == []
    assert d["preexisting_red"] == ["tests/contract_docs.py::test_stale"]


def test_scenario_b_new_red_blocks():
    """场景B「本轮引入的红测试」→ 仍阻断(保留门禁强度), 冻结可见 + 首轮 P1。"""
    d = gst.decide_gate(_gate(["scripts/test_new.py::test_broke"], ok=False, rc=1),
                        {"gate_red_baseline": []})
    assert d["proceed"] is False, "新红必须阻断(绝不降低强度), got=%r" % d
    assert d["freeze"] is True
    assert d["alert_priority"] == "P1", "首冻结轮=P1, got=%r" % d["alert_priority"]
    assert "改动引入" in d["frozen_reason"], d.get("frozen_reason")
    assert d["frozen_since"], "冻结必须落 frozen_since(可见), got=%r" % d.get("frozen_since")


# ---------------------------------------------------------------- 升级 / 全绿 / 超时
def test_new_red_escalates_to_p0_on_second_round():
    """连续第 2 轮判红 → 升 P0(FREEZE_P0_AFTER_ROUNDS=2)。"""
    d = gst.decide_gate(_gate(["x"], ok=False, rc=1),
                        {"frozen_consecutive_rounds": 1,
                         "frozen_since": "2026-10-19T06:00:00"})
    assert d["alert_priority"] == "P0", d.get("alert_priority")


def test_new_red_escalates_to_p0_after_2h():
    """冻结持续 > 2h(即使第 1 轮) → 升 P0(FREEZE_P0_AFTER_HOURS=2.0)。"""
    old = (_dt.datetime.now() - _dt.timedelta(hours=3)).isoformat(timespec="seconds")
    d = gst.decide_gate(_gate(["x"], ok=False, rc=1),
                        {"frozen_since": old, "frozen_consecutive_rounds": 0})
    assert d["alert_priority"] == "P0", "冻结>2h 必须升 P0, got=%r" % d.get("alert_priority")


def test_green_proceeds_no_alert():
    d = gst.decide_gate(_gate([], ok=True, rc=0), {"gate_red_baseline": ["a"]})
    assert d["proceed"] is True and d["alert_priority"] is None
    assert d["baseline_after"] == [], "全绿推送后基线应清空, got=%r" % d["baseline_after"]


def test_timeout_is_p0_freeze_visible():
    """门禁超时 = 比红更坏(挂死无人知) → 直接 P0 + 落 frozen_reason(可见)。"""
    d = gst.decide_gate(_gate([], rc=-9, timed_out=True), {})
    assert d["freeze"] is True and d["alert_priority"] == "P0"
    assert d["frozen_reason"], "超时必须落 frozen_reason(可见)"


# ---------------------------------------------------------------- 生产真被改: 返回形状 + 真派生
def test_run_gate_returns_failing_nodes_shape():
    """run_pytest_gate 返回必须含 failing_nodes 键(证明生产代码真被改)。哨兵路径最快。"""
    old = os.environ.get("ZQ_PYTEST_GATE")
    os.environ["ZQ_PYTEST_GATE"] = "1"
    try:
        r = gst.run_pytest_gate()
    finally:
        if old is None:
            os.environ.pop("ZQ_PYTEST_GATE", None)
        else:
            os.environ["ZQ_PYTEST_GATE"] = old
    assert "failing_nodes" in r, "run_pytest_gate 返回缺 failing_nodes(生产未改?)"
    assert r["failing_nodes"] == []


# ---------------------------------------------------------------- 复审返工 D1: 门禁强度洞(error 形态不得放行)
def test_d1_error_form_gate_run_blocks_not_proceeds():
    """D1(P0): error 形态门禁跑(rc≠0、failed=0、无 FAILED 行: collection/import error、
    pytest 内部错) 绝不可 proceed。先红实证: 旧代码"全绿"分支仅凭 failing_nodes 为空判放行,
    这些输入在旧代码下 decide_gate → proceed=True(等于"失败也推"在 error 类开口),
    违反 §二 硬约束「禁止降低门禁强度」(旧代码 gate.ok=False 一律阻断)。
    修复后: 非绿且解析不到 FAILED 节点 → 阻断 + 冻结可见 + P0(与超时同类: 门禁基建坏,
    无法枚举红集, 严格差于"已知红", 自足判定取 P0 直判, 与 timed_out→P0 同一升级口径)。"""
    cases = [
        {"ok": False, "passed": 0, "failed": 0, "rc": 1, "timed_out": False, "failing_nodes": []},
        {"ok": False, "passed": 0, "failed": 0, "rc": 2, "timed_out": False, "failing_nodes": []},
        {"ok": False, "passed": 7, "failed": 0, "rc": 3, "timed_out": False, "failing_nodes": []},
    ]
    for gate in cases:
        d = gst.decide_gate(gate, {})
        assert d["proceed"] is False, "error 形态不得放行: %r -> proceed=%r" % (gate, d.get("proceed"))
        assert d["freeze"] is True, "error 形态必须冻结可见: %r" % d.get("frozen_reason")
        assert d["alert_priority"] == "P0", "error 形态必须 P0(门禁基建坏), got=%r" % d.get("alert_priority")
        assert d["frozen_reason"] and "不绿不推" in d["frozen_reason"], d.get("frozen_reason")
        assert d["frozen_since"], "冻结必须落 frozen_since(可见)"


def test_d1_error_form_ignores_preexisting_baseline():
    """error 形态即使基线钉着既存红也仍阻断: FAILED 节点解析不到 ⇒ 无法证明
    '只有既存红', 强度不降。"""
    gate = {"ok": False, "passed": 0, "failed": 0, "rc": 1,
            "timed_out": False, "failing_nodes": []}
    d = gst.decide_gate(gate, {"gate_red_baseline": ["scripts/test_x.py::test_a"]})
    assert d["proceed"] is False and d["freeze"] is True and d["alert_priority"] == "P0"


def test_d1_all_green_ok_true_still_proceeds():
    """防过度阻断: 真全绿(ok=True、无 FAILED 节点)仍放行, 正常路径不变。"""
    d = gst.decide_gate(_gate([], ok=True, rc=0), {})
    assert d["proceed"] is True and d["freeze"] is False, d


# ---------------------------------------------------------------- 复审返工 D2: 强推审计留痕(经唯一投递器)
import queue_integration  # noqa: E402  (message_queue 生产端唯一规范写口, 夹具重定向对象)


@pytest.fixture()
def force_push_env(tmp_path, monkeypatch):
    """main() 强制推送夹具: 全部 git/推送/门禁调用重定向到假实现, STATE_FILE/ALERT_LOG
    指向 tmp(不污染生产台账), queue_integration.add_alert 捕获(证明队列写真的发生)。
    场景 = 新红被阻断(--force-with-reason 人工审计强推放行)。"""
    captured_queue = []
    monkeypatch.setenv("USERNAME", "fixture_user")
    monkeypatch.setattr(gst, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(gst, "ALERT_LOG", str(tmp_path / "alert_log.jsonl"))
    monkeypatch.setattr(gst, "check_dirty",
                        lambda: {"ok": True, "count": 0, "note": "fixture", "sample": []})
    monkeypatch.setattr(gst, "run_pytest_gate",
                        lambda: {"ok": False, "passed": 5, "failed": 1, "rc": 1,
                                 "timed_out": False,
                                 "failing_nodes": ["scripts/test_x.py::test_a"]})
    monkeypatch.setattr(gst, "push_once", lambda remote: (True, "fixture ok"))
    monkeypatch.setattr(gst, "remote_tip_and_ahead",
                        lambda remote: {"remote": remote, "reachable": True,
                                        "tip": "feedbeef1234", "tip_time": None,
                                        "age_hours": 0.1, "local_ahead": 0})

    def fake_git(args, timeout=300):
        if args[0] == "rev-parse":
            return 0, "0123456789abcdef", ""
        if args[0] == "rev-list":
            return 0, "3", ""
        return 0, "", ""

    monkeypatch.setattr(gst, "_git", fake_git)
    monkeypatch.setattr(queue_integration, "add_alert",
                        lambda **kw: captured_queue.append(kw) or None)
    monkeypatch.setattr(sys, "argv",
                        ["git_sync_task.py", "--force",
                         "--force-with-reason", "D2 fixture 审计验证"])
    return captured_queue


def test_d2_force_push_writes_audit_to_alert_log_and_queue(force_push_env, tmp_path):
    """D2(P1 口径欠账): 强推成功必须强制写告警留痕(谁按的/为什么/推了什么) —
    ① state.force_push_audit ② alert_log.jsonl(gitsync_force_push, P0, what 含
    commit range + 当前红集) ③ message_queue.json(queue_integration.add_alert 真被调)。
    先红实证: 旧代码 forced 块 0 个 emit_alerts 调用, ②③ 缺失; 修复后全绿。"""
    import json as _json
    rc = gst.main()
    assert rc == 0, "夹具下强推应正常结束(0), rc=%s" % rc
    state = _json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    audit = state.get("force_push_audit")
    assert audit, "state.force_push_audit 未写: keys=%r" % list(state)
    assert audit["who"] == "fixture_user"
    assert audit["why"] == "D2 fixture 审计验证"
    assert "commit range" in audit["what"], "what 必须含 commit range: %r" % audit["what"]
    assert "scripts/test_x.py::test_a" in audit["what"], "what 必须含当前红集: %r" % audit["what"]
    # ② alert_log.jsonl 审计留痕
    alert_lines = (tmp_path / "alert_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert alert_lines, "alert_log.jsonl 审计留痕缺失(D2 欠账)"
    last = _json.loads(alert_lines[-1])
    assert last["alert"].startswith("gitsync_force_push"), last
    assert last["priority"] == "P0"
    assert "fixture_user" in last["alert"] and "commit range" in last["alert"]
    # ③ message_queue.json 经唯一投递器
    assert force_push_env, "queue_integration.add_alert 未被调用(message_queue 未写, D2 欠账)"
    q = force_push_env[-1]
    assert q["alert_type"] == "gitsync_force_push" and q["priority"] == "P0"
    assert "fixture_user" in q["content"] and "commit range" in q["content"]
    assert q["data"]["failing_nodes"] == ["scripts/test_x.py::test_a"], \
        "队列 data 必须带当前红集(推了什么), got=%r" % q.get("data")


@pytest.mark.skipif(os.environ.get("ZQ_PYTEST_GATE") == "1",
                    reason="门禁上下文内跳过真派生(防自递归); 独立运行时才跑")
def test_run_gate_captures_real_failing_nodes():
    """真派生: monkeypatch PROJECT→临时 fixture, run_pytest_gate 子进程只跑 fixture
    (不含本文件, 无自递归), 证明 failing_nodes 真能抓到红色测试 node id。"""
    fix = tempfile.mkdtemp(prefix="zq_p1d_gate_")
    sdir = os.path.join(fix, "scripts")
    os.makedirs(sdir)
    with open(os.path.join(sdir, "test_fix.py"), "w", encoding="utf-8") as f:
        f.write("def test_this_is_red():\n    assert False, 'boom'\n")
    old_proj = gst.PROJECT
    old_guards = gst.CONTRACT_GUARD_TESTS
    old_sent = os.environ.get("ZQ_PYTEST_GATE")
    gst.PROJECT = fix
    gst.CONTRACT_GUARD_TESTS = []
    os.environ.pop("ZQ_PYTEST_GATE", None)  # 允许真派生(子进程只跑 fixture, 无递归)
    try:
        r = gst.run_pytest_gate()
    finally:
        gst.PROJECT = old_proj
        gst.CONTRACT_GUARD_TESTS = old_guards
        if old_sent is None:
            os.environ.pop("ZQ_PYTEST_GATE", None)
        else:
            os.environ["ZQ_PYTEST_GATE"] = old_sent
        shutil.rmtree(fix, ignore_errors=True)
    assert r["ok"] is False, r
    assert any("test_this_is_red" in n for n in r.get("failing_nodes", [])), \
        "failing_nodes 未抓到 fixture 红测试(生产未被改?): %r" % r.get("failing_nodes")
