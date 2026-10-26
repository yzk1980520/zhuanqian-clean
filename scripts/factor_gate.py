import core.pipeline.atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
factor_gate.py — 因子门禁系统 (2026-08-24)
==========================================
基于 QuantSkills backtest-overfit 技能
用于新因子/新策略上线前的过拟合检测

使用流程:
  1. 计算因子IC/IR
  2. 运行DSR/PBO检测
  3. 生成门禁报告
  4. 决定PASS/FAIL

门禁标准 (老大确认):
  - IC > 0.03 (信息系数)
  - IR > 0.3 (信息比率)
  - DSR > 0.5 (去通胀夏普)
  - PBO < 0.5 (过拟合概率)
  - 样本量 >= 100笔交易
"""
import json
import os
import numpy as np
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# ═══════════════════════════════════════════
#  门禁配置
# ═══════════════════════════════════════════
GATE_CONFIG = {
    "ic_threshold": 0.03,           # IC门槛
    "ir_threshold": 0.3,            # IR门槛
    "dsr_threshold": 0.5,           # DSR门槛
    "pbo_threshold": 0.5,           # PBO门槛（<50%通过）
    "min_trades": 100,              # 最小交易次数
    "min_trials": 1,                # 最少试验次数（必须申报）
}

# ═══════════════════════════════════════════
#  DSR/PBO 计算函数
# ═══════════════════════════════════════════

def compute_sharpe(returns: List[float], periods_per_year: int = 252) -> float:
    """计算夏普比率"""
    if not returns or len(returns) < 10:
        return 0.0
    arr = np.array(returns)
    mean_ret = np.mean(arr)
    std_ret = np.std(arr, ddof=1)
    if std_ret == 0:
        return 0.0
    return mean_ret / std_ret * np.sqrt(periods_per_year)


def compute_dsr(sharpe_star: float, n_trials: int, T: int, 
                skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """
    计算去通胀夏普比率 (Deflated Sharpe Ratio)
    
    公式参考: Bailey, Lopez de Prado, Zhang (2014)
    DSR = Phi(sqrt(T) * SR* - (1/sqrt(2)) * Phi^(-1)(1-1/e) * sqrt(ln(n)))
    
    参数:
        sharpe_star: 最佳 Sharpe
        n_trials: 试验次数
        T: 期数
        skew: 偏度（默认0，正态）
        kurtosis: 峰度（默认3，正态）
    """
    try:
        from scipy import stats
        constant = 1.0 / np.sqrt(2.0) * stats.norm.ppf(1 - 1.0 / np.e)
    except ImportError:
        # 无 scipy 时使用近似值
        constant = 0.849  # Phi^(-1)(1-1/e) / sqrt(2) 的近似值
    
    if T < 10 or n_trials < 1:
        return 0.0
    
    # 调整Sharpe（考虑偏度和峰度）
    psr = sharpe_star - (skew / 6.0 * sharpe_star**3) / np.sqrt(T)
    
    # DSR公式（近似）
    adjustment = constant * np.sqrt(np.log(n_trials))
    
    # 使用sigmoid近似Phi
    z = np.sqrt(T) * psr - adjustment
    dsr = 1.0 / (1.0 + np.exp(-0.07056 * z**3 - 1.5976 * z))
    
    return dsr


def estimate_pbo(sharpe_is: float, sharpe_oos: float, n_trials: int) -> float:
    """
    估算回测过拟合概率 (Probability of Backtest Overfitting)
    
    简化版：基于IS/OOS绩效差距估算
    精确版需要完整 trials_matrix（T×N）
    """
    if n_trials <= 1:
        return 0.0
    
    # 性能差距
    performance_drop = sharpe_is - sharpe_oos
    
    # 简易估算：差距越大，过拟合概率越高
    # 使用sigmoid函数映射到[0,1]
    pbo = 1.0 / (1.0 + np.exp(-2.0 * performance_drop))
    
    # 试验次数修正（试验越多，过拟合风险越高）
    trial_factor = min(n_trials / 10.0, 2.0)
    pbo = min(pbo * trial_factor, 1.0)
    
    return pbo


# ═══════════════════════════════════════════
#  门禁检测主函数
# ═══════════════════════════════════════════

class FactorGate:
    """因子门禁检测器"""
    
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or GATE_CONFIG
        self.results = {}
    
    def check_factor(self, 
                     ic: float,
                     ir: float,
                     sharpe_is: float,
                     sharpe_oos: Optional[float] = None,
                     n_trials: int = 1,
                     n_trades: int = 0,
                     factor_name: str = "unknown") -> Dict:
        """
        执行因子门禁检测
        
        参数:
            ic: 信息系数
            ir: 信息比率
            sharpe_is: 样本内夏普
            sharpe_oos: 样本外夏普（可选，用于PBO估算）
            n_trials: 试验次数（必须诚实申报）
            n_trades: 交易次数
            factor_name: 因子名称
        
        返回:
            门禁报告字典
        """
        report = {
            "factor_name": factor_name,
            "timestamp": datetime.now().isoformat(),
            "checks": {},
            "verdict": "PENDING",
            "details": []
        }
        
        # 1. IC/IR 门禁
        ic_pass = ic > self.config["ic_threshold"]
        ir_pass = ir > self.config["ir_threshold"]
        report["checks"]["ic"] = {
            "value": ic,
            "threshold": self.config["ic_threshold"],
            "passed": ic_pass
        }
        report["checks"]["ir"] = {
            "value": ir,
            "threshold": self.config["ir_threshold"],
            "passed": ir_pass
        }
        
        if not ic_pass:
            report["details"].append(f"IC={ic:.4f} < {self.config['ic_threshold']}，不通过")
        if not ir_pass:
            report["details"].append(f"IR={ir:.2f} < {self.config['ir_threshold']}，不通过")
        
        # 2. 样本量检查
        sample_pass = n_trades >= self.config["min_trades"]
        report["checks"]["sample_size"] = {
            "value": n_trades,
            "threshold": self.config["min_trades"],
            "passed": sample_pass
        }
        if not sample_pass:
            report["details"].append(f"样本量{n_trades} < {self.config['min_trades']}，建议补充数据")
        
        # 3. DSR 检测
        dsr = compute_dsr(sharpe_is, n_trials, n_trades)
        dsr_pass = dsr > self.config["dsr_threshold"]
        report["checks"]["dsr"] = {
            "value": dsr,
            "threshold": self.config["dsr_threshold"],
            "sharpe_is": sharpe_is,
            "n_trials": n_trials,
            "passed": dsr_pass
        }
        if not dsr_pass:
            report["details"].append(f"DSR={dsr:.3f} < {self.config['dsr_threshold']}，校正后夏普不显著")
        
        # 4. PBO 检测（如果有OOS数据）
        if sharpe_oos is not None:
            pbo = estimate_pbo(sharpe_is, sharpe_oos, n_trials)
            pbo_pass = pbo < self.config["pbo_threshold"]
            report["checks"]["pbo"] = {
                "value": pbo,
                "threshold": self.config["pbo_threshold"],
                "sharpe_is": sharpe_is,
                "sharpe_oos": sharpe_oos,
                "passed": pbo_pass
            }
            if not pbo_pass:
                report["details"].append(f"PBO={pbo:.1%} >= {self.config['pbo_threshold']}，疑似过拟合")
        
        # 5. 试验次数诚实申报检查
        trial_check = n_trials >= self.config["min_trials"]
        report["checks"]["trial_declaration"] = {
            "value": n_trials,
            "passed": trial_check
        }
        
        # 综合判定
        all_passed = all([
            ic_pass, ir_pass, sample_pass, dsr_pass, trial_check
        ])
        if sharpe_oos is not None:
            all_passed = all_passed and pbo_pass
        
        report["verdict"] = "PASS" if all_passed else "FAIL"
        report["metrics"] = {
            "ic": ic,
            "ir": ir,
            "sharpe_is": sharpe_is,
            "sharpe_oos": sharpe_oos,
            "dsr": dsr,
            "pbo": estimate_pbo(sharpe_is, sharpe_oos or sharpe_is, n_trials) if sharpe_oos is None else None,
            "n_trials": n_trials,
            "n_trades": n_trades
        }
        
        return report
    
    def save_report(self, report: Dict, output_path: str):
        """保存门禁报告"""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # 转换numpy类型为Python原生类型
        def convert(obj):
            if hasattr(obj, 'item'):
                return obj.item()
            raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")
        atomic_json.atomic_dump(report, output_path, ensure_ascii=False, indent=2, default=convert, encoding="utf-8")
        print(f"[OK] Report saved: {output_path}")
    
    def print_report(self, report: Dict):
        """打印门禁报告"""
        print("\n" + "="*60)
        print(f"因子门禁报告: {report['factor_name']}")
        print("="*60)
        print(f"Verdict: {report['verdict']}")
        print(f"\n指标:")
        for key, val in report['metrics'].items():
            if val is not None:
                print(f"  {key}: {val}")
        print(f"\n检查项:")
        for key, check in report['checks'].items():
            status = "[PASS]" if check.get('passed') else "[FAIL]"
            print(f"  {status} {key}: {check.get('value')}")
        if report['details']:
            print(f"\n备注:")
            for detail in report['details']:
                print(f"  - {detail}")
        print("="*60 + "\n")


# ═══════════════════════════════════════════
#  批量检测工具
# ═══════════════════════════════════════════

def batch_check(factor_results: List[Dict], output_dir: str = "data/gate_reports") -> List[Dict]:
    """
    批量检测多个因子
    
    参数:
        factor_results: 因子结果列表，每项包含:
            - factor_name: 因子名称
            - ic: 信息系数
            - ir: 信息比率
            - sharpe_is: 样本内夏普
            - sharpe_oos: 样本外夏普（可选）
            - n_trials: 试验次数
            - n_trades: 交易次数
    
    返回:
        报告列表
    """
    gate = FactorGate()
    reports = []
    
    for i, result in enumerate(factor_results):
        report = gate.check_factor(
            ic=result.get("ic", 0),
            ir=result.get("ir", 0),
            sharpe_is=result.get("sharpe_is", 0),
            sharpe_oos=result.get("sharpe_oos"),
            n_trials=result.get("n_trials", 1),
            n_trades=result.get("n_trades", 0),
            factor_name=result.get("factor_name", f"factor_{i+1}")
        )
        reports.append(report)
        
        # 保存单个报告
        gate.save_report(report, f"{output_dir}/{report['factor_name']}_gate.json")
    
    # 保存汇总报告
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total": len(reports),
        "pass": sum(1 for r in reports if r['verdict'] == "PASS"),
        "fail": sum(1 for r in reports if r['verdict'] == "FAIL"),
        "reports": reports
    }
    atomic_json.atomic_dump(summary, f"{output_dir}/summary.json", ensure_ascii=False, indent=2, encoding="utf-8")
    
    print(f"\n📊 批量检测完成: {summary['pass']}通过, {summary['fail']}失败")
    return reports


# ═══════════════════════════════════════════
#  命令行入口
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="因子门禁检测系统")
    parser.add_argument("--check", nargs="*", help="示例检测")
    parser.add_argument("--batch", help="批量检测JSON文件")
    parser.add_argument("--output", default="data/gate_reports", help="输出目录")
    
    args = parser.parse_args()
    
    gate = FactorGate()
    
    if args.check:
        # 示例检测
        print("=== 因子门禁系统 v1.0 ===")
        print("使用方法:")
        print('  python factor_gate.py --check "factor_name" --ic 0.05 --ir 0.5 --sharpe 1.2 --trials 23 --trades 128')
        print()
        print("示例:")
        print('  python factor_gate.py --check max_ret5 --ic -0.17 --ir 1.2 --sharpe 0.8 --trials 1 --trades 132')
    
    elif args.batch:
        with open(args.batch, 'r', encoding='utf-8') as f:
            results = json.load(f)
        batch_check(results, args.output)
    
    else:
        # 运行P17策略门禁检测示例
        print("=== P17移动止盈策略门禁检测 ===\n")
        
        # 从 p17_backtest_results.json 提取数据
        p17_path = os.path.join(os.path.dirname(__file__), "data", "p17_backtest_results.json")
        if os.path.exists(p17_path):
            with open(p17_path, 'r', encoding='utf-8') as f:
                p17_data = json.load(f)
            
            # 检测最佳配置
            best_config = "原方案_宽松_原方案"
            for result in p17_data.get("results", []):
                if result["key"] == best_config:
                    metrics = result.get("metrics", {})
                    print(f"检测配置: {best_config}")
                    print(f"  胜率: {metrics.get('win_rate', 0):.2f}%")
                    print(f"  avg_pnl: {metrics.get('avg_pnl', 0):.3f}%")
                    print(f"  profit_factor: {metrics.get('profit_factor', 0):.2f}")
                    print()
                    
                    # 执行门禁检测
                    # 假设Sharpe ≈ avg_pnl / std_pnl * sqrt(252)
                    avg_pnl = metrics.get("avg_pnl", 0)
                    std_pnl = metrics.get("std_pnl", 1)
                    sharpe = avg_pnl / std_pnl * np.sqrt(252) if std_pnl > 0 else 0
                    
                    report = gate.check_factor(
                        ic=0.05,  # 假设值，需实际计算
                        ir=0.5,   # 假设值
                        sharpe_is=sharpe,
                        n_trials=23,
                        n_trades=metrics.get("total_trades", 128),
                        factor_name=f"P17_{best_config}"
                    )
                    gate.print_report(report)
                    gate.save_report(report, f"{args.output}/p17_gate.json")
        else:
            print("⚠️ 未找到 p17_backtest_results.json")
            print("请先运行回测生成数据")
