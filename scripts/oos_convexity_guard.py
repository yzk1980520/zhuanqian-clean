"""
OOS凸性风险保护器 - 跃迁④实现
功能：
1. 自动划分In-Sample和Out-of-Sample数据
2. 计算In/Out样本夏普比率并比较
3. 凸性风险等级评估与自动决策
4. 集成到回测流水线
"""
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

class OOSConvexityGuard:
    """OOS凸性风险保护器"""
    
    def __init__(self, oos_ratio_threshold=0.7, embargo_days=30):
        self.oos_ratio_threshold = oos_ratio_threshold
        self.embargo_days = embargo_days
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.audit_dir = Path(__file__).parent.parent / 'data' / 'audit'
    
    def split_sample(self, trades: List[Dict], oos_ratio: float = 0.3) -> Tuple[List[Dict], List[Dict]]:
        """划分In-Sample和Out-of-Sample数据集"""
        if not trades:
            return [], []
        
        # 按日期排序
        sorted_trades = sorted(trades, key=lambda x: x.get('date', '2000-01-01'))
        
        # 划分比例
        split_idx = int(len(sorted_trades) * (1 - oos_ratio))
        
        in_sample = sorted_trades[:split_idx]
        oos_sample = sorted_trades[split_idx:]
        
        return in_sample, oos_sample
    
    def calculate_sharpe(self, trades: List[Dict]) -> float:
        """计算夏普比率"""
        if len(trades) < 10:
            return 0.0
        
        # 计算每日收益
        daily_pnl = {}
        for trade in trades:
            date = trade.get('date', '')
            pnl = trade.get('pnl', 0)
            if date not in daily_pnl:
                daily_pnl[date] = 0
            daily_pnl[date] += pnl
        
        returns = list(daily_pnl.values())
        
        if len(returns) < 10:
            return 0.0
        
        arr = np.array(returns)
        mean_return = np.mean(arr)
        std_return = np.std(arr)
        
        if std_return == 0:
            return 0.0
        
        # 年化夏普比率
        sharpe = (mean_return / std_return) * np.sqrt(252)
        
        return float(sharpe)
    
    def check_convexity_risk(self, sr_in: float, sr_oos: float) -> Dict:
        """检查凸性风险"""
        if sr_in <= 0:
            return {
                'ratio': 0,
                'risk_level': 'UNKNOWN',
                'is_overfitting': True,
                'action': 'RETRAIN_STRATEGY'
            }
        
        ratio = sr_oos / sr_in
        
        # 风险等级判定
        if ratio >= 0.8:
            risk_level = 'SAFE'
            is_overfitting = False
            action = 'MAINTAIN'
        elif ratio >= 0.7:
            risk_level = 'WARNING'
            is_overfitting = False
            action = 'REDUCE_POSITION_50%'
        elif ratio >= 0.6:
            risk_level = 'DANGER'
            is_overfitting = True
            action = 'PAUSE_NEW_POSITIONS'
        else:
            risk_level = 'CRITICAL'
            is_overfitting = True
            action = 'ROLLBACK_TO_LAST_VERSION'
        
        return {
            'ratio': round(ratio, 4),
            'risk_level': risk_level,
            'is_overfitting': is_overfitting,
            'action': action,
            'sr_in_sample': round(sr_in, 2),
            'sr_oos_sample': round(sr_oos, 2)
        }
    
    def load_backtest_data(self) -> Dict:
        """加载回测数据"""
        # 尝试多个可能的路径
        candidates = [
            self.data_dir / 'rotation_backtest_result_recovered.json',
            self.data_dir / 'rotation_backtest_result.json',
            self.data_dir / 'backtest' / 'result.json'
        ]
        
        for path in candidates:
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        
        return {}
    
    def generate_report(self) -> Dict:
        """生成OOS凸性风险报告"""
        # 加载回测数据
        bt_data = self.load_backtest_data()
        
        if not bt_data:
            return {
                'status': 'ERROR',
                'message': '无法加载回测数据',
                'action': 'CHECK_DATA_SOURCE'
            }
        
        # 提取交易记录
        trades = bt_data.get('trades', [])
        
        # 空数据保护
        if not trades or len(trades) < 10:
            return {
                'status': 'INSUFFICIENT_DATA',
                'message': f'交易数据不足: {len(trades) if trades else 0}笔 < 10笔',
                'action': 'COLLECT_MORE_DATA',
                'trade_count': len(trades) if trades else 0
            }
        print(f"📊 加载回测交易数: {len(trades)}笔")
        
        # 划分样本
        in_sample, oos_sample = self.split_sample(trades, oos_ratio=0.3)
        print(f"📈 In-Sample: {len(in_sample)}笔, Out-of-Sample: {len(oos_sample)}笔")
        
        # 计算夏普比率
        sr_in = self.calculate_sharpe(in_sample)
        sr_oos = self.calculate_sharpe(oos_sample)
        
        print(f"🎯 In-Sample夏普: {sr_in:.2f}")
        print(f"🎯 OOS夏普: {sr_oos:.2f}")
        
        # 检查凸性风险
        risk_check = self.check_convexity_risk(sr_in, sr_oos)
        
        # 生成报告
        report = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'sample_split': {
                'in_sample_count': len(in_sample),
                'oos_sample_count': len(oos_sample),
                'oos_ratio': 0.3
            },
            'sharpe_ratios': {
                'in_sample': round(sr_in, 2),
                'oos': round(sr_oos, 2),
                'ratio': risk_check['ratio']
            },
            'convexity_risk': risk_check,
            'recommendations': []
        }
        
        # 添加建议
        if risk_check['risk_level'] == 'SAFE':
            report['recommendations'].append({
                'priority': 'INFO',
                'action': '维持策略',
                'detail': 'OOS凸性风险低，策略泛化能力良好'
            })
        elif risk_check['risk_level'] == 'WARNING':
            report['recommendations'].append({
                'priority': 'P1',
                'action': '减仓50%',
                'detail': 'OOS表现略有衰减，建议降低仓位'
            })
        elif risk_check['risk_level'] in ['DANGER', 'CRITICAL']:
            report['recommendations'].append({
                'priority': 'P0',
                'action': risk_check['action'],
                'detail': '策略存在过拟合风险，需重新训练或回滚版本'
            })
        
        return report


def main():
    """主函数"""
    print("=" * 80)
    print("🛡️ OOS凸性风险保护器 - 跃迁④实现")
    print("=" * 80)
    
    # 初始化保护器
    guard = OOSConvexityGuard(oos_ratio_threshold=0.7)
    
    # 生成报告
    report = guard.generate_report()
    
    if report.get('status') == 'ERROR':
        print(f"\n❌ {report['message']}")
        return 1
    
    # 输出报告
    print("\n" + "=" * 80)
    print("📊 OOS凸性风险报告")
    print("=" * 80)
    
    print(f"\n样本划分:")
    print(f"  In-Sample: {report['sample_split']['in_sample_count']}笔")
    print(f"  Out-of-Sample: {report['sample_split']['oos_sample_count']}笔")
    
    print(f"\n夏普比率:")
    print(f"  In-Sample: {report['sharpe_ratios']['in_sample']:.2f}")
    print(f"  OOS: {report['sharpe_ratios']['oos']:.2f}")
    print(f"  比率: {report['sharpe_ratios']['ratio']:.4f}")
    
    print(f"\n凸性风险:")
    print(f"  风险等级: {report['convexity_risk']['risk_level']}")
    print(f"  过拟合: {'是' if report['convexity_risk']['is_overfitting'] else '否'}")
    print(f"  建议行动: {report['convexity_risk']['action']}")
    
    if report['recommendations']:
        print(f"\n【优化建议】")
        for rec in report['recommendations']:
            print(f"  [{rec['priority']}] {rec['action']}: {rec['detail']}")
    
    # 保存报告
    report_file = Path(__file__).parent.parent / 'data' / 'audit' / f'oos_convexity_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ 报告已保存: {report_file}")
    
    return 0 if report['convexity_risk']['risk_level'] in ['SAFE', 'WARNING'] else 1


if __name__ == '__main__':
    exit(main())
