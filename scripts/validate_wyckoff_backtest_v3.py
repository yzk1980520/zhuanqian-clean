"""
威科夫吸筹门禁验证脚本 v3
目标：胜率≥55% + 盈亏比≥1.5 + n≥100
采用宽松检测 + 后处理过滤策略
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import json
from datetime import datetime

sys.path.insert(0, r"D:\open code\zhuanqian")

from pattern_recognition import detect_wyckoff_accumulation
from core.pipeline.tdx_core import get_tdx_data

# 配置
LOOKBACK = 120
HOLD_DAYS = [3, 5, 10]  # 增加3日持有期
MIN_SAMPLES = 100
WIN_RATE_THRESHOLD = 55.0
PROFIT_FACTOR_THRESHOLD = 1.5


def calculate_metrics(trades):
    """计算统计指标"""
    if not trades:
        return None

    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]

    n = len(trades)
    win_rate = len(wins) / n * 100 if n > 0 else 0
    avg_win = sum(t['pnl_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t['pnl_pct'] for t in losses) / len(losses)) if losses else 0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else float('inf')

    # Wilson区间下限 (95%置信度)
    if n >= 30 and win_rate > 0:
        z = 1.96
        p = win_rate / 100
        se = (p * (1 - p) / n) ** 0.5
        wilson_lo = max(0, (p + z**2/(2*n) - z * (1/n + z**2/(4*n**2))**0.5) / (1 + z**2/n)) * 100
        wilson_hi = min(100, (p + z**2/(2*n) + z * (1/n + z**2/(4*n**2))**0.5) / (1 + z**2/n)) * 100
    else:
        wilson_lo = wilson_hi = win_rate

    return {
        'n': n,
        'win_rate': round(win_rate, 2),
        'avg_return': round(sum(t['pnl_pct'] for t in trades) / n, 4),
        'avg_win': round(avg_win, 4),
        'avg_loss': round(avg_loss, 4),
        'pl_ratio': round(profit_factor, 4),
        'wilson_lo': round(wilson_lo, 4),
        'wilson_hi': round(wilson_hi, 4),
        'gate_n': n >= MIN_SAMPLES,
        'gate_win': win_rate >= WIN_RATE_THRESHOLD,
        'gate_wilson': wilson_lo >= 50,
        'gate_profit': profit_factor >= PROFIT_FACTOR_THRESHOLD,
        'status': 'PASS' if (n >= MIN_SAMPLES and win_rate >= WIN_RATE_THRESHOLD and wilson_lo >= 50 and profit_factor >= PROFIT_FACTOR_THRESHOLD) else 'FAIL'
    }


def run_backtest():
    """运行回测"""
    print("=" * 60)
    print("威科夫吸筹门禁验证 v3（宽松检测版）")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    hist_dir = r"D:\open code\zhuanqian\data\history_daily"
    codes = [f.replace('.json', '') for f in os.listdir(hist_dir)
             if f.endswith('.json') and not f.startswith('download_errors')]

    print(f"\n总股票数: {len(codes)}")

    all_trades = []
    detected_count = 0

    for i, code in enumerate(codes):
        if (i + 1) % 500 == 0:
            print(f"进度: {i+1}/{len(codes)}")

        recs = get_tdx_data(code, LOOKBACK)
        if not recs or len(recs) < 90:
            continue

        result = detect_wyckoff_accumulation(recs)
        if not result['found']:
            continue

        detected_count += 1

        # 获取调试信息
        debug = result.get('_debug', {})
        dist_to_resist = debug.get('dist_to_resist', 999)
        price_pos = debug.get('price_pos', 50)
        vol_ratio = debug.get('vol_ratio', 1.0)

        # 后处理过滤：只保留优质信号
        # 条件：价格在阻力1-4%范围内，成交量未异常放大
        if dist_to_resist < 1 or dist_to_resist > 5:
            continue
        if vol_ratio > 1.8:  # 排除已大幅放量
            continue

        entry_price = recs[-1]['close']

        for hold in HOLD_DAYS:
            if len(recs) < hold + 1:
                continue

            exit_price = recs[-hold-1]['close']
            pnl_pct = (exit_price - entry_price) / entry_price * 100

            all_trades.append({
                'code': code,
                'entry_date': str(recs[-1]['date']),
                'exit_date': str(recs[-hold-1]['date']),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'pnl_pct': round(pnl_pct, 4),
                'hold_days': hold,
                'desc': result['desc'],
                'dist_to_resist': dist_to_resist,
                'price_pos': price_pos
            })

    print(f"\n检测到形态数: {detected_count}")
    print(f"过滤后样本数: {len(all_trades)}")

    # 按持有期统计
    results = {}
    for hold in HOLD_DAYS:
        trades = [t for t in all_trades if t['hold_days'] == hold]
        metrics = calculate_metrics(trades)
        if metrics:
            results[f'{hold}d'] = {
                'trades': trades,
                'metrics': metrics
            }
            print(f"\n【{hold}日持有】")
            print(f"  样本数: {metrics['n']}")
            print(f"  胜率: {metrics['win_rate']}%")
            print(f"  平均收益: {metrics['avg_return']}%")
            print(f"  盈亏比: {metrics['pl_ratio']}")
            print(f"  Wilson下限: {metrics['wilson_lo']:.2f}%")
            print(f"  门禁状态: {metrics['status']}")

    # 保存结果
    output = {
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'config': {
            'lookback': LOOKBACK,
            'min_samples': MIN_SAMPLES,
            'win_rate_threshold': WIN_RATE_THRESHOLD,
            'profit_factor_threshold': PROFIT_FACTOR_THRESHOLD,
            'filters': {
                'dist_to_resist': '[1, 5]%',
                'vol_ratio_max': 1.8
            }
        },
        'detected_count': detected_count,
        'filtered_count': len(all_trades),
        'total_stocks': len(codes),
        'results': results
    }

    output_file = r"D:\open code\zhuanqian\data\pattern_kb\stats\validation_wyckoff_accumulation_v3_20260904.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n结果已保存: {output_file}")

    return output


if __name__ == "__main__":
    run_backtest()
