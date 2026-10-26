#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""门禁产物指纹台账 (2026-10-21 治理任务 B)。

背景
----
``data/walk_forward_gate.json`` 与 ``data/factor_ic/factor_ic_latest.json``
被 .gitignore 的 ``data/`` 规则挡在库外, 没有 git 历史 => 谁在什么时候把
门禁结论改成什么样, 事后无法追溯。这正是"复制旧文件改时间戳 + 手写数字"
类造假能瞒过去的原因之一。

方案选择说明(不要改成 data/*)
----------------------------
不能把 .gitignore 的 ``data/`` 改成 ``data/*`` 再加 ``!data/xxx.json``:
1. git 不会遍历被整体排除的目录, 所以 ``!data/xxx.json`` 这种例外无效;
2. 改成 ``data/*`` 后 git 会遍历 ``data/`` 全树(含约 3.2G 的
   ``data/history_daily``), git status / add 会被拖垮, 且有误纳超大/敏感
   文件的风险。

因此改为"受控指纹台账": 产物本身仍不入库, 但每次写完产物后把
sha256 + 关键值 + 来源文件 sha256 + 写入者 追加一行到
``state/gate_fingerprints.jsonl``(该目录入库, 见 git check-ignore 验证)。

用法
----
CLI(手动/补基线)::

    python scripts/record_gate_fingerprint.py --artifact data/walk_forward_gate.json
    python scripts/record_gate_fingerprint.py --artifact data/factor_ic/factor_ic_latest.json \
        --keys last_date,computed_at,total_samples --source <上游输入> --note "基线"

库调用(门禁脚本内接线)::

    from record_gate_fingerprint import record_fingerprint
    record_fingerprint(artifact=Path("data/walk_forward_gate.json"),
                       keys=["blocked", "decay"],
                       source=Path("output/diagnostic/xxx.json"),
                       writer="scripts/walk_forward_gate.py")

设计约束
--------
* 台账写入失败 **不许静默**: 打 [WARN] 到 stderr/stdout 并返回 False,
  由调用方决定是否升级(门禁本体不因台账失败而改变判定与退出码, 但在输出里
  留痕)。
* 只追加, 不覆写、不删除历史行 —— 台账本身即是审计链。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "state" / "gate_fingerprints.jsonl"

SCHEMA_VERSION = "1.0"

# 各产物默认抽取的关键值(CLI 未显式给 --keys 时用)
DEFAULT_KEYS: Dict[str, List[str]] = {
    "data/walk_forward_gate.json": [
        "blocked", "exit_code", "decay", "decay_abs", "decay_ratio",
        "is_sharpe", "oos_sharpe", "n_windows", "threshold", "metric",
        "computed_at", "source_file", "source_timestamp", "data_age_days",
    ],
    "data/factor_ic/factor_ic_latest.json": [
        "last_date", "freshness_days", "computed_at", "window_days",
        "forward_days", "total_samples", "source", "effective_factors",
    ],
}


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _default_writer() -> str:
    for k in ("GATE_WRITER", "USERNAME", "USER"):
        v = os.environ.get(k)
        if v:
            return v
    return "unknown"


def _extract_keys(payload: Any, keys: Iterable[str]) -> Dict[str, Any]:
    """从产物 JSON 里抽关键值; dict/list 只记长度, 避免台账被大对象撑爆。"""
    out: Dict[str, Any] = {}
    if not isinstance(payload, dict):
        return out
    for k in keys:
        if k not in payload:
            continue
        v = payload[k]
        if isinstance(v, (dict, list)):
            out[k] = f"<{type(v).__name__} len={len(v)}>"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = repr(v)
    return out


def _load_payload(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as e:  # noqa: BLE001 - 台账要能记录"坏档"这一事实
        return None, f"{type(e).__name__}: {e}"


def record_fingerprint(
    artifact: Path,
    keys: Optional[Iterable[str]] = None,
    source: Optional[Path] = None,
    writer: Optional[str] = None,
    note: str = "",
    ledger: Optional[Path] = None,
) -> bool:
    """算指纹并追加一行台账。成功 True; 失败打 [WARN] 并返回 False(不抛)。

    ledger 默认 None -> 调用时再解析模块级 LEDGER(便于测试重定向, 不被默认参数绑死)。
    """
    ledger = Path(ledger) if ledger is not None else LEDGER
    artifact = Path(artifact)
    try:
        if not artifact.exists():
            print(f"[WARN] 台账未写入: 产物不存在 {artifact}", file=sys.stderr)
            return False

        rel = _rel(artifact)
        if keys is None:
            keys = DEFAULT_KEYS.get(rel)
        payload, load_err = _load_payload(artifact)
        if payload is None:
            key_values: Dict[str, Any] = {}
            parse_error = load_err
        else:
            key_values = _extract_keys(payload, keys or list(payload.keys()))
            parse_error = None

        row: Dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "ts": _now(),
            "artifact": rel,
            "sha256": sha256_of(artifact),
            "size_bytes": artifact.stat().st_size,
            "mtime": _dt.datetime.fromtimestamp(
                artifact.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S"),
            "key_values": key_values,
            "source_sha256": sha256_of(source) if source and Path(source).exists() else None,
            "source": _rel(source) if source else None,
            "writer": writer or _default_writer(),
            "note": note,
        }
        if parse_error:
            row["parse_error"] = parse_error

        ledger = Path(ledger)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        print(f"[LEDGER] {rel} sha256={row['sha256'][:16]}... -> {_rel(ledger)}")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 台账写入失败(产物已写但无指纹留痕): "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="门禁产物指纹台账写入器")
    ap.add_argument("--artifact", required=True, help="产物路径(相对仓库根或绝对)")
    ap.add_argument("--keys", default="", help="逗号分隔的关键字段名; 省略则用内置默认")
    ap.add_argument("--source", default="", help="上游输入文件(记录其 sha256)")
    ap.add_argument("--writer", default="", help="写入者标识; 省略取 $GATE_WRITER/$USERNAME")
    ap.add_argument("--note", default="", help="备注(如 '基线')")
    ap.add_argument("--ledger", default=str(LEDGER), help="台账路径(一般不用改)")
    args = ap.parse_args()

    art = Path(args.artifact)
    if not art.is_absolute():
        art = ROOT / art
    keys = [k.strip() for k in args.keys.split(",") if k.strip()] or None
    src = Path(args.source) if args.source else None

    ok = record_fingerprint(
        artifact=art, keys=keys, source=src,
        writer=args.writer or None, note=args.note, ledger=Path(args.ledger),
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
