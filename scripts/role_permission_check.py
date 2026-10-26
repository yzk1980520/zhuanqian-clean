#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""角色权限校验器 — profile→文件路径映射 (US4)

读取 data/system/role_permissions.json，检查当前 profile 对目标文件的写权限。
越界写 → sys.exit(1) + 写入 P1 告警到 data/message_queue.json。

FR-004: 每次 git commit 时验证提交者角色与其操作权限匹配。
宪法 VII: 无裸 except:，显式异常类型。
"""
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from fnmatch import fnmatch

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT = Path(__file__).resolve().parent.parent
PERMS_PATH = PROJECT / "data" / "system" / "role_permissions.json"
MSG_QUEUE = PROJECT / "data" / "message_queue.json"


def get_current_profile() -> str:
    """从环境变量或进程名推断当前 Hermes profile。

    宪法 VII: 异常不得静默，推断失败显式 WARN。
    """
    # Hermes 设置 HERMES_PROFILE 环境变量
    profile = os.environ.get("HERMES_PROFILE", "default")
    if profile:
        return profile
    # 从进程命令行推断
    try:
        import subprocess
        result = subprocess.run(
            ["ps", "-p", str(os.getppid()), "-o", "command="],
            capture_output=True, text=True, timeout=5,
        )
        cmd = result.stdout.lower()
        if "opencode" in cmd or "老三" in cmd:
            return "opencode"
        if "atomcode" in cmd or "老五" in cmd:
            return "atomcode"
        if "laosi" in cmd or "老四" in cmd:
            return "laosi"
        if "workbuddy" in cmd or "老六" in cmd:
            return "workbuddy"
        if "prime" in cmd or "牛马" in cmd:
            return "prime"
    except Exception as exc:
        print(f"[WARN] get_current_profile inference failed: {exc}", file=sys.stderr)
    return "default"


def load_permissions() -> list:
    """加载 role_permissions.json。"""
    if not PERMS_PATH.exists():
        raise FileNotFoundError(f"role_permissions.json not found: {PERMS_PATH}")
    data = json.loads(PERMS_PATH.read_text(encoding="utf-8"))
    return data.get("profiles", [])


def find_profile(profiles: list, name: str) -> dict | None:
    """查找 profile 配置。"""
    for p in profiles:
        if p.get("profile_name") == name:
            return p
    return None


def path_matches_glob(filepath: str, glob_pattern: str) -> bool:
    """检查 filepath 是否匹配 glob 模式（支持 ** 递归）。"""
    # PurePath.match 不支持 **，用 fnmatch 逐级匹配
    import fnmatch
    # 将 ** 替换为 * 后再用 fnmatch（fnmatch 不支持 **，但可以分步匹配）
    parts_path = Path(filepath).parts
    parts_pattern = Path(glob_pattern).parts

    def _match_parts(path_parts, pattern_parts):
        """递归匹配路径片段和模式片段。"""
        if not pattern_parts:
            return not path_parts
        head, *tail = pattern_parts
        if head == "**":
            # ** 匹配零个或多个路径片段
            for i in range(len(path_parts) + 1):
                if _match_parts(path_parts[i:], tail):
                    return True
            return False
        if not path_parts:
            return False
        if fnmatch.fnmatch(path_parts[0], head):
            return _match_parts(path_parts[1:], tail)
        return False

    return _match_parts(parts_path, parts_pattern)


def check_path_against_globs(filepath: str, globs: list[str]) -> bool:
    """检查 filepath 是否匹配任一 glob 模式。"""
    for pattern in globs:
        if path_matches_glob(filepath, pattern):
            return True
    return False


def check_permission(
    profile_name: str | None = None,
    action: str = "write",
    target_path: str | None = None,
) -> dict:
    """检查单个权限请求。

    返回:
        {
            "allowed": bool,
            "level": "P0" | "P1" | None,
            "type": "permission_violation" | None,
            "profile": str,
            "action": str,
            "target": str,
            "reason": str,
        }
    """
    if profile_name is None:
        profile_name = get_current_profile()

    result = {
        "allowed": True,
        "level": None,
        "type": None,
        "profile": profile_name,
        "action": action,
        "target": target_path or "",
        "reason": "",
    }

    if action != "write":
        return result  # 只检查写权限

    if target_path is None:
        result["allowed"] = True
        result["reason"] = "no target specified"
        return result

    try:
        profiles = load_permissions()
    except FileNotFoundError as exc:
        result["allowed"] = False
        result["level"] = "P0"
        result["type"] = "permission_check_failed"
        result["reason"] = str(exc)
        return result

    profile = find_profile(profiles, profile_name)
    if profile is None:
        # 未知 profile → 保守策略：DENY（fail-closed，不得 fail-open）
        result["allowed"] = False
        result["level"] = "P1"
        result["type"] = "unknown_profile"
        result["reason"] = f"unknown profile '{profile_name}' — deny by default (fail-closed)"
        return result

    # 黑名单优先于白名单（FR-004 约束）
    blocked_writes = profile.get("blocked_writes", [])
    allowed_writes = profile.get("allowed_writes", [])

    # 检查是否在黑名单中
    for pattern in blocked_writes:
        if path_matches_glob(target_path, pattern):
            result["allowed"] = False
            result["level"] = "P1"
            result["type"] = "permission_violation"
            result["reason"] = f"blocked by profile '{profile_name}': matches pattern '{pattern}'"
            return result

    # 检查是否在白名单中
    if allowed_writes:
        matched = False
        for pattern in allowed_writes:
            if path_matches_glob(target_path, pattern):
                matched = True
                break
        if not matched:
            result["allowed"] = False
            result["level"] = "P1"
            result["type"] = "permission_violation"
            result["reason"] = f"not in allowed_writes for profile '{profile_name}'"
            return result

    result["allowed"] = True
    result["reason"] = f"allowed for profile '{profile_name}'"
    return result


def write_alert(alert: dict) -> None:
    """写入 P1 告警到 message_queue.json（共享队列，读-改-写追加语义）。

    宪法: 不得用 atomic_dump 覆盖共享 list（会把 list 变成 dict，销毁队列）。
    使用 update_json 追加，非原子 fallback 时必须写告警日志（不得静默）。
    """
    try:
        from core.pipeline.atomic_json import update_json
        def _append(existing):
            if existing is None:
                existing = []
            if not isinstance(existing, list):
                # 队列被写坏成 dict/其它：包成 list 保留
                existing = [existing]
            existing.append(alert)
            return existing
        update_json(str(MSG_QUEUE), _append, default=[])
    except ImportError as exc:
        # fallback: 非原子写，必须显式告警（宪法 VII 不得静默吞）
        print(f"[WARN] atomic_json unavailable, using non-atomic append: {exc}", file=sys.stderr)
        if MSG_QUEUE.exists():
            try:
                existing = json.loads(MSG_QUEUE.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    existing.append(alert)
                else:
                    existing = [existing, alert]
                MSG_QUEUE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            except json.JSONDecodeError as exc2:
                print(f"[WARN] message_queue.json corrupt, resetting to [alert]: {exc2}", file=sys.stderr)
                MSG_QUEUE.write_text(json.dumps([alert], ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            MSG_QUEUE.write_text(json.dumps([alert], ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] Failed to write alert to message_queue.json: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：检查权限，越界则 exit(1) + 写告警。

    用法:
        python role_permission_check.py write data/holdings.json [--profile opencode]
    """
    args = argv or sys.argv[1:]
    if len(args) < 2:
        print("Usage: role_permission_check.py <action> <target_path> [--profile <name>]", file=sys.stderr)
        return 2

    action = args[0]
    target = args[1]
    profile = None
    i = 2
    while i < len(args):
        if args[i] == "--profile" and i + 1 < len(args):
            profile = args[i + 1]
            i += 2
        else:
            i += 1

    if profile is None:
        profile = get_current_profile()

    result = check_permission(profile_name=profile, action=action, target_path=target)

    if result["allowed"]:
        print(f"ALLOWED: {result['reason']}")
        return 0
    else:
        print(f"BLOCKED [{result['level']}]: {result['reason']}", file=sys.stderr)
        alert = {
            "level": result["level"],
            "type": result["type"],
            "profile": result["profile"],
            "action": result["action"],
            "target": result["target"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reason": result["reason"],
        }
        write_alert(alert)
        return 1


if __name__ == "__main__":
    sys.exit(main())
