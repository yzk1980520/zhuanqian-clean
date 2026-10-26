# -*- coding: utf-8 -*-
"""
手动交易记录合并脚本
将manual_trade_*.json合并到trade_log.json
"""

import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent / 'data'
TRADE_LOG = DATA_DIR / 'trade_log.json'
MANUAL_PATTERN = 'manual_trade_*.json'


def load_trade_log():
    """加载交易记录"""
    with open(TRADE_LOG, encoding='utf-8') as f:
        return json.load(f)


def save_trade_log(data):
    """保存交易记录"""
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_manual_trades():
    """查找所有手动交易记录"""
    import glob
    pattern = str(DATA_DIR / MANUAL_PATTERN)
    return sorted(glob.glob(pattern))


def merge_manual_trade(manual_file, trade_log):
    """合并单个手动交易记录"""
    with open(manual_file, encoding='utf-8') as f:
        manual = json.load(f)
    
    # 检查是否已存在
    trade_id = manual.get('trade_id')
    for existing in trade_log['trades']:
        if existing.get('trade_id') == trade_id:
            return False
    
    # 添加source标记
    manual['source'] = 'manual_merge'
    trade_log['trades'].append(manual)
    
    # 更新时间戳
    trade_log['last_updated'] = datetime.now().isoformat()
    
    return True


def main():
    
    # 加载当前交易记录
    trade_log = load_trade_log()
    
    # 查找手动交易文件
    manual_files = find_manual_trades()
    
    if not manual_files:
        return
    
    # 逐个合并
    merged = 0
    skipped = 0
    for mf in manual_files:
        try:
            if merge_manual_trade(mf, trade_log):
                merged += 1
            else:
                skipped += 1
        except Exception as e:
            skipped += 1
    
    # 保存
    save_trade_log(trade_log)
    


if __name__ == '__main__':
    main()
