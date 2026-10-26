"""
凸性保护验证模块 (Convexity Protector)
========================================
跃迁④核心实现：样本外凸性风险保护

数学原理：
  - OOS/IS 比率检验过拟合
  - CV (变异系数) 衡量收益稳定性
  - Sharpe 约束确保风险调整后收益

验收标准：
  - OOS/IS >= 0.5 (不过拟合)
  - CV < 0.5 (收益稳定)
  - OOS Sharpe >= 1.0 (风险调整收益达标)
"""

import json
import os
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ConvexityProtector:
    """样本外凸性风险保护器"""
    
    def __init__(
        self,
        oos_ratio: float = 0.3,
        cv_threshold: float = 0.5,
        sharpe_min: float = 1.0,
        oos_is_min: float = 0.5
    ):
        """
        参数:
            oos_ratio: 样本外比例（默认30%）
            cv_threshold: 变异系数阈值（默认0.5）
            sharpe_min: 最小夏普比率（默认1.0）
            oos_is_min: OOS/IS最小比率（默认0.5）
        """
        self.oos_ratio = oos_ratio
        self.cv_threshold = cv_threshold
        self.sharpe_min = sharpe_min
        self.oos_is_min = oos_is_min
        self.validation_history: List[Dict] = []
    
    def split_sample(
        self, 
        data: List[Dict], 
        train_ratio: float = 0.7
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        划分样本内和样本外
        
        参数:
            data: 回测数据列表
            train_ratio: 训练集比例（默认70%）
        
        返回:
            (is_data, oos_data): 样本内、样本外数据
        """
        n = len(data)
        train_end = int(n * train_ratio)
        
        is_data = data[:train_end]
        oos_data = data[train_end:]
        
        return is_data, oos_data
    
    def calculate_metrics(self, data: List[Dict]) -> Dict[str, float]:
        """
        计算回测指标
        
        参数:
            data: 回测结果数据
        
        返回:
            包含 return, sharpe, dd, win_rate, std, mean 的字典
        """
        if not data:
            return {
                'return': 0.0,
                'sharpe': 0.0,
                'dd': 1.0,
                'win_rate': 0.0,
                'std': 0.0,
                'mean': 0.0,
                'trades': 0
            }
        
        # 提取收益序列
        returns = [d.get('return', 0) for d in data if 'return' in d]
        
        if not returns:
            return {
                'return': 0.0,
                'sharpe': 0.0,
                'dd': 1.0,
                'win_rate': 0.0,
                'std': 0.0,
                'mean': 0.0,
                'trades': 0
            }
        
        # 计算指标
        total_return = np.sum(returns)
        mean_return = np.mean(returns)
        std_return = np.std(returns) if len(returns) > 1 else 0.001
        
        # 夏普比率（简化版，假设无风险利率为0）
        sharpe = mean_return / std_return if std_return > 0 else 0
        
        # 最大回撤
        cumulative = np.cumprod(1 + np.array(returns))
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        max_dd = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0
        
        # 胜率
        wins = sum(1 for r in returns if r > 0)
        win_rate = wins / len(returns) if len(returns) > 0 else 0
        
        return {
            'return': total_return,
            'sharpe': sharpe,
            'dd': max_dd,
            'win_rate': win_rate,
            'std': std_return,
            'mean': mean_return,
            'trades': len(returns)
        }
    
    def validate_convexity(
        self,
        is_results: Dict[str, float],
        oos_results: Dict[str, float]
    ) -> Dict:
        """
        验证凸性风险保护
        
        参数:
            is_results: 样本内回测结果
            oos_results: 样本外回测结果
        
        返回:
            包含验证结果的字典
        """
        # 计算OOS/IS比率
        oos_is_ratio = (
            oos_results['return'] / is_results['return']
            if is_results['return'] != 0
            else 0
        )
        
        # 计算变异系数
        cv = (
            oos_results['std'] / abs(oos_results['mean'])
            if oos_results['mean'] != 0
            else 999
        )
        
        # 过拟合检测
        overfit_flag = oos_is_ratio < self.oos_is_min or cv > self.cv_threshold
        
        # 凸性保护判定
        protection_passed = (
            oos_is_ratio >= self.oos_is_min and
            cv < self.cv_threshold and
            oos_results.get('sharpe', 0) >= self.sharpe_min
        )
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'oos_is_ratio': round(oos_is_ratio, 4),
            'cv': round(cv, 4),
            'overfit_flag': overfit_flag,
            'protection_passed': protection_passed,
            'is_metrics': is_results,
            'oos_metrics': oos_results
        }
        
        # 记录历史
        self.validation_history.append(result)
        
        # 生成警告
        result['warnings'] = self.generate_warnings(result)
        
        return result
    
    def generate_warnings(self, results: Dict) -> List[str]:
        """生成风险预警"""
        warnings = []
        
        if results['oos_is_ratio'] < 0.7:
            warnings.append(
                f"⚠️ OOS收益偏低 ({results['oos_is_ratio']:.2%})，可能存在过拟合"
            )
        
        if results['cv'] > 0.3:
            warnings.append(
                f"⚠️ 变异系数偏高 ({results['cv']:.2f})，收益不稳定"
            )
        
        if results['overfit_flag']:
            warnings.append("🚨 凸性保护失败，建议暂停实盘")
        
        if results['oos_metrics'].get('sharpe', 0) < self.sharpe_min:
            warnings.append(
                f"⚠️ OOS夏普比率过低 "
                f"({results['oos_metrics'].get('sharpe', 0):.2f} < {self.sharpe_min})"
            )
        
        return warnings
    
    def save_result(self, result: Dict, output_path: str = None):
        """保存验证结果"""
        if output_path is None:
            output_path = f"data/convexity_validation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # 转换为可序列化的字典
        serializable_result = {}
        for k, v in result.items():
            if isinstance(v, bool):
                serializable_result[k] = bool(v)
            elif isinstance(v, np.bool_):
                serializable_result[k] = bool(v)
            elif isinstance(v, (np.integer,)):
                serializable_result[k] = int(v)
            elif isinstance(v, (np.floating,)):
                serializable_result[k] = float(v)
            elif isinstance(v, np.ndarray):
                serializable_result[k] = v.tolist()
            else:
                serializable_result[k] = v

        # R4b(#4 根因): 原子写 (同目录 tmp + os.replace)。
        # 裸 open(output_path,'w') 写中断(进程被杀)会留下截断坏文件(111字节 overfit_flag 后断),
        # 半成品只在 tmp, 未 os.replace 前目标路径不动 → 写中断不留坏文件。
        tmp_path = f"{output_path}.tmp_convexity"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(serializable_result, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, output_path)  # 原子替换: 成功才覆盖目标
        finally:
            # 写中断(异常路径)时清理 tmp, 不残留半成品
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    print(f"⚠️ [scripts\convexity_protector.py] 兼容处理: except OSError:", file=sys.stderr)
        return output_path
    
    def load_backtest_data(self, data_path: str) -> List[Dict]:
        """
        加载回测数据
        
        参数:
            data_path: 回测数据文件路径
        
        返回:
            回测数据列表
        """
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 处理不同格式
        if isinstance(data, dict):
            # 如果是字典，提取trades或results
            if 'trades' in data:
                return data['trades']
            elif 'results' in data:
                return data['results']
            else:
                # 尝试转换为列表
                return [data]
        elif isinstance(data, list):
            return data
        else:
            raise ValueError(f"不支持的数据格式: {type(data)}")
    
    def run_validation(
        self,
        backtest_data: List[Dict],
        output_path: str = None
    ) -> Dict:
        """
        运行完整凸性保护验证
        
        参数:
            backtest_data: 回测数据
            output_path: 输出路径
        
        返回:
            验证结果
        """
        print(f"\n{'='*60}")
        print(f"🔒 凸性保护验证启动")
        print(f"{'='*60}")
        
        # 划分样本
        is_data, oos_data = self.split_sample(backtest_data, self.oos_ratio)
        
        print(f"\n📊 样本划分:")
        print(f"  样本内 (IS): {len(is_data)} 笔交易")
        print(f"  样本外 (OOS): {len(oos_data)} 笔交易")
        
        # 计算指标
        is_metrics = self.calculate_metrics(is_data)
        oos_metrics = self.calculate_metrics(oos_data)
        
        print(f"\n📈 样本内 (IS) 指标:")
        print(f"  收益率: {is_metrics['return']:.2%}")
        print(f"  夏普比率: {is_metrics['sharpe']:.2f}")
        print(f"  最大回撤: {is_metrics['dd']:.2%}")
        print(f"  胜率: {is_metrics['win_rate']:.2%}")
        
        print(f"\n📈 样本外 (OOS) 指标:")
        print(f"  收益率: {oos_metrics['return']:.2%}")
        print(f"  夏普比率: {oos_metrics['sharpe']:.2f}")
        print(f"  最大回撤: {oos_metrics['dd']:.2%}")
        print(f"  胜率: {oos_metrics['win_rate']:.2%}")
        
        # 验证凸性
        result = self.validate_convexity(is_metrics, oos_metrics)
        
        # 打印结果
        print(f"\n{'='*60}")
        print(f"✅ 凸性保护验证结果")
        print(f"{'='*60}")
        print(f"  OOS/IS 比率: {result['oos_is_ratio']:.2%}")
        print(f"  变异系数: {result['cv']:.4f}")
        print(f"  过拟合标志: {'是' if result['overfit_flag'] else '否'}")
        print(f"  保护通过: {'✅ 通过' if result['protection_passed'] else '❌ 未通过'}")
        
        if result['warnings']:
            print(f"\n⚠️  风险预警:")
            for warning in result['warnings']:
                print(f"  {warning}")
        
        # 保存结果
        if output_path:
            self.save_result(result, output_path)
            print(f"\n💾 验证结果已保存: {output_path}")
        
        return result


def main():
    """测试主函数"""
    print("\n" + "="*60)
    print("🔬 凸性保护验证模块测试")
    print("="*60)
    
    # 创建保护器
    protector = ConvexityProtector(
        oos_ratio=0.3,
        cv_threshold=0.5,
        sharpe_min=1.0,
        oos_is_min=0.5
    )
    
    # 模拟回测数据
    np.random.seed(42)
    n_trades = 100
    is_returns = np.random.normal(0.01, 0.03, int(n_trades * 0.7))
    oos_returns = np.random.normal(0.008, 0.035, int(n_trades * 0.3))
    
    is_data = [{'return': r} for r in is_returns]
    oos_data = [{'return': r} for r in oos_returns]
    
    # 计算指标
    is_metrics = protector.calculate_metrics(is_data)
    oos_metrics = protector.calculate_metrics(oos_data)
    
    print(f"\n📊 模拟回测数据:")
    print(f"  IS: {len(is_data)} 笔交易")
    print(f"  OOS: {len(oos_data)} 笔交易")
    
    # 验证
    result = protector.validate_convexity(is_metrics, oos_metrics)
    
    # 打印结果
    print(f"\n{'='*60}")
    print(f"✅ 验证结果")
    print(f"{'='*60}")
    print(f"  OOS/IS 比率: {result['oos_is_ratio']:.2%}")
    print(f"  变异系数: {result['cv']:.4f}")
    print(f"  保护通过: {'✅ 通过' if result['protection_passed'] else '❌ 未通过'}")
    
    if result['warnings']:
        print(f"\n⚠️  风险预警:")
        for warning in result['warnings']:
            print(f"  {warning}")
    
    print(f"\n{'='*60}")
    print("✅ 凸性保护验证模块测试完成")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
