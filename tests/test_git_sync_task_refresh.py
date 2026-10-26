# -*- coding: utf-8 -*-
"""D-21 复发场景单测 (t_eecab269 AC2): main 领先 github-main(allow-empty 造 1 笔) → 刷新步骤(函数级调用) → 归零落后 + 无新 P0。

卡片契约:
- allow-empty 测试 commit 留痕不删 (message 标 test(D-21), 禁 force 回滚)。
- 幂等: main 近100笔历史已含 test(D-21) 留痕则不再造(防门禁复跑重复造痕), 首次运行才创建。
- 本测试只做本地 ref 操作, 不实际推送远端("推送成功+无 P0" 由 AC1 实跑覆盖;
  此处归零落后 = 下轮推送源=main tip, 推送必为 ff)。
- trail commit 用 --no-verify: 空 commit 无内容物, 跳过钩子校验(留痕目的, 非绕过质量门);
  正式代码 commit 仍走完整钩子。
"""
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
if os.path.join(PROJECT, "scripts") not in sys.path:
    sys.path.insert(0, os.path.join(PROJECT, "scripts"))

ALERT_LOG = os.path.join(PROJECT, "data", "alert_log.jsonl")
TRAIL_MSG = "test(D-21)"


def _git(args):
    r = subprocess.run(["git"] + args, cwd=PROJECT, capture_output=True,
                       text=True, encoding="utf-8")
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _count(a, b):
    rc, out, err = _git(["rev-list", "--count", "%s..%s" % (a, b)])
    assert rc == 0, "rev-list --count %s..%s 失败: %s" % (a, b, err)
    return int(out)


def _trail_exists():
    """main 近 100 笔历史内是否存在 test(D-21) 留痕 commit(留痕判据=历史存在, 不要求在 tip)。"""
    rc, out, _ = _git(["log", "-n", "100", "--format=%s", "main"])
    assert rc == 0, "读取 main 历史主题失败"
    return any(l.startswith(TRAIL_MSG) for l in out.splitlines())


def _p0_count():
    if not os.path.exists(ALERT_LOG):
        return 0
    n = 0
    with open(ALERT_LOG, "r", encoding="utf-8") as f:
        for line in f:
            if "gitsync_p0" in line:
                n += 1
    return n


def test_d21_refresh_zeroes_github_main_lag():
    """main 领先 github-main(≥1 笔) → refresh_source_branch() → github-main 归零落后 + 无新 P0 + 留痕在位。"""
    import git_sync_task as gst

    # 前置: 工作仓必须停在 main(生产仓契约; 本测试会造 trail commit)
    rc, branch, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    assert rc == 0 and branch == "main", "本测试要求 main 分支, 当前=%s" % branch

    p0_before = _p0_count()

    # 1) trail commit 留痕(幂等: main 近100笔历史已含 test(D-21) 则不再造, 防门禁复跑重复造痕)
    created = False
    if not _trail_exists():
        rc, out, err = _git(["-c", "user.name=laosan", "-c", "user.email=laosan@zhuanqian.local",
                             "commit", "--allow-empty", "--no-verify",
                             "-m", "%s: github-main 刷新复发场景留痕 (t_eecab269 AC2, 不删, 禁 force 回滚)" % TRAIL_MSG])
        assert rc == 0, "test(D-21) allow-empty commit 创建失败: %s" % ((err or out)[:200])
        created = True

    # 2) 新建 commit 后, 复发场景应成立: main 领先 github-main
    if created:
        assert _count("github-main", "main") >= 1, "复发场景未成立: github-main..main=0 (main 未领先)"

    # 3) 函数级调用刷新步骤(等价于脚本成功分支内的那一步)
    assert gst.refresh_source_branch() is True, "refresh_source_branch() 返回 False (git branch -f 失败, 见 stderr 日志)"

    # 4) github-main 归零落后 = 下轮推送源=main tip
    assert _count("github-main", "main") == 0, "刷新后 github-main..main != 0, D-21 风险态仍在"

    # 5) 无新 gitsync_p0 (刷新步骤是本地 ref 操作, 不得写 P0)
    assert _p0_count() == p0_before, "刷新步骤后 alert_log 新增 gitsync_p0"

    # 6) 留痕在位: main 历史内 test(D-21) 留痕 commit 不被删/不回滚
    assert _trail_exists(), "留痕 commit 丢失: main 近100笔历史无 test(D-21) 主题"
