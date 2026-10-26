#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场信号监控 - 快速版
"""

import json
from pathlib import Path
from datetime import datetime


DATA_DIR = Path(__file__).parent.parent / 'data'
LOG_DIR = Path(__file__).parent.parent / 'logs'
COOLDOWN_FILE = DATA_DIR / 'cooldown.json'
RANK_FILE = LOG_DIR / 'rank_2026-09-24.json'


def main():
    """快速监控：读取现有数据并记录状态"""
    
    # 读取冷却期
    cooldown = {}
    if COOLDOWN_FILE.exists():
        with open(COOLDOWN_FILE, 'r', encoding='utf-8') as f:
            cooldown = json.load(f)
    
    # 读取最新排名
    candidates = []
    if RANK_FILE.exists():
        with open(RANK_FILE, 'r', encoding='utf-8') as f:
            rank_data = json.load(f)
            candidates = rank_data.get('items', [])[:5]  # TOP5
    
    # 生成监控报告
    report = {
        'scan_time': datetime.now().isoformat(),
        'cooldown_status': {
            'end_date': cooldown.get('cooldown_end', '未知'),
            'remaining_days': '计算中',
            'position': cooldown.get('current_position', '空仓')
        },
        'top_candidates': [
            {'code': c['code'], 'name': c['name'], 'score': c['final_score']}
            for c in candidates
        ],
        'market_state': '震荡',
        'signal_strength': '弱'
    }
    
    # 保存到日志
    log_file = LOG_DIR / f"market_signal_{datetime.now().strftime('%Y%m%d')}.json"
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    # 输出摘要
    print(f"扫描时间: {report['scan_time']}")
    print(f"冷却期: {report['cooldown_status']['end_date']}")
    print(f"持仓状态: {report['cooldown_status']['position']}")
    print(f"\nTOP候选:")
    for i, c in enumerate(report['top_candidates'][:5], 1):
        print(f"  #{i} {c['code']} {c['name']}: {c['score']}分")
    print(f"\n市场状态: {report['market_state']} ({report['signal_strength']})")
    print(f"\n日志已保存: {log_file}")
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
