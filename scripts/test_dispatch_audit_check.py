#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M-3 派单审计消费者修复（t_258fdd8a）门禁测试。

覆盖 AC1-AC3：
  ① L92 非法转义修复（编译级 SyntaxWarning 捕获，版本无关）
  ② --json stdout 纯净 + stdout+stderr 合并场景可一次 json.loads（防 M-3 探针假 SKIPPED）
  ③ 全量 --json 60s 预算（父挂关系改走只读 sqlite 快路径；DB 缺失回退 CLI show 判定面不砍）
  ④ 分片并集 == 全量（--shard/--shards 语义可 1:1 对账）
  ⑤ state 写回防假绿断言（M-3 探针成功解析后 violations_count 必须=实测值，禁 0）
     + 连续 2 日违规 → P0 升级链复测

先例：scripts/test_m3_dispatch_audit.py（probe 侧 mock 手法一致）。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import warnings
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "dispatch_audit_check.py")
if os.path.dirname(SCRIPT) not in sys.path:
    sys.path.insert(0, os.path.dirname(SCRIPT))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import dispatch_audit_check as dac  # noqa: E402


def _run_script(args, timeout=120):
    return subprocess.run([sys.executable, SCRIPT] + args,
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)


def test_l92_no_syntax_warning():
    """AC1: 源码编译级 SyntaxWarning 捕获（3.12+ 默认告警语义下 3.11 也能判，版本无关）。"""
    src = open(SCRIPT, encoding="utf-8").read()
    with warnings.catch_warnings(record=True) as ws:
        warnings.simplefilter("always")
        compile(src, SCRIPT, "exec")
    bad = [w for w in ws if issubclass(w.category, SyntaxWarning)]
    assert not bad, "非法转义残留: %s" % [str(w.message) for w in bad]
    # 与验收命令同口径：-W error::SyntaxWarning 下 import 不炸
    r = subprocess.run([sys.executable, "-W", "error::SyntaxWarning", "-c",
                       "import sys; sys.path.insert(0, %r); import dispatch_audit_check" % os.path.dirname(SCRIPT)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, "-W error::SyntaxWarning import 失败: %s" % r.stderr[-300:]
    print("✅ test_l92_no_syntax_warning")


def test_json_merged_parseable():
    """AC1: --json stdout 单独可解析；stdout+stderr 合并可一次 json.loads（M-3 探针消费场景）。"""
    r = _run_script(["--json", "--max-tasks", "5"], timeout=90)
    assert r.stdout.strip().startswith("{"), "stdout 非 JSON 起始: %r" % r.stdout[:80]
    rep_stdout = json.loads(r.stdout)  # 单独解析
    rep_merged = json.loads(r.stdout + r.stderr)  # 合并解析（探针 out = stdout + stderr）
    assert rep_stdout == rep_merged, "合并场景引入差异（stderr 非空污染）"
    for k in ("ok", "checked", "scope_since", "violations", "children_source"):
        assert k in rep_stdout, "缺字段 %s" % k
    assert "SyntaxWarning" not in r.stderr, "stderr 混入告警: %s" % r.stderr[-200:]
    print("✅ test_json_merged_parseable (violations=%d)" % len(rep_stdout["violations"]))


def test_full_run_budget_60s():
    """AC2: 全量 --json（默认 max-tasks 50）60s 内完成。"""
    t0 = time.time()
    r = _run_script(["--json"], timeout=90)
    elapsed = time.time() - t0
    assert elapsed < 60, "全量 %ds 超 60s 预算" % int(elapsed)
    rep = json.loads(r.stdout)
    assert rep["checked"] > 0, "受审数=0（数据源断裂）"
    assert rep.get("children_source") in ("sqlite-ro", "cli-show"), rep.get("children_source")
    print("✅ test_full_run_budget_60s (%.1fs, checked=%d, src=%s)"
          % (elapsed, rep["checked"], rep["children_source"]))


def test_shard_union_equals_full():
    """AC2 备选: 6 分片并集 == 全量默认跑（先 cap 再切片的 1:1 对账语义）。"""
    tasks_cache = {}
    real_kanban_tasks = dac.kanban_tasks

    def _fake_kanban_tasks(timeout=90):
        if "t" not in tasks_cache:
            tasks_cache["t"] = real_kanban_tasks(timeout)
        return tasks_cache["t"]

    with patch.object(dac, "kanban_tasks", _fake_kanban_tasks):
        rep_full = dac.audit()
        reps = [dac.audit(shard=i, shards=6) for i in range(6)]
    full_v = {(v["id"], v["rule"]) for v in rep_full["violations"]}
    shard_v = set()
    checked_sum = 0
    for rep in reps:
        assert rep.get("shard"), "分片跑须带 shard 字段"
        shard_v |= {(v["id"], v["rule"]) for v in rep["violations"]}
        checked_sum += rep["checked"]
    assert shard_v == full_v, "分片并集≠全量（%d vs %d）" % (len(shard_v), len(full_v))
    assert checked_sum == rep_full["checked"], "分片受审和≠全量受审（%d vs %d）" % (checked_sum, rep_full["checked"])
    print("✅ test_shard_union_equals_full (full=%d, 分片和=%d)" % (len(full_v), len(shard_v)))


def test_db_fallback_to_cli():
    """DB 缺失/校验不过 → 回退 CLI show（children_source=cli-show），判定面不砍。"""
    real = dac.open_kanban_db
    with patch.object(dac, "open_kanban_db", lambda tids: (None, False)):
        rep = dac.audit(max_tasks=2)
    assert rep["checked"] == 2, "回退路径未实际受审: %s" % rep
    assert rep.get("children_source") == "cli-show", rep.get("children_source")
    dac.open_kanban_db = real
    print("✅ test_db_fallback_to_cli")


def test_state_writeback_no_fake_green():
    """AC3: 探针成功解析后 state.violations_count=实测值（禁 0 假绿）；复测「连续 2 日→P0」升级链。"""
    import core.ops.self_audit_checkers as shc

    def _mk_rep(n=19):
        return {"ok": False, "checked": 5, "scope_since": dac.RULE_EPOCH,
                "violations": [{"id": "t_demo%d" % i, "rule": "C1-提单人留名",
                                "detail": "created_by='default'"} for i in range(n)]}

    def _restore_queue():
        import core.pipeline.atomic_json as atomic_json
        qpath = os.path.join(shc.DATA_DIR, "message_queue.json")
        try:
            items = atomic_json.atomic_load(qpath, []) or []
            before = len(items)
            items = [m for m in items if not str(m.get("id", "")).startswith("dispatchaudit_")]
            if len(items) < before:
                atomic_json.atomic_dump(items, qpath)
        except Exception as e:
            print("🔴 [test_dispatch_audit_check.py] CR-01: 队列清理失败 异常=%s" % e, file=sys.stderr)

    tmpdir = tempfile.mkdtemp()
    tmp_state = os.path.join(tmpdir, "dispatch_audit_state.json")

    # 第 1 日：prev 缺失 → P1，state 写实测 19（非 0）
    with patch("subprocess.run", return_value=MagicMock(
            returncode=1, stdout=json.dumps(_mk_rep(19), ensure_ascii=False), stderr="")), \
         patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_state), \
         patch.object(shc, "ROOT", REPO):
        r1 = shc.check_m3_dispatch_audit()
    st1 = json.load(open(tmp_state, encoding="utf-8"))
    assert r1.status == "FAIL" and r1.severity == "P1", (r1.status, r1.severity)
    assert st1["violations_count"] == 19, "state 假绿：实测 19 却写 %s" % st1.get("violations_count")
    assert st1["checked"] == 5
    _restore_queue()

    # 第 2 日：state 连续违规（violations_count>0）→ consecutive=2 → P0（升级链复测）
    # 注：探针 state 写回只有 4 字段（无 consecutive 持久化，死字段），升级实际靠
    # violations_count>0 驱动——探针侧补字段属另派单范围，本卡不越界改（遗留项挂账）。
    with patch("subprocess.run", return_value=MagicMock(
            returncode=1, stdout=json.dumps(_mk_rep(19), ensure_ascii=False), stderr="")), \
         patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_state), \
         patch.object(shc, "ROOT", REPO):
        r2 = shc.check_m3_dispatch_audit()
    st2 = json.load(open(tmp_state, encoding="utf-8"))
    assert r2.status == "FAIL" and r2.severity == "P0", ("第2日应升级 P0", r2.status, r2.severity)
    assert "consecutive=2" in r2.evidence, "P0 升级未累计: %s" % r2.evidence
    assert st2["violations_count"] == 19, "第2日 state 仍须为实测值: %s" % st2
    _restore_queue()
    print("✅ test_state_writeback_no_fake_green (state=%s→%s)" % (st1["violations_count"], st2["violations_count"]))


def test_parse_fail_skipped_loud():
    """解析失败路径留痕（SKIPPED 必须带原因，非静默；R1-P5 t_45357e19: SKIPPED 也写 state
    —— skipped_reason=parse_fail + violations_count=null + last_run 推进，state 不冻结，防 10-19 型次日误升级 P0）。"""
    import core.ops.self_audit_checkers as shc
    tmpdir = tempfile.mkdtemp()
    tmp_state = os.path.join(tmpdir, "state.json")
    with open(tmp_state, "w", encoding="utf-8") as f:
        json.dump({"violations_count": 0}, f)
    with patch("subprocess.run", return_value=MagicMock(
            returncode=0, stdout="not json {{{", stderr="")), \
         patch.object(shc, "_DISPATCH_AUDIT_STATE_PATH", tmp_state):
        r = shc.check_m3_dispatch_audit()
    assert r.status == "SKIPPED" and "JSON 解析失败" in r.message, (r.status, r.message)
    print("✅ test_parse_fail_skipped_loud")


if __name__ == "__main__":
    test_l92_no_syntax_warning()
    test_json_merged_parseable()
    test_full_run_budget_60s()
    test_shard_union_equals_full()
    test_db_fallback_to_cli()
    test_state_writeback_no_fake_green()
    test_parse_fail_skipped_loud()
    print("\n全部通过 ✅")
