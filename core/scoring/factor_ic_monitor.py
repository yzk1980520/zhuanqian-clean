"""
因子IC监控模块 — 自动化因子有效性监测
======================================

作用:
  实时监控因子IC（Information Coefficient），检测因子失效，
  提供停用建议，避免策略基于无效因子选股。

功能:
  1. 计算近期因子IC（滚动窗口）
  2. 检测IC单调性（是否稳定为正/负）
  3. 对比历史IC均值，判断是否失效
  4. 自动生成停用建议

门禁标准（参考AGENTS.md）:
  - IC > 0.03: 有效
  - IR > 0.3: 稳定
  - 单调性: 连续N期同向

使用方式:
  from core.scoring.factor_ic_monitor import FactorICMonitor
  
  monitor = FactorICMonitor(window=20)
  result = monitor.check('chg5', ic_history)
  if result['status'] == 'failed':
      print(result['suggestion'])

历史:
  2026-10-05 P2优化: 原IC监控需人工触发，现已建立自动化流程
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ICMonitorResult:
    """IC监控结果"""
    factor_name: str
    status: str  # 'passed', 'warning', 'failed'
    recent_ic: float
    historical_mean: float
    icir: float
    monotonicity: str  # 'stable_positive', 'stable_negative', 'unstable', 'flipping'
    suggestion: str
    check_time: str
    
    def to_dict(self) -> dict:
        return {
            'factor_name': self.factor_name,
            'status': self.status,
            'recent_ic': self.recent_ic,
            'historical_mean': self.historical_mean,
            'icir': self.icir,
            'monotonicity': self.monotonicity,
            'suggestion': self.suggestion,
            'check_time': self.check_time,
        }


class FactorICMonitor:
    """因子IC监控器"""
    
    # 门禁阈值
    IC_THRESHOLD = 0.03       # IC > 0.03 为有效
    IR_THRESHOLD = 0.3        # IR > 0.3 为稳定
    MONOTONICITY_WINDOW = 5   # 连续5期同向为稳定
    
    def __init__(
        self,
        window: int = 20,
        ic_threshold: float = None,
        ir_threshold: float = None
    ):
        """
        初始化监控器
        
        Args:
            window: 计算IC的滚动窗口期数
            ic_threshold: IC阈值（默认0.03）
            ir_threshold: IR阈值（默认0.3）
        """
        self.window = window
        self.ic_threshold = ic_threshold or self.IC_THRESHOLD
        self.ir_threshold = ir_threshold or self.IR_THRESHOLD
        
        # IC历史记录（因子名 → [ic_values]）
        self._ic_history: Dict[str, List[float]] = {}
        
        # 监控结果缓存
        self._last_check: Dict[str, ICMonitorResult] = {}
    
    def add_ic_record(self, factor_name: str, ic_value: float, date: str = None):
        """
        添加单期IC记录
        
        Args:
            factor_name: 因子名称
            ic_value: IC值
            date: 日期字符串 (YYYY-MM-DD)
        """
        if factor_name not in self._ic_history:
            self._ic_history[factor_name] = []
        
        self._ic_history[factor_name].append({
            'date': date or datetime.now().strftime('%Y-%m-%d'),
            'ic': ic_value
        })
        
        # 保持窗口大小
        if len(self._ic_history[factor_name]) > self.window * 2:
            self._ic_history[factor_name] = self._ic_history[factor_name][-self.window * 2:]
    
    def add_ic_records(self, factor_name: str, records: List[Dict]):
        """
        批量添加IC记录
        
        Args:
            factor_name: 因子名称
            records: 记录列表，每项包含'date'和'ic'
        """
        for record in records:
            self.add_ic_record(factor_name, record['ic'], record.get('date'))
    
    def get_recent_ic(self, factor_name: str) -> Optional[float]:
        """
        获取近期IC均值
        
        Args:
            factor_name: 因子名称
            
        Returns:
            float: 近期IC均值，无数据返回None
        """
        history = self._ic_history.get(factor_name, [])
        
        if len(history) < self.window:
            return None
        
        recent = history[-self.window:]
        return sum(r['ic'] for r in recent) / len(recent)
    
    def get_historical_mean(self, factor_name: str) -> Optional[float]:
        """
        获取历史IC均值
        
        Args:
            factor_name: 因子名称
            
        Returns:
            float: 历史IC均值，无数据返回None
        """
        history = self._ic_history.get(factor_name, [])
        
        if not history:
            return None
        
        return sum(r['ic'] for r in history) / len(history)
    
    def calculate_icir(self, factor_name: str) -> Optional[float]:
        """
        计算ICIR（IC信息比率）
        
        IR = Mean(IC) / Std(IC)
        
        Args:
            factor_name: 因子名称
            
        Returns:
            float: ICIR值，无数据返回None
        """
        history = self._ic_history.get(factor_name, [])
        
        if len(history) < 10:
            return None
        
        ic_values = [r['ic'] for r in history]
        mean_ic = sum(ic_values) / len(ic_values)
        
        # 计算标准差
        variance = sum((x - mean_ic) ** 2 for x in ic_values) / (len(ic_values) - 1)
        std_ic = variance ** 0.5
        
        if std_ic == 0:
            return None
        
        return mean_ic / std_ic
    
    def check_monotonicity(self, factor_name: str) -> str:
        """
        检查IC单调性
        
        Args:
            factor_name: 因子名称
            
        Returns:
            str: 'stable_positive', 'stable_negative', 'unstable', 'flipping'
        """
        history = self._ic_history.get(factor_name, [])
        
        if len(history) < self.MONOTONICITY_WINDOW:
            return 'insufficient_data'
        
        # 取最近N期
        recent = history[-self.MONOTONICITY_WINDOW:]
        signs = [1 if r['ic'] > 0 else -1 for r in recent]
        
        # 检查是否全为正或全为负
        if all(s == 1 for s in signs):
            return 'stable_positive'
        elif all(s == -1 for s in signs):
            return 'stable_negative'
        elif len(set(signs)) == 2:
            return 'flipping'  # 频繁反转
        else:
            return 'unstable'
    
    def check_factor(
        self,
        factor_name: str,
        ic_history: Optional[List[Dict]] = None
    ) -> ICMonitorResult:
        """
        检查单个因子的有效性
        
        Args:
            factor_name: 因子名称
            ic_history: IC历史数据（可选，如不提供则使用内部缓存）
            
        Returns:
            ICMonitorResult: 检查结果
        """
        # 如果有外部历史数据，先加载
        if ic_history:
            self.add_ic_records(factor_name, ic_history)
        
        # 计算指标
        recent_ic = self.get_recent_ic(factor_name)
        historical_mean = self.get_historical_mean(factor_name)
        icir = self.calculate_icir(factor_name)
        monotonicity = self.check_monotonicity(factor_name)
        
        # 判断状态
        status = 'passed'
        suggestions = []
        
        if recent_ic is None or historical_mean is None:
            status = 'warning'
            suggestions.append("IC数据不足，无法评估")
        else:
            # 检查IC阈值
            if recent_ic < self.ic_threshold:
                status = 'failed'
                suggestions.append(f"近期IC={recent_ic:.3f} < 阈值{self.ic_threshold}")
            
            # 检查ICIR
            if icir is not None and icir < self.ir_threshold:
                if status == 'passed':
                    status = 'warning'
                suggestions.append(f"ICIR={icir:.2f} < 阈值{self.ir_threshold}（稳定性不足）")
            
            # 检查单调性
            if monotonicity == 'flipping':
                status = 'failed'
                suggestions.append("IC频繁反转，因子失效")
            elif monotonicity == 'unstable':
                if status == 'passed':
                    status = 'warning'
                suggestions.append("IC不稳定，建议观察")
            
            # 检查历史均值
            if abs(historical_mean) < self.ic_threshold * 0.5:
                if status == 'passed':
                    status = 'warning'
                suggestions.append(f"历史IC均值={historical_mean:.3f}偏低")
        
        # 生成建议
        if status == 'passed':
            suggestion = "因子有效，继续使用"
        elif status == 'warning':
            suggestion = "；".join(suggestions) + "，建议观察或降低权重"
        else:
            suggestion = "；".join(suggestions) + "，建议停用该因子"
        
        result = ICMonitorResult(
            factor_name=factor_name,
            status=status,
            recent_ic=recent_ic or 0,
            historical_mean=historical_mean or 0,
            icir=icir or 0,
            monotonicity=monotonicity,
            suggestion=suggestion,
            check_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        
        # 缓存结果
        self._last_check[factor_name] = result
        
        return result
    
    def check_all_factors(self, factor_configs: Dict[str, Dict]) -> List[ICMonitorResult]:
        """
        批量检查所有因子
        
        Args:
            factor_configs: 因子配置字典，键为因子名，值为包含'ic_history'的字典
            
        Returns:
            list: 检查结果列表
        """
        results = []
        
        for factor_name, config in factor_configs.items():
            ic_history = config.get('ic_history', [])
            result = self.check_factor(factor_name, ic_history)
            results.append(result)
        
        return results
    
    def generate_report(self) -> str:
        """
        生成监控报告
        
        Returns:
            str: 报告文本
        """
        lines = [
            "=" * 60,
            "因子IC监控报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 60,
            ""
        ]
        
        if not self._last_check:
            lines.append("⚠️ 暂无监控数据")
            return "\n".join(lines)
        
        # 分类统计
        passed = []
        warning = []
        failed = []
        
        for name, result in self._last_check.items():
            if result.status == 'passed':
                passed.append(result)
            elif result.status == 'warning':
                warning.append(result)
            else:
                failed.append(result)
        
        # 输出统计
        lines.append(f"检查因子数: {len(self._last_check)}")
        lines.append(f"  ✅ 有效: {len(passed)}")
        lines.append(f"  ⚠️ 警告: {len(warning)}")
        lines.append(f"  ❌ 失效: {len(failed)}")
        lines.append("")
        
        # 详细结果
        if failed:
            lines.append("【失效因子】")
            for r in failed:
                lines.append(f"  ❌ {r.factor_name}: {r.suggestion}")
            lines.append("")
        
        if warning:
            lines.append("【警告因子】")
            for r in warning:
                lines.append(f"  ⚠️ {r.factor_name}: {r.suggestion}")
            lines.append("")
        
        if passed:
            lines.append("【有效因子】")
            for r in passed:
                lines.append(f"  ✅ {r.factor_name}: IC={r.recent_ic:.3f}, IR={r.icir:.2f}")
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)
    
    def save_results(self, output_path: str = None):
        """
        保存监控结果
        
        Args:
            output_path: 输出路径，默认为data/ic_monitor_results.json
        """
        if output_path is None:
            project_path = Path(__file__).parent.parent.parent  # 基地化S3: 根锚点(core/scoring→仓库根)
            output_path = Path(project_path) / 'data' / 'ic_monitor_results.json'
        
        results = {
            'check_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'results': {name: result.to_dict() for name, result in self._last_check.items()}
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"✅ IC监控结果已保存: {output_path}")
    
    def load_ic_history(self, factor_name: str, history_path: str = None) -> List[Dict]:
        """
        从文件加载IC历史数据
        
        Args:
            factor_name: 因子名称
            history_path: 历史数据路径
            
        Returns:
            list: IC历史记录
        """
        if history_path is None:
            # 默认路径
            project_path = Path(__file__).parent.parent.parent  # 基地化S3: 根锚点(core/scoring→仓库根)
            history_path = Path(project_path) / 'data' / 'factor_ic_history.json'
        
        if not Path(history_path).exists():
            print(f"⚠️ IC历史文件不存在: {history_path}")
            return []
        
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(factor_name, [])
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ 加载IC历史失败: {e}")
            return []


def check_factor_effectiveness(
    factor_name: str,
    ic_history: Optional[List[Dict]] = None,
    window: int = 20
) -> ICMonitorResult:
    """
    便捷函数：检查单个因子有效性
    
    Args:
        factor_name: 因子名称
        ic_history: IC历史数据
        window: 滚动窗口
        
    Returns:
        ICMonitorResult: 检查结果
    """
    monitor = FactorICMonitor(window=window)
    return monitor.check_factor(factor_name, ic_history)


def run_ic_monitor(batch_mode: bool = False) -> str:
    """
    运行IC监控（可作为独立脚本）
    
    Args:
        batch_mode: 是否批量模式
        
    Returns:
        str: 监控报告
    """
    monitor = FactorICMonitor()
    
    if batch_mode:
        # 批量模式：从文件加载所有因子历史
        project_path = Path(__file__).parent.parent.parent  # 基地化S3: 根锚点(core/scoring→仓库根)
        history_file = Path(project_path) / 'data' / 'factor_ic_history.json'
        
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                all_history = json.load(f)
            
            results = monitor.check_all_factors(all_history)
            
            # 保存结果
            monitor.save_results()
            
            return monitor.generate_report()
        else:
            return "⚠️ 未找到IC历史数据文件"
    else:
        # 单因子模式
        # TODO: 从命令行参数读取因子名
        return "请指定因子名称或使用batch_mode"


if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("factor_ic_monitor.py 测试")
    print("=" * 60)
    
    # 测试1: 创建监控器
    monitor = FactorICMonitor(window=20)
    print("\n✅ 监控器初始化成功")
    
    # 测试2: 添加模拟数据
    test_history = [
        {'date': '2026-09-01', 'ic': 0.05},
        {'date': '2026-09-02', 'ic': 0.04},
        {'date': '2026-09-03', 'ic': 0.06},
        {'date': '2026-09-04', 'ic': 0.03},
        {'date': '2026-09-05', 'ic': 0.07},
    ]
    
    monitor.add_ic_records('chg5', test_history)
    print("✅ 添加测试数据成功")
    
    # 测试3: 检查因子
    result = monitor.check_factor('chg5')
    print(f"\n📊 因子检查: {result.factor_name}")
    print(f"   状态: {result.status}")
    print(f"   近期IC: {result.recent_ic:.3f}")
    print(f"   历史均值: {result.historical_mean:.3f}")
    print(f"   ICIR: {result.icir:.2f}")
    print(f"   建议: {result.suggestion}")
    
    # 测试4: 生成报告
    report = monitor.generate_report()
    print(f"\n{report}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
