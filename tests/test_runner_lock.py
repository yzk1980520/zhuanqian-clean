# -*- coding: utf-8 -*-
"""runner 独占锁回归 (老三 2026-09-27, 老五④制度条款, 交@laowu验收)。

P1 并发写盘事故固化: 回测产物 .p2_runner.lock 独占锁 + 产物名 pid 后缀, 防串写。
验收锚点:
  ① 无锁时获取 → 创建锁, prev_holder=None
  ② 抢占死锁(持有者 pid 已死) → 留痕 prev_holder, 不静默吞
  ③ 活锁冲突(持有者 pid 存活) → 抛 LockConflictError(绝不静默抢占)
  ④ 产物名 pid 后缀: p2_fuse_online.json → p2_fuse_online.{pid}.json
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import runner_lock
from runner_lock import RunnerLock, LockConflictError, released_pid_suffix


def _dead_lock(path, dead_pid=99999999):
    """造一个"持有者已死"的锁文件(死 pid 探测保守判 False → 可抢占)。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"pid": dead_pid, "owner": "dead_runner",
                   "acquired_at": "2026-09-27 00:00:00"}, f)


class TestRunnerLock:
    def test_acquire_when_no_lock(self, tmp_path):
        """① 无锁 → 获取成功, prev_holder=None, 锁文件落地。"""
        p = str(tmp_path / ".p2_runner.lock")
        with RunnerLock(p, owner="test") as h:
            assert h["prev_holder"] is None
            assert h["pid"] == os.getpid()
            assert os.path.exists(p)
        assert not os.path.exists(p), "正常退出应释放锁"

    def test_steal_dead_lock_leaves_trace(self, tmp_path):
        """② 抢占死锁 → prev_holder 留痕持有者, 不静默。"""
        p = str(tmp_path / ".p2_runner.lock")
        _dead_lock(p, dead_pid=99999999)
        with patch.object(runner_lock, "_pid_alive", return_value=False):
            with RunnerLock(p, owner="test") as h:
                assert h["prev_holder"] is not None
                assert h["prev_holder"]["owner"] == "dead_runner", "抢占必须留痕原持有者"

    def test_live_lock_conflict_raises(self, tmp_path):
        """③ 活锁冲突(持有者 pid 存活且 != 自己) → 抛 LockConflictError, 不静默抢占。
        RunnerLock 是 @contextmanager, 必须 with 包一层才执行 __enter__(冲突在 yield 前抛)。"""
        p = str(tmp_path / ".p2_runner.lock")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"pid": 12345, "owner": "live_runner"}, f)
        with patch.object(runner_lock, "_pid_alive", return_value=True):
            try:
                with RunnerLock(p, owner="test"):
                    raise AssertionError("活锁不得被获取, 应在此前抛 LockConflictError")
            except LockConflictError:
                print(f"🔴 [tests\test_runner_lock.py] CR-01: except LockConflictError:", file=sys.stderr)
        assert os.path.exists(p), "冲突后不得改动他人持有的锁文件"

    def test_pid_suffix_naming(self):
        """④ 产物名 pid 后缀(防串写): 同 basename 不同 pid 不重名。"""
        s = released_pid_suffix("p2_fuse_online.json")
        assert s == f"p2_fuse_online.{os.getpid()}.json", f"pid 后缀格式错误: {s}"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
