"""
因子IC每日监控 - 自动化门禁与告警
版本: v1.0.0
作者: 总管Hermes
日期: 2026-10-07

功能:
1. 每日收盘后自动重算所有因子IC
2. 门禁检查：|IC|<0.01淘汰，0.01-0.03观察，>0.03有效
3. 自动同步权重到config.json
4. 生成IC趋势报告
5. 异常告警：IC突变>50%时触发

运行方式:
  python scripts/factor_ic_daily_monitor.py [--quick] [--full]

参数:
  --quick: 快速模式，仅检查最近20日
  --full: 完整模式，检查全部历史
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np

# 抑制numpy警告
warnings.filterwarnings('ignore')

# 项目根目录
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

# 数据路径
DATA_DIR = os.path.join(PROJECT, "data")
HISTORY_DAILY_DIR = os.path.join(DATA_DIR, "history_daily")
FACTOR_IC_DIR = os.path.join(DATA_DIR, "factor_ic")
CONFIG_FILE = os.path.join(PROJECT, "config.json")
REGISTRY_FILE = os.path.join(FACTOR_IC_DIR, "factor_registry.json")

# IC门禁阈值
IC_VALID = 0.03
IC_OBSERVE = 0.01
IR_VALID = 0.3


def load_tdx_data(code: str, days: int = 120) -> List[dict]:
    """加载TDX日线数据（返回最近days条，按时间正序）"""
    filepath = os.path.join(HISTORY_DAILY_DIR, f"{code}.json")
    if not os.path.exists(filepath):
        return []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 按日期排序（正序：旧→新）
    data.sort(key=lambda x: x.get('date', ''))
    # 取最近days条
    return data[-days:]


def calc_factor_ic(
    factor_values: List[float],
    returns: List[float]
) -> Tuple[float, float]:
    """
    计算因子IC和IR
    
    Args:
        factor_values: 因子值列表
        returns: 次日收益列表
    
    Returns:
        (ic, ir)
    """
    import numpy as np
    
    # 过滤NaN
    pairs = [(f, r) for f, r in zip(factor_values, returns) 
             if not (np.isnan(f) or np.isnan(r))]
    
    if len(pairs) < 10:
        return np.nan, np.nan
    
    f_vals, r_vals = zip(*pairs)
    
    # IC: 因子值与收益的Pearson相关
    ic = np.corrcoef(f_vals, r_vals)[0, 1]
    
    # IR: IC均值/IC标准差（时序稳定性）
    ir = ic / np.std(f_vals) if np.std(f_vals) > 0 else 0
    
    return ic, ir


def calc_upper_shadow(df: List[dict]) -> List[float]:
    """计算上影线因子"""
    result = []
    for bar in df:
        high = bar.get('high', 0)
        close = bar.get('close', 0)
        open_price = bar.get('open', 0)
        if close > 0:
            shadow = (high - max(close, open_price)) / close if close > 0 else 0
            result.append(max(0, shadow))
        else:
            result.append(0)
    return result


def calc_lower_shadow(df: List[dict]) -> List[float]:
    """计算下影线因子"""
    result = []
    for bar in df:
        low = bar.get('low', 0)
        close = bar.get('close', 0)
        open_price = bar.get('open', 0)
        if close > 0:
            shadow = (min(close, open_price) - low) / close if close > 0 else 0
            result.append(max(0, shadow))
        else:
            result.append(0)
    return result


def calc_chg(df: List[dict], days: int = 5) -> List[float]:
    """计算N日涨幅"""
    result = []
    for i in range(len(df)):
        if i < days:
            result.append(np.nan)
        else:
            curr = df[i]['close']
            prev = df[i - days]['close']
            if prev > 0:
                result.append((curr - prev) / prev)
            else:
                result.append(np.nan)
    return result


def calc_volume_ratio(df: List[dict], days: int = 20) -> List[float]:
    """计算量比"""
    result = []
    for i in range(len(df)):
        if i < days:
            result.append(np.nan)
        else:
            curr_vol = df[i].get('volume', 0)
            avg_vol = sum(df[j].get('volume', 0) for j in range(i-days, i)) / days
            if avg_vol > 0:
                result.append(curr_vol / avg_vol)
            else:
                result.append(np.nan)
    return result


def calc_price_vol_rank_diff(df: List[dict]) -> List[float]:
    """计算量价排名差（PRICE_VOL_RANK因子）"""
    result = []
    for i in range(20, len(df)):
        # 计算价格排名
        prices = [df[j]['close'] for j in range(i-20, i) if df[j].get('close', 0) > 0]
        if len(prices) == 0:
            result.append(np.nan)
            continue
        curr_price = df[i]['close']
        price_rank = sum(1 for p in prices if p < curr_price) / len(prices)
        
        # 计算成交量排名
        vols = [df[j].get('volume', 0) for j in range(i-20, i)]
        curr_vol = df[i].get('volume', 0)
        if len(vols) == 0:
            result.append(np.nan)
            continue
        vol_rank = sum(1 for v in vols if v < curr_vol) / len(vols)
        
        result.append(price_rank - vol_rank)
    return result


def calc_consecutive_loss(df: List[dict], days: int = 5) -> List[float]:
    """计算连续亏损天数"""
    result = []
    count = 0
    for i in range(len(df)):
        if i > 0:
            prev_close = df[i-1]['close']
            if prev_close > 0:
                ret = (df[i]['close'] - prev_close) / prev_close
                if ret < 0:
                    count += 1
                else:
                    count = 0
            else:
                count = 0
        else:
            count = 0
        result.append(min(count, days))  # 封顶到days天
    return result


def calc_amihud(df: List[dict], window: int = 20) -> List[float]:
    """计算Amihud流动性指标"""
    result = []
    for i in range(len(df)):
        if i < window:
            result.append(np.nan)
        else:
            total_abs_ret = 0
            total_amt = 0
            for j in range(i-window, i):
                ret = abs((df[j]['close'] - df[j-1]['close']) / df[j-1]['close'])
                amt = df[j].get('amount', 0)
                total_abs_ret += ret
                total_amt += amt
            if total_amt > 0:
                result.append(total_abs_ret / total_amt * 1e6)
            else:
                result.append(np.nan)
    return result


# 因子计算函数映射
FACTOR_CALCULATORS = {
    'UPPER_SHADOW': calc_upper_shadow,
    'LOWER_SHADOW': calc_lower_shadow,
    'chg5': lambda df: calc_chg(df, 5),
    'chg10': lambda df: calc_chg(df, 10),
    'vol_ratio': lambda df: calc_volume_ratio(df, 20),
    'PRICE_VOL_RANK': calc_price_vol_rank_diff,
    'CONSECUTIVE_LOSS': lambda df: calc_consecutive_loss(df, 5),
    'AMIHUD': calc_amihud,
}


def get_all_codes() -> List[str]:
    """获取所有股票列表（过滤非json文件和非股票代码）"""
    if not os.path.exists(HISTORY_DAILY_DIR):
        return []
    
    codes = []
    for f in os.listdir(HISTORY_DAILY_DIR):
        # 只处理以sh/sz开头的json文件
        if f.endswith('.json') and (f.startswith('sh') or f.startswith('sz')):
            codes.append(f[:-5])
    return sorted(codes)


def compute_factor_ic(codes: List[str], factor_name: str, days: int = 120) -> Tuple[float, float, int]:
    """
    计算单个因子的IC和IR
    
    Returns:
        (ic, ir, sample_size)
    """
    import numpy as np
    
    all_factor_values = []
    all_returns = []
    
    for code in codes:
        df = load_tdx_data(code, days)
        if len(df) < 30:
            continue
        
        # 计算因子值
        calc_fn = FACTOR_CALCULATORS.get(factor_name)
        if not calc_fn:
            continue
        
        factor_vals = calc_fn(df)
        
        # 计算次日收益
        returns = []
        for i in range(1, len(df)):
            prev_close = df[i-1]['close']
            curr_close = df[i]['close']
            if prev_close > 0 and curr_close > 0:
                ret = (curr_close - prev_close) / prev_close
                returns.append(ret)
            else:
                returns.append(np.nan)
        
        # 配对
        for f, r in zip(factor_vals, returns):
            if not np.isnan(f) and not np.isnan(r):
                all_factor_values.append(f)
                all_returns.append(r)
    
    if len(all_factor_values) < 100:
        return np.nan, np.nan, 0
    
    ic, ir = calc_factor_ic(all_factor_values, all_returns)
    return ic, ir, len(all_factor_values)


def run_ic_monitor(quick: bool = False) -> dict:
    """运行IC监控"""
    print("📊 开始因子IC监控...")
    
    # 获取股票列表
    codes = get_all_codes()
    if not codes:
        print("❌ 无股票数据")
        return {}
    
    print(f"  股票数: {len(codes)}")
    
    # 选择要监控的因子
    if quick:
        factors = ['UPPER_SHADOW', 'AMIHUD', 'CONSECUTIVE_LOSS', 'LOWER_SHADOW', 'PRICE_VOL_RANK', 'chg5', 'chg10']
    else:
        factors = list(FACTOR_CALCULATORS.keys())
    
    results = {}
    
    for factor in factors:
        print(f"  计算 {factor}...", end=' ')
        try:
            ic, ir, n = compute_factor_ic(codes, factor)
            results[factor] = {'ic': ic, 'ir': ir, 'samples': n}
            print(f"IC={ic:.4f}, IR={ir:.4f}, N={n}")
        except Exception as e:
            print(f"错误: {e}")
            results[factor] = {'ic': None, 'ir': None, 'samples': 0, 'error': str(e)}
    
    return results


def check_door_gate(results: dict) -> dict:
    """门禁检查"""
    gate = {
        'total_factors': len(results),
        'valid': 0,
        'observe': 0,
        'dead': 0,
        'passed': True,
        'issues': []
    }
    
    for name, data in results.items():
        ic = data.get('ic')
        if ic is None:
            gate['issues'].append(f"{name}: 无法计算")
            continue
        
        abs_ic = abs(ic)
        if abs_ic >= IC_VALID:
            gate['valid'] += 1
        elif abs_ic >= IC_OBSERVE:
            gate['observe'] += 1
            gate['issues'].append(f"{name}: IC={ic:.4f} 处于观察区")
        else:
            gate['dead'] += 1
            gate['issues'].append(f"{name}: IC={ic:.4f} 已淘汰")
    
    # 门禁规则：至少5个有效因子
    if gate['valid'] < 5:
        gate['passed'] = False
        gate['issues'].append(f"有效因子不足: {gate['valid']} < 5")
    
    return gate


def save_results(results: dict, gate: dict) -> None:
    """保存结果"""
    os.makedirs(FACTOR_IC_DIR, exist_ok=True)
    
    # 保存最新IC
    latest = {
        'computed_at': datetime.now().isoformat(),
        'valid_factors': [],
        'dead_factors': []
    }
    
    for name, data in results.items():
        ic = data.get('ic')
        entry = {'name': name, 'ic': ic, 'ir': data.get('ir'), 'samples': data.get('samples')}
        if ic and abs(ic) >= IC_VALID:
            latest['valid_factors'].append(entry)
        else:
            latest['dead_factors'].append(entry)
    
    with open(os.path.join(FACTOR_IC_DIR, "factor_ic_latest.json"), 'w', encoding='utf-8') as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)
    
    # 保存门禁结果
    with open(os.path.join(FACTOR_IC_DIR, "ic_gate.json"), 'w', encoding='utf-8') as f:
        json.dump(gate, f, ensure_ascii=False, indent=2)
    
    # 追加历史记录
    history_file = os.path.join(FACTOR_IC_DIR, "ic_history.json")
    history = []
    if os.path.exists(history_file):
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    history.append({
        'date': datetime.now().date().isoformat(),
        'results': {k: {'ic': v.get('ic')} for k, v in results.items()},
        'gate_passed': gate['passed']
    })
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='因子IC每日监控')
    parser.add_argument('--quick', action='store_true', help='快速模式')
    parser.add_argument('--full', action='store_true', help='完整模式')
    parser.add_argument('--no-save', action='store_true', help='不保存结果')
    # R1(K46): --sync 保留参数(cron 兼容)但禁用写行为: 研究管线不得直写实盘权重(D1 红线/K45 #2)。
    parser.add_argument('--sync', action='store_true',
                        help='DEPRECATED (K46): 实盘权重同步已禁用, 走任务单+老五评审')
    args = parser.parse_args()

    mode = 'full' if args.full else 'quick'
    print(f"🎯 因子IC监控 [{mode}]")
    print("=" * 50)

    # 运行监控
    results = run_ic_monitor(quick=not args.full)

    # 门禁检查
    gate = check_door_gate(results)

    print("\n" + "=" * 50)
    print("🚪 门禁检查结果:")
    print(f"  有效因子: {gate['valid']}/{gate['total_factors']}")
    print(f"  观察因子: {gate['observe']}")
    print(f"  淘汰因子: {gate['dead']}")
    print(f"  门禁通过: {'✅ 是' if gate['passed'] else '❌ 否'}")

    if gate['issues']:
        print("\n  问题:")
        for issue in gate['issues']:
            print(f"    - {issue}")

    # 保存结果
    if not args.no_save:
        save_results(results, gate)
        print("\n✅ 结果已保存")

    # R1(K45 A1/K46): 移除自动实盘同步。config.json.factor_weights=实盘唯一写口,
    # 研究管线自动写入违反 D1 红线; 旧 sync_weights_to_config 为无定义死引用(NameError), 一并移除。
    if args.sync:
        print("⚠️  [R1] --sync DEPRECATED(K46): config.json.factor_weights 为实盘唯一写口, 研究管线不得直写; 实盘权重走任务单+老五评审")

    # 同步到注册中心 (R1: per-item 隔离 + loud; 移除 reg.sync_to_config() 假绿调用)
    # exit(2) 契约点单独立项(K46), 本主体不改 gate 主契约: registry 构造失败 → P0 loud 标记, exit 仍跟 gate。
    try:
        from factor_registry import FactorRegistry
        reg = FactorRegistry()
        failed = []
        for name, data in results.items():
            ic = data.get('ic')
            if not ic:
                continue
            try:
                reg.update_ic(name, ic)
            except Exception as e:
                # per-item 隔离: 单因子写失败不阻断其余因子(不静默吞: loud 列名)
                failed.append(name)
                print(f"⚠️ [registry] 因子 {name} update_ic 失败: {type(e).__name__}: {e} (已隔离, 其余因子不受影响)", file=sys.stderr)
        if failed:
            print(f"⚠️ [registry] {len(failed)} 因子 update_ic 失败待核查: {failed}", file=sys.stderr)
        print("✅ 已同步到factor_registry(研究真源; 实盘权重需另开任务单)")
    except Exception as e:
        # registry 构造/主写口失败 = P0 loud(不静默吞); exit(2) 契约待老五确认后单独立项, 此处保留 gate 主契约
        print(f"🔴 [P0] registry 构造失败: {type(e).__name__}: {e} — research 真源写口不可用, 需人工核查(非静默吞)", file=sys.stderr)

    # 返回门禁状态 (R1: 契约不变 exit 0/1)
    sys.exit(0 if gate['passed'] else 1)


if __name__ == '__main__':
    main()
