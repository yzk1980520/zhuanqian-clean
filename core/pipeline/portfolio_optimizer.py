#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_optimizer.py - 御龙决组合优化引擎 v0.3（纯Python版）

核心功能:
1. 风险平价分配 (RiskParity)
2. 协方差矩阵估计（样本协方差）
3. 约束检查与修正 (PortfolioGuard)
4. CLI入口

依赖: 仅标准库（无numpy/scipy/sklearn）

用法:
  python portfolio_optimizer.py --candidates data/candidates.json
  python portfolio_optimizer.py --help
"""
import sys
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import argparse
import math
import random
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple


class Matrix:
    """简单矩阵类（替代numpy）"""
    
    def __init__(self, data: List[List[float]]):
        self.data = data
        self.rows = len(data)
        self.cols = len(data[0]) if self.rows > 0 else 0
    
    @staticmethod
    def identity(n: int):
        return Matrix([[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)])
    
    def transpose(self) -> 'Matrix':
        return Matrix([[self.data[j][i] for j in range(self.rows)] for i in range(self.cols)])
    
    def __matmul__(self, other: 'Matrix') -> 'Matrix':
        assert self.cols == other.rows, "维度不匹配"
        result = [[0.0] * other.cols for _ in range(self.rows)]
        for i in range(self.rows):
            for j in range(other.cols):
                s = 0.0
                for k in range(self.cols):
                    s += self.data[i][k] * other.data[k][j]
                result[i][j] = s
        return Matrix(result)
    
    def trace(self) -> float:
        return sum(self.data[i][i] for i in range(min(self.rows, self.cols)))
    
    def frobenius_norm(self) -> float:
        return math.sqrt(sum(x*x for row in self.data for x in row))


def mat_covariance(returns: List[List[float]]) -> Matrix:
    """计算协方差矩阵"""
    if not returns:
        return Matrix([])
    
    n = len(returns[0])
    T = len(returns)
    
    means = [0.0] * n
    for t in range(T):
        for i in range(n):
            means[i] += returns[t][i]
    means = [m / T for m in means]
    
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            s = 0.0
            for t in range(T):
                s += (returns[t][i] - means[i]) * (returns[t][j] - means[j])
            cov[i][j] = s / (T - 1)
    
    for i in range(n):
        if cov[i][i] < 1e-8:
            cov[i][i] = 1e-6
    
    return Matrix(cov)


def mat_vec_mul(mat: Matrix, vec: List[float]) -> List[float]:
    return [sum(mat.data[i][j] * vec[j] for j in range(len(vec))) for i in range(mat.rows)]


def vec_dot(v1: List[float], v2: List[float]) -> float:
    return sum(a*b for a, b in zip(v1, v2))


def optimize_risk_parity(cov: Matrix, n: int, max_weight: float = 0.20, min_weight: float = 0.05, max_iter: int = 1000) -> List[float]:
    """风险平价优化（简化版梯度下降）"""
    w = [1.0 / n] * n
    lr = 0.01
    
    for iteration in range(max_iter):
        wp = mat_vec_mul(cov, w)
        sigma = math.sqrt(vec_dot(w, wp))
        
        if sigma < 1e-12:
            break
        
        rc = [w[i] * wp[i] / sigma for i in range(n)]
        
        gradient = [0.0] * n
        for i in range(n):
            gradient[i] = rc[i] - rc[i] * wp[i] / (sigma * sigma) * w[i]
        
        w = [w[i] - lr * gradient[i] for i in range(n)]
        w = [max(min_weight, min(max_weight, wi)) for wi in w]
        s = sum(w)
        if s > 0:
            w = [wi / s for wi in w]
    
    return w


class CovarianceEstimator:
    def __init__(self, lookback: int = 120):
        self.lookback = lookback
    
    def estimate(self, returns: List[List[float]]) -> Matrix:
        recent = returns[-self.lookback:] if len(returns) > self.lookback else returns
        return mat_covariance(recent)


class PortfolioGuard:
    def __init__(self, max_single: float = 0.20, min_holdings: int = 3, max_holdings: int = 5):
        self.max_single = max_single
        self.min_holdings = min_holdings
        self.max_holdings = max_holdings
    
    def check(self, weights: List[float], names: List[str]) -> Dict:
        violations = []
        warnings = []
        
        max_idx = weights.index(max(weights))
        max_w = max(weights)
        if max_w > self.max_single:
            violations.append(f"单票超限: {names[max_idx]} {max_w:.1%} > {self.max_single:.0%}")
        
        n_holdings = sum(1 for w in weights if w > 0.01)
        if n_holdings < self.min_holdings:
            warnings.append(f"持仓过少: {n_holdings} < {self.min_holdings}")
        elif n_holdings > self.max_holdings:
            warnings.append(f"持仓过多: {n_holdings} > {self.max_holdings}")
        
        return {'violations': violations, 'warnings': warnings, 'passed': len(violations) == 0}
    
    def correct(self, weights: List[float], names: List[str]) -> Tuple[List[float], List[str]]:
        corrections = []
        
        for i, w in enumerate(weights):
            if w > self.max_single:
                weights[i] = self.max_single
                corrections.append(f"裁剪{names[i]}: {w:.1%}→{self.max_single:.0%}")
        
        s = sum(weights)
        if s > 0:
            weights = [w/s for w in weights]
        
        sorted_indices = sorted(range(len(weights)), key=lambda i: -weights[i])
        if sum(1 for w in weights if w > 0.01) < self.min_holdings:
            for idx in sorted_indices:
                if weights[idx] < 0.01:
                    weights[idx] = 0.01
                    corrections.append(f"补充{names[idx]}: 0→1%")
                    if sum(1 for w in weights if w > 0.01) >= self.min_holdings:
                        break
        
        s = sum(weights)
        if s > 0:
            weights = [w/s for w in weights]
        
        return weights, corrections


class PortfolioOptimizer:
    def __init__(self, lookback: int = 120, method: str = 'risk_parity'):
        self.lookback = lookback
        self.method = method
        self.guard = PortfolioGuard()
    
    def optimize(self, candidates: List[Dict], returns: List[List[float]]) -> Dict:
        n = len(candidates)
        codes = [c['code'] for c in candidates]
        names = [c['name'] for c in candidates]
        
        cov = CovarianceEstimator(self.lookback).estimate(returns)
        
        if self.method == 'risk_parity':
            weights = optimize_risk_parity(cov, n)
        else:
            weights = [1.0/n] * n
        
        guard_result = self.guard.check(weights, names)
        if not guard_result['passed']:
            weights, corrections = self.guard.correct(weights, names)
            guard_result['corrections'] = corrections
        
        wp = mat_vec_mul(cov, weights)
        port_vol = math.sqrt(vec_dot(weights, wp))
        port_annual_vol = port_vol * math.sqrt(252)
        
        portfolio = {
            'timestamp': datetime.now().isoformat(),
            'method': self.method,
            'lookback': self.lookback,
            'n_candidates': n,
            'n_holdings': sum(1 for w in weights if w > 0.01),
            'holdings': [],
            'weights': {code: round(w, 4) for code, w in zip(codes, weights)},
            'metrics': {
                'annual_volatility': f"{port_annual_vol:.2%}",
                'max_weight': f"{max(weights):.2%}",
                'min_weight': f"{min(w for w in weights if w > 0):.2%}" if any(w > 0 for w in weights) else "N/A"
            },
            'guard': guard_result
        }
        
        for i, (code, weight) in enumerate(zip(codes, weights)):
            if weight > 0.01:
                portfolio['holdings'].append({
                    'code': code,
                    'name': names[i],
                    'weight': round(weight, 4),
                    'score': candidates[i].get('score', 0)
                })
        
        portfolio['holdings'].sort(key=lambda x: -x['weight'])
        return portfolio


def main():
    parser = argparse.ArgumentParser(description='御龙决组合优化引擎（纯Python版）')
    parser.add_argument('--candidates', '-c', required=True, help='候选股票JSON文件')
    parser.add_argument('--returns', '-r', default=None, help='历史收益率CSV文件')
    parser.add_argument('--output', '-o', default='data/portfolio.json', help='输出文件')
    parser.add_argument('--method', '-m', choices=['risk_parity', 'equal'], default='risk_parity')
    parser.add_argument('--lookback', '-l', type=int, default=120, help='滚动窗口')
    parser.add_argument('--dry-run', action='store_true', help='仅输出建议')
    args = parser.parse_args()
    
    with open(args.candidates, 'r', encoding='utf-8') as f:
        candidates = json.load(f)
    
    
    if args.returns:
        with open(args.returns, 'r') as f:
            reader = csv.reader(f)
            returns = [[float(x) for x in row] for row in reader]
    else:
        n = len(candidates)
        returns = [[random.gauss(0, 0.02) for _ in range(n)] for _ in range(120)]
    
    optimizer = PortfolioOptimizer(lookback=args.lookback, method=args.method)
    portfolio = optimizer.optimize(candidates, returns)
    
    for h in portfolio['holdings']:
        print(f"  {h['code']}: {h['weight']:.2%}")

    if portfolio['guard']['violations']:
        for v in portfolio['guard']['violations']:
            print(f"  ⚠️  违规: {v}")

    if portfolio['guard']['warnings']:
        for w in portfolio['guard']['warnings']:
            print(f"  ⚠️  警告: {w}")
    
    if not args.dry_run:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
    
    return portfolio


if __name__ == '__main__':
    main()
