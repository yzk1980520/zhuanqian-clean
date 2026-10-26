# -*- coding: utf-8 -*-
"""S1 全量回测（日合并缓存）"""
import sys, os, json, time
from pathlib import Path

# 自动检测项目根目录（支持从任意路径运行）
BASE = str(Path(__file__).parent.resolve())
if BASE not in sys.path:
    sys.path.insert(0, BASE)
CACHE_DIR = os.path.join(BASE, 'data/stock_cache')
MERGED_DIR = os.path.join(BASE, 'data/daily_cache')
os.makedirs(MERGED_DIR, exist_ok=True)

INITIAL_CAPITAL = 100000.0

def build_daily_cache():
    """构建日合并缓存：每个交易日一个 JSON 文件"""
    print('Building daily cache...')
    t0 = time.time()
    
    # 收集所有日期
    all_dates = set()
    for f in os.listdir(CACHE_DIR):
        if f.endswith('.json'):
            try:
                with open(os.path.join(CACHE_DIR, f), encoding='utf-8') as fh:
                    data = json.load(fh)
                all_dates.update(data.get('temporal', {}).keys())
            except (AttributeError, FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
                continue
    
    all_dates = sorted(all_dates)
    print(f'Total dates: {len(all_dates)}')
    
    # 按日期聚合
    for i, date in enumerate(all_dates):
        day_data = {}
        for f in os.listdir(CACHE_DIR):
            if not f.endswith('.json'):
                continue
            code = f.replace('.json', '')
            try:
                with open(os.path.join(CACHE_DIR, f), encoding='utf-8') as fh:
                    data = json.load(fh)
                if date in data.get('temporal', {}):
                    day_data[code] = data['temporal'][date]
            except (FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
                continue
        
        # 写入日合并缓存
        with open(os.path.join(MERGED_DIR, f'{date}.json'), 'w', encoding='utf-8') as f:
            json.dump(day_data, f, ensure_ascii=False, separators=(',', ':'))
        
        if (i + 1) % 100 == 0:
            print(f'  [{i+1}/{len(all_dates)}] {date}: {len(day_data)} stocks', flush=True)
    
    print(f'Daily cache built: {time.time()-t0:.1f}s')
    return all_dates

def score_stock(inds, cross, code):
    score = 50.0
    mom20 = inds.get('momentum_20', 0) or 0
    if mom20 > 5: score += 15
    elif mom20 > 2: score += 10
    elif mom20 > 0: score += 5
    elif mom20 < -5: score -= 15
    elif mom20 < -2: score -= 10
    
    rsi = inds.get('rsi14', 50) or 50
    if rsi < 30: score += 15
    elif rsi < 40: score += 10
    elif rsi > 70: score -= 15
    elif rsi > 60: score -= 5
    
    vr = inds.get('vol_ratio', 1.0) or 1.0
    if vr > 1.5: score += 10
    elif vr > 1.2: score += 5
    elif vr < 0.7: score -= 10
    
    if inds.get('gap_up'): score += 10
    if inds.get('gap_down'): score -= 5
    
    if cross and code in cross:
        mr = cross[code].get('mom_rank', 0.5)
        if mr >= 0.8: score += 12
        elif mr >= 0.6: score += 6
        elif mr <= 0.2: score -= 12
        elif mr <= 0.4: score -= 6
        
        vr_r = cross[code].get('vol_rank', 0.5)
        if 0.4 <= vr_r <= 0.8: score += 5
        elif vr_r > 0.95: score -= 5
    
    return min(100, max(0, score))

def cross_section(market_t):
    if not market_t:
        return {}
    factors = {'momentum_20': [], 'vol_ratio': [], 'rsi14': []}
    for code, inds in market_t.items():
        for f in factors:
            v = inds.get(f)
            if isinstance(v, (int, float)):
                factors[f].append(v)
    
    result = {}
    for code, inds in market_t.items():
        result[code] = {}
        for f, vals in factors.items():
            v = inds.get(f)
            if v is None or not vals:
                result[code][f'{f}_rank'] = 0.5
            else:
                result[code][f'{f}_rank'] = sum(1 for x in vals if x <= v) / len(vals)
    return result

def run_bt(timeline):
    """回测（从日合并缓存加载）"""
    trades = []
    holding = None
    cash = INITIAL_CAPITAL
    scan_days = set(timeline[i] for i in range(0, len(timeline), 5))
    
    for idx, day in enumerate(timeline):
        # 加载日数据
        day_file = os.path.join(MERGED_DIR, f'{day}.json')
        if not os.path.exists(day_file):
            continue
        with open(day_file, encoding='utf-8') as f:
            mt = json.load(f)
        
        if holding is not None:
            st = mt.get(holding['code'])
            if st and st.get('close', 0) > 0:
                price = st['close']
                high = st.get('high', price)
                if high > holding.get('high', 0):
                    holding['high'] = high
                
                reason = None
                if price < holding['buy_price'] * 0.92:
                    reason = 'hard_stop'
                else:
                    hp = holding.get('high', holding['buy_price'])
                    dd = (hp - price) / hp if hp > 0 else 0
                    if dd >= 0.12: reason = 'trail_12'
                    elif dd >= 0.08: reason = 'trail_8'
                    elif idx - holding['buy_idx'] > 120: reason = 'time_stop'
                
                if reason:
                    sell_p = price * 0.999
                    shares = holding['shares']
                    proceeds = sell_p * shares
                    comm = max(5.0, proceeds * 0.00025)
                    tax = proceeds * 0.0005
                    trades.append({
                        'code': holding['code'], 'buy_date': holding['buy_date'],
                        'sell_date': day, 'buy_price': holding['buy_price'],
                        'sell_price': sell_p, 'shares': shares,
                        'pnl': proceeds - holding['cost'] - comm - tax,
                        'return_pct': (sell_p / holding['buy_price'] - 1) * 100,
                        'holding_days': idx - holding['buy_idx'],
                        'exit_reason': reason,
                    })
                    cash += proceeds - comm - tax
                    holding = None
        
        if day in scan_days and holding is None:
            if mt:
                cross = cross_section(mt)
                cands = [(score_stock(c, cross, code), code) for code, c in mt.items()]
                cands = [(s, c) for s, c in cands if s >= 50]
                
                if cands:
                    cands.sort(key=lambda x: -x[0])
                    _, code = cands[0]
                    st = mt[code]
                    price = st.get('close', 0)
                    if price > 0 and (st.get('momentum_20', 0) or 0) <= 4.0:
                        shares = int(cash * 0.95 / (price * 1.001))
                        if shares > 0:
                            cost = shares * price * 1.001
                            holding = {'code': code, 'buy_date': day, 'buy_idx': idx,
                                       'buy_price': price, 'shares': shares,
                                       'cost': cost + max(5.0, cost * 0.00025),
                                       'high': price}
                            cash -= holding['cost']
    
    if not trades:
        return {'total_return_pct': 0, 'win_rate': 0, 'n_trades': 0, 'trades': []}
    eq = INITIAL_CAPITAL + sum(t['pnl'] for t in trades)
    ret = (eq / INITIAL_CAPITAL - 1) * 100
    wins = [t for t in trades if t['pnl'] > 0]
    wr = len(wins) / len(trades) * 100 if trades else 0
    return {'total_return_pct': ret, 'win_rate': wr, 'n_trades': len(trades), 'trades': trades}

# === Main ===
print('Step 1: Build daily cache')
all_dates = build_daily_cache()

print(f'\nStep 2: Run backtest')
test_dates = all_dates[-132:]
print(f'Testing: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)} days)')

t0 = time.time()
result = run_bt(test_dates)
elapsed = time.time() - t0

print(f'\nBacktest ({elapsed:.1f}s):')
print(f'  Total Return: {result["total_return_pct"]:.2f}%')
print(f'  Win Rate: {result["win_rate"]:.1f}%')
print(f'  Total Trades: {result["n_trades"]}')
if result['trades']:
    wins = [t for t in result['trades'] if t['pnl'] > 0]
    losses = [t for t in result['trades'] if t['pnl'] < 0]
    avg_win = sum(t['return_pct'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['return_pct'] for t in losses) / len(losses) if losses else 0
    print(f'  Avg Win: {avg_win:.2f}%')
    print(f'  Avg Loss: {avg_loss:.2f}%')
    
    from collections import Counter
    reasons = Counter(t['exit_reason'] for t in result['trades'])
    print(f'  Exit reasons: {dict(reasons)}')

with open('data/baseline_v2.json', 'w', encoding='utf-8') as f:
    json.dump({
        'stats': {k:v for k,v in result.items() if k != 'trades'},
        'trades': result['trades'],
        'period': f'{test_dates[0]} ~ {test_dates[-1]}',
        'n_days': len(test_dates),
    }, f, ensure_ascii=False, indent=2)
print('\nBaseline v2 saved: data/baseline_v2.json')
