#!/usr/bin/env python3
"""Debug: Check score distribution on a scan day"""
import os, json

BASE = 'D:/open code/zhuanqian'
HISTORY_DIR = os.path.join(BASE, 'data/history_daily')

def score_stock(inds):
    if not inds: return 0.0
    close = inds.get('close')
    if close is None or close <= 0: return 0.0
    score = 50.0
    mom20 = inds.get('momentum_20')
    if mom20 is not None:
        if mom20 > 5: score += 15
        elif mom20 > 2: score += 10
        elif mom20 > 0: score += 5
        elif mom20 < -5: score -= 15
        elif mom20 < -2: score -= 10
    rsi = inds.get('rsi14')
    if rsi is not None:
        if rsi < 30: score += 15
        elif rsi < 40: score += 10
        elif rsi > 70: score -= 15
        elif rsi > 60: score -= 5
    vr = inds.get('vol_ratio')
    if vr is not None:
        if vr > 1.5: score += 10
        elif vr > 1.2: score += 5
        elif vr < 0.7: score -= 10
    if inds.get('gap_up'): score += 10
    if inds.get('gap_down'): score -= 5
    return min(100, max(0, score))

def compute_indicators(records):
    n = len(records)
    if n < 30: return {}
    closes = [r.get('close', 0) or 0 for r in records]
    volumes = [r.get('volume', 0) or 0 for r in records]
    opens = [r.get('open', 0) or 0 for r in records]
    
    temporal = {}
    for j in range(n):
        date = records[j].get('date')
        if not date: continue
        
        mom20 = None
        if j >= 20 and closes[j-20] > 0:
            mom20 = (closes[j] / closes[j-20] - 1) * 100
        
        vr = 1.0
        if j >= 20:
            a5 = sum(volumes[max(0,j-4):j+1]) / min(5, j+1)
            a20 = sum(volumes[max(0,j-19):j+1]) / 20
            vr = a5 / a20 if a20 > 0 else 1.0
        
        rsi = 50.0
        if j >= 14:
            gains = losses = 0
            for k in range(max(1,j-13), j+1):
                chg = closes[k] - closes[k-1]
                if chg > 0: gains += chg
                else: losses -= chg
            if losses > 0:
                rsi = 100 - 100 / (1 + gains/losses)
        
        gap_up = gap_down = False
        if j >= 1 and closes[j-1] > 0 and opens[j] > 0:
            gp = (opens[j] / closes[j-1] - 1) * 100
            gap_up = gp > 2.0
            gap_down = gp < -2.0
        
        temporal[date] = {
            'close': closes[j], 'momentum_20': mom20, 'vol_ratio': vr,
            'rsi14': rsi, 'gap_up': gap_up, 'gap_down': gap_down,
        }
    return temporal

# Load a few stocks for a specific date
test_date = '2026-09-04'
print(f'Checking scores on {test_date}')

scores = []
for f in os.listdir(HISTORY_DIR):
    if not f.endswith('.json'): continue
    code = f.replace('.json', '')
    try:
        with open(os.path.join(HISTORY_DIR, f)) as fh:
            records = json.load(fh)
        if not isinstance(records, list): continue
        temporal = compute_indicators(records)
        if test_date in temporal:
            s = score_stock(temporal[test_date])
            scores.append((s, code))
    except (AttributeError) as e:
        continue

scores.sort(key=lambda x: -x[0])
print(f'Stocks with data: {len(scores)}')
print(f'Top 10: {scores[:10]}')
print(f'Scores >= 60: {sum(1 for s, c in scores if s >= 60)}')
print(f'Scores >= 50: {sum(1 for s, c in scores if s >= 50)}')
print(f'Scores >= 40: {sum(1 for s, c in scores if s >= 40)}')
print(f'Scores >= 30: {sum(1 for s, c in scores if s >= 30)}')

# Check mom20 distribution
mom20s = [s for s, c in scores if s >= 50]
print(f'\nCandidates >= 50: {len(mom20s)}')
if mom20s:
    # Check how many pass chase ban
    pass_chase = 0
    for s, c in scores:
        if s >= 50:
            # Find mom20
            for f2 in os.listdir(HISTORY_DIR):
                if f2 == c + '.json':
                    try:
                        with open(os.path.join(HISTORY_DIR, f2)) as fh:
                            records = json.load(fh)
                        temporal = compute_indicators(records)
                        if test_date in temporal:
                            mom20 = temporal[test_date].get('momentum_20')
                            if mom20 is not None and mom20 <= 4.0:
                                pass_chase += 1
                    except (KeyError) as e:
                        pass
    print(f'Pass chase ban (mom20 <= 4): {pass_chase}')
