# -*- coding: utf-8 -*-
"""test_daily_pick_selection.py — daily_pick.py cron 入口选股修复 (故障②, RED→GREEN)

故障②根因: daily_pick.py 第4步 `from tdx_core import TDXCore; TDXCore().select_stocks(top_n=10)`
但 tdx_core 根本没有 TDXCore 类(只有函数) → cron 每日选股必崩, data/daily_picks 从未生成。
修复: 抽 daily_pick.select_picks(top_n) 委托 auto_live_pipeline.run_stock_selection
(唯一实盘路径, Slice1/2 已接主板白名单剔除), 移除 TDXCore 引用。

RED: select_picks 尚不存在(第4步还在用 TDXCore) → AttributeError + 源码仍含 TDXCore。
"""
import sys
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))


def test_select_picks_delegates_to_pipeline(monkeypatch):
    """select_picks 委托 run_stock_selection (剔除路径), top_n 透传, 只返回 picks

    2026-10-19: run_stock_selection 自 T2a 起返回 (picks, processed) 二元组,
    fake 按真实契约返回元组 —— 旧 fake 返回裸 list 会把"daily_pick 没解包"
    这个真 bug 掩盖掉 (P0-A 修复连带发现)。
    """
    import daily_pick
    import auto_live_pipeline

    captured = {}

    def fake_run_stock_selection(top_n=10, scan_range=3000):
        captured["top_n"] = top_n
        return [{"code": "sh600519", "score": 93.0, "details": []}], 3367

    monkeypatch.setattr(auto_live_pipeline, "run_stock_selection", fake_run_stock_selection)
    picks = daily_pick.select_picks(top_n=5)
    assert captured.get("top_n") == 5, "top_n 应透传给 run_stock_selection"
    assert picks == [{"code": "sh600519", "score": 93.0, "details": []}], "应解包只取 picks"


def test_no_broken_TDXCore_reference():
    """回归锁: daily_pick 不得再引用 tdx_core 里不存在的 TDXCore (cron 崩的根因)"""
    import daily_pick
    src = Path(daily_pick.__file__).read_text(encoding="utf-8")
    assert "TDXCore" not in src, "daily_pick.py 仍引用不存在的 TDXCore → cron 第4步会崩"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
