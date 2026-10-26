#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_laosi_research_review.py — 三模块集成测试
覆盖：precheck_cli / research_hub / review_iterator
"""
import json
import os
import subprocess
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
def _run(script, *args):
    r = subprocess.run([PY, os.path.join(ROOT, script), *args],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout, r.stderr
def test_precheck_runs_and_returns_structured():
    """precheck_cli --json 必须返回合法 JSON 且含 verdict/items。"""
    code, out, err = _run("scripts/precheck_cli.py", "--json")
    # 退出码 0/1/2 均合法（取决于当前系统状态）
    assert code in (0, 1, 2), f"异常退出码 {code}: {err[:300]}"
    data = json.loads(out)
    assert "verdict" in data and data["verdict"] in ("PASS", "WARN_ONLY", "BLOCK")
    assert "items" in data and len(data["items"]) >= 8
    for it in data["items"]:
        assert it["status"] in ("PASS", "FAIL", "WARN", "SKIPPED")
        assert it["severity"] in ("P0", "P1", "P2")
        assert it.get("evidence"), f"{it['cid']} 缺少证据"
def test_precheck_blocking_logic():
    """P0+FAIL 必须导致 BLOCK。"""
    code, out, _ = _run("scripts/precheck_cli.py", "--json")
    data = json.loads(out)
    p0_fail = [i for i in data["items"] if i["severity"] == "P0" and i["status"] == "FAIL"]
    if p0_fail:
        assert data["verdict"] == "BLOCK"
        assert code == 1
def test_research_hub_list():
    code, out, err = _run("scripts/research_hub.py", "list")
    assert code == 0, err[:300]
    assert "研究域" in out
def test_research_hub_index_generates():
    code, out, err = _run("scripts/research_hub.py", "index")
    assert code == 0, err[:300]
    idx = os.path.join(ROOT, "research", "index.md")
    assert os.path.exists(idx)
    with open(idx, "r", encoding="utf-8") as f:
        content = f.read()
    assert "研究域总索引" in content
def test_review_iterator_run():
    code, out, err = _run("scripts/review_iterator.py", "run")
    assert code == 0, err[:300]
    assert "复盘迭代主理人" in out
    # 产物存在
    prop = os.path.join(ROOT, "data", "review_iteration", "proposals.json")
    assert os.path.exists(prop)
    with open(prop, "r", encoding="utf-8") as f:
        reg = json.load(f)
    assert "proposals" in reg
def test_review_iterator_proposals():
    code, out, err = _run("scripts/review_iterator.py", "proposals")
    assert code == 0, err[:300]
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n结果: {passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)