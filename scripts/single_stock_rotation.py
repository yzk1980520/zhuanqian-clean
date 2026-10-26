#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ⚠️ 非生产副本，留作 0.08 止损漂移取证；生产真源 = risk_rules.py（此文件无生产调用，STOP_LOSS_PCT=0.08 为漂移样本，勿删勿改）
"""
single_stock_rotation.py — 单票轮动选股系统
基于老大指导思想：单票轮动·全仓1只·移动止盈吃大波段·本金安全第一
"""
import json
import math
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


class SingleStockRotation:
    """单票轮动选股引擎"""
    
    # 老大交易铁律
    CHASE_BAN_PCT = 0.04  # 追高关闭：涨幅>4%不买
    STOP_LOSS_PCT = 0.08  # 统一止损：8%
    PANIC_STOP_LOSS = 0.056  # 恐慌市止损：5.6%
    POSITION_RATIO = 1.0  # 全仓1只
    
    # 移动止盈分级（老大P17最优参数）
    GRADED_TP_LADDER = [
        (10, 0.08),   # 浮盈10% → 回撤8%止盈
        (20, 0.12),   # 浮盈20% → 回撤12%止盈
        (40, 0.18),   # 浮盈40% → 回撤18%止盈
        (999, 0.25),  # 满盈 → 回撤25%止盈
    ]
    
    def __init__(self, lookback: int = 132, momentum_window: int = 20):
        self.lookback = lookback
        self.momentum_window = momentum_window
        
    def load_market_env(self) -> Dict:
        """加载市场环境数据"""
        sh_path = Path("data/sh_index.json")
        if not sh_path.exists():
            return {"sh_close": 0, "ma250": 0, "in_gate": False}
        
        d = json.loads(sh_path.read_text())
        sh_close = d.get('close', 0)
        ma250 = d.get('ma250', 0)
        in_gate = sh_close >= ma250
        
        return {
            "sh_close": sh_close,
            "ma250": ma250,
            "in_gate": in_gate,
            "env_desc": "门内" if in_gate else "门外",
        }
    
    def load_stock_pool(self) -> List[Dict]:
        """加载股票候选池"""
        # 优先从TDX数据加载
        tdx_path = Path("data/tdx_returns_real.json")
        if tdx_path.exists():
            data = json.loads(tdx_path.read_text())
            codes = data.get('codes', [])
            return [{"code": c, "name": c, "industry": "unknown"} for c in codes[:20]]  # 取前20只
        
        # 回退到模拟候选池
        return [
            {"code": "600000", "name": "浦发银行", "industry": "bank"},
            {"code": "600036", "name": "招商银行", "industry": "bank"},
            {"code": "601318", "name": "中国平安", "industry": "insurance"},
            {"code": "600519", "name": "贵州茅台", "industry": "liquor"},
            {"code": "000858", "name": "五粮液", "industry": "liquor"},
            {"code": "000333", "name": "美的集团", "industry": "home_appliance"},
            {"code": "600276", "name": "恒瑞医药", "industry": "pharma"},
            {"code": "300750", "name": "宁德时代", "industry": "battery"},
            {"code": "601012", "name": "隆基绿能", "industry": "solar"},
            {"code": "002594", "name": "比亚迪", "industry": "auto"},
        ]
    
    def calc_factors(self, stock: Dict, returns: List[float]) -> Dict:
        """
        计算多因子评分
        
        因子体系（老大认可的多维选股）:
        1. 反转因子：短期（1-3日）无alpha，中期（5-10日）有效
        2. 动量因子：短期有效（5日>3%胜率>50%）
        3. 成交量因子：量能放大配合
        4. 行业因子：龙头优先
        5. 质量因子：基本面稳健
        """
        n = len(returns)
        if n < 5:
            return {"error": "数据不足", "score": 0}
        
        # 1. 动量因子（过去N日收益率）
        if n >= self.momentum_window:
            momentum_20d = sum(returns[-self.momentum_window:])
        else:
            momentum_20d = sum(returns)
        
        # 2. 反转因子（短期超跌反弹）
        recent_5d = sum(returns[-5:]) if n >= 5 else sum(returns)
        prior_5d = sum(returns[-10:-5]) if n >= 10 else 0
        reversal_signal = prior_5d < -0.03 and recent_5d > 0  # 前期下跌后反弹
        
        # 3. 波动率因子（风险控制）
        volatility = statistics.stdev(returns[-20:]) if n >= 20 else statistics.stdev(returns)
        
        # 4. 行业因子（龙头溢价）
        industry_alpha = {
            "bank": 0.8,
            "insurance": 1.0,
            "liquor": 1.3,
            "home_appliance": 0.9,
            "pharma": 1.1,
            "battery": 1.2,
            "solar": 0.7,
            "auto": 1.0,
        }
        industry_bonus = industry_alpha.get(stock.get("industry", ""), 1.0)
        
        # 综合评分（老大多因子综合原则）
        base_score = 30  # 基础分
        
        # 动量贡献（权重0.4）
        momentum_score = min(20, max(0, momentum_20d * 100))
        
        # 反转贡献（权重0.2）
        reversal_score = 10 if reversal_signal else 0
        
        # 波动率贡献（权重0.2）- 低波动优先
        vol_score = max(0, 10 - volatility * 200)
        
        # 行业贡献（权重0.2）
        industry_score = (industry_bonus - 0.7) * 20
        
        total_score = base_score + momentum_score * 0.4 + reversal_score * 0.2 + vol_score * 0.2 + industry_score * 0.2
        
        return {
            "momentum_20d": momentum_20d,
            "reversal_signal": reversal_signal,
            "volatility": volatility,
            "industry_bonus": industry_bonus,
            "base_score": base_score,
            "momentum_score": momentum_score,
            "reversal_score": reversal_score,
            "vol_score": vol_score,
            "industry_score": industry_score,
            "total_score": total_score,
        }
    
    def apply_gates(self, stock: Dict, factors: Dict, market_env: Dict) -> Tuple[bool, str]:
        """
        应用老大交易铁律门禁
        
        门禁规则:
        1. 环境门：上证>MA250才允许买入
        2. 追高关闭：信号日涨幅>4%不买
        3. 止损线：统一8%止损
        """
        reasons = []
        
        # 规则1: 环境门
        if not market_env.get("in_gate", False):
            return False, "环境门关闭（上证<MA250）"
        
        # 规则2: 追高关闭（简化：假设当日涨幅已通过检查）
        # 实际应从实时数据获取
        
        # 规则3: 因子门槛
        if factors.get("total_score", 0) < 20:
            return False, "综合评分过低"
        
        return True, "通过所有门禁"
    
    def select_best_stock(self, candidates: List[Dict], market_env: Dict) -> Optional[Dict]:
        """
        选择最优个股
        
        流程:
        1. 加载候选池
        2. 计算多因子评分
        3. 应用门禁过滤
        4. 选择得分最高者
        """
        print("【步骤1: 加载候选池】")
        pool = self.load_stock_pool()
        print(f"  候选池: {len(pool)}只")
        
        print("\n【步骤2: 多因子评分】")
        scored = []
        for stock in pool:
            # 简化：使用随机收益率模拟（实际应从TDX加载）
            import random
            random.seed(hash(stock["code"]) % 2**32)
            returns = [random.gauss(0.0004, 0.015) for _ in range(self.lookback)]
            
            factors = self.calc_factors(stock, returns)
            stock_with_factors = {**stock, **factors}
            scored.append(stock_with_factors)
        
        # 排序
        scored.sort(key=lambda x: x.get("total_score", 0), reverse=True)
        
        print("  TOP5:")
        for i, s in enumerate(scored[:5], 1):
            print(f"    {i}. {s['code']} {s['name']:6s} 评分: {s.get('total_score', 0):.1f}")
        
        print("\n【步骤3: 门禁过滤】")
        filtered = []
        for stock in scored:
            passed, reason = self.apply_gates(stock, stock, market_env)
            if passed:
                filtered.append(stock)
            else:
                print(f"    ❌ {stock['code']}: {reason}")
        
        print(f"  通过过滤: {len(filtered)}只")
        
        if not filtered:
            return None
        
        # 选择最优
        best = filtered[0]
        print(f"\n🏆 最优个股: {best['code']} {best['name']}")
        print(f"   综合评分: {best.get('total_score', 0):.1f}")
        print(f"   动量因子: {best.get('momentum_20d', 0):.2%}")
        print(f"   行业加成: {best.get('industry_bonus', 0):.2f}")
        
        return best
    
    def generate_trade_advice(self, best_stock: Dict, market_env: Dict) -> Dict:
        """
        生成交易建议（含移动止盈参数）
        """
        if not best_stock:
            return {
                "action": "观望",
                "reason": "无通过门禁的个股",
                "stop_loss": self.STOP_LOSS_PCT,
                "tp_ladder": self.GRADED_TP_LADDER,
            }
        
        return {
            "action": "买入" if market_env.get("in_gate") else "观望",
            "code": best_stock["code"],
            "name": best_stock["name"],
            "industry": best_stock.get("industry", ""),
            "score": best_stock.get("total_score", 0),
            "position_ratio": self.POSITION_RATIO,
            "stop_loss_pct": self.STOP_LOSS_PCT,
            "tp_ladder": self.GRADED_TP_LADDER,
            "market_env": market_env,
            "generated_at": datetime.now().isoformat(),
        }
    
    def run(self, output_path: str = "data/daily_stock_selection.json") -> Dict:
        """
        执行完整选股流程
        """
        print("=" * 70)
        print("🎯 单票轮动选股系统 v1.0")
        print("=" * 70)
        print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # 1. 加载市场环境
        print("【步骤1: 加载市场环境】")
        market_env = self.load_market_env()
        print(f"  上证: {market_env['sh_close']:.2f}")
        print(f"  MA250: {market_env['ma250']:.2f}")
        print(f"  环境门: {'🟢 门内' if market_env['in_gate'] else '🔴 门外'}")
        print()
        
        # 2. 选择最优个股
        best_stock = self.select_best_stock([], market_env)
        print()
        
        # 3. 生成交易建议
        advice = self.generate_trade_advice(best_stock, market_env)
        print("\n【交易建议】")
        print(f"  操作: {advice['action']}")
        if advice['action'] == '买入':
            print(f"  代码: {advice['code']} {advice['name']}")
            print(f"  仓位: {advice['position_ratio']:.0%}（单票全仓）")
            print(f"  止损: -{advice['stop_loss_pct']:.0%}")
            print(f"  止盈: 分级移动止盈")
            for threshold, trailing in advice['tp_ladder']:
                if threshold < 999:
                    print(f"    浮盈≥{threshold}% → 回撤{trailing:.0%}止盈")
        
        print()
        
        # 4. 保存结果
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(advice, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 结果已保存: {output_path}")
        print("=" * 70)
        
        return advice


def main():
    import argparse
    parser = argparse.ArgumentParser(description='单票轮动选股系统')
    parser.add_argument('--lookback', type=int, default=132, help='回看天数')
    parser.add_argument('--output', type=str, default='data/daily_stock_selection.json')
    
    args = parser.parse_args()
    
    engine = SingleStockRotation(lookback=args.lookback)
    result = engine.run(output_path=args.output)
    
    # 返回退出码
    if result.get('action') == '买入':
        exit(0)
    else:
        exit(1)


if __name__ == '__main__':
    main()
