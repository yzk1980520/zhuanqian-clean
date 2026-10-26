# -*- coding: utf-8 -*-
"""test_scan_error_registry.py — SOUL#9 收窄: run_stock_selection 异常登记 (RED→GREEN)

根因(门专家 C1 遗留#1): scripts/auto_live_pipeline.py:192 `except Exception: continue`
静默吞掉一切异常 (09-25 假绿的帮凶)。故障③ 时 3000 只全崩却只见 "0只股票", 无从排查。
修复: 异常分类登记 (data=文件/JSON 损坏, logic=指标/评分层 bug) + 采样进 picks_latest.json,
逻辑异常控制台告警 (限 5 条), 不再无声。

seam: run_stock_selection 产物 picks_latest.json 的 scan_errors 键 (独立计数断言)。
"""
import sys, json
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))


def _bars(marker=None, n=120):
    out = []
    for i in range(n):
        r = {"date": "2026-09-01", "open": 10.0, "close": 10.0 + i * 0.01,
             "high": 11.0, "low": 9.0, "volume": 1_000_000, "amount": 10_000_000}
        if marker:
            r["marker"] = marker
        out.append(r)
    return out


def _setup(tmp_path, monkeypatch):
    import auto_live_pipeline as ALP
    (tmp_path / "data").mkdir()
    (tmp_path / "config.json").write_text(
        json.dumps({"strategy": "趋势", "factor_weights": {}}), encoding="utf-8")
    hd = tmp_path / "data" / "history_daily"
    hd.mkdir()
    (hd / "sh600000.json").write_text(json.dumps(_bars()), encoding="utf-8")   # 正常
    (hd / "sh600519.json").write_text(json.dumps(_bars("boom")), encoding="utf-8")  # 触发逻辑异常
    (hd / "sh600100.json").write_text("not valid json{{{", encoding="utf-8")       # 数据损坏

    # 2026-10-24 T051 C4 对齐 (S4): 管线真源读口 = core.pipeline.tdx_core (根级 tdx_core 仅为 shim,
    # mock shim 不影响管线)
    import core.pipeline.tdx_core as tdx_core
    import tdx_score

    def fake_compute(data):
        if data and data[0].get("marker") == "boom":
            raise ValueError("boom: 逻辑层异常(模拟)")
        return {"close": 10.0}

    monkeypatch.setattr(tdx_core, "compute_indicators", fake_compute)
    monkeypatch.setattr(tdx_score, "score_stock", lambda inds, strategy=None: (90.0, ["ok"]))
    monkeypatch.setattr(ALP, "PROJECT_ROOT", tmp_path)
    return ALP


def test_logic_error_registered(tmp_path, monkeypatch):
    """指标/评分层异常 → logic_errors 计数 + 采样(代码+异常类名), 正常票仍进 picks"""
    ALP = _setup(tmp_path, monkeypatch)
    ALP.run_stock_selection(top_n=5, scan_range=10)  # 10 > 3文件, 扫全部
    out = json.loads((tmp_path / "data" / "picks_latest.json").read_text(encoding="utf-8"))
    se = out["scan_errors"]
    assert se["logic_errors"] == 1, f"应登记 1 条逻辑异常, 实际 {se['logic_errors']}"
    assert any(s["code"] == "sh600519" and s["kind"] == "logic" for s in se["samples"])
    assert any(s["error"].startswith("ValueError") for s in se["samples"] if s["code"] == "sh600519")
    # 正常票行为不变
    assert "sh600000" in [p["code"] for p in out["picks"]]


def test_data_error_registered(tmp_path, monkeypatch):
    """文件/JSON 损坏 → data_skipped 计数 (与逻辑异常分类, 不混)"""
    ALP = _setup(tmp_path, monkeypatch)
    ALP.run_stock_selection(top_n=5, scan_range=10)  # 扫全部 3 文件
    out = json.loads((tmp_path / "data" / "picks_latest.json").read_text(encoding="utf-8"))
    se = out["scan_errors"]
    assert se["data_skipped"] == 1
    assert any(s["code"] == "sh600100" and s["kind"] == "data" for s in se["samples"])
    # 分类互斥: 损坏文件不得计入 logic
    assert not any(s["code"] == "sh600100" and s["kind"] == "logic" for s in se["samples"])


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
