# -*- coding: utf-8 -*-
"""refresh_holdings.py — 每日盘后刷新持仓现价（16:00 cron）
2026-08-26 P0: 从子代理手动操作升级为自动化闭环
"""
import sys, json, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date
sys.path = [p for p in sys.path if 'Python314' not in p]
sys.path.insert(0, PROJECT_ROOT)  # P1修复(20261023): S4迁移后误插core/pipeline/, 改仓库根
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'research_archive'))

from core.pipeline import tdx_core
from core.pipeline.atomic_json import atomic_dump, FileLock

R = PROJECT_ROOT  # P1修复(20261023): S4迁移后误指core/pipeline/, data/holdings.json与archive/在仓库根
# 2026-09-09 P0-4: 持仓真源统一为 data/holdings.json (写方对齐读方)
HOLDINGS = os.path.join(R, 'data', 'holdings.json')
ARCHIVE = os.path.join(R, 'archive')
os.makedirs(ARCHIVE, exist_ok=True)

# P0修复(2026-09-25): 读-改-写全程持有跨进程文件锁, 防与 record_trade/trade_tracker 并发丢更新
_hold_lock = FileLock(os.path.join(R, 'data', '.holdings_rw.lock'), timeout=60)
_hold_lock.acquire()
try:
    with open(HOLDINGS, encoding='utf-8') as f:
        h = json.load(f)
    # P1修复(2026-09-25): 强制修正position_ratio，避免门禁误判"已满仓"
    total_position = sum(pos.get('position_value', 0) for pos in h.get('holdings', []))
    h['total_assets'] = h.get('available_cash', 0) + total_position
    h['position_ratio'] = total_position / h['total_assets'] if h['total_assets'] > 0 else 0

    ts = date.today().strftime('%Y%m%d_%H%M%S')
    with open(os.path.join(ARCHIVE, f'holdings.bak_{ts}.json'), 'w', encoding='utf-8') as f:
        json.dump(h, f, ensure_ascii=False, indent=2)

    today = date.today().strftime('%Y-%m-%d')
    n_ok = 0
    for item in h.get('holdings', []):
        code = item.get('code')
        if not code:
            continue
        try:
            data = tdx_core.get_tdx_data(code, 20)
        except Exception as e:
            print(f'  ⚠️ {code}: {type(e).__name__}: {e}', file=sys.stderr)
            data = []
        if not data or len(data) < 1:
            continue
        latest = data[-1]
        highs = [d.get('high', 0) for d in data if d.get('high')]
        lows = [d.get('low', 0) for d in data if d.get('low')]
        cur = latest.get('close') or latest.get('price')
        if not cur:
            continue
        item['current'] = cur
        item['current_price'] = cur
        item['high'] = max(item.get('high', 0) or 0, max(highs) if highs else 0)
        # P1修复(2026-10-23·老三): 上版 `else 0` 在 lows 为空(TDX 20窗口全记录 low 缺失/0)时会把 low 水位清零,
        # 与 high=max 语义(空→0→保持原值)不对称 → 移动止盈参考线塌方风险。恢复空数据时保持原水位:
        item['low'] = min(item.get('low', 999) or 999, min(lows) if lows else item.get('low', 999) or 999)
        # P0修复(2026-10-23): 写方对齐读方 — 补写 last_price/market_price/position_value/pnl/pnl_pct
        item['last_price'] = cur
        item['market_price'] = cur
        shares = item.get('shares', 0)
        cost = item.get('cost_price', item.get('cost', 0))
        if shares > 0:
            item['position_value'] = cur * shares
            if cost > 0:
                item['pnl'] = round((cur - cost) * shares, 2)
                item['pnl_pct'] = round((cur - cost) / cost * 100, 4)
        d_val = latest.get('date')
        if hasattr(d_val, 'isoformat'):
            d_val = d_val.isoformat()
        elif d_val is not None:
            d_val = str(d_val)
        item['date'] = d_val or today
        item['market_date'] = d_val or today
        item['last_source'] = f'tdx_pipeline_{today}'
        n_ok += 1
        print(f'  {code} {item.get("name")} close={cur} high={item["high"]:.2f} low={item["low"]:.2f} shares={shares} pnl={item.get("pnl",0):.2f}')

    # P0修复: 用更新后的 position_value 重算 total_assets / position_ratio
    total_position = sum(pos.get('position_value', 0) for pos in h.get('holdings', []))
    h['total_assets'] = h.get('available_cash', 0) + total_position
    h['position_ratio'] = total_position / h['total_assets'] if h['total_assets'] > 0 else 0
    h['updated'] = today
    h['updated_at'] = f'{today}T{date.today().strftime("%H:%M:%S")}'
    h['price_asof'] = today
    atomic_dump(h, HOLDINGS)
    print(f'\nrefreshed {n_ok} holdings, updated={today}, position_ratio={h["position_ratio"]:.4f}')
finally:
    _hold_lock.release()  # P0修复(2026-09-25): 写完立即释放; 进程崩溃时 OS 自动释放 msvcrt 锁