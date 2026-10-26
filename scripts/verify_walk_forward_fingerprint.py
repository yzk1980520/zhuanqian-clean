#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""walk_forward_gate 源结果指纹判据 —— 双向实测 (2026-10-21 立)。

防的是 9a13bb8d 的手法: 复制旧结果 → 只改 timestamp / mtime → 冒充"新的重标定"。

用例(全部在临时目录跑, 不碰生产 output/diagnostic 与 data/):
  A1  内容 A, 内容时间戳 2026-10-17T06:34:23
  A2  内容 A(与 A1 除 timestamp 外字节级相同), 内容时间戳 2026-10-21T03:10:52
      —— 且刻意把 A2 的 **mtime 设成最旧**, A1 的 mtime 设成最新:
         若选源仍按 mtime, 会选中 A1; 新逻辑必须仍选中 A2。
  第 1 跑(仅 A1)      → 首见, recalibration_verified=True
  第 2 跑(加入 A2)     → 指纹与上次相同 + 时间戳被推进 ⇒ 必须识别为"不是新重标定"
  第 3 跑(加入 B, 内容真不同) → 必须识别为新结果

退出码: 0=三项判据全过  1=有判据不过
用法: python scripts/verify_walk_forward_fingerprint.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "walk_forward_gate.py"


def _load_module():
    # 门禁会把产物指纹追加到 record_gate_fingerprint 的台账; 测试期把它也指向临时目录,
    # 避免把 C:/Users/.../Temp 路径写进生产台账 state/gate_fingerprints.jsonl。
    sys.path.insert(0, str(MODULE_PATH.parent))
    import record_gate_fingerprint  # noqa: E402
    record_gate_fingerprint.LEDGER = Path(tempfile.gettempdir()) / "wf_fp_gate_ledger.jsonl"
    spec = importlib.util.spec_from_file_location("wfg_under_test", MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _base(ts, oos=0.2122, isv=0.9906, windows=894):
    return {
        "timestamp": ts,
        "total_windows": windows,
        "successful_windows": windows,
        "mean_oos_sharpe": oos,
        "mean_is_sharpe": isv,
        "sharpe_drop": round(isv - oos, 4),
        "results": [{"oos_sharpe": 0.5, "is_sharpe": 1.0, "stock_code": "sh000001"}],
    }


def _write(path: Path, payload: dict, mtime: float):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.utime(path, (mtime, mtime))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wf_fp_"))
    out_dir = tmp / "output" / "diagnostic"
    out_dir.mkdir(parents=True)
    gate_file = tmp / "data" / "walk_forward_gate.json"
    ledger = tmp / "state" / "walk_forward_source_ledger.jsonl"
    failures = []

    try:
        mod = _load_module()
        mod.OUT_DIR = out_dir
        mod.GATE_FILE = gate_file
        mod.SOURCE_LEDGER = ledger

        # ---- 构造 A1 / A2: 内容相同(除 timestamp), mtime 刻意反着给 ----
        a1 = out_dir / "walk-forward-test-20261017_0634.json"
        a2 = out_dir / "walk-forward-test-20261021_0310.json"
        old_mt, new_mt = 1_700_000_000, 1_800_000_000
        _write(a1, _base("2026-10-17T06:34:23.076394"), mtime=new_mt)   # mtime 最新
        _write(a2, _base("2026-10-21T03:10:52.392804"), mtime=old_mt)   # mtime 最旧
        fp_a = mod._content_fingerprint(a1)[0]
        fp_a2 = mod._content_fingerprint(a2)[0]
        print("[构造] A1/A2 内容指纹(剔除 timestamp):")
        print(f"       A1={fp_a}")
        print(f"       A2={fp_a2}")
        print(f"       A1 原始字节 sha256={mod._file_sha256(a1)}")
        print(f"       A2 原始字节 sha256={mod._file_sha256(a2)}")
        print(f"       mtime: A1={a1.stat().st_mtime:.0f}(新)  A2={a2.stat().st_mtime:.0f}(旧)")
        if fp_a != fp_a2:
            failures.append("A1/A2 除 timestamp 外内容应完全相同, 指纹却不同")
        if mod._file_sha256(a1) == mod._file_sha256(a2):
            failures.append("A1/A2 原始字节不应相同(timestamp 不同)")

        # ---- 第 1 跑: 只有 A1 ----
        a2.unlink()
        code1, p1 = mod.evaluate(today=__import__("datetime").date(2026, 10, 21))
        print("\n[跑1] 只有 A1 在场:")
        print(f"       选中源        : {p1['source_file']}")
        print(f"       content_sha256: {p1['source_content_sha256'][:16]}...")
        print(f"       duplicate     : {p1['duplicate_submission']}  "
              f"recalibration_verified={p1['recalibration_verified']}")
        if p1["source_file"] != a1.name:
            failures.append(f"跑1 应选中 {a1.name}, 实际 {p1['source_file']}")
        if p1["duplicate_submission"] is not False:
            failures.append("跑1 是首见, duplicate_submission 应为 False")
        if p1["recalibration_verified"] is not True:
            failures.append("跑1 是首见, recalibration_verified 应为 True")

        # ---- 第 2 跑: 伪造者加入 A2(内容相同, 时间戳推进) ----
        _write(a2, _base("2026-10-21T03:10:52.392804"), mtime=old_mt)
        code2, p2 = mod.evaluate(today=__import__("datetime").date(2026, 10, 21))
        print("\n[跑2] 伪造者加入 A2(内容 = A1, 仅 timestamp 推进, mtime 反而最旧):")
        print(f"       选中源        : {p2['source_file']}   (按 mtime 排序会选 A1, "
              f"说明 mtime 已不参与选择)")
        print(f"       content_sha256: {p2['source_content_sha256'][:16]}... (与跑1 相同)")
        print(f"       duplicate_submission                    = {p2['duplicate_submission']}")
        print(f"       timestamp_advanced_without_content_change= "
              f"{p2['timestamp_advanced_without_content_change']}")
        print(f"       recalibration_verified                  = {p2['recalibration_verified']}")
        print(f"       上次时间戳 -> 本次: {p2['prev_source_timestamp']} -> "
              f"{p2['source_timestamp']}")
        print(f"       台账: 该指纹第 {p2['source_seen_count']} 次出现, "
              f"首次 {p2['source_first_seen_at']}, 此前文件名 {p2['source_prev_seen_files']}")
        if p2["source_file"] != a2.name:
            failures.append(f"跑2 应按内容时间戳选中 {a2.name}, 实际 {p2['source_file']} "
                            f"(mtime 仍在参与选择?)")
        if p2["duplicate_submission"] is not True:
            failures.append("跑2 内容指纹与上次相同, duplicate_submission 应为 True —— "
                            "没识别出来就等于还能被改时间戳骗过")
        if p2["timestamp_advanced_without_content_change"] is not True:
            failures.append("跑2 时间戳被推进而内容未变, 该标记应为 True")
        if p2["recalibration_verified"] is not False:
            failures.append("跑2 不得被认作新的重标定")

        # ---- 第 3 跑: 真·新内容 B ----
        b = out_dir / "walk-forward-test-20261021_0900.json"
        _write(b, _base("2026-10-21T09:00:00.000000", oos=0.85, isv=0.95), mtime=new_mt + 10)
        code3, p3 = mod.evaluate(today=__import__("datetime").date(2026, 10, 21))
        print("\n[跑3] 真·新内容 B(oos=0.85 is=0.95):")
        print(f"       选中源        : {p3['source_file']}")
        print(f"       content_sha256: {p3['source_content_sha256'][:16]}... (应不同于跑1/跑2)")
        print(f"       duplicate_submission   = {p3['duplicate_submission']}")
        print(f"       recalibration_verified = {p3['recalibration_verified']}")
        print(f"       decay={p3['decay']} blocked={p3['blocked']}")
        if p3["source_file"] != b.name:
            failures.append(f"跑3 应选中 {b.name}, 实际 {p3['source_file']}")
        if p3["duplicate_submission"] is not False:
            failures.append("跑3 内容真变了, duplicate_submission 应为 False")
        if p3["recalibration_verified"] is not True:
            failures.append("跑3 内容真变了, recalibration_verified 应为 True")

        # ---- 台账留痕 ----
        print("\n[台账] state/walk_forward_source_ledger.jsonl (追加写, 只增不删):")
        for line in ledger.read_text(encoding="utf-8").strip().split("\n"):
            row = json.loads(line)
            print(f"       #{row['seen_count']} ts={row['ts']} file={row['source_file']} "
                  f"fp={row['source_content_sha256'][:16]}...")

        print("\n" + "=" * 70)
        if failures:
            for f in failures:
                print(f"❌ {f}")
            print(f"合计 {len(failures)} 项判据不过")
            return 1
        print("✅ 三项判据全过: 内容相同+时间戳不同 ⇒ 识别为同一份(非新重标定); "
              "内容真不同 ⇒ 识别为新结果; 选择不受 mtime 影响")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
