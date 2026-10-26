# P-C2 对照组测试: fixguard_check (P-C1 未固化修复守卫)
# 老五切片 P-C1, 老三 10/24 04:3x 补对照组 (合成 git 仓, 不动主仓)
# 口径: run(root) 直调, 断言 {pass,p0,p1,detail} 同构输出
import os
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fixguard_check  # noqa: E402


def _git(cwd, *args):
    import subprocess
    r = subprocess.run(["git", "-C", str(cwd)] + list(args),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r.stdout


@pytest.fixture
def bare(tmp_path):
    """最小合成仓: tracked 文件齐备 + 干净基线"""
    root = tmp_path / "repo"
    root.mkdir()
    for sub, name in (("core", "a.py"), ("scripts", "b.py")):
        (root / sub).mkdir()
        (root / sub / name).write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def test_t1_clean_pass(bare):
    r = fixguard_check.run(str(bare))
    assert r["pass"] is True, r
    assert r["p0"] == [] and r["p1"] == []


def test_t2_a1_stale_modified_p1(bare):
    # 核心面 M 件且 mtime 超龄 (>STALE_HOURS) → A1 P1
    f = bare / "core" / "a.py"
    f.write_text("x = 2\n", encoding="utf-8")
    old = time.time() - 49 * 3600
    os.utime(f, (old, old))
    r = fixguard_check.run(str(bare))
    assert r["pass"] is False
    assert any("A1" in x for x in r["p1"]), r["p1"]
    assert r["detail"]["stale_modified"] and r["detail"]["stale_modified"][0]["file"] == "core/a.py"


def test_t3_a2_untracked_code_p1(bare):
    # 核心面 untracked 代码件 → A2 P1
    (bare / "scripts" / "new_mod.py").write_text("y = 1\n", encoding="utf-8")
    r = fixguard_check.run(str(bare))
    assert r["pass"] is False
    assert any("A2" in x and "new_mod.py" in x for x in r["p1"]), r["p1"]


def test_t4_a2_exempt_not_flagged(bare):
    # 豁免件 (.bak_/docs/.md 等) 不入 A2
    (bare / "scripts").mkdir(exist_ok=True)
    for n in ("legacy.py.bak_20261024", "note.md", "tmp.tmp"):
        (bare / "scripts" / n).write_text("z", encoding="utf-8")
    r = fixguard_check.run(str(bare))
    assert r["pass"] is True, r
    assert r["detail"]["untracked_core"] == []


def test_t5_a3_metadata_modified_p1(bare):
    # metadata 白名单件 M → A3 P1 (闭环缺口)
    assert fixguard_check.METADATA_WHITELIST, "白名单为空=对照失效"
    rel = fixguard_check.METADATA_WHITELIST[0]
    p = bare / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}\n", encoding="utf-8")
    _git(bare, "add", "-A")
    _git(bare, "commit", "-qm", "add meta")
    p.write_text("{\"k\":1}\n", encoding="utf-8")
    r = fixguard_check.run(str(bare))
    assert r["pass"] is False
    assert any("A3" in x and rel in x for x in r["p1"]), r["p1"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
