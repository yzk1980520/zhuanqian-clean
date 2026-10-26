"""
因子IC复利效应计算器
时间：2026-10-06
编制：老五（数据回测专家）

核心功能：
1. IC序列累积效应计算
2. 年化信息比率（IR）计算
3. 预期收益预测（基于IC×√N模型）
4. 因子衰减建模
"""

import json
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional


class ICCapitalCompound:
    """因子IC复利效应计算器"""
    
    def __init__(self, ic_series: List[float], period: int = 250):
        """
        初始化IC复利计算器
        
        Args:
            ic_series: 历史IC序列（按时间顺序）
            period: 年化交易日数（默认250）
        """
        self.ic_series = np.array(ic_series)
        self.period = period
        
        if len(self.ic_series) < 3:
            raise ValueError(f"IC序列至少需要3个样本（当前{len(self.ic_series)}个）")
    
    def calculate_cumulative_ic(self) -> float:
        """
        计算累计IC效应（复利修正）
        
        公式：
          累计IC ≈ Σ(IC_i) + 0.5×Σ(IC_i²)
          
        解释：
          - 第一项：简单累加（线性效应）
          - 第二项：复利修正（非线性增强）
        
        Returns:
            累计IC效应值
        """
        simple_sum = np.sum(self.ic_series)
        compound_correction = 0.5 * np.sum(self.ic_series ** 2)
        return simple_sum + compound_correction
    
    def calculate_ir_annual(self) -> float:
        """
        计算年化信息比率（Information Ratio）
        
        公式：
          IR = ( mean(IC) / std(IC) ) × √period
          
        解释：
          - IR > 0.5：优秀因子
          - IR > 0.3：良好因子
          - IR > 0.1：可接受因子
          - IR < 0.1：无效因子
        
        Returns:
            年化信息比率
        """
        if len(self.ic_series) < 3:
            # 样本不足，无法计算标准差，返回0
            return 0.0
        
        mean_ic = np.mean(self.ic_series)
        std_ic = np.std(self.ic_series, ddof=1)
        
        if std_ic == 0:
            return 0.0
        
        ir = (mean_ic / std_ic) * np.sqrt(self.period)
        return ir
    
    def predict_cumulative_return(self, n_trades: int, efficiency: float = 0.7) -> float:
        """
        预测N次交易的累积超额收益
        
        公式：
          预期收益 ≈ IC × √N × 配置效率
          
        参数：
          - IC：平均IC值
          - N：交易次数
          - efficiency：配置效率（0-1，默认0.7）
        
        Returns:
            预测累积超额收益（小数形式，如0.15表示15%）
        """
        base_ic = np.mean(self.ic_series)
        predicted_return = base_ic * np.sqrt(n_trades) * efficiency
        return predicted_return
    
    def calculate_factor_contribution(self) -> Dict[str, float]:
        """
        计算各因子对累计收益的贡献度
        
        Returns:
            {因子名: 贡献度} 字典
        """
        contributions = {}
        cumulative = self.calculate_cumulative_ic()
        
        if cumulative == 0:
            for i, ic in enumerate(self.ic_series):
                contributions[f"factor_{i}"] = 0.0
        else:
            for i, ic in enumerate(self.ic_series):
                contributions[f"factor_{i}"] = ic / cumulative
        
        return contributions
    
    def detect_ic_decay(self, window: int = 10) -> Tuple[bool, float]:
        """
        检测IC衰减趋势
        
        Args:
            window: 滚动窗口大小
        
        Returns:
            (is_decaying, decay_rate)
            - is_decailing: 是否衰减
            - decay_rate: 衰减速率（负值表示衰减）
        """
        if len(self.ic_series) < window * 2:
            return False, 0.0
        
        # 计算前后半段平均IC
        half = len(self.ic_series) // 2
        early_ic = np.mean(self.ic_series[:half])
        late_ic = np.mean(self.ic_series[half:])
        
        # 计算滚动IC趋势
        rolling_mean = []
        for i in range(window, len(self.ic_series)):
            rolling_mean.append(np.mean(self.ic_series[i-window:i]))
        
        if len(rolling_mean) < 2:
            return False, 0.0
        
        # 线性回归计算斜率
        x = np.arange(len(rolling_mean))
        slope, _, _, _, _ = np.linalg.lstsq(
            np.column_stack([x, np.ones(len(x))]), 
            rolling_mean, 
            rcond=None
        )[0]
        
        is_decaying = slope < -0.001  # 斜率<-0.001判定为衰减
        
        return is_decaying, slope
    
    def generate_report(self) -> Dict:
        """生成IC复利效应报告"""
        cumulative_ic = self.calculate_cumulative_ic()
        ir_annual = self.calculate_ir_annual()
        decay_detected, decay_rate = self.detect_ic_decay()
        
        # 预测不同交易次数下的收益
        predictions = {}
        for n in [10, 37, 50, 100, 200]:
            predictions[n] = self.predict_cumulative_return(n)
        
        return {
            'timestamp': datetime.now().isoformat(),
            'ic_samples': len(self.ic_series),
            'cumulative_ic': round(cumulative_ic, 6),
            'ir_annual': round(ir_annual, 4),
            'ir_rating': self._rate_ir(ir_annual),
            'ic_decay_detected': decay_detected,
            'ic_decay_rate': round(decay_rate, 6),
            'mean_ic': round(float(np.mean(self.ic_series)), 6),
            'std_ic': round(float(np.std(self.ic_series)), 6),
            'predictions': {k: round(v, 6) for k, v in predictions.items()},
            'recommendation': self._get_recommendation(ir_annual, decay_detected)
        }
    
    def _rate_ir(self, ir: float) -> str:
        """评级IR"""
        if ir > 0.5:
            return "EXCELLENT（优秀）"
        elif ir > 0.3:
            return "GOOD（良好）"
        elif ir > 0.1:
            return "ACCEPTABLE（可接受）"
        else:
            return "POOR（无效）"
    
    def _get_recommendation(self, ir: float, decay: bool) -> str:
        """生成建议"""
        if decay:
            return "🔴 IC衰减 detected，建议重新校准因子权重"
        elif ir > 0.3:
            return "🟢 IC质量优秀，可加大因子权重"
        elif ir > 0.1:
            return "🟡 IC质量一般，建议优化因子组合"
        else:
            return "🔴 IC质量不足，建议剔除或替换因子"


def load_ic_data(ic_file: Path) -> ICCapitalCompound:
    """加载IC数据并创建计算器"""
    with open(ic_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 兼容不同格式：valid_factors列表或factors列表
    factors = data.get('valid_factors', [])
    if not factors:
        factors = data.get('factors', [])
    
    if not factors:
        raise ValueError(f"IC数据文件中未找到因子数据: {ic_file}")
    
    ic_values = [f.get('ic', 0) for f in factors]
    
    return ICCapitalCompound(ic_values)


def main():
    """主函数：执行IC复利分析"""
    root = Path(r'D:\open code\zhuanqian')
    ic_file = root / 'data' / 'factor_ic' / 'factor_ic_latest.json'
    
    print('='*70)
    print('  因子IC复利效应分析')
    print('='*70)
    print()
    
    # 加载数据
    if not ic_file.exists():
        print(f"❌ IC数据文件不存在: {ic_file}")
        return
    
    calculator = load_ic_data(ic_file)
    
    # 生成报告
    report = calculator.generate_report()
    
    # 输出报告
    print(f"IC样本数: {report['ic_samples']}")
    print(f"累计IC效应: {report['cumulative_ic']:.6f}")
    print(f"年化IR: {report['ir_annual']:.4f} ({report['ir_rating']})")
    print(f"IC衰减检测: {'⚠️ 检测到衰减' if report['ic_decay_detected'] else '✅ 无衰减'}")
    print(f"衰减速率: {report['ic_decay_rate']:.6f}")
    print()
    
    print("预期收益预测:")
    for n, pred in report['predictions'].items():
        print(f"  {n:3d}笔交易 → {pred*100:+.2f}%")
    print()
    
    print(f"建议: {report['recommendation']}")
    print()
    
    # 保存报告
    output_file = root / 'data' / 'ic_capital_compound_report.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"报告已保存: {output_file}")
    print()
    print('='*70)


if __name__ == '__main__':
    main()
