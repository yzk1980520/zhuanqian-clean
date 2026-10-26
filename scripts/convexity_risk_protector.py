"""
样本外凸性风险保护器
时间：2026-10-06
编制：老五（数据回测专家）

核心功能：
1. CVaR（条件在险价值）计算
2. 压力测试模拟
3. 凸性风险检验
4. 极端场景分析
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from scipy import stats


class ConvexityRiskProtector:
    """样本外凸性风险保护器"""
    
    def __init__(self, train_returns: List[float], test_returns: List[float], 
                 confidence: float = 0.95):
        """
        初始化凸性风险保护器
        
        Args:
            train_returns: 训练集收益率序列
            test_returns: 测试集收益率序列
            confidence: 置信水平（默认95%）
        """
        self.train_returns = np.array(train_returns)
        self.test_returns = np.array(test_returns)
        self.confidence = confidence
    
    def calculate_cvar(self, returns: np.ndarray) -> Tuple[float, float]:
        """
        计算VaR和CVaR（条件在险价值）
        
        Args:
            returns: 收益率序列
        
        Returns:
            (VaR, CVaR) 都是负值表示损失
        """
        # VaR：给定置信水平下的最大损失
        var = np.percentile(returns, (1-self.confidence)*100)
        
        # CVaR：超过VaR的平均损失（尾部期望）
        cvar = returns[returns <= var].mean()
        
        return float(var), float(cvar)
    
    def stress_test(self, scenarios: Dict[str, np.ndarray]) -> Dict[str, Dict]:
        """
        压力测试：模拟极端市场环境
        
        Args:
            scenarios: 场景名称→收益率冲击向量
        
        Returns:
            各场景下的风险指标
        """
        results = {}
        
        for name, shock in scenarios.items():
            # 应用冲击
            stressed_returns = self.test_returns + shock
            
            # 计算风险指标
            var, cvar = self.calculate_cvar(stressed_returns)
            max_dd = self.calculate_max_drawdown(stressed_returns)
            worst_day = np.min(stressed_returns)
            
            results[name] = {
                'VaR': round(var, 6),
                'CVaR': round(cvar, 6),
                'max_drawdown': round(max_dd, 6),
                'worst_day': round(float(worst_day), 6)
            }
        
        return results
    
    def check_convexity_risk(self) -> Dict:
        """
        检查凸性风险（训练vs测试性能差异）
        
        Returns:
            凸性风险诊断结果
        """
        train_pf = self.calculate_pf(self.train_returns)
        test_pf = self.calculate_pf(self.test_returns)
        
        decay_ratio = test_pf / train_pf if train_pf > 0 else 0
        
        train_cvar = self.calculate_cvar(self.train_returns)[1]
        test_cvar = self.calculate_cvar(self.test_returns)[1]
        
        cvar_degradation = abs(test_cvar / train_cvar) if train_cvar != 0 else 0
        
        return {
            'train_pf': round(train_pf, 4),
            'test_pf': round(test_pf, 4),
            'decay_ratio': round(decay_ratio, 4),
            'cvar_degradation': round(cvar_degradation, 4),
            'risk_level': self._assess_risk_level(decay_ratio, cvar_degradation)
        }
    
    def calculate_max_drawdown(self, returns: np.ndarray) -> float:
        """计算最大回撤"""
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        return float(np.min(drawdown))
    
    def calculate_pf(self, returns: np.ndarray) -> float:
        """计算盈亏比（Profit Factor）"""
        gains = returns[returns > 0].sum()
        losses = abs(returns[returns < 0].sum())
        return float(gains / losses) if losses > 0 else float('inf')
    
    def _assess_risk_level(self, decay_ratio: float, cvar_deg: float) -> str:
        """评估风险等级"""
        if decay_ratio < 0.5 or cvar_deg > 2.0:
            return "CRITICAL（严重过拟合）"
        elif decay_ratio < 0.8 or cvar_deg > 1.5:
            return "WARNING（中等风险）"
        else:
            return "OK（风险可控）"
    
    def generate_protection_report(self) -> Dict:
        """生成风险保护报告"""
        train_var, train_cvar = self.calculate_cvar(self.train_returns)
        test_var, test_cvar = self.calculate_cvar(self.test_returns)
        
        convexity = self.check_convexity_risk()
        
        # 定义压力测试场景
        scenarios = {
            'market_crash': np.full(len(self.test_returns), -0.05),  # 日跌5%
            'flash_crash': np.concatenate([np.full(10, -0.15), np.full(len(self.test_returns)-10, -0.02)]),  # 闪崩
            'slow_bleed': np.linspace(0, -0.03, len(self.test_returns)),  # 缓跌
            'high_volatility': np.random.normal(0, 0.03, len(self.test_returns))  # 高波动
        }
        
        stress_results = self.stress_test(scenarios)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'train_stats': {
                'var': round(train_var, 6),
                'cvar': round(train_cvar, 6),
                'max_drawdown': round(self.calculate_max_drawdown(self.train_returns), 6),
                'pf': convexity['train_pf']
            },
            'test_stats': {
                'var': round(test_var, 6),
                'cvar': round(test_cvar, 6),
                'max_drawdown': round(self.calculate_max_drawdown(self.test_returns), 6),
                'pf': convexity['test_pf']
            },
            'convexity_risk': convexity,
            'stress_tests': stress_results,
            'recommendation': self._get_recommendation(test_cvar, convexity['risk_level'])
        }
    
    def _get_recommendation(self, test_cvar: float, risk_level: str) -> str:
        """生成建议"""
        if risk_level == "CRITICAL":
            return "🔴 禁止实盘：严重过拟合，策略不可信"
        elif risk_level == "WARNING":
            return "🟡 谨慎实盘：需加强风控（缩小仓位/降低杠杆）"
        elif test_cvar < -0.15:
            return "🟡 中风险：极端损失可达15%，建议仓位≤10%"
        elif test_cvar < -0.10:
            return "🟢 低风险：可适度实盘，仓位≤20%"
        else:
            return "🟢 风险可控：可正常实盘"


def main():
    """主函数：执行凸性风险分析"""
    print('='*70)
    print('  样本外凸性风险保护器 v1.0')
    print('='*70)
    print()
    
    # 使用模拟数据（实际应从回测结果加载）
    np.random.seed(42)
    
    # 模拟训练集和测试集收益率
    train_returns = np.random.normal(0.001, 0.02, 500)  # 训练集
    test_returns = np.random.normal(0.0008, 0.025, 100)  # 测试集（略有退化）
    
    # 创建保护器
    protector = ConvexityRiskProtector(train_returns, test_returns)
    
    # 生成报告
    report = protector.generate_protection_report()
    
    # 输出结果
    print("【训练集统计】")
    print(f"  VaR (95%): {report['train_stats']['var']:.2%}")
    print(f"  CVaR: {report['train_stats']['cvar']:.2%}")
    print(f"  最大回撤: {report['train_stats']['max_drawdown']:.2%}")
    print(f"  盈亏比: {report['train_stats']['pf']:.2f}")
    print()
    
    print("【测试集统计】")
    print(f"  VaR (95%): {report['test_stats']['var']:.2%}")
    print(f"  CVaR: {report['test_stats']['cvar']:.2%}")
    print(f"  最大回撤: {report['test_stats']['max_drawdown']:.2%}")
    print(f"  盈亏比: {report['test_stats']['pf']:.2f}")
    print()
    
    print("【凸性风险诊断】")
    print(f"  衰减比: {report['convexity_risk']['decay_ratio']:.2%}")
    print(f"  CVaR退化: {report['convexity_risk']['cvar_degradation']:.2f}x")
    print(f"  风险等级: {report['convexity_risk']['risk_level']}")
    print()
    
    print("【压力测试结果】")
    for scenario, results in report['stress_tests'].items():
        print(f"  {scenario:20s}: CVaR={results['CVaR']:.2%}, 最大回撤={results['max_drawdown']:.2%}")
    print()
    
    print(f"【建议】{report['recommendation']}")
    print()
    
    # 保存报告
    output_file = Path(r'D:\open code\zhuanqian\data\convexity_risk_report.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"报告已保存: {output_file}")
    print()
    print('='*70)


if __name__ == '__main__':
    main()
