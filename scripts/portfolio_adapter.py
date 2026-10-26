#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_adapter.py — 组合优化器与现有系统集成适配器
"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime

PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

def load_candidates():
    """加载候选池"""
    # 尝试多种格式
    for fname in ['data/picks.json', 'data/candidates.json', 'data/v5_candidates_register.json']:
        fpath = PROJECT / fname
        if not fpath.exists():
            continue
        
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 解析不同格式
        if isinstance(data, list):
            return data[:5]
        elif isinstance(data, dict):
            # 尝试candidates键
            if 'candidates' in data:
                return data['candidates'][:5]
            # 尝试register键
            if 'register' in data:
                reg = data['register']
                if isinstance(reg, list):
                    return reg[:5]
                elif isinstance(reg, dict):
                    return list(reg.values())[:5]
            # 其他键
            for key in ['picks', 'stocks', 'pool']:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val[:5]
    
    return []

def load_returns(codes, days=120):
    """加载历史收益率（TODO: 接入TDX）"""
    import random
    return [[random.gauss(0, 0.02) for _ in range(len(codes))] for _ in range(days)]

def generate_decision(portfolio):
    """生成positioner兼容决策"""
    return {
        'timestamp': datetime.now().isoformat(),
        'action': 'rebalance',
        'method': portfolio.get('method', 'risk_parity'),
        'holdings': portfolio.get('holdings', []),
        'weights': portfolio.get('weights', {}),
        'metrics': portfolio.get('metrics', {}),
        'risk_check': portfolio.get('guard', {}),
        'notes': '组合优化自动调仓'
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description='组合优化适配器')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--method', default='risk_parity', choices=['risk_parity', 'equal'])
    args = parser.parse_args()
    
    print(f"📊 组合优化适配器 v0.1")
    print(f"   方法: {args.method}")
    
    candidates = load_candidates()
    if not candidates:
        candidates = [
            {"code": "600000", "name": "浦发银行", "score": 85},
            {"code": "600036", "name": "招商银行", "score": 90},
            {"code": "601318", "name": "中国平安", "score": 88},
        ]
    
    # 确保有code/name字段
    for c in candidates:
        if 'code' not in c:
            c['code'] = c.get('symbol', 'UNKNOWN')
        if 'name' not in c:
            c['name'] = c.get('name_cn', 'UNKNOWN')
        if 'score' not in c:
            c['score'] = 80
    
    print(f"   候选数: {len(candidates)}只")
    
    codes = [c['code'] for c in candidates]
    returns = load_returns(codes)
    
    from core.pipeline.portfolio_optimizer import PortfolioOptimizer
    optimizer = PortfolioOptimizer(method=args.method)
    portfolio = optimizer.optimize(candidates, returns)
    
    decision = generate_decision(portfolio)
    
    print(f"持仓数: {len(decision['holdings'])}")
    print(f"年化波动率: {portfolio['metrics']['annual_volatility']}")
    print(f"\n持仓明细:")
    for h in decision['holdings']:
        print(f"  {h['code']} {h['name']:8s} {h['weight']:6.1%}")
    
    if portfolio['guard']['violations']:
        print(f"\n⚠️ 风控预警:")
        for v in portfolio['guard']['violations']:
            print(f"  - {v}")
    
    if not args.dry_run:
        output_path = PROJECT / "data" / "portfolio_decision.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(decision, f, indent=2, ensure_ascii=False)
        print(f"\n✅ 决策已保存: {output_path}")
    
    return decision

if __name__ == '__main__':
    main()
