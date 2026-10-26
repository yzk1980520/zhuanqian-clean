#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disk_cleanup_safe.py — 安全清理 Temp / CrashDumps / Hermes 缓存 / __pycache__

2026-10-26 P1 加固 (t_8969284a)：原脚本名为 safe 实为全量裸删（无龄期、
无 dry-run、三处裸 except: 静默吞没，SOUL 准则 9 P0 缺陷）。本版：
  - 所有目录加龄期门槛：Temp>2天 / CrashDumps>30天 / Hermes缓存>7天
    （均可 CLI 配置：--temp-age-days / --crashdumps-age-days / --cache-age-days）
  - 默认 dry-run：只列候选、0 删除；显式 --apply 才真删
  - 向后兼容：旧调用不传 flag → 打印告警「本次 0 删除」，按 dry-run 处理，非静默
  - except 全部改计数留痕（每段打印 skipped= 数），禁裸 except / 静默 pass
  - 护栏：盘符根 一律拒绝；目录不存在 打印 SKIP 跳过

用法:
  python scripts/disk_cleanup_safe.py                 # dry-run（默认，安全）
  python scripts/disk_cleanup_safe.py --dry-run       # 显式 dry-run（与默认相同）
  python scripts/disk_cleanup_safe.py --apply         # 真删
  python scripts/disk_cleanup_safe.py --temp-age-days 3 --crashdumps-age-days 60
"""
import argparse
import os
import time

# 固定清理目标（与 6b31ecba 原版一致，路径不随环境漂移）
TEMP_DIR = r'C:\Users\WIN10\AppData\Local\Temp'
CRASHDUMPS_DIR = r'C:\Users\WIN10\AppData\Local\CrashDumps'
HERMES_CACHE_DIR = r'D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\cache'
PYCACHE_BASE = r'D:\open code'

CANDIDATE_PRINT_CAP = 50  # dry-run 候选清单打印上限，防刷屏


def _safe_guard(path, desc):
    """护栏：盘符根 一律拒绝；目录不存在 打印 SKIP 跳过。返回是否继续。"""
    abspath = os.path.abspath(path)
    if len(abspath) <= 3 and abspath[1:2] == ':':  # 'C:\' 形式的盘符根
        print(f'GUARD [{desc}]: 拒绝清理盘符根 {path}')
        return False
    if not os.path.exists(path):
        print(f'SKIP [{desc}]: not found -> {path}')
        return False
    return True


def cleanup_dir(path, desc, max_age_days, apply, now=None):
    """按龄期门槛清理目录内文件。

    apply=False (dry-run): 只统计并列候选（前 CANDIDATE_PRINT_CAP 条 + 总数），0 删除。
    apply=True:            删除超龄文件并清理由此变空的目录（只删空目录）。

    返回 (freed_mb, removed, skipped, candidates)。
    skipped = 因权限/文件句柄/竞态删除失败被跳过的次数（留痕，非静默）。
    """
    if not _safe_guard(path, desc):
        return 0.0, 0, 0, 0
    now = time.time() if now is None else now
    threshold = max_age_days * 86400
    freed = 0
    removed = 0
    skipped = 0
    candidates = []
    print(f'CLEANING [{desc}] mode={"APPLY" if apply else "DRY-RUN"} age>{max_age_days:g}d -> {path}')
    for root, dirs, files in os.walk(path, topdown=True):
        for f in files:
            fp = os.path.join(root, f)
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                skipped += 1
                continue
            if now - mtime <= threshold:
                continue  # 未超龄，保留
            try:
                sz = os.path.getsize(fp)
            except OSError:
                skipped += 1
                continue
            candidates.append((fp, sz))
            if not apply:
                continue
            try:
                os.remove(fp)
                freed += sz
                removed += 1
            except (PermissionError, OSError):
                skipped += 1
        if apply:
            # 清理由此变空的目录（只删空目录，不递归炸目录树）
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    if os.path.isdir(dp) and not os.listdir(dp):
                        os.rmdir(dp)
                except OSError:
                    skipped += 1
    if apply:
        print(f'CLEANED [{desc}] {freed/1e6:.1f}MB/{removed} files removed, skipped={skipped}')
    else:
        shown = candidates[:CANDIDATE_PRINT_CAP]
        print(f'WOULD CLEAN [{desc}] 0 removed (dry-run), candidates={len(candidates)}, skipped={skipped}')
        for fp, sz in shown:
            print(f'  候选: {sz/1e6:.2f}MB  {fp}')
        if len(candidates) > len(shown):
            print(f'  ...（候选共 {len(candidates)} 件，仅列前 {len(shown)} 件）')
    return freed / 1e6, removed, skipped, len(candidates)


def main(argv=None):
    ap = argparse.ArgumentParser(description='安全清理临时目录（默认 dry-run，--apply 才真删）')
    ap.add_argument('--apply', action='store_true',
                    help='真删。不传则默认 dry-run（0 删除，仅列候选）')
    ap.add_argument('--dry-run', action='store_true',
                    help='显式 dry-run（与默认相同，仅列候选不删）')
    ap.add_argument('--temp-age-days', type=float, default=2.0,
                    help='Temp 龄期门槛天数（默认 2）')
    ap.add_argument('--crashdumps-age-days', type=float, default=30.0,
                    help='CrashDumps 龄期门槛天数（默认 30）')
    ap.add_argument('--cache-age-days', type=float, default=7.0,
                    help='Hermes 缓存龄期门槛天数（默认 7，行为与原版一致）')
    args = ap.parse_args(argv)

    apply = bool(args.apply and not args.dry_run)
    if args.dry_run and args.apply:
        print('⚠️  --dry-run 与 --apply 同传：按 dry-run 处理（0 删除）')
    if not (args.apply or args.dry_run):
        # 向后兼容降级路径：旧调用不传 flag → 告警不删，非静默
        print('⚠️  未传 --apply / --dry-run：向后兼容 → 本次 0 删除（按 dry-run 处理并列出候选）。真删请显式加 --apply。')

    results = [
        (label, cleanup_dir(path, desc, days, apply))
        for label, path, desc, days in [
            ('Temp', TEMP_DIR, '用户临时文件', args.temp_age_days),
            ('CrashDumps', CRASHDUMPS_DIR, '崩溃转储', args.crashdumps_age_days),
            ('Hermes Cache', HERMES_CACHE_DIR, 'Hermes缓存', args.cache_age_days),
        ]
    ]

    # __pycache__：不做龄期保护（编译产物），口径 = apply 全删 / dry-run 只列
    pycache_total = [0.0, 0, 0, 0]
    for root, dirs, files in os.walk(PYCACHE_BASE):
        if '__pycache__' in dirs:
            pyc = os.path.join(root, '__pycache__')
            r = cleanup_dir(pyc, f'__pycache__ @{root}', 0, apply)
            for i in range(4):
                pycache_total[i] += r[i]
    results.append(('__pycache__', tuple(pycache_total)))

    total_removed = sum(rm for _, (_, _, rm, _) in results)
    total_freed = sum(f for _, (_, f, _, _) in results)
    total_candidates = sum(c for _, (_, _, _, c) in results)
    mode = 'APPLY' if apply else 'DRY-RUN'
    print(f'\n=== {mode} 清理汇总：删除 {total_removed} 件（{total_freed/1000:.2f} GB），候选 {total_candidates} 件 ===')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
