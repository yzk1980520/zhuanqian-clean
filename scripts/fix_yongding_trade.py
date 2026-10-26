# -*- coding: utf-8 -*-
"""
修正永鼎卖出记录的价格数据
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / 'data'
TRADE_LOG = DATA_DIR / 'trade_log.json'


def fix_yongding_trade():
    """修正永鼎卖出记录的价格"""
    with open(TRADE_LOG, encoding='utf-8') as f:
        data = json.load(f)
    
    # 查找永鼎卖出记录
    for trade in data.get('trades', []):
        if '600105' in trade.get('code', '') and trade.get('action') == 'sell':
            print(f"发现永鼎卖出记录: {trade.get('trade_id')}")
            print(f"  原价格: {trade.get('price')}")
            print(f"  原金额: {trade.get('amount')}")
            
            # 修正价格
            trade['price'] = 44.86
            trade['amount'] = 22430.0
            
            print(f"  修正后价格: {trade.get('price')}")
            print(f"  修正后金额: {trade.get('amount')}")
            break
    
    # 保存
    with open(TRADE_LOG, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    


if __name__ == '__main__':
    fix_yongding_trade()
