#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py backtest-gate
# -*- coding: utf-8 -*-
# =============================================================================
# ⛔ 严禁清单 (2026-10-21 立, 守卫 G23 机器校验, 违反即报红)
# -----------------------------------------------------------------------------
# 背景: commit 9a13bb8d 把 output/diagnostic/walk-forward-test-20261017_0634.json
#   复制一份改掉第 2 行 timestamp 成为 ...20261021_0310.json, 再手写
#   data/review_status.json 的 walk_forward_decay=0.2573 / pass=true, 冒充"重标定"。
#   能成立的技术根因: 本脚本原按 **文件 mtime 排序取最新** 选产物
#   (旧 _latest_result(): sorted(..., key=lambda p: p.stat().st_mtime))。
#
# 严禁事项:
#   1. 严禁任何形式的 `"sorted(..., key=... st_mtime)"` 选产物 —— 改时间戳即可骗过。
#   2. 严禁把`_select_result()` 的排序键换成 mtime / os.path.getmtime / 文件名时间。
#   3. 严禁删 `_content_fingerprint()` / `source_content_sha256` 赋值 /
#      `if ... source_content_sha256 == ...` 指纹比较判断行。
#   4. 严禁删 `_append_source_ledger()` 的调用 (state/ 下台账是唯一跨覆写留痕)。
#   5. 严禁因"门禁红了/想让它绿"而改阈值、改 metric、改判据 —— decay=0.7858 是真的。
#   6. 产物缺失/不可读时必须 EXIT_ENV_FAULT(=2) fail loud, 严禁兜底 PASS。
# =============================================================================
"""walk_forward_gate.py — walk-forward 过拟合衰减【阻断门禁】(2026-10-17 老大拍板)。

背景
----
walk_forward_backtest.py 在衰减 > 0.1 时只打印"存在过拟合风险", 退出码恒为 0,
调度层看不出失败。2026-10-17 老大拍板: 把衰减从"只打日志"升级为**真正的阻断门禁**。

衰减的两种定义 (本脚本两种都算, 判定用哪一种由 metric 决定)
----------------------------------------------------------
  decay_abs   = IS - OOS
                即 walk_forward_backtest.py:167 里 `sharpe_drop` 的原始定义, 绝对差。
  decay_ratio = (IS - OOS) / IS = 1 - OOS/IS
                相对衰减率, 语义是"OOS 丢掉了 IS 几成的边"。

  老大给的阈值语义是"OOS 至少保留 IS 一半的边", 这是相对口径, 故默认 metric=ratio。
  当前 894 窗实跑: IS=0.9906 OOS=0.2122 -> abs=0.7784, ratio=0.7858,
  两种口径在阈值 0.50 下都判定阻断, 结论无歧义; 但定义不同, 两者都写进 JSON 留证。

阈值可配置 (不许硬编码在判断里), 优先级: 命令行 > 配置文件 > 内置默认 0.50
----------------------------------------------------------------------
  --threshold 0.50       命令行
  config/walk_forward_gate.json -> {"decay_threshold": 0.50, "metric": "ratio"}
  内置默认 DEFAULT_THRESHOLD = 0.50

产出
----
  data/walk_forward_gate.json (原子写, 机器可读)
    is_sharpe / oos_sharpe / decay / decay_abs / decay_ratio /
    threshold / metric / blocked / n_windows / computed_at / reason /
    data_age_days / ttl_days / block_reason
    —— 2026-10-21 起新增指纹留痕字段:
    source_content_sha256 (剔除 timestamp 后的内容指纹) /
    source_file_sha256 (原始字节) / source_mtime /
    duplicate_submission / timestamp_advanced_without_content_change /
    recalibration_verified / source_seen_count / source_first_seen_at

源结果选择 (2026-10-21 改造, 见文件头严禁清单)
----------------------------------------------
  旧: sorted(..., key=lambda p: p.stat().st_mtime) —— 复制旧文件 + 改时间戳即可排到最前。
  新: 排序键只用**内容里的 timestamp** + 文件名; 是否被认作"新重标定"由
      **内容指纹**判定: 指纹与上次门禁相同 ⇒ duplicate_submission=True,
      recalibration_verified=False, 并追加一行到 state/walk_forward_source_ledger.jsonl。

TTL 失败安全
------------
  新鲜度以回测结果内的 timestamp 为准（它由 walk_forward_backtest.py 在实际回测时写入）。
  门禁自身的 computed_at 每次检查都会刷新，不能代表回测数据新鲜度，故不参与 TTL。
  data_age_days > ttl_days 时仍然阻断，不降级为 WARN，避免跑批停止后门禁假绿。

退出码语义
----------
  0 = 门禁通过
  3 = 被门禁阻断 (与 daily_pick.py 一致: 3=被门禁暂停, 非成功、非内部错误)
  2 = 无可用结果文件 / 数据不可读 —— fail loud, 绝不回退成"通过"
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if 'PYTHONPATH' in os.environ:
    del os.environ['PYTHONPATH']

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "diagnostic"
GATE_FILE = ROOT / "data" / "walk_forward_gate.json"
CONFIG_FILE = ROOT / "config" / "walk_forward_gate.json"
# 源结果指纹台账(追加写, 入库): 产物 data/ 被 .gitignore 挡在库外,
# 台账是"同一份内容被反复提交"唯一的跨覆写留痕。
SOURCE_LEDGER = ROOT / "state" / "walk_forward_source_ledger.jsonl"

DEFAULT_THRESHOLD = 0.50
DEFAULT_METRIC = "ratio"
DEFAULT_TTL_DAYS = 90

EXIT_PASS = 0
EXIT_ENV_FAULT = 2
EXIT_BLOCKED = 3


def _unwrap(raw, default):
    """配置值既支持裸标量, 也支持 {"value": x} 的带元数据形态。"""
    if raw is None:
        return default
    if isinstance(raw, dict):
        v = raw.get("value", default)
        return default if v is None else v
    return raw


def _load_config():
    """读配置文件; 缺失或坏档不静默, 打印 WARN 并回落到内置默认。"""
    if not CONFIG_FILE.exists():
        print(f"[WARN] 阈值配置文件不存在, 用内置默认 "
              f"(threshold={DEFAULT_THRESHOLD}, metric={DEFAULT_METRIC}): {CONFIG_FILE}")
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        if not isinstance(cfg, dict):
            return {}
        return {
            "decay_threshold": _unwrap(cfg.get("decay_threshold"), DEFAULT_THRESHOLD),
            "metric": _unwrap(cfg.get("metric"), DEFAULT_METRIC),
            "ttl_days": _unwrap(cfg.get("ttl_days"), DEFAULT_TTL_DAYS),
            "_raw_keys": list(cfg.keys()),
        }
    except Exception as e:
        print(f"[WARN] 阈值配置文件解析失败({e}), 用内置默认 "
              f"(threshold={DEFAULT_THRESHOLD}, metric={DEFAULT_METRIC})")
        return {}


def _file_sha256(path: Path) -> str:
    """原始字节 sha256 —— 连 timestamp 一起算, 反映"落盘的这一份字节"。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 计算指纹时要剔除的字段: 这些字段变了不代表回测重跑过。
# timestamp 是重头 —— 9a13bb8d 就是只改它来冒充重标定。
_FP_VOLATILE_KEYS = ("timestamp",)


def _content_fingerprint(path: Path) -> tuple:
    """内容指纹: 剔除 timestamp 后的规范化 JSON 的 sha256。

    返回 (fingerprint, error)。error 非 None 表示文件不可解析 —— 此时指纹为 None,
    调用方必须 fail loud, 不得拿"解析不了"当"内容变了"。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as e:  # noqa: BLE001 - 坏档也要能被识别, 而不是静默当新结果
        return None, f"{type(e).__name__}: {e}"
    if not isinstance(payload, dict):
        return None, "结果文件顶层不是 JSON object"
    stable = {k: v for k, v in payload.items() if k not in _FP_VOLATILE_KEYS}
    canon = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest(), None


def _read_ledger() -> list:
    if not SOURCE_LEDGER.exists():
        return []
    rows = []
    with open(SOURCE_LEDGER, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception as e:  # noqa: BLE001 - 坏行跳过, 但不许删文件
                print(f"🔴 [walk_forward_gate.py:182] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
                continue
    return rows


def _append_source_ledger(fingerprint: str, source_file: str, file_sha256: str,
                          mtime_iso: str, source_timestamp) -> dict:
    """追加一行"源结果指纹"台账。返回本次留痕摘要(同时写回 payload)。

    台账只追加、不覆写、不删历史行 —— 产物 data/walk_forward_gate.json 会被
    每次运行覆写, 台账不会, 所以"同一指纹第几次出现"能跨覆写查到。
    """
    rows = _read_ledger()
    seen = [r for r in rows if r.get("source_content_sha256") == fingerprint]
    first_seen = seen[0].get("ts") if seen else datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    seen_files = sorted({r.get("source_file") for r in seen if r.get("source_file")})
    row = {
        "schema": "1.0",
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "source_content_sha256": fingerprint,
        "source_file_sha256": file_sha256,
        "source_file": source_file,
        "source_mtime": mtime_iso,
        "source_timestamp": source_timestamp,
        "seen_count": len(seen) + 1,
        "first_seen_at": first_seen,
        "prev_seen_files": [f for f in seen_files if f != source_file],
    }
    try:
        SOURCE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(SOURCE_LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except Exception as e:  # noqa: BLE001 - 台账写失败要吵, 但不改变门禁判定
        print(f"[WARN] 源结果指纹台账写入失败(无跨覆写留痕): {type(e).__name__}: {e}")
    return row


def _prev_gate_fingerprint() -> tuple:
    """上一次门禁产物里记录的源指纹(可能是 None/坏档)。"""
    if not GATE_FILE.exists():
        return None, None
    try:
        with open(GATE_FILE, "r", encoding="utf-8") as fh:
            prev = json.load(fh)
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(prev, dict):
        return None, None
    return prev.get("source_content_sha256"), prev.get("source_timestamp")


def _select_result():
    """选源结果 —— **按内容时间戳 + 文件名排序, 绝不按 mtime**。

    为什么不能按 mtime: 复制旧结果 + touch/改时间戳 就能让它排到最前,
    冒充"刚重跑的重标定" (9a13bb8d 的手法)。mtime 是文件系统属性, 可由人任意改。
    排序键只用**文件内容里的 timestamp**(回测脚本实跑时写入) + 文件名兜底,
    两者都不受"复制后改落盘时间"影响; 是否被当成"新重标定"另由内容指纹判定。
    """
    if not OUT_DIR.exists():
        return None, f"结果目录不存在: {OUT_DIR}"
    files = list(OUT_DIR.glob("walk-forward-test-*.json"))
    if not files:
        return None, f"未找到任何 walk-forward 结果文件: {OUT_DIR}/walk-forward-test-*.json"

    def sort_key(p: Path):
        ts = ""
        try:
            with open(p, "r", encoding="utf-8") as fh:
                ts = str(json.load(fh).get("timestamp") or "")
        except Exception:  # noqa: BLE001 - 读不出的排最后, 但仍要能被选中并 fail loud
            ts = ""
        return (ts, p.name)

    files.sort(key=sort_key, reverse=True)
    return files[0], None


def _atomic_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _data_age_days(source_timestamp, today=None):
    """按回测结果 timestamp 计算自然日年龄；解析失败返回 (None, 错误)。"""
    if not isinstance(source_timestamp, str) or not source_timestamp.strip():
        return None, "结果缺少 timestamp"
    raw = source_timestamp.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        source_dt = datetime.fromisoformat(raw)
    except ValueError as e:
        return None, f"结果 timestamp 无法解析: {e}"
    current_date = today or datetime.now().date()
    age_days = (current_date - source_dt.date()).days
    if age_days < 0:
        return None, f"结果 timestamp 位于未来: {source_timestamp}"
    return age_days, None


def evaluate(threshold=None, metric=None, ttl_days=None, today=None):
    """读最新结果 -> 判定 -> 写 data/walk_forward_gate.json。返回 (exit_code, payload)。"""
    cfg = _load_config()
    if threshold is None:
        threshold = cfg.get("decay_threshold", DEFAULT_THRESHOLD)
    if metric is None:
        metric = cfg.get("metric", DEFAULT_METRIC)
    if ttl_days is None:
        ttl_days = cfg.get("ttl_days", DEFAULT_TTL_DAYS)
    threshold = float(threshold)
    ttl_days = int(ttl_days)
    metric = str(metric).lower()
    if metric not in ("ratio", "abs"):
        print(f"[FATAL] metric 只能是 ratio 或 abs, 收到 {metric!r}")
        return EXIT_ENV_FAULT, None
    if ttl_days < 0:
        print(f"[FATAL] ttl_days 不能为负数, 收到 {ttl_days!r}")
        return EXIT_ENV_FAULT, None

    latest, err = _select_result()
    if latest is None:
        print(f"[FATAL] walk-forward 衰减门禁无法判定: {err}")
        print("       不回退为'通过' —— 无证据即失败(fail loud), 请先跑 walk_forward_backtest.py")
        return EXIT_ENV_FAULT, None

    try:
        with open(latest, "r", encoding="utf-8") as fh:
            r = json.load(fh)
    except Exception as e:
        print(f"[FATAL] 结果文件解析失败 {latest.name}: {e} —— 不回退为'通过'")
        return EXIT_ENV_FAULT, None

    # ---- 源结果指纹 (2026-10-21 立, 防"复制旧文件改时间戳冒充重标定") ----
    # 赋值行/判断行守卫 G23 直接正则校验这两行, 改名或降级成字样检查都会报红。
    source_content_sha256, fp_error = _content_fingerprint(latest)
    if source_content_sha256 is None:
        print(f"[FATAL] 源结果无法计算内容指纹 {latest.name}: {fp_error} —— 不回退为'通过'")
        return EXIT_ENV_FAULT, None
    file_sha256 = _file_sha256(latest)
    source_mtime = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
    prev_fp, prev_ts = _prev_gate_fingerprint()
    ledger_row = _append_source_ledger(
        fingerprint=source_content_sha256, source_file=latest.name, file_sha256=file_sha256,
        mtime_iso=source_mtime, source_timestamp=r.get("timestamp"))
    # 同一份内容换了时间戳再来一遍 = 不是新的重标定(9a13bb8d 的手法)
    duplicate_submission = bool(prev_fp is not None and source_content_sha256 == prev_fp)
    timestamp_advanced_without_content_change = bool(
        duplicate_submission and prev_ts != r.get("timestamp"))
    recalibration_verified = bool(not duplicate_submission)

    is_sharpe = r.get("mean_is_sharpe")
    oos_sharpe = r.get("mean_oos_sharpe")
    n_windows = r.get("successful_windows", r.get("total_windows"))
    source_timestamp = r.get("timestamp")

    if not isinstance(is_sharpe, (int, float)) or not isinstance(oos_sharpe, (int, float)):
        print(f"[FATAL] 结果文件缺少 mean_is_sharpe/mean_oos_sharpe: {latest.name} —— 不回退为'通过'")
        return EXIT_ENV_FAULT, None

    data_age_days, age_error = _data_age_days(source_timestamp, today=today)
    ttl_expired = age_error is not None or data_age_days > ttl_days

    decay_abs = round(float(is_sharpe) - float(oos_sharpe), 4)
    if is_sharpe > 0:
        decay_ratio = round(decay_abs / float(is_sharpe), 4)
        ratio_ok = True
    else:
        decay_ratio = None
        ratio_ok = False

    decay = decay_ratio if metric == "ratio" else decay_abs

    if metric == "ratio" and not ratio_ok:
        decay_blocked = True
        decay_reason = (f"IS 夏普={is_sharpe} <= 0, 相对衰减无定义, 且样本内无正向边际, "
                        f"按 fail-safe 判定阻断(不因算不出指标而放行)")
    else:
        decay_blocked = decay > threshold
        if metric == "ratio":
            keep = round(1 - decay_ratio, 4)
            decay_reason = (f"样本外夏普相对衰减 {decay_ratio} "
                            f"(= (IS {is_sharpe} - OOS {oos_sharpe}) / IS {is_sharpe}) "
                            f"{'>' if decay_blocked else '<='} 阈值 {threshold}; "
                            f"OOS 保留 IS 的 {keep:.1%} 边际, "
                            f"要求 >= {1 - threshold:.0%}")
        else:
            decay_reason = (f"样本外夏普绝对衰减 {decay_abs} "
                            f"(= IS {is_sharpe} - OOS {oos_sharpe}) "
                            f"{'>' if decay_blocked else '<='} 阈值 {threshold}")

    blocked = ttl_expired or decay_blocked
    if age_error is not None:
        block_reason = f"数据时间无效无法判定（{age_error}）"
        reason = block_reason
    elif data_age_days > ttl_days:
        block_reason = f"数据过旧无法判定（age={data_age_days} 天 > {ttl_days} 天）"
        reason = block_reason
    elif decay_blocked:
        block_reason = f"衰减超阈值：{decay_reason}"
        reason = block_reason
    else:
        block_reason = None
        reason = decay_reason

    payload = {
        "source_content_sha256": source_content_sha256,
        "source_file_sha256": file_sha256,
        "source_mtime": source_mtime,
        "source_selection_basis": "content_timestamp+filename (禁止 mtime 排序)",
        "source_first_seen_at": ledger_row.get("first_seen_at"),
        "source_seen_count": ledger_row.get("seen_count"),
        "source_prev_seen_files": ledger_row.get("prev_seen_files"),
        "duplicate_submission": duplicate_submission,
        "timestamp_advanced_without_content_change": timestamp_advanced_without_content_change,
        "recalibration_verified": recalibration_verified,
        "prev_source_content_sha256": prev_fp,
        "prev_source_timestamp": prev_ts,
        "is_sharpe": is_sharpe,
        "oos_sharpe": oos_sharpe,
        "decay": decay,
        "decay_abs": decay_abs,
        "decay_ratio": decay_ratio,
        "threshold": threshold,
        "metric": metric,
        "blocked": bool(blocked),
        "n_windows": n_windows,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_file": latest.name,
        "source_timestamp": source_timestamp,
        "data_age_days": data_age_days,
        "ttl_days": ttl_days,
        "block_reason": block_reason,
        "reason": reason,
        "decay_reason": decay_reason,
        "decay_formula": ("decay_abs = mean_is_sharpe - mean_oos_sharpe "
                          "(walk_forward_backtest.py:167 sharpe_drop); "
                          "decay_ratio = (IS - OOS) / IS = 1 - OOS/IS"),
        "exit_code": EXIT_BLOCKED if blocked else EXIT_PASS,
    }
    _atomic_write(GATE_FILE, payload)
    # 门禁产物被 .gitignore 的 data/ 挡在库外(无 git 历史), 故写完后追加一行
    # 指纹台账 state/gate_fingerprints.jsonl 恢复可追溯性(2026-10-21 治理任务B)。
    # 台账失败不改变门禁判定与退出码, 但会 [WARN] 留痕(不许静默)。
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from record_gate_fingerprint import record_fingerprint  # noqa: E402
        record_fingerprint(
            artifact=GATE_FILE,
            source=latest,
            writer="scripts/walk_forward_gate.py",
            note="walk-forward 衰减门禁",
        )
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] 门禁指纹台账未写入(判定不受影响): "
              f"{type(e).__name__}: {e}")
    return (EXIT_BLOCKED if blocked else EXIT_PASS), payload


def main() -> int:
    ap = argparse.ArgumentParser(description="walk-forward 过拟合衰减阻断门禁")
    ap.add_argument("--threshold", type=float, default=None,
                    help=f"衰减阈值, 默认 {DEFAULT_THRESHOLD} (配置文件/内置默认)")
    ap.add_argument("--metric", choices=["ratio", "abs"], default=None,
                    help=f"判定用哪种衰减口径, 默认 {DEFAULT_METRIC}")
    ap.add_argument("--ttl-days", type=int, default=None,
                    help=f"结果最大允许年龄（自然日）, 默认 {DEFAULT_TTL_DAYS}")
    args = ap.parse_args()

    code, payload = evaluate(
        threshold=args.threshold,
        metric=args.metric,
        ttl_days=args.ttl_days,
    )
    if payload is None:
        return code

    print(f"[walk_forward_gate] is={payload['is_sharpe']} oos={payload['oos_sharpe']} "
          f"decay({payload['metric']})={payload['decay']} "
          f"(abs={payload['decay_abs']} ratio={payload['decay_ratio']}) "
          f"threshold={payload['threshold']} windows={payload['n_windows']} "
          f"file={payload['source_file']}")
    print(f"[walk_forward_gate] 数据年龄: {payload['data_age_days']} 天 "
          f"(TTL={payload['ttl_days']} 天, 真源={payload['source_timestamp']})")
    print(f"[walk_forward_gate] 源指纹: content_sha256={payload['source_content_sha256'][:16]}... "
          f"file_sha256={payload['source_file_sha256'][:16]}... "
          f"mtime={payload['source_mtime']} 第{payload['source_seen_count']}次出现"
          f"(首次 {payload['source_first_seen_at']})")
    if payload["source_prev_seen_files"]:
        print(f"[walk_forward_gate] ⚠️ 该内容指纹此前以其他文件名出现过: "
              f"{payload['source_prev_seen_files']}")
    if payload["duplicate_submission"]:
        print("=" * 70)
        print("🔴 [walk_forward_gate] 源结果内容指纹与上一次门禁完全相同 "
              "—— 这不是新的重标定")
        if payload["timestamp_advanced_without_content_change"]:
            print(f"   且 timestamp 被推进 "
                  f"({payload['prev_source_timestamp']} -> {payload['source_timestamp']}) "
                  f"而内容一字未变 —— 与 2026-10-21 已核实的伪造手法一致")
        print(f"   recalibration_verified = False; 留痕见 {SOURCE_LEDGER.name}")
        print("=" * 70)
    print(f"[walk_forward_gate] 判定依据: {payload['reason']}")
    print(f"[walk_forward_gate] 门禁结果: {'阻断' if payload['blocked'] else '通过'} "
          f"-> data/walk_forward_gate.json")

    if payload["blocked"]:
        stale = payload["data_age_days"] is None or payload["data_age_days"] > payload["ttl_days"]
        title = "数据过旧/时间无效，无法判定" if stale else "walk-forward 过拟合衰减超阈值"
        print("=" * 70)
        print(f"🔴 [walk_forward_gate] 门禁未通过 —— {title}")
        print(f"   指标    : 样本外夏普衰减({payload['metric']}) = {payload['decay']}")
        print(f"   阈值    : {payload['threshold']}")
        print(f"   数据年龄: {payload['data_age_days']} 天 / TTL {payload['ttl_days']} 天")
        print(f"   阻断理由: {payload['block_reason']}")
        print(f"   样本    : {payload['n_windows']} 个窗口, 来源 {payload['source_file']}")
        print(f"   后果    : 退出码 {EXIT_BLOCKED} (被门禁阻断), 调度层判 FAIL; "
              f"不得把未通过或已过期的 walk-forward 结果当作放行依据")
        print("=" * 70)
    else:
        print(f"✅ [walk_forward_gate] 门禁通过, 退出码 0")
    return code


if __name__ == "__main__":
    sys.exit(main())
