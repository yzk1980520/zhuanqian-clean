# -*- coding: utf-8 -*-
"""test_live_board_filter_integration.py — run_stock_selection 集成剔除验证 (RED→GREEN)

Slice 2: 锁死"剔除真的接进实盘评分链路"。
seam = auto_live_pipeline.run_stock_selection(top_n, scan_range):
  临时 PROJECT_ROOT(隔离, 不碰生产) + mock 恒高分 + 临时池
  断言: 创业板/科创/ST/退市 即使打分最高, 也绝不进 picks; 主板非ST保留。
若不接线剔除, 它们会进 picks → RED。

Slice 3 (2026-10-19 P0-A 闭环审查): ST/退市段依赖 name 传入 ——
  is_tradable_code(code, name="") 的 `if name and is_st_stock(name)` 只在传了 name 时
  生效; 实盘链路曾调 is_tradable_code(code) 不传 name, ST/退市股全额进评分。
  名称表 stock_names.json 对白名单池覆盖率 100% (实测), 所以 name 一定拿得到,
  拿不到只能是没传 —— 本文件的 ST 用例就是把"传了 name"钉死。

注: run_stock_selection 自 T2a 起返回 (picks, processed) 二元组, 调用方须解包。
"""
import sys, json
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))


def _make_bars(n=120):
    # 最小合法日线记录 (compute_indicators 被 mock, 这里只要 ≥100 条过门槛即可)
    return [{"date": f"2026-{(i//31)%12+1:02d}-{i%28+1:02d}",
             "open": 10.0, "close": 10.0, "high": 11.0, "low": 9.0,
             "volume": 1_000_000, "amount": 10_000_000} for i in range(n)]


def test_run_stock_selection_excludes_gem(tmp_path, monkeypatch):
    """创业板即使恒打最高分, 也进不了 picks (剔除已接进评分链路)"""
    import auto_live_pipeline as ALP

    # 临时 PROJECT_ROOT: config + history_daily(创业板 1 只 + 主板 2 只)
    (tmp_path / "data" / "history_daily").mkdir(parents=True)
    (tmp_path / "config.json").write_text(json.dumps({"strategy": "基本面+", "factor_weights": {}}),
                                           encoding="utf-8")
    (tmp_path / "data" / "history_daily" / "sz300001.json").write_text(
        json.dumps(_make_bars()), encoding="utf-8")   # 创业板
    (tmp_path / "data" / "history_daily" / "sh600519.json").write_text(
        json.dumps(_make_bars()), encoding="utf-8")   # 沪主板
    (tmp_path / "data" / "history_daily" / "sz000001.json").write_text(
        json.dumps(_make_bars()), encoding="utf-8")   # 深主板

    monkeypatch.setattr(ALP, "PROJECT_ROOT", tmp_path)

    # mock 评分: 每只都打最高分(若没剔除, 创业板 300001 会凭分数进 top)
    # 2026-10-24 T051 C4 对齐 (S4): 根级 tdx_core 仅为 shim, mock 须落在真源 core.pipeline.tdx_core
    import core.pipeline.tdx_core as tdx_core
    import tdx_score
    monkeypatch.setattr(tdx_core, "compute_indicators", lambda data: {"close": 10.0})
    monkeypatch.setattr(tdx_score, "score_stock", lambda inds, strategy=None: (99.0, ["mock"]))

    picks, _processed = ALP.run_stock_selection(top_n=10, scan_range=10)
    codes = [p["code"] for p in picks]

    # 主板保留
    assert "sh600519" in codes, "主板 sh600519 应保留"
    assert "sz000001" in codes, "主板 sz000001 应保留"
    # 创业板被剔
    assert "sz300001" not in codes, "创业板 sz300001 已打最高分 99 却进了 picks → 剔除没接进链路"
    # 数量: 3 只里剔 1 创业板 → 2 只
    assert len(picks) == 2, f"应剩 2 只主板, 实际 {len(picks)}: {codes}"


def test_run_stock_selection_excludes_st_and_delisting(tmp_path, monkeypatch):
    """ST/退市即使恒打最高分, 也进不了 picks (P0-A: name 必须传进 is_tradable_code)

    RED 场景 (修复前): is_tradable_code(code) 不传 name → ST/退市段被短路 →
    sh600079(ST人福)/sz000004(国华退) 与主板票同分进 picks。
    GREEN 场景 (修复后): name 从 stock_names.json 传入, 两只在门禁处被挡。
    名称取自真实名称表 (tdx_data.load_name_cache 的键与 history_daily 文件名一致)。
    """
    import auto_live_pipeline as ALP
    from tdx_data import load_name_cache

    cache = load_name_cache()
    assert cache.get("sh600079", "").startswith("ST"), "名称表前提: sh600079 应为 ST 票"
    assert "退" in cache.get("sz000004", ""), "名称表前提: sz000004 名称应含'退'"

    # 临时 PROJECT_ROOT: 5 只 (主板干净×2 + ST×1 + 退市×1 + 创业板×1)
    (tmp_path / "data" / "history_daily").mkdir(parents=True)
    (tmp_path / "config.json").write_text(json.dumps({"strategy": "基本面+", "factor_weights": {}}),
                                           encoding="utf-8")
    for code in ("sh600519", "sz000001", "sh600079", "sz000004", "sz300001"):
        (tmp_path / "data" / "history_daily" / f"{code}.json").write_text(
            json.dumps(_make_bars()), encoding="utf-8")

    monkeypatch.setattr(ALP, "PROJECT_ROOT", tmp_path)

    # mock 评分: 每只都打最高分(若没剔除, ST/退市会凭分数进 top)
    # 2026-10-24 T051 C4 对齐 (S4): 根级 tdx_core 仅为 shim, mock 须落在真源 core.pipeline.tdx_core
    import core.pipeline.tdx_core as tdx_core
    import tdx_score
    monkeypatch.setattr(tdx_core, "compute_indicators", lambda data: {"close": 10.0})
    monkeypatch.setattr(tdx_score, "score_stock", lambda inds, strategy=None: (99.0, ["mock"]))

    picks, _processed = ALP.run_stock_selection(top_n=10, scan_range=10)
    codes = [p["code"] for p in picks]

    # 主板非 ST 保留
    assert "sh600519" in codes, "主板非ST sh600519 应保留"
    assert "sz000001" in codes, "主板非ST sz000001 应保留"
    # ST / 退市 被剔 (即使恒打 99 分)
    assert "sh600079" not in codes, "ST人福 打了99分却进了 picks → name 没传进 is_tradable_code"
    assert "sz000004" not in codes, "国华退 打了99分却进了 picks → name 没传进 is_tradable_code"
    # 创业板继续被剔
    assert "sz300001" not in codes, "创业板 sz300001 应继续被剔除"
    # 数量: 5 只里剔 ST/退市/创业板 3 只 → 2 只
    assert len(picks) == 2, f"应剩 2 只主板非ST, 实际 {len(picks)}: {codes}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
