#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py backtest-gate
# -*- coding: utf-8 -*-
"""
check_backtest_result_fresh.py —— 回测结果文件的「新鲜度闸门」
===============================================================
为什么需要:
    132 日全量回测与 sanity 验收被串在同一个 Windows 计划任务里（scripts/Zhuanqian_Rotation132d.bat），
    顺序是: 审计 → 回测(auto_pipeline.py --wait, 阻塞) → 验收(check_backtest_sanity.py)。
    --wait 只保证「回测子进程已经退出」，**不保证它真的写了结果文件**。
    若 backtest_rotation.py 退出码 0 但压根没落盘（或写到了别处），
    验收会拿上一轮的旧 rotation_backtest_result.json 去判 → 门禁假绿。
    这正是本项目最怕的静默失效，所以加一道独立闸门: 结果文件的 mtime 必须晚于本轮开始时刻。

用法:
    # 取当前时间戳（bat 在开始回测前调用，避免 cmd 拼脆弱的日期字符串）
    python scripts/check_backtest_result_fresh.py --now

    # 判断结果文件是否为本轮新产出
    python scripts/check_backtest_result_fresh.py --since 2026-11-01T04:00:00 \
        [--file data/rotation_backtest_result.json]

退出码:
    0 = 新鲜: 文件存在且 mtime 晚于 --since → 可以跑验收
    1 = 不新鲜: 文件不存在 / mtime 早于或等于 --since → 判定本轮未产出, 禁止跑验收
        （原因会打印到 stdout, 区分「没写文件」还是「文件是旧的」, 供 logs\\scheduler.log 留证）
    2 = 内部错误: --since 缺失或不可解析、--file 路径不可读等

设计取舍:
    时间比较放在 Python 而不是 cmd —— cmd 的 %date%/%time% 受区域设置影响, 字符串比较边界全错。
    本脚本只读, 不修改任何回测产物。
"""
import argparse
import os
import sys
from datetime import datetime

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(PROJECT, "data", "rotation_backtest_result.json")

EXIT_FRESH = 0
EXIT_STALE = 1
EXIT_ERROR = 2


def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_ts(text):
    """解析时间戳: 接受 ISO(2026-11-01T04:00:00) 或 '2026-11-01 04:00:00'。失败返回 None。"""
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip())
    except ValueError as e:
        print(f"🔴 [check_backtest_result_fresh.py:56] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 ValueError → 兜底, 异常={e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description="回测结果文件新鲜度闸门")
    parser.add_argument("--now", action="store_true", help="打印当前 ISO 时间戳后退出(供 bat 记录本轮开始时刻)")
    parser.add_argument("--since", help="本轮回测开始时刻(ISO), 结果文件 mtime 必须晚于它")
    parser.add_argument("--file", default=DEFAULT_FILE, help=f"待检查的结果文件(默认 {DEFAULT_FILE})")
    args = parser.parse_args()

    if args.now:
        print(_fmt(datetime.now()))
        return EXIT_FRESH

    if not args.since:
        print("内部错误: 缺少 --since (本轮回测开始时刻)。用法见 --help", file=sys.stderr)
        return EXIT_ERROR

    since = _parse_ts(args.since)
    if since is None:
        print(f"内部错误: --since 时间串不可解析: {args.since!r}", file=sys.stderr)
        return EXIT_ERROR

    if not os.path.exists(args.file):
        print(
            f"不新鲜: 本轮未产出 —— 结果文件不存在: {args.file}\n"
            f"  判据: 回测已退出(退出码0)但未落盘, 禁止用上一轮的旧结果跑验收(防假绿)。\n"
            f"  排查: 看 .scratch/backtest_132d_*.log 里回测是否中途跳过写盘 / 写到了别处。",
            file=sys.stderr,
        )
        return EXIT_STALE

    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(args.file))
    except OSError as e:
        print(f"内部错误: 读取 mtime 失败: {args.file} ({e})", file=sys.stderr)
        return EXIT_ERROR

    if mtime <= since:
        print(
            f"不新鲜: 结果是旧的 —— 文件 mtime={_fmt(mtime)} 未晚于本轮开始时刻 {_fmt(since)}\n"
            f"  判据: 本轮回测没有更新 {args.file}, 现有文件是上一轮的产物。\n"
            f"  排查: 看 .scratch/backtest_132d_*.log, 确认回测是否真的跑完并写盘。",
            file=sys.stderr,
        )
        return EXIT_STALE

    print(f"新鲜: {args.file} mtime={_fmt(mtime)} 晚于本轮开始时刻 {_fmt(since)} → 可以跑验收")
    return EXIT_FRESH


if __name__ == "__main__":
    sys.exit(main())
