# -*- coding: utf-8 -*-
"""test_scan_range_zero.py — footgun: scan_range=0/None 应扫全部, 不是扫 0 (RED→GREEN)

根因 (2026-10-09 验证 B链全量时发现): scripts/auto_live_pipeline.py:164
`for filename in files[:scan_range]` 在 scan_range=0 时 → files[:0] = 空切片 = 扫 0 只,
输出"评分完成: 0只股票"假绿 (与 fault③ 同类: 静默空扫)。
修复: scan_range<=0 / None → 视为"扫全部", 不再被 0 值静默踩空。
seam: run_stock_selection(scan_range=0) 的 picks_latest.json total_scanned (应=fixture全量, 非0)。
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
        out.append({"date": "2026-09-01", "open": 10.0, "close": 10.0 + i * 0.01,
                    "high": 11.0, "low": 9.0, "volume": 1_000_000, "amount": 10_000_000,
                    **({"marker": marker} if marker else {})})
    return out


def _setup(tmp_path, monkeypatch):
    import auto_live_pipeline as ALP
    (tmp_path / "data").mkdir()
    (tmp_path / "config.json").write_text(json.dumps({"strategy": "趋势", "factor_weights": {}}), encoding="utf-8")
    hd = tmp_path / "data" / "history_daily"
    hd.mkdir()
    for code in ("sh600000", "sh600519", "sh600100"):
        (hd / f"{code}.json").write_text(json.dumps(_bars()), encoding="utf-8")  # 3 只都合法

    import tdx_core, tdx_score
    monkeypatch.setattr(tdx_core, "compute_indicators", lambda data: {"close": 10.0})
    monkeypatch.setattr(tdx_score, "score_stock", lambda inds, strategy=None: (90.0, ["ok"]))
    monkeypatch.setattr(ALP, "PROJECT_ROOT", tmp_path)
    return ALP


def test_scan_range_zero_scans_all(tmp_path, monkeypatch):
    """scan_range=0 → 扫全部 fixture (3只), 不再 files[:0] 空扫假绿"""
    ALP = _setup(tmp_path, monkeypatch)
    ALP.run_stock_selection(top_n=5, scan_range=0)
    out = json.loads((tmp_path / "data" / "picks_latest.json").read_text(encoding="utf-8"))
    assert out["total_scanned"] == 3, f"scan_range=0 应扫全部3只, 实际 {out['total_scanned']}"
    assert out["total_valid"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])
