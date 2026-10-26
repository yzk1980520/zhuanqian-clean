"""
trade_log_snapshot.py — 在写 trade_log.json / holdings.json 前自动快照
用法: python scripts/trade_log_snapshot.py [--target data/trade_log.json] [--label "写入描述"]

设计:
- 每次调用前把当前内容拷贝到 data/trade_log_snapshots.json（最近 5 份）
- 快照格式: [{"ts": "...", "label": "...", "before_hash": "...", "data": {...}}]
- 若目标文件不存在，快照记 null

2026-10-26 P1+P2 修复 (t_64c8bbf0):
- T1: 原子写 (.tmp + os.replace, 宪法 VIII: kill -9 不截断损坏快照文件)
- T2: SNAPSHOT_FILE 绝对路径 (锚定文件位置, 不再依赖 CWD)
- T3: before_data 超 1MB 只存 {"_truncated": True, "_keys": [...]} 摘要
- T4: ts 秒级精度 + 3 位毫秒尾, 防同一秒内多次调用 ts 碰撞
"""

import logging
import os
import json
import hashlib
import time
import argparse
from pathlib import Path

logger = logging.getLogger("trade_log_snapshot")

# T2: 绝对路径 —— 基于文件自身位置锚定, 无论进程 CWD 在哪, 快照都落在 <repo>/data/ 下
SNAPSHOT_FILE = str(Path(__file__).resolve().parent.parent / "data" / "trade_log_snapshots.json")
MAX_SNAPSHOTS = 5
# T3: before_data 大小上限 1MB —— 超限只存顶层键摘要, 不存全量
MAX_BEFORE_DATA_BYTES = 1024 * 1024


def _file_hash(path: Path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_snapshots(path: Path) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            logger.warning("trade_log_snapshot: %s 损坏，跳过: %s", path.name, e)
            return []
    return []


def take_snapshot(target_rel: str, label: str = "") -> dict:
    """在 target_rel 文件写前调用，返回快照记录。

    target_rel 可以是：
    - 绝对路径：/D/open code/zhuanqian/data/trade_log.json
    - 相对仓库根：data/trade_log.json（会自动归一化为绝对路径，锚定 SNAPSHOT_FILE 所在 <repo>/）
    """
    target = Path(target_rel)
    if not target.is_absolute():
        # 锚定到 <repo>/ 下（SNAPSHOT_FILE 是 <repo>/data/...）
        target = Path(SNAPSHOT_FILE).parent.parent / target
    snap_path = Path(SNAPSHOT_FILE)
    snap_path.parent.mkdir(parents=True, exist_ok=True)

    before_hash = _file_hash(target)
    before_data = None
    if target.exists():
        try:
            raw_text = target.read_text(encoding="utf-8")
        except Exception:
            # utf-8 不可解码（二进制/重损坏）→ 记 raw 摘要, 不崩
            before_data = {"_raw_corrupt": target.read_text(encoding="utf-8", errors="replace")[:2000]}
        else:
            if len(raw_text.encode("utf-8")) > MAX_BEFORE_DATA_BYTES:
                # T3: 超限 → 只存顶层键摘要, 不存全量
                try:
                    _parsed = json.loads(raw_text)
                    _keys = list(_parsed.keys()) if isinstance(_parsed, dict) else []
                except Exception:
                    _keys = []
                before_data = {"_truncated": True, "_keys": _keys}
            else:
                try:
                    before_data = json.loads(raw_text)
                except Exception:
                    before_data = {"_raw_corrupt": raw_text[:2000]}

    # T4: 秒级精度 + 3 位毫秒尾, 防同一秒内多次调用 ts 碰撞
    ts = time.strftime("%Y-%m-%dT%H:%M:%S") + f"_{int(time.time() * 1000) % 1000:03d}"
    record = {
        "ts": ts,
        "target": str(target),  # 存归一化后的绝对路径
        "label": label or "(no label)",
        "before_hash": before_hash,
        "before": before_data,
    }

    snaps = _load_snapshots(snap_path)
    snaps.append(record)
    snaps = snaps[-MAX_SNAPSHOTS:]
    # T1 (宪法 VIII): 原子写 —— 先写 .tmp 再 os.replace 原子替换, kill -9 不会留下截断损坏的快照文件
    tmp = snap_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snaps, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, snap_path)

    return record


def diff_snapshots(target_rel: str, snap_ts_a: str, snap_ts_b: str) -> dict:
    """对比同一 target 的两份快照（ts 为快照时间戳字符串）。

    target_rel 会做与 take_snapshot 相同的归一化：相对路径锚定到 <repo>/，绝对路径原样使用。
    """
    target = Path(target_rel)
    if not target.is_absolute():
        target = Path(SNAPSHOT_FILE).parent.parent / target
    target_norm = str(target)

    snap_path = Path(SNAPSHOT_FILE)
    snaps = _load_snapshots(snap_path)
    target_snaps = [s for s in snaps if s["target"] == target_norm]

    snap_a = next((s for s in target_snaps if s["ts"] == snap_ts_a), None)
    snap_b = next((s for s in target_snaps if s["ts"] == snap_ts_b), None)
    if snap_a is None or snap_b is None:
        return {"error": f"snapshot not found: {snap_ts_a} / {snap_ts_b}", "available": [s["ts"] for s in target_snaps]}

    diff = {}
    data_a = snap_a.get("before") or {}
    data_b = snap_b.get("before") or {}
    keys = set(data_a.keys()) | set(data_b.keys())
    for k in keys:
        va, vb = data_a.get(k), data_b.get(k)
        if va != vb:
            diff[k] = {"a": va, "b": vb}
    return {"ts_a": snap_ts_a, "ts_b": snap_ts_b, "target": target_norm, "diff": diff}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="data/trade_log.json", help="相对路径，默认 data/trade_log.json")
    ap.add_argument("--label", default="", help="本次写入的描述")
    ap.add_argument("--diff-a", default="", help="diff: 快照 A 时间戳")
    ap.add_argument("--diff-b", default="", help="diff: 快照 B 时间戳")
    ap.add_argument("--list", action="store_true", help="列出所有快照")
    args = ap.parse_args()

    if args.list:
        snaps = _load_snapshots(Path(SNAPSHOT_FILE))
        for s in snaps:
            print(f"  {s['ts']}  {s['target']}  {s['label']}  hash={s['before_hash']}")
        if not snaps:
            print("(no snapshots)")

    elif args.diff_a and args.diff_b:
        result = diff_snapshots(args.target, args.diff_a, args.diff_b)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        record = take_snapshot(args.target, args.label)
        print(f"snapshot taken: {record['ts']}  {record['target']}  hash={record['before_hash']}  label={record['label']}")


if __name__ == "__main__":
    main()
