"""
修正持仓成本价
减仓后成本价应保持不变，不是按比例调整
"""
import json


def save_holdings(data, path='data/holdings.json'):
    """R4c #1 唯一写口（取代原 L44 裸 open('data/holdings.json','w')）。

    走 atomic_json.update_json: FileLock(跨进程) + tmp+fsync+os.replace+目录 fsync。
    写中断时目标文件保持写前原值（不被截断/半成品污染）。
    文件存在但读失败(损坏) → update_json 抛 RuntimeError(R4 防护), 拒绝静默覆盖。
    """
    # S4 基地化对齐 (2026-10-24 T051 C4): 裸 import 只绑定 core → atomic_json NameError
    from core.pipeline import atomic_json
    return atomic_json.update_json(path, lambda _fresh: data)


def main():
    with open('data/holdings.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    for h in data['holdings']:
        print(f"修正前: {h['name']}")
        print(f"  股数: {h['shares']}")
        print(f"  成本: {h['cost_price']}元")
        print(f"  现价: {h.get('last_price', h.get('market_price', 0))}元")

        # 修正成本价：保持原始成本不变
        # 原买入成本45.7元，减仓后成本仍为45.7元
        h['cost_price'] = 45.7

        # 重新计算浮盈
        current_price = h.get('last_price', h.get('market_price', 0))
        if current_price > 0:
            h['profit_pct'] = (current_price - h['cost_price']) / h['cost_price']
            h['profit_amt'] = (current_price - h['cost_price']) * h['shares']

        # 重新计算市值
        h['position_value'] = h['shares'] * current_price

        print(f"修正后: {h['name']}")
        print(f"  股数: {h['shares']}")
        print(f"  成本: {h['cost_price']}元")
        print(f"  浮盈: {h['profit_pct']*100:.2f}%")
        print(f"  浮盈金额: {h['profit_amt']:.2f}元")

    # 重新计算总资产和仓位
    total_position_value = sum(h['position_value'] for h in data['holdings'])
    total_cash = data['available_cash']
    total_assets = total_position_value + total_cash
    position_ratio = total_position_value / total_assets if total_assets > 0 else 0

    data['total_assets'] = total_assets
    data['position_ratio'] = position_ratio

    # R4c #1 改动①: 原子写（原 L44 裸 open('w') 根因修复）
    save_holdings(data)

    print(f"总资产: {total_assets:.2f}元")
    print(f"仓位比例: {position_ratio*100:.1f}%")


if __name__ == '__main__':
    # R4c #1 改动②: 顶层守护 — import 本模块不再执行修正/写盘（副作用隔离）
    main()
