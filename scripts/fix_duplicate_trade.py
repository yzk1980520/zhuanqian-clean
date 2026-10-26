# -*- coding: utf-8 -*-
"""
修正trade_log.json中的重复卖出记录
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'
TRADE_LOG = DATA_DIR / 'trade_log.json'


def remove_duplicate_sell():
    """删除重复的永鼎卖出记录"""
    with open(TRADE_LOG, encoding='utf-8') as f:
        data = json.load(f)
    
    # 找到并删除错误的重复记录
    original_count = len(data['trades'])
    data['trades'] = [
        t for t in data['trades'] 
        if not (t.get('trade_id') == 'T20260923001' and t.get('action') == 'sell')
    ]
    new_count = len(data['trades'])
    
    print(f"交易记录数: {original_count} -> {new_count}")
    
    # 保存
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    


if __name__ == '__main__':
    remove_duplicate_sell()
