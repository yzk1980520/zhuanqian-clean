#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_portfolio_optimize.py — 组合优化全自动执行脚本

职责:
1. 从integrated_picker获取候选池
2. 从TDX获取历史收益率
3. 运行组合优化
4. 输出positioner.json格式决策
5. 写入message_queue供notification使用

用法:
  python scripts/auto_portfolio_optimize.py [--dry-run] [--method risk_parity]
"""
import sys
import os
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta

# 项目根目录
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

def load_candidates_from_picker():
    """从integrated_picker输出加载候选池"""
    # 尝试多种可能的输出位置
    candidates_paths = [
        PROJECT / "data" / "picks.json",
        PROJECT / "data" / "candidates.json",
        PROJECT / "data" / "v5_candidates_register.json",
        PROJECT / "data" / "v4_candidates_register.json",
    ]
    
    for fpath in candidates_paths:
        if not fpath.exists():
            continue
        
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 解析不同格式
        if isinstance(data, list):
            return data[:5]
        elif isinstance(data, dict):
            for key in ['candidates', 'picks', 'register', 'stocks', 'pool']:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val[:5]
                    elif isinstance(val, dict):
                        return list(val.values())[:5]
    
    return []

def load_returns_from_tdx(codes, days=120):
    """从TDX数据加载历史收益率"""
    # TODO: 接入tdx_core获取真实数据
    # 暂时返回随机数据用于测试
    import random
    
    n = len(codes)
    returns = []
    for _ in range(days):
        row = [random.gauss(0, 0.02) for _ in range(n)]
        returns.append(row)
    
    return returns

def load_returns_from_csv(csv_path):
    """从CSV文件加载收益率"""
    path = PROJECT / csv_path if not csv_path.is_absolute() else csv_path
    if not path.exists():
        return None
    
    returns = []
    with open(path, 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            try:
                returns.append([float(x) for x in row])
            except ValueError:
                print(f"⚠️ [scripts\auto_portfolio_optimize.py] 兼容处理: except ValueError:", file=sys.stderr)
    return returns if returns else None

def run_optimization(candidates, returns, method='risk_parity'):
    """运行组合优化"""
    from core.pipeline.portfolio_optimizer import PortfolioOptimizer
    
    optimizer = PortfolioOptimizer(method=method)
    return optimizer.optimize(candidates, returns)

def generate_decision(portfolio, candidates):
    """生成positioner兼容决策"""
    return {
        'timestamp': datetime.now().isoformat(),
        'action': 'rebalance',
        'method': portfolio.get('method', 'risk_parity'),
        'holdings': portfolio.get('holdings', []),
        'weights': portfolio.get('weights', {}),
        'metrics': {
            'annual_volatility': portfolio.get('metrics', {}).get('annual_volatility', 'N/A'),
            'max_weight': portfolio.get('metrics', {}).get('max_weight', 'N/A'),
            'n_holdings': len(portfolio.get('holdings', [])),
        },
        'risk_check': portfolio.get('guard', {}),
        'notes': '组合优化自动调仓',
        'auto_generated': True
    }

def write_decision(decision):
    """写入决策文件"""
    output_path = PROJECT / "data" / "portfolio_decision.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(decision, f, indent=2, ensure_ascii=False)
    return output_path

def write_to_message_queue(decision):
    """写入消息队列供notification使用"""
    mq_path = PROJECT / "data" / "message_queue.json"
    
    # 读取现有队列
    if mq_path.exists():
        with open(mq_path, 'r', encoding='utf-8') as f:
            queue = json.load(f)
    else:
        queue = []
    
    # 添加新消息
    message = {
        'type': 'portfolio_optimization',
        'timestamp': datetime.now().isoformat(),
        'data': decision,
        'priority': 'normal',
        'status': 'pending'
    }
    queue.append(message)
    
    # 写回
    with open(mq_path, 'w', encoding='utf-8') as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)
    
    return mq_path

def main():
    import argparse
    parser = argparse.ArgumentParser(description='组合优化全自动执行')
    parser.add_argument('--dry-run', action='store_true', help='仅输出不写文件')
    parser.add_argument('--method', default='risk_parity', choices=['risk_parity', 'equal'])
    parser.add_argument('--returns-csv', default=None, help='收益率CSV文件路径')
    parser.add_argument('--output', default='data/portfolio_decision.json', help='输出文件')
    args = parser.parse_args()
    
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"方法: {args.method}")
    
    # Step 1: 加载候选池
    candidates = load_candidates_from_picker()
    
    if not candidates:
        candidates = [
            {"code": "600000", "name": "浦发银行", "score": 85},
            {"code": "600036", "name": "招商银行", "score": 90},
            {"code": "601318", "name": "中国平安", "score": 88},
            {"code": "600519", "name": "贵州茅台", "score": 95},
            {"code": "000858", "name": "五粮液", "score": 82},
        ]
    
    # 确保有code/name字段
    for c in candidates:
        c.setdefault('code', 'UNKNOWN')
        c.setdefault('name', 'UNKNOWN')
        c.setdefault('score', 80)
    
    print(f"  ✅ 候选数: {len(candidates)}只")
    for c in candidates[:3]:
        print(f"     - {c['code']} {c['name']}")
    
    # Step 2: 加载收益率
    if args.returns_csv:
        returns = load_returns_from_csv(args.returns_csv)
        if returns:
            print(f"  ✅ 从CSV加载: {len(returns)}天 × {len(returns[0])}只")
        else:
            returns = [[__import__('random').gauss(0, 0.02) for _ in range(len(candidates))] for _ in range(120)]
    else:
        import random
        returns = [[random.gauss(0, 0.02) for _ in range(len(candidates))] for _ in range(120)]
        print(f"  ⚠️ 使用随机数据（TODO: 接入TDX）")
    
    # Step 3: 运行优化
    portfolio = run_optimization(candidates, returns, args.method)
    
    print(f"  ✅ 持仓数: {portfolio['n_holdings']}")
    print(f"  ✅ 年化波动率: {portfolio['metrics']['annual_volatility']}")
    
    # Step 4: 生成决策
    decision = generate_decision(portfolio, candidates)
    
    # 输出结果
    print(f"方法: {decision['method']}")
    print(f"持仓数: {decision['metrics']['n_holdings']}")
    print(f"年化波动率: {decision['metrics']['annual_volatility']}")
    print(f"\n持仓明细:")
    for h in decision['holdings']:
        print(f"  {h['code']} {h['name']:8s} {h['weight']:6.1%}")
    
    if decision['risk_check'].get('violations'):
        print(f"\n⚠️ 风控预警:")
        for v in decision['risk_check']['violations']:
            print(f"  - {v}")
    
    # 写入文件
    if not args.dry_run:
        output_path = write_decision(decision)
        print(f"\n✅ 决策已保存: {output_path}")
        
        # 写入消息队列
        mq_path = write_to_message_queue(decision)
        print(f"✅ 消息队列已更新: {mq_path}")
    else:
        pass
    
    return decision

if __name__ == '__main__':
    main()
