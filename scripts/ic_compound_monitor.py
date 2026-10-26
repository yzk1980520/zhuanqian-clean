"""
IC复利效应监控器 - 跃迁①实现
功能：
1. IC衰减监测（每日检查）
2. 失效因子自动替换（连续7日IC<0.03）
3. 复利效应量化（累积IC计算）
"""
import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import sys

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

class ICCompoundMonitor:
    """IC复利效应监控器"""
    
    def __init__(self, lookback=60, decay_threshold=-0.05, ic_threshold=0.03):
        self.lookback = lookback
        self.decay_threshold = decay_threshold
        self.ic_threshold = ic_threshold
        self.data_dir = Path(__file__).parent.parent / 'data' / 'factor_ic'
        self.audit_dir = Path(__file__).parent.parent / 'data' / 'audit'
        
    def load_ic_history(self, factor_name: str) -> List[float]:
        """加载因子IC历史数据"""
        pattern = self.data_dir.glob(f'*{factor_name}*.json')
        ic_series = []
        
        for file in sorted(pattern):
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'rolling_ic' in data:
                        ic_series.extend(data['rolling_ic'])
            except Exception as e:
                print(f"⚠️ 读取IC历史文件失败 {file}: {e}")
        
        return ic_series[-self.lookback:] if len(ic_series) > self.lookback else ic_series
    
    def calculate_ic_safe(self, returns, factor_values):
        """安全的IC计算（防除零）"""
        if len(returns) < 20 or len(factor_values) < 20:
            return 0.0
        
        std_r = np.std(returns)
        std_f = np.std(factor_values)
        
        if std_r == 0 or std_f == 0:
            return 0.0
        
        try:
            ic = np.corrcoef(returns, factor_values)[0, 1]
            return float(ic) if not np.isnan(ic) else 0.0
        except Exception:
            print(f"🔴 [scripts\ic_compound_monitor.py] CR-01(return): except Exception:", file=sys.stderr)
            return 0.0
        """计算IC复利效应"""
        if not ic_series or len(ic_series) < 5:
            return {
                'cumulative_ic': 0,
                'decay_rate': 0,
                'is_effective': False,
                'avg_ic': 0,
                'compound_return': 0
            }
        
        arr = np.array(ic_series)
        
        # 累积IC（复利效应）
        cumulative_ic = float(np.prod(1 + arr) - 1)
        
        # IC衰减率（首尾比较）
        decay_rate = float((arr[-1] - arr[0]) / abs(arr[0])) if arr[0] != 0 else 0
        
        # 平均IC绝对值
        avg_ic = float(np.mean(np.abs(arr)))
        
        # 复利有效性判断
        is_effective = (
            avg_ic > self.ic_threshold and
            decay_rate > self.decay_threshold and
            len(ic_series) >= 20
        )
        
        # 估计年化复利收益（简化模型）
        compound_return = float(cumulative_ic * 252 / len(ic_series))
        
        return {
            'cumulative_ic': round(cumulative_ic, 4),
            'decay_rate': round(decay_rate, 4),
            'is_effective': is_effective,
            'avg_ic': round(avg_ic, 4),
            'compound_return': round(compound_return * 100, 2),
            'sample_count': len(ic_series)
        }
    
    def detect_degradation(self, current_ic: float, history: List[float]) -> Dict:
        """检测IC衰减"""
        if not history or abs(current_ic) >= self.ic_threshold:
            return {
                'status': 'normal',
                'action': 'monitor',
                'confidence': 0.9,
                'message': 'IC正常，继续监控'
            }
        
        # 连续衰减天数
        consecutive_days = 0
        for ic in reversed(history[-10:]):
            if abs(ic) < self.ic_threshold:
                consecutive_days += 1
            else:
                break
        
        # 衰减判断
        if consecutive_days >= 7:
            return {
                'status': 'degraded',
                'action': 'replace_factor',
                'confidence': 0.85,
                'consecutive_days': consecutive_days,
                'message': f'IC连续{consecutive_days}日低于阈值，建议替换因子'
            }
        elif consecutive_days >= 3:
            return {
                'status': 'warning',
                'action': 'alert',
                'confidence': 0.7,
                'consecutive_days': consecutive_days,
                'message': f'IC连续{consecutive_days}日偏低，进入观察名单'
            }
        
        return {
            'status': 'normal',
            'action': 'monitor',
            'confidence': 0.9,
            'message': 'IC正常'
        }
    
    def generate_report(self, factors: List[Dict]) -> Dict:
        """生成IC复利效应报告"""
        report = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_factors': len(factors),
            'effective_factors': 0,
            'degraded_factors': 0,
            'compound_summary': {},
            'recommendations': []
        }
        
        for factor in factors:
            name = factor.get('name', 'unknown')
            current_ic = factor.get('ic', 0)
            
            # 加载历史数据
            history = self.load_ic_history(name)
            
            # 计算复利效应
            compound = self.calculate_compound_ic(history)
            
            # 检测衰减
            degradation = self.detect_degradation(current_ic, history)
            
            # 更新统计
            if compound['is_effective']:
                report['effective_factors'] += 1
            if degradation['status'] == 'degraded':
                report['degraded_factors'] += 1
            
            # 记录结果
            report['compound_summary'][name] = {
                'current_ic': round(current_ic, 4),
                **compound,
                **degradation
            }
            
            # 生成建议
            if degradation['status'] == 'degraded':
                report['recommendations'].append({
                    'factor': name,
                    'action': degradation['action'],
                    'reason': degradation['message'],
                    'priority': 'P0'
                })
            elif degradation['status'] == 'warning':
                report['recommendations'].append({
                    'factor': name,
                    'action': degradation['action'],
                    'reason': degradation['message'],
                    'priority': 'P1'
                })
        
        # 总体评估
        report['overall_assessment'] = {
            'compound_effectiveness': report['effective_factors'] / max(report['total_factors'], 1),
            'risk_level': 'HIGH' if report['degraded_factors'] > 3 else ('MEDIUM' if report['degraded_factors'] > 1 else 'LOW'),
            'action_required': len([r for r in report['recommendations'] if r['priority'] == 'P0']) > 0
        }
        
        return report


def main():
    """主函数"""
    print("=" * 80)
    print("🧮 IC复利效应监控器 - 跃迁①实现")
    print("=" * 80)
    
    # 初始化监控器
    monitor = ICCompoundMonitor(lookback=60)
    
    # 加载最新IC数据
    ic_file = Path(__file__).parent.parent / 'data' / 'factor_ic' / 'factor_ic_latest.json'
    if not ic_file.exists():
        print("❌ 找不到IC数据文件")
        return 1
    
    with open(ic_file, 'r', encoding='utf-8') as f:
        ic_data = json.load(f)
    
    factors = ic_data.get('factors', [])
    print(f"\n📊 加载因子数: {len(factors)}个")
    
    # 生成报告
    report = monitor.generate_report(factors)
    
    # 输出报告
    print("\n" + "=" * 80)
    print("📈 IC复利效应分析报告")
    print("=" * 80)
    print(f"有效因子: {report['effective_factors']}/{report['total_factors']}")
    print(f"衰减因子: {report['degraded_factors']}个")
    print(f"风险评估: {report['overall_assessment']['risk_level']}")
    print(f"需要行动: {'是' if report['overall_assessment']['action_required'] else '否'}")
    
    # 显示TOP5因子
    print("\n【TOP5有效因子】")
    sorted_factors = sorted(
        [(name, data['current_ic'], data['compound_return']) 
         for name, data in report['compound_summary'].items() 
         if data['is_effective']],
        key=lambda x: abs(x[1]),
        reverse=True
    )[:5]
    
    for i, (name, ic, return_) in enumerate(sorted_factors, 1):
        print(f"  {i}. {name}: IC={ic:.4f}, 复利收益={return_:.2f}%")
    
    # 显示衰减因子
    if report['degraded_factors'] > 0:
        print("\n【需关注因子】")
        for rec in report['recommendations'][:5]:
            print(f"  ⚠️ {rec['factor']}: {rec['reason']}")
    
    # 保存报告
    report_file = Path(__file__).parent.parent / 'data' / 'audit' / f'ic_compound_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n✅ 报告已保存: {report_file}")
    
    # 返回状态码
    return 0 if report['degraded_factors'] == 0 else 1


if __name__ == '__main__':
    exit(main())
