"""trade_log_snapshot.py 单测 (t_64c8bbf0, 2026-10-26) — 17-case 门禁中的 7 case。

覆盖 P1+P2 修复:
- T1 原子写 / T2 绝对路径 / T3 before_data 1MB 上限 / T4 ts 秒级+毫秒尾
- 快照语义: 新目标/旧目标/损坏目标/5 份上限/diff

隔离原则: SNAPSHOT_FILE monkeypatch 到 tmp_path, 不污染生产 data/trade_log_snapshots.json;
时间 monkeypatch 为受控时钟, 保证 ts 唯一且测试确定 (同一毫秒内两次调用不再依赖真实时钟)。
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "trade_log_snapshot.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("trade_log_snapshot_under_test", SCRIPT)
    assert spec is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _FakeTime:
    """受控时钟: strftime 固定, time() 每次调用 +1ms → ts 单调唯一。"""

    def __init__(self):
        self._ms = 0

    def strftime(self, fmt, *args, **kwargs):
        return "2026-10-26T12:00:00"

    def time(self):
        self._ms += 1
        # 1_000_000_000_000 ms 可被 1000 整除, 取模后即为 self._ms
        return 1_000_000_000.0 + self._ms / 1000.0


@pytest.fixture()
def snap_env(mod, tmp_path, monkeypatch):
    """SNAPSHOT_FILE → tmp; time → 受控时钟。返回快照文件路径。"""
    snap_file = tmp_path / "trade_log_snapshots.json"
    monkeypatch.setattr(mod, "SNAPSHOT_FILE", str(snap_file))
    monkeypatch.setattr(mod, "time", _FakeTime())
    return snap_file


def test_file_hash_not_found(mod, tmp_path):
    """target 不存在 → _file_hash 返回 None。"""
    assert mod._file_hash(tmp_path / "no_such_file.json") is None


def test_file_hash_found(mod, tmp_path):
    """target 存在 → 返回 sha256 前 16 位 (对照手算)。"""
    p = tmp_path / "x.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    expected = hashlib.sha256(b'{"a": 1}').hexdigest()[:16]
    assert mod._file_hash(p) == expected


def test_take_snapshot_new_target(mod, snap_env, tmp_path):
    """target 不存在 → before_data is None, before_hash is None。"""
    target = tmp_path / "trade_log_new.json"  # 不创建
    rec = mod.take_snapshot(str(target), label="new_target")
    assert rec["before"] is None
    assert rec["before_hash"] is None
    # 快照已原子落盘
    snaps = json.loads(snap_env.read_text(encoding="utf-8"))
    assert len(snaps) == 1
    assert snaps[0]["before"] is None


def test_take_snapshot_existing_target(mod, snap_env, tmp_path):
    """target 有数据 → before_data 与原内容一致。"""
    target = tmp_path / "trade_log.json"
    data = {"trades": [{"symbol": "SH600000", "pnl": 1.5}], "meta": "v1"}
    target.write_text(json.dumps(data), encoding="utf-8")
    rec = mod.take_snapshot(str(target), label="before_update")
    assert rec["before"] == data
    assert rec["before_hash"] == hashlib.sha256(target.read_bytes()).hexdigest()[:16]


def test_max_snapshots_cap(mod, snap_env, tmp_path):
    """连续 6 次调用 → 只保留 5 份, 最旧的被丢弃。"""
    target = tmp_path / "t.json"
    target.write_text("{}", encoding="utf-8")
    for i in range(6):
        mod.take_snapshot(str(target), label=f"call{i}")
    snaps = json.loads(snap_env.read_text(encoding="utf-8"))
    assert len(snaps) == 5
    labels = [s["label"] for s in snaps]
    assert labels == ["call1", "call2", "call3", "call4", "call5"]  # call0 被丢弃


def test_corrupt_target_file(mod, snap_env, tmp_path):
    """target 是损坏 JSON → before_data = {"_raw_corrupt": 原文前 2000 字}。"""
    target = tmp_path / "bad.json"
    raw = "this is {not, valid json"
    target.write_text(raw, encoding="utf-8")
    rec = mod.take_snapshot(str(target))
    assert rec["before"] == {"_raw_corrupt": raw}


def test_diff_snapshots_normal(mod, snap_env, tmp_path):
    """两份快照 diff → 正确列出 changed_fields。"""
    target = tmp_path / "d.json"
    v1 = {"a": 1, "b": 2}
    target.write_text(json.dumps(v1), encoding="utf-8")
    rec1 = mod.take_snapshot(str(target), label="v1")
    v2 = {"a": 1, "b": 3, "c": 4}
    target.write_text(json.dumps(v2), encoding="utf-8")
    rec2 = mod.take_snapshot(str(target), label="v2")

    diff = mod.diff_snapshots(str(target), rec1["ts"], rec2["ts"])
    assert "error" not in diff
    assert set(diff["diff"].keys()) == {"b", "c"}
    assert diff["diff"]["b"] == {"a": 2, "b": 3}
    assert diff["diff"]["c"] == {"a": None, "b": 4}


def test_take_snapshot_truncated_over_1mb(mod, snap_env, tmp_path):
    """T3: before_data 超 1MB → 存 {"_truncated": True, "_keys": [...]} 摘要，不存全量。"""
    target = tmp_path / "big.json"
    # 构造 > 1MB 的 JSON（200_000 个 key ≈ 3MB）
    data = {"key_%d" % i: i for i in range(200_000)}
    raw = json.dumps(data)
    target.write_text(raw, encoding="utf-8")
    assert len(target.read_bytes()) > 1024 * 1024, "test precondition: file must exceed 1MB"
    rec = mod.take_snapshot(str(target), label="large")
    assert rec["before"]["_truncated"] is True
    assert "key_0" in rec["before"]["_keys"]
    assert rec["before"].get("key_0") is None  # 全量值不存在，只有 keys 摘要


def test_take_snapshot_ts_unique_in_same_second(mod, snap_env, tmp_path):
    """T4: 同一秒内连续两次调用 → ts 不同（毫秒尾防止碰撞）。"""
    target = tmp_path / "ts_test.json"
    target.write_text("{}", encoding="utf-8")
    rec1 = mod.take_snapshot(str(target), label="first")
    rec2 = mod.take_snapshot(str(target), label="second")
    assert rec1["ts"] != rec2["ts"], f"ts collision: {rec1['ts']} == {rec2['ts']}"
