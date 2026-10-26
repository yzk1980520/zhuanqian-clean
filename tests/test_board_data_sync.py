#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看板数据同步测试
测试seam: board_server.py 读取 holdings.json 的字段兼容性
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def test_holdings_field_compatibility():
    """测试1: holdings.json 字段与board_server.py期望一致"""
    holdings = load_json(ROOT / 'data' / 'holdings.json')
    positions = holdings.get('holdings', [])
    
    assert len(positions) > 0, "holdings为空"
    
    # 模拟board_server.py第155-159行的读取逻辑
    for pos in positions:
        code = pos.get("code", "")
        name = pos.get("name", "")
        cost = pos.get("cost", pos.get("cost_price", 0))
        shares = pos.get("shares", 0)
        sl_manual = pos.get("stop_loss")
        
        assert code, f"code字段缺失: {pos}"
        assert name, f"name字段缺失: {pos}"
        assert cost > 0, f"cost字段缺失或为0: {pos}"
        assert shares > 0, f"shares字段缺失或为0: {pos}"
        assert sl_manual is not None, f"stop_loss字段缺失: {pos}"
        
        print(f"✅ {code} {name}: cost={cost}, shares={shares}, stop={sl_manual}")

def test_holdings_sync_consistency():
    """测试2: real_holdings.json 已归档，data/ 下不应残留（A2 单源约束）"""
    rh_path = ROOT / 'data' / 'real_holdings.json'
    assert not rh_path.exists(), f"real_holdings.json 应已归档，但残留于 {rh_path} — A2 将 FAIL"
    print(f"✅ A2 约束验证: real_holdings.json 不存在于 data/（已归档至 .trash/）")

def test_board_server_rendering():
    """测试3: 模拟board_server.py的持仓卡片生成"""
    holdings = load_json(ROOT / 'data' / 'holdings.json')
    positions = holdings.get('holdings', [])
    
    # 模拟board_server.py的持仓卡片生成逻辑
    pos_cards = ""
    for pi, p in enumerate(positions[:5]):
        code = p.get("code", "")
        name = p.get("name", "")
        cost = p.get("cost", p.get("cost_price", 0))
        shares = p.get("shares", 0)
        sl_manual = p.get("stop_loss")
        
        # 检查是否成功提取字段
        assert code and name and cost > 0 and shares > 0, f"字段提取失败: {p}"
        
        # 生成简化的HTML（模拟board_server的逻辑）
        pnl = ((19.36 / cost) - 1) * 100 if cost > 0 else 0  # 假设现价
        pnl_cls = "pos" if pnl >= 0 else "neg"
        
        pos_cards += f"<div class='hold-card'>{name}</div>"
    
    assert len(pos_cards) > 0, "持仓卡片为空"
    print(f"✅ 持仓卡片生成成功: {len(positions)} 张")

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 看板数据同步测试")
    print("=" * 60)
    print()
    
    try:
        test_holdings_field_compatibility()
        test_holdings_sync_consistency()
        test_board_server_rendering()
        print()
        print("=" * 60)
        print("✅ 全部测试通过")
        print("=" * 60)
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ 测试失败: {e}")
        print("=" * 60)
        sys.exit(1)
