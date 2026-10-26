#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断文件定期轮转脚本
====================
功能：
  1. 归档 output/diagnostic/ 中超过7天的文件
  2. 清理 _archive/diagnostic-*/ 中超过90天的旧归档
  3. 记录轮转日志

执行方式：
  - 手动：python scripts/diagnostic_rotator.py
  - Cron：每日 02:00 自动执行
"""

import os
import glob
import shutil
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(r'D:\open code\zhuanqian')
DIAGNOSTIC = BASE / 'output' / 'diagnostic'
ARCHIVE_BASE = BASE / '_archive'
LOG_FILE = BASE / 'logs' / 'diagnostic_rotator.log'

# 轮转阈值
ARCHIVE_AFTER_DAYS = 7      # diagnostic/ 文件保留天数
PURGE_AFTER_DAYS = 90       # 归档文件清理天数


def log(msg):
    """写入日志"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')
    print(line)


def rotate_diagnostic():
    """轮转 output/diagnostic/ 文件"""
    if not DIAGNOSTIC.exists():
        log("diagnostic/ 目录不存在，跳过")
        return 0
    
    cutoff = datetime.now() - timedelta(days=ARCHIVE_AFTER_DAYS)
    moved = 0
    
    # 创建当日归档目录
    today = datetime.now().strftime('%Y%m%d')
    archive_dir = ARCHIVE_BASE / f'diagnostic-{today}'
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    for f in DIAGNOSTIC.glob('*'):
        if f.is_file() and f.stat().st_mtime < cutoff.timestamp():
            dest = archive_dir / f.name
            try:
                shutil.move(str(f), str(dest))
                moved += 1
                log(f"归档: {f.name}")
            except Exception as e:
                log(f"归档失败 {f.name}: {e}")
    
    return moved


def purge_old_archives():
    """清理超过90天的旧归档"""
    cutoff = datetime.now() - timedelta(days=PURGE_AFTER_DAYS)
    purged = 0
    
    for d in ARCHIVE_BASE.glob('diagnostic-*'):
        if d.is_dir() and d.stat().st_mtime < cutoff.timestamp():
            try:
                shutil.rmtree(d)
                purged += 1
                log(f"清理旧归档: {d.name}")
            except Exception as e:
                log(f"清理失败 {d.name}: {e}")
    
    return purged


def main():
    log("=" * 50)
    log("开始诊断文件轮转")
    
    # 轮转
    moved = rotate_diagnostic()
    log(f"归档 {moved} 个文件")
    
    # 清理旧归档
    purged = purge_old_archives()
    log(f"清理 {purged} 个旧归档目录")
    
    log("轮转完成")
    log("=" * 50)
    
    return moved, purged


if __name__ == '__main__':
    main()
