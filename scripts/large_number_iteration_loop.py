"""
实盘大数迭代闭环系统
时间：2026-10-06
编制：老五（数据回测专家）

核心功能：
1. 样本量计算与统计显著性检验
2. 迭代反馈闭环
3. 置信区间动态更新
4. 大数定律验证
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from scipy import stats


class LargeNumberIterationLoop:
    """实盘大数迭代闭环系统"""
    
    def __init__(self, trades: List[Dict], confidence_level: float = 0.95):
        """
        初始化大数迭代闭环
        
        Args:
            trades: 交易记录列表
            confidence_level: 置信水平（默认95%）
        """
        self.trades = trades
        self.confidence_level = confidence_level
        
        if len(trades) < 5:
            raise ValueError(f"交易记录至少需要5笔（当前{len(trades)}笔）")
    
    def calculate_sample_size(self) -> Dict:
        """
        计算所需最小样本量
        
        Returns:
            {
              'current_n': int,
              'required_n': int,
              'is_sufficient': bool,
              'confidence_interval': Tuple[float, float]
            }
        """
        returns = [trade.get('pnl_pct', 0) / 100 for trade in self.trades]
        n = len(returns)
        
        # 计算置信区间
        mean = np.mean(returns)
        stderr = stats.sem(returns)
        t_crit = stats.t.ppf((1 + self.confidence_level) / 2, df=n-1)
        ci_lower = mean - t_crit * stderr
        ci_upper = mean + t_crit * stderr
        
        # 计算所需最小样本量（目标：CI宽度<5%）
        target_width = 0.05
        required_n = int(np.ceil((2 * t_crit * stderr / target_width) ** 2))
        required_n = max(required_n, 30)  # 最小30笔
        
        return {
            'current_n': n,
            'required_n': required_n,
            'is_sufficient': n >= required_n,
            'confidence_interval': (round(ci_lower, 6), round(ci_upper, 6)),
            'mean_return': round(mean, 6),
            'std_return': round(np.std(returns, ddof=1), 6)
        }
    
    def perform_significance_test(self) -> Dict:
        """
        执行统计显著性检验（t-test）
        
        Returns:
            {
              't_statistic': float,
              'p_value': float,
              'is_significant': bool,
              'effect_size': float  # Cohen's d
            }
        """
        returns = [trade.get('pnl_pct', 0) / 100 for trade in self.trades]
        
        # 单样本t检验（检验均值是否显著大于0）
        t_stat, p_value = stats.ttest_1samp(returns, 0)
        
        # 计算效应量（Cohen's d）
        mean = np.mean(returns)
        std = np.std(returns, ddof=1)
        effect_size = mean / std if std > 0 else 0
        
        return {
            't_statistic': round(float(t_stat), 4),
            'p_value': round(float(p_value), 6),
            'is_significant': bool(p_value < (1 - self.confidence_level)),
            'effect_size': round(float(effect_size), 4),
            'interpretation': self._interpret_result(p_value, effect_size)
        }
    
    def calculate_convergence(self) -> Dict:
        """
        计算收敛性（大数定律验证）
        
        Returns:
            {
              'convergence_rate': float,
              'stable_since': str,
              'fluctuation': float
            }
        """
        returns = [trade.get('pnl_pct', 0) / 100 for trade in self.trades]
        
        # 计算滚动均值
        rolling_means = []
        window = min(10, len(returns))
        for i in range(window, len(returns)):
            rolling_means.append(np.mean(returns[i-window:i]))
        
        if len(rolling_means) < 5:
            return {
                'convergence_rate': 0.0,
                'stable_since': 'N/A',
                'fluctuation': 0.0
            }
        
        # 计算收敛速率（最后5个rolling mean的方差）
        recent = rolling_means[-5:]
        variance = np.var(recent)
        
        # 计算稳定时间（最后连续稳定的交易号）
        stable_idx = len(returns)
        for i in range(len(rolling_means)-1, max(0, len(rolling_means)-10), -1):
            if abs(rolling_means[i] - rolling_means[i-1]) > 0.01:
                stable_idx = i + window
                break
        
        # 安全获取日期字段
        try:
            stable_date = self.trades[stable_idx-1].get('date', 'N/A') if stable_idx > 0 and stable_idx <= len(self.trades) else 'N/A'
        except (IndexError, AttributeError):
            stable_date = 'N/A'
        
        return {
            'convergence_rate': round(float(variance), 8),
            'stable_since_trade': stable_idx,
            'stable_since_date': stable_date,
            'fluctuation': round(float(np.std(recent)), 6),
            'latest_mean': round(float(rolling_means[-1]), 6)
        }
    
    def build_feedback_loop(self) -> Dict:
        """
        构建闭环反馈机制
        
        Returns:
            {
              'feedback_cycle': str,
              'next_action': str,
              'monitoring_points': List[str]
            }
        """
        sample_info = self.calculate_sample_size()
        sig_test = self.perform_significance_test()
        
        # 确定下一步行动
        if not sample_info['is_sufficient']:
            next_action = f"继续积累样本（当前{sample_info['current_n']}笔，需{sample_info['required_n']}笔）"
        elif sig_test['is_significant']:
            next_action = "统计显著，可进入下一阶段验证"
        else:
            next_action = "统计不显著，需优化策略或等待更多样本"
        
        # 监控要点
        monitoring_points = [
            "交易笔数达到50笔",
            "日均收益置信区间上界>0",
            "夏普比率>0.5",
            "最大回撤<20%",
            "IC衰减率<10%"
        ]
        
        return {
            'feedback_cycle': '样本收集→统计检验→策略优化→再验证',
            'next_action': next_action,
            'sample_status': sample_info,
            'significance_test': sig_test,
            'monitoring_points': monitoring_points
        }
    
    def _interpret_result(self, p_value: float, effect_size: float) -> str:
        """解释检验结果"""
        if p_value < 0.01:
            sig_level = "极显著（p<0.01）"
        elif p_value < 0.05:
            sig_level = "显著（p<0.05）"
        else:
            sig_level = "不显著（p≥0.05）"
        
        if abs(effect_size) >= 0.8:
            eff_level = "大效应"
        elif abs(effect_size) >= 0.5:
            eff_level = "中等效应"
        elif abs(effect_size) >= 0.2:
            eff_level = "小效应"
        else:
            eff_level = "微弱效应"
        
        return f"{sig_level}，{eff_level}"
    
    def generate_report(self) -> Dict:
        """生成大数迭代闭环报告"""
        sample_info = self.calculate_sample_size()
        sig_test = self.perform_significance_test()
        convergence = self.calculate_convergence()
        feedback = self.build_feedback_loop()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'sample_analysis': sample_info,
            'significance_test': sig_test,
            'convergence': convergence,
            'feedback_loop': feedback,
            'summary': self._generate_summary(sample_info, sig_test, convergence)
        }
    
    def _generate_summary(self, sample: Dict, sig: Dict, conv: Dict) -> str:
        """生成摘要"""
        lines = []
        lines.append(f"【样本状态】当前{sample['current_n']}笔{'✅达标' if sample['is_sufficient'] else '❌不足'}（需{sample['required_n']}笔）")
        lines.append(f"【显著性】p={sig['p_value']:.4f} {sig['interpretation']}")
        lines.append(f"【收敛性】方差={conv['convergence_rate']:.6f}")
        
        if sample['is_sufficient'] and sig['is_significant']:
            lines.append("✅ 满足大数定律条件，策略统计显著")
        elif sample['is_sufficient']:
            lines.append("⚠️ 样本充足但统计不显著，需优化策略")
        else:
            lines.append(f"⏳ 样本不足，还需{sample['required_n']-sample['current_n']}笔交易")
        
        return '\n'.join(lines)


def load_trades_from_signals(signals_file: Path) -> List[Dict]:
    """从交易信号文件加载交易记录"""
    with open(signals_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 尝试多种可能的格式
    if 'trade_list' in data:
        return data['trade_list']
    elif 'trades' in data:
        return data['trades']
    elif 'results' in data and isinstance(data['results'], list):
        return data['results']
    
    # 如果没有现成的，生成模拟数据用于演示
    print("警告：未找到交易记录，使用模拟数据演示")
    return generate_simulation_trades(50)


def generate_simulation_trades(n: int) -> List[Dict]:
    """生成模拟交易数据（用于演示）"""
    np.random.seed(42)
    trades = []
    
    base_date = datetime(2026, 1, 1)
    for i in range(n):
        # 模拟正态分布收益（均值1%，标准差3%）
        pnl_pct = np.random.normal(1.0, 3.0)
        trades.append({
            'id': i+1,
            'date': (base_date + timedelta(days=i*2)).strftime('%Y-%m-%d'),
            'symbol': f'SZ{np.random.randint(100000, 999999)}',
            'action': 'BUY' if i % 2 == 0 else 'SELL',
            'pnl_pct': round(pnl_pct, 2),
            'holding_days': np.random.randint(5, 30)
        })
    
    return trades


def main():
    """主函数：执行大数迭代闭环分析"""
    print('='*70)
    print('  实盘大数迭代闭环系统 v1.0')
    print('='*70)
    print()
    
    root = Path(r'D:\open code\zhuanqian')
    
    # 尝试加载真实交易数据
    trade_file = root / 'data' / 'trade_signals.json'
    
    try:
        trades = load_trades_from_signals(trade_file)
    except Exception as e:
        print(f"加载交易数据失败：{e}")
        print("使用模拟数据演示")
        trades = generate_simulation_trades(50)
    
    print(f"交易记录数: {len(trades)}笔")
    print()
    
    # 创建闭环系统
    loop = LargeNumberIterationLoop(trades)
    
    # 生成报告
    report = loop.generate_report()
    
    # 输出结果
    print(report['summary'])
    print()
    
    print("【样本分析】")
    sample = report['sample_analysis']
    print(f"  当前样本: {sample['current_n']}笔")
    print(f"  需要样本: {sample['required_n']}笔")
    print(f"  是否达标: {'✅是' if sample['is_sufficient'] else '❌否'}")
    print(f"  95%置信区间: [{sample['confidence_interval'][0]:.4f}, {sample['confidence_interval'][1]:.4f}]")
    print(f"  平均收益: {sample['mean_return']:.4f} ({sample['mean_return']*100:+.2f}%)")
    print()
    
    print("【显著性检验】")
    sig = report['significance_test']
    print(f"  t统计量: {sig['t_statistic']:.4f}")
    print(f"  p值: {sig['p_value']:.6f}")
    print(f"  是否显著: {'✅是' if sig['is_significant'] else '❌否'}")
    print(f"  效应量: {sig['effect_size']:.4f} ({sig['interpretation']})")
    print()
    
    print("【收敛性分析】")
    conv = report['convergence']
    print(f"  收敛速率: {conv['convergence_rate']:.8f}")
    print(f"  波动性: {conv['fluctuation']:.6f}")
    print(f"  最新均值: {conv['latest_mean']:.6f}")
    print()
    
    print("【反馈闭环】")
    fb = report['feedback_loop']
    print(f"  循环模式: {fb['feedback_cycle']}")
    print(f"  下一步: {fb['next_action']}")
    print()
    
    print("【监控要点】")
    for point in fb['monitoring_points']:
        print(f"  • {point}")
    print()
    
    # 保存报告
    output_file = root / 'data' / 'large_number_iteration_report.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"报告已保存: {output_file}")
    print()
    print('='*70)


if __name__ == '__main__':
    main()
