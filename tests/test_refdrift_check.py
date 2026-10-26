# P-C2 对照组测试: refdrift_check (P-C3 ref 漂移自检)
# 老五切片 P-C3, 老三 10/24 04:3x 补对照组 (合成 git 仓 + bare remote, 不动主仓)
# 口径: run(root) 直调, 断言 R1/R2/R3 分级与 {pass,p0,p1,detail} 输出
import pytest
from pathlib import Path

sys_path_done = False
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import refdrift_check  # noqa: E402


def _git(cwd, *args, check=True):
    import subprocess
    r = subprocess.run(["git", "-C", str(cwd)] + list(args),
                       capture_output=True, text=True, timeout=60)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)} failed: {r.stderr}"
    return r


@pytest.fixture
def env(tmp_path):
    """合成仓: bare remote + main + github-main, 全部对齐 + FETCH_HEAD 新鲜"""
    server = tmp_path / "server.git"
    server.mkdir()
    _git(server, "init", "-q", "--bare")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "core").mkdir()
    (root / "core" / "a.py").write_text("x=1\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(server))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    _git(root, "branch", "github-main")
    _git(root, "push", "-q", "origin", "main")
    _git(server, "symbolic-ref", "HEAD", "refs/heads/main")  # 供 T3 第二克隆
    _git(root, "fetch", "-q", "origin")  # 生成新鲜 FETCH_HEAD
    # main 与 github-main 此刻同为 base (init -b main + 同一提交), 无需 force
    return root


def test_t1_aligned_pass(env):
    r = refdrift_check.run(str(env))
    assert r["pass"] is True, r
    assert r["p0"] == [] and r["p1"] == []
    assert r["detail"]["ghmain_ahead_origin"] == 0
    assert r["detail"]["ghmain_behind_origin"] == 0


def test_t2_unpushed_p1(env):
    # github-main 领先未推 → R2 P1 (server 灾备缺口)
    (env / "core" / "b.py").write_text("y=1\n", encoding="utf-8")
    _git(env, "checkout", "-q", "github-main")
    _git(env, "add", "-A")
    _git(env, "commit", "-qm", "unpushed")
    _git(env, "checkout", "-q", "main")
    r = refdrift_check.run(str(env))
    assert r["pass"] is False
    assert any("R2" in x and "领先" in x for x in r["p1"]), r["p1"]
    assert r["detail"]["ghmain_ahead_origin"] == 1


def test_t3_behind_p0(env):
    # server main 前进 (旁支提交推 server + update-ref 移动 server 端 main), 本地 github-main 落后 = P0 (继续工作=丢提交)
    import subprocess
    (env / "core" / "c.py").write_text("z=1\n", encoding="utf-8")
    _git(env, "checkout", "-q", "-B", "side")
    _git(env, "add", "-A")
    _git(env, "commit", "-qm", "server-side")
    _git(env, "push", "-q", "origin", "side")
    sha = _git(env, "rev-parse", "side").stdout.strip()
    _git(env, "checkout", "-q", "github-main")
    _git(env.parent / "server.git", "update-ref", "refs/heads/main", sha)  # server 端 main 前移
    _git(env, "fetch", "-q", "origin")
    r = refdrift_check.run(str(env))
    assert r["pass"] is False
    assert any("R2" in x and "落后" in x for x in r["p0"]), r["p0"]
    assert r["detail"]["ghmain_behind_origin"] == 1


def test_t4_stale_fetch_head_p1(env):
    # FETCH_HEAD 停更 >26h → R3 P1 (ref 快照陈旧, 漂移断言不可信)
    import time
    fh = env / ".git" / "FETCH_HEAD"
    old = time.time() - 30 * 3600
    import os
    os.utime(fh, (old, old))
    r = refdrift_check.run(str(env))
    assert r["pass"] is False
    assert any("R3" in x for x in r["p1"]), r["p1"]
    assert r["detail"]["fetch_head_age_h"] is not None and r["detail"]["fetch_head_age_h"] > 26


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
