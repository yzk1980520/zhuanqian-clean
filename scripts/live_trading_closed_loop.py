"""
实盘大数迭代闭环 - 跃迁⑤实现
功能：
1. 每日实盘数据收集（交易+持仓+收益）
2. 损失梯度计算（实盘vs回测偏差）
3. 自动策略参数更新
4. 大数定律验证（交易次数统计）
"""
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

class LiveTradingClosedLoop:
    """实盘大数迭代闭环"""
    
    def __init__(self, learning_rate=0.1, min_trades_for_stats=100):
        self.learning_rate = learning_rate
        self.min_trades_for_stats = min_trades_for_stats
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.audit_dir = Path(__file__).parent.parent / 'data' / 'audit'
        self.iteration_count = 0
        self.history = []
    
    def collect_live_data(self) -> Dict:
        """收集实盘数据"""
        data = {
            'timestamp': datetime.now().isoformat(),
            'trades': [],
            'holdings': None,
            'daily_returns': [],
            'total_assets': 0,
            'available_cash': 0
        }
        
        # 加载交易记录
        trade_log = self.data_dir / 'trade_log.json'
        if trade_log.exists():
            with open(trade_log, 'r', encoding='utf-8') as f:
                trade_data = json.load(f)
                data['trades'] = trade_data.get('trades', [])
                data['total_trades'] = len(data['trades'])
        
        # 加载持仓
        holdings = self.data_dir / 'holdings.json'
        if holdings.exists():
            with open(holdings, 'r', encoding='utf-8') as f:
                data['holdings'] = json.load(f)
                data['total_assets'] = data['holdings'].get('total_assets', 0)
                data['available_cash'] = data['holdings'].get('available_cash', 0)
        
        # 计算每日收益
        data['daily_returns'] = self._calculate_daily_returns(data['trades'])
        
        return data
    
    def _calculate_daily_returns(self, trades: List[Dict]) -> List[float]:
        """计算每日收益率"""
        if not trades:
            return []
        
        # 按日期分组盈亏
        daily_pnl = {}
        for trade in trades:
            date = trade.get('date', '')
            pnl = trade.get('pnl', 0)
            if date not in daily_pnl:
                daily_pnl[date] = 0
            daily_pnl[date] += pnl
        
        # 转换为收益率（假设初始资金22000元）
        initial_capital = 22000
        returns = []
        cumulative = initial_capital
        for date in sorted(daily_pnl.keys()):
            cumulative += daily_pnl[date]
            daily_return = daily_pnl[date] / cumulative
            returns.append(daily_return)
        
        return returns[-30:] if len(returns) > 30 else returns
    
    def calculate_gradient(self, live_data: Dict, backtest_data: Dict) -> Dict:
        """计算损失梯度"""
        # 空仓保护
        daily_returns = live_data.get('daily_returns', [])
        if len(daily_returns) < 10:
            return {
                'live_sharpe': 0.0,
                'backtest_sharpe': backtest_data.get('sharpe', 0),
                'deviation': 0.0,
                'needs_update': False,
                'reason': '交易数据不足，跳过更新',
                'trade_count': len(daily_returns)
            }
        
        # 实盘夏普比率
        live_sharpe = self._calculate_sharpe(daily_returns)
        
        # 回测夏普比率（从历史数据获取）
        bt_sharpe = backtest_data.get('sharpe', 2.58)
        
        # 偏差
        deviation = live_sharpe - bt_sharpe
        
        # 损失函数（均方误差）
        loss = deviation ** 2
        
        # 梯度
        gradient = 2 * deviation
        
        return {
            'live_sharpe': round(live_sharpe, 4),
            'backtest_sharpe': bt_sharpe,
            'deviation': round(deviation, 4),
            'loss': round(loss, 6),
            'gradient': round(gradient, 6),
            'needs_update': abs(deviation) > 0.1  # 偏差>10%才更新
        }
    
    def update_strategy(self, gradient: float, current_params: Dict) -> Dict:
        """更新策略参数"""
        updated_params = current_params.copy()
        
        # 参数更新规则（简化版）
        if gradient < -0.05:  # 实盘表现显著差于回测
            # 降低风险偏好
            updated_params['position_ratio'] = max(0.3, current_params.get('position_ratio', 0.5) - 0.1)
            updated_params['stop_loss_pct'] = min(0.15, current_params.get('stop_loss_pct', 0.08) + 0.02)
            update_reason = "实盘表现差，降低风险偏好"
        elif gradient > 0.05:  # 实盘表现优于回测
            # 提高风险偏好
            updated_params['position_ratio'] = min(0.7, current_params.get('position_ratio', 0.5) + 0.05)
            update_reason = "实盘表现优，适度提升仓位"
        else:
            update_reason = "偏差在正常范围，保持参数不变"
        
        return {
            'updated_params': updated_params,
            'update_reason': update_reason,
            'iteration': self.iteration_count
        }
    
    def _calculate_sharpe(self, returns: List[float]) -> float:
        """计算夏普比率"""
        if not returns or len(returns) < 10:
            return 0.0
        
        arr = np.array(returns)
        if np.std(arr) == 0:
            return 0.0
        
        sharpe = np.mean(arr) / np.std(arr) * np.sqrt(252)
        return float(sharpe)
    
    def validate_large_number(self, trades: List[Dict]) -> Dict:
        """大数定律验证"""
        if len(trades) < self.min_trades_for_stats:
            return {
                'valid': False,
                'current_count': len(trades),
                'required_count': self.min_trades_for_stats,
                'progress': round(len(trades) / self.min_trades_for_stats * 100, 1),
                'message': f"交易次数不足，当前{len(trades)}笔，需要{self.min_trades_for_stats}笔"
            }
        
        # 计算统计显著性
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        win_rate = wins / len(trades)
        
        # 标准误差
        se = np.sqrt(win_rate * (1 - win_rate) / len(trades))
        
        # 95%置信区间
        ci_lower = win_rate - 1.96 * se
        ci_upper = win_rate + 1.96 * se
        
        return {
            'valid': True,
            'current_count': len(trades),
            'win_rate': round(win_rate, 4),
            'std_error': round(se, 4),
            'confidence_interval_95': [round(ci_lower, 4), round(ci_upper, 4)],
            'message': f"大数定律生效，胜率{win_rate*100:.1f}%±{se*100:.1f}%"
        }
    
    def generate_report(self) -> Dict:
        """生成迭代闭环报告"""
        # 收集数据
        print("📊 收集实盘数据...")
        live_data = self.collect_live_data()
        
        # 加载回测基准
        backtest_file = self.data_dir / 'audit' / 'backtest-validation-summary_20261003.json'
        if backtest_file.exists():
            with open(backtest_file, 'r', encoding='utf-8') as f:
                backtest_data = json.load(f)
        else:
            backtest_data = {'sharpe': 2.58}
        
        print(f"📈 实盘交易数: {live_data.get('total_trades', 0)}笔")
        print(f"💰 总资产: {live_data.get('total_assets', 0):.2f}元")
        
        # 计算梯度
        print("\n🧮 计算损失梯度...")
        gradient_info = self.calculate_gradient(live_data, backtest_data)
        
        print(f"实盘Sharpe: {gradient_info['live_sharpe']:.4f}")
        print(f"回测Sharpe: {gradient_info['backtest_sharpe']:.4f}")
        print(f"偏差: {gradient_info['deviation']:.4f}")
        print(f"需要更新: {'是' if gradient_info['needs_update'] else '否'}")
        
        # 大数验证
        print("\n📊 大数定律验证...")
        large_number_check = self.validate_large_number(live_data.get('trades', []))
        print(f"交易次数: {large_number_check['current_count']}")
        print(f"状态: {'✅ 大数生效' if large_number_check['valid'] else '⏳ 等待更多交易'}")
        
        # 生成报告
        report = {
            'timestamp': datetime.now().isoformat(),
            'iteration': self.iteration_count,
            'live_data': {
                'total_trades': live_data.get('total_trades', 0),
                'total_assets': live_data.get('total_assets', 0),
                'available_cash': live_data.get('available_cash', 0)
            },
            'gradient_analysis': gradient_info,
            'large_number_validation': large_number_check,
            'next_action': 'UPDATE' if gradient_info['needs_update'] else 'MONITOR'
        }
        
        # 保存报告
        report_file = self.audit_dir / f'closed_loop_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ 报告已保存: {report_file}")
        
        return report


def main():
    """主函数"""
    print("=" * 80)
    print("🔄 实盘大数迭代闭环 - 跃迁⑤实现")
    print("=" * 80)
    
    # 初始化闭环
    loop = LiveTradingClosedLoop(learning_rate=0.1)
    
    # 生成报告
    report = loop.generate_report()
    
    # 输出关键指标
    print("\n" + "=" * 80)
    print("📊 迭代闭环报告")
    print("=" * 80)
    
    print(f"\n迭代次数: {report['iteration']}")
    print(f"实盘交易: {report['live_data']['total_trades']}笔")
    print(f"总资产: {report['live_data']['total_assets']:.2f}元")
    
    print(f"\n梯度分析:")
    print(f"  实盘Sharpe: {report['gradient_analysis']['live_sharpe']:.4f}")
    print(f"  回测Sharpe: {report['gradient_analysis']['backtest_sharpe']:.4f}")
    print(f"  偏差: {report['gradient_analysis']['deviation']:.4f}")
    print(f"  需要更新: {'是' if report['gradient_analysis']['needs_update'] else '否'}")
    
    print(f"\n大数验证:")
    print(f"  {report['large_number_validation']['message']}")
    
    print(f"\n下一步行动: {report['next_action']}")
    
    print("\n✅ 跃迁⑤实盘闭环迭代实现完成")


if __name__ == '__main__':
    main()
