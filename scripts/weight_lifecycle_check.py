#!/usr/bin/env python
"""T004: 权重元数据生命周期检查 (FR-003, FR-004, 宪法XI)

功能:
- 扫描 models/ 下所有权重文件
- 检查/生成 metadata.json（trained_at / data_window / ic_baseline / status）
- 过期 90 日自动标 needs_retrain
- 缺失元数据 P2 告警
- 结果汇总写 data/weight_status.json

CLI:
    python scripts/weight_lifecycle_check.py [--dry-run] [--verbose]

宪法 VII 合规: 无裸 except，显式异常类型。
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
LAYA_DIR = MODELS_DIR / "laya-typed-decisions"
WEIGHT_STATUS_FILE = PROJECT_ROOT / "data" / "weight_status.json"
MESSAGE_QUEUE_FILE = PROJECT_ROOT / "data" / "message_queue.json"
WEIGHT_VALIDITY_DAYS = 90

# 权重文件模式
WEIGHT_GLOBS = [
    (MODELS_DIR, "*.pkl"),
    (MODELS_DIR, "*.pt"),
    (LAYA_DIR, "*.safetensors"),
]


def find_weight_files() -> list[dict]:
    """扫描所有权重文件，返回 [{path, model_type}] 列表

    2026-10-24 T011: 排除 dl_retrain_pipeline 原子切换产出的归档件
    (*_archive_*.pkl) — 归档是历史权重 (metadata 跟随, status 不再更新),
    若纳入每日扫描会因 trained_at 过期刷 P2 告警风暴。
    """
    results = []
    for base_dir, pattern in WEIGHT_GLOBS:
        if not base_dir.exists():
            continue
        for f in sorted(base_dir.glob(pattern)):
            if f.name.endswith(".metadata.json"):
                continue  # 跳过元数据文件本身
            if "_archive_" in f.stem:
                continue  # 跳过 T011 归档件 (见 docstring)
            model_type = "laya" if "laya" in str(f) else "dl_predictor"
            results.append({"path": f, "model_type": model_type})
    return results


def get_metadata_path(weight_path: Path) -> Path:
    """权重文件的元数据路径: xxx.pkl → xxx.metadata.json"""
    return weight_path.with_suffix(weight_path.suffix + ".metadata.json")


def load_metadata(meta_path: Path) -> dict:
    """读取 metadata.json，缺失/损坏返回 None"""
    if not meta_path.exists():
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [WARN] 元数据读取失败 {meta_path.name}: {exc}")
        return None


def compute_status(meta: dict | None, weight_path: Path) -> str:
    """根据 metadata 计算权重状态"""
    if meta is None:
        return "no_metadata"

    trained_at_str = meta.get("trained_at")
    if not trained_at_str:
        return "no_metadata"

    try:
        trained_at = datetime.fromisoformat(trained_at_str)
    except (ValueError, TypeError) as exc:
        print(f"  [WARN] trained_at 格式无效 {weight_path.name}: {trained_at_str!r}")
        return "no_metadata"

    # 归一化到 UTC 对比
    if trained_at.tzinfo is None:
        trained_at = trained_at.replace(tzinfo=timezone(timedelta(hours=8)))

    age_days = (datetime.now(timezone.utc) - trained_at).total_seconds() / 86400
    if age_days > WEIGHT_VALIDITY_DAYS:
        return "needs_retrain"

    # 如果之前标记为 extended，保留
    if meta.get("status") == "extended":
        return "extended"

    return "valid"


def write_metadata(meta_path: Path, meta: dict, status: str) -> None:
    """写入/更新 metadata.json（原子写, os.replace 跨平台原子覆盖）

    P0修复 (2026-10-24 T009): 原 Path.rename 覆盖已存在文件在 Windows
    WinError 183 — 每日 cron 更新既有 metadata 必踩。
    """
    import os
    meta["status"] = status
    meta["checked_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_path)


def alert_p2(message: str, severity: str = "P2") -> None:
    """写 P2/P1 告警到 message_queue.json"""
    if not MESSAGE_QUEUE_FILE.parent.exists():
        MESSAGE_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

    queue: list[dict] = []
    if MESSAGE_QUEUE_FILE.exists():
        try:
            with open(MESSAGE_QUEUE_FILE, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
                if isinstance(raw, list):
                    queue = raw
                elif isinstance(raw, dict) and "messages" in raw:
                    queue = raw.get("messages", [])
        except (json.JSONDecodeError, OSError):
            pass

    ts = datetime.now(timezone(timedelta(hours=8))).isoformat()
    queue.append({
        "ts": ts,
        "severity": severity,
        "source": "weight_lifecycle_check",
        "message": message,
    })

    tmp = MESSAGE_QUEUE_FILE.with_suffix(MESSAGE_QUEUE_FILE.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(queue, fh, indent=2, ensure_ascii=False)
    import os
    os.replace(tmp, MESSAGE_QUEUE_FILE)  # P0修复(2026-10-24): 原子覆盖, 防 WinError 183


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="权重元数据生命周期检查")
    parser.add_argument("--dry-run", action="store_true", help="只报告不写入")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    args = parser.parse_args()

    print(f"[weight_lifecycle_check] {datetime.now().isoformat()}")
    weights = find_weight_files()
    print(f"  发现 {len(weights)} 个权重文件")

    report: list[dict] = []
    for w in weights:
        path: Path = w["path"]
        meta_path = get_metadata_path(path)
        meta = load_metadata(meta_path)
        status = compute_status(meta, path)
        entry = {
            "file": path.name,
            "model_type": w["model_type"],
            "status": status,
            "trained_at": meta.get("trained_at") if meta else None,
            "data_window": meta.get("data_window") if meta else None,
            "ic_baseline": meta.get("ic_baseline") if meta else None,
        }
        report.append(entry)

        if args.verbose:
            print(f"  {path.name:40s} → {status:16s} trained_at={entry['trained_at']}")

        if status == "no_metadata" and not args.dry_run:
            alert_p2(f"权重 {path.name} 缺失元数据（no_metadata），需三方补录", "P2")

        if status == "needs_retrain" and not args.dry_run:
            alert_p2(f"权重 {path.name} 已过期 90 日（trained_at={entry['trained_at']}），待重训", "P2")

    # 汇总
    summary = {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "total_weights": len(report),
        "valid": sum(1 for r in report if r["status"] == "valid"),
        "needs_retrain": sum(1 for r in report if r["status"] == "needs_retrain"),
        "no_metadata": sum(1 for r in report if r["status"] == "no_metadata"),
        "extended": sum(1 for r in report if r["status"] == "extended"),
        "weights": report,
    }

    if not args.dry_run:
        WEIGHT_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(WEIGHT_STATUS_FILE, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        print(f"  汇总写入 {WEIGHT_STATUS_FILE.name}")
    else:
        print(f"  [DRY-RUN] 汇总: {json.dumps({k: v for k, v in summary.items() if k != 'weights'}, ensure_ascii=False)}")

    # 退出码: 0=全有效, 1=有需要重训/缺失
    has_issue = any(r["status"] in ("needs_retrain", "no_metadata") for r in report)
    print(f"  结果: {'⚠️ 有异常' if has_issue else '✅ 全部有效'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
