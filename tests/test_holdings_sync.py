#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓数据同步测试
验证: holdings.json ↔ real_holdings.json 字段映射正确性

R-2 修复（2026-10-16 老六L2审查）：
  补真实测试用例，import sync_holdings 模块
  覆盖：源空→False / 正常同步→字段正确 / 写入失败→loud fail
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))  # 确保能 import sync_holdings（在 scripts/ 下）

# Import 被测模块（R-2 修复）
import sync_holdings

def test_holdings_fields_mapping():
    """测试1: holdings.json 字段映射到看板预期格式"""
    holdings_path = ROOT / "data" / "holdings.json"
    assert holdings_path.exists(), "holdings.json 不存在"
    
    with open(holdings_path, encoding="utf-8") as f:
        h = json.load(f)
    
    # 验证结构
    assert "holdings" in h, "缺少 holdings 数组"
    assert isinstance(h["holdings"], list), "holdings 应为数组"
    
    # 检查603727持仓
    if h["holdings"]:
        pos = h["holdings"][0]
        # 支持两种字段名: 新版(symbol)或旧版(code)
        symbol = pos.get("symbol") or pos.get("code")
        assert symbol == "sh603727", f"期望sh603727, 实际{symbol}"
        
        # 成本字段兼容
        cost = pos.get("avg_cost") or pos.get("cost") or pos.get("cost_price")
        assert cost > 0, f"成本字段缺失: {pos}"
        
        # 股数字段
        shares = pos.get("shares")
        assert shares > 0, f"股数字段缺失: {pos}"
        
        print(f"✅ 字段映射正确: {symbol} {shares}股 @ {cost}")

def test_real_holdings_sync():
    """测试2: real_holdings.json 已归档，data/ 下不应残留（A2 单源约束）"""
    real_holdings_path = ROOT / "data" / "real_holdings.json"
    assert not real_holdings_path.exists(), f"real_holdings.json 应已归档，但残留于 {real_holdings_path} — A2 将 FAIL"
    print(f"✅ A2 约束验证: real_holdings.json 不存在于 data/（已归档至 .trash/）")

def test_board_server_field_access():
    """测试3: board_server.py 字段访问兼容性"""
    # 模拟board_server的字段访问逻辑
    holdings_path = ROOT / "data" / "holdings.json"
    
    with open(holdings_path, encoding="utf-8") as f:
        h = json.load(f)
    
    for pos in h.get("holdings", []):
        # 兼容新旧字段名
        code = pos.get("code") or pos.get("symbol", "")
        name = pos.get("name", "")
        cost = pos.get("cost") or pos.get("cost_price") or pos.get("avg_cost", 0)
        shares = pos.get("shares", 0)
        current = pos.get("last_price") or pos.get("market_price") or cost
        
        assert code, f"code/symbol缺失: {pos}"
        assert name, f"name缺失: {pos}"
        assert cost > 0, f"cost字段缺失: {pos}"
        
        print(f"✅ 字段可访问: {code} {name} 成本{cost}")


def test_save_json_atomic_write():
    """测试4: save_json 原子写 + read-back 断言（R-1 + R-2）"""
    # 创建临时目录模拟 QSP 路径
    tmpdir = tempfile.mkdtemp(prefix="sync_holdings_test_")
    test_file = Path(tmpdir) / "test_holdings.json"
    
    # 构造测试数据
    test_data = {
        "holdings": [{"code": "sh603727", "name": "吉华集团", "shares": 2700, "cost_price": 8.60}],
        "total_assets": 100000.0,
        "available_cash": 50000.0,
        "position_ratio": 0.5,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "test"
    }
    
    # 执行原子写
    success = sync_holdings.save_json(test_file, test_data, dry_run=False)
    assert success is True, "save_json 应返回 True"
    
    # Read-back 验证
    assert test_file.exists(), "文件应被创建"
    with open(test_file, encoding="utf-8") as f:
        readback = json.load(f)
    
    assert readback["updated_at"] == test_data["updated_at"], "updated_at 不匹配"
    assert readback["holdings"] == test_data["holdings"], "holdings 不匹配"
    
    # 清理
    test_file.unlink()
    os.rmdir(tmpdir)
    
    print("✅ save_json 原子写 + read-back 断言通过")


def test_save_json_readback_fail():
    """测试5: save_json atomic_dump 异常分支 → False（P1 真注入）

    P1 根因（老六二审）：
      旧版写入合法数据后 assert success is True → 恒过，
      三条失败分支（atomic_dump 异常 / read-back 读失败 / 断言不匹配）均未触发。

    修复：monkeypatch atomic_dump 抛异常 → 断言 success is False。
    验证可复现性：删掉 patch 守卫，测试应变 FAIL（loud fail 路径确认）。
    """
    from unittest.mock import patch

    tmpdir = tempfile.mkdtemp(prefix="sync_holdings_test_")
    test_file = Path(tmpdir) / "test_fail.json"
    test_data = {
        "holdings": [],
        "updated_at": "2026-10-16 12:00:00"
    }

    # 真注入：mock atomic_dump 抛异常 → 触发 L77-79 失败分支
    # 注意：atomic_dump 是 from core.pipeline.atomic_json import atomic_dump（函数内局部），
    # 故 patch target 为 core.pipeline.atomic_json.atomic_dump（每次 save_json 调用时重新导入,
    # 解析到真源模块命名空间 —— 2026-10-24 T051 C4 对齐: 根级 atomic_json 仅为 S4 shim,
    # patch shim 命名空间不影响函数内局部导入）。
    with patch("core.pipeline.atomic_json.atomic_dump") as mock_dump:
        mock_dump.side_effect = OSError("fake atomic_dump failure")
        success = sync_holdings.save_json(test_file, test_data, dry_run=False)

    # 断言 loud fail 路径触发：返回 False
    assert success is False, \
        "atomic_dump 抛异常时 save_json 应返回 False（loud fail 未触发 = P1 回归）"

    # 清理
    if test_file.exists():
        test_file.unlink()
    os.rmdir(tmpdir)

    print("✅ P1: atomic_dump 异常 → save_json 返回 False（loud fail 路径真断言）")


def test_sync_holdings_source_empty():
    """测试7: sync_holdings 源文件为空/缺失 → False（P2 补测，老六二审 §1 P2 项）"""
    from unittest.mock import patch

    tmpdir = tempfile.mkdtemp(prefix="sync_holdings_test_")
    empty_file = Path(tmpdir) / "empty_holdings.json"

    # 写一个空 JSON 对象（模拟源文件缺失/空内容）
    empty_file.write_text("{}", encoding="utf-8")

    # monkeypatch ZR_HOLDINGS 指向空文件
    with patch.object(sync_holdings, "ZR_HOLDINGS", empty_file):
        result = sync_holdings.sync_holdings(dry_run=True)

    assert result is False, \
        "源文件为空时 sync_holdings 应返回 False（L154-155 路径未覆盖 = P2 缺口）"

    # 清理
    empty_file.unlink()
    os.rmdir(tmpdir)

    print("✅ P2: 源空 → sync_holdings 返回 False")


def test_sync_holdings_import_verified():
    """测试6: 验证 sync_holdings 模块已被 import（R-2 假覆盖检测）"""
    # 检查模块是否存在关键函数
    assert hasattr(sync_holdings, "save_json"), "sync_holdings 应导出 save_json"
    assert hasattr(sync_holdings, "sync_holdings"), "sync_holdings 应导出 sync_holdings"
    assert hasattr(sync_holdings, "sync_qsp_holdings"), "sync_holdings 应导出 sync_qsp_holdings"
    
    # 验证 save_json 签名（接受 dry_run 参数，返回 bool）
    import inspect
    sig = inspect.signature(sync_holdings.save_json)
    params = list(sig.parameters.keys())
    assert "filepath" in params, "save_json 应有 filepath 参数"
    assert "data" in params, "save_json 应有 data 参数"
    assert "dry_run" in params, "save_json 应有 dry_run 参数"
    
    print("✅ sync_holdings 模块 import 验证通过")


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 持仓数据同步测试（R-1 + R-2 修复版）")
    print("=" * 60)
    print()
    
    try:
        test_holdings_fields_mapping()
        test_real_holdings_sync()
        test_board_server_field_access()
        test_save_json_atomic_write()
        test_save_json_readback_fail()
        test_sync_holdings_import_verified()
        test_sync_holdings_source_empty()
        print()
        print("=" * 60)
        print("✅ 全部测试通过（R-1+R-2+P1+P2）")
        print("=" * 60)
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ 测试失败: {e}")
        print("=" * 60)
        sys.exit(1)
