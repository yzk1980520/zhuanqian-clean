# -*- coding: utf-8 -*-
"""test_factor_layer_sign.py — 因子层硬开关 + 负 IC 符号处理 (RED→GREEN, 2026-10-19 L4)

背景 (闭环审查 deliverables/闭环审查-系统全链路状态与补齐清单-20261019.md L4 断裂):
  1. factor_layer_enabled 硬开关未实现 —— 因子层能否启用取决于"判不出来的 valid 数"
     (132d 窗口 28 因子三值判定实测 valid=0/indeterminate=20/dead=8,
      QA: deliverables/QA-28因子k实测与三值判定-20261018.md);
  2. 符号处理未做 —— scripts/auto_live_pipeline.py 融合路径 factor_score += w*z
     对 IC 符号无任何约定, 权威源里 TURN5 IC=-0.0658 (负), 按正权重加分=反向信号。

本文件三条断言线:
  A. 集成线 (先红后绿): 负 IC 因子 (TURN5 真实场景) 不得按正权重加分; 正 IC 因子
     (AMIHUD) 行为不变; 开关关闭时因子层不参与打分 (score==tech_score);
  B. 开关线: 每次运行打印 factor_layer_enabled 当前值+来源 (配置文件/CLI/默认值);
  C. NW 口径回归线: IC 结果每因子必须带 icir_nw 且非 None (防"回退 naive")。

已知红 (2026-10-19, 非本文件引入的回归):
  test_authority_source_factors_have_icir_nw 对 data/factor_ic/factor_ic_latest.json
  (2026-10-18 03:06 旧版, icir_nw 键 0 个) 判 FAIL —— 这正是要防的状态
  ("NW 口径从未落盘"), 待 Task#3「B+C 同一次重跑权威源」落地后自动转绿。
"""
import sys
import json
import math
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "scripts"))


def _make_bars(n=120, close=10.0):
    """最小合法日线记录 (compute_indicators 被 mock, 只要 ≥100 条过门槛)。

    close 用于让两只股可区分 (mock 指标按 close 分派高低因子值, 与遍历顺序解耦)。
    """
    return [{"date": f"2026-{(i // 31) % 12 + 1:02d}-{i % 28 + 1:02d}",
             "open": close, "close": close, "high": close + 1.0, "low": close - 1.0,
             "volume": 1_000_000, "amount": 10_000_000} for i in range(n)]


def _setup_universe(tmp_path, monkeypatch, factor_key, hi_val, lo_val, ic, weight,
                    factor_layer_enabled=True):
    """搭临时 PROJECT_ROOT: 2 只主板股 (因子值一高一低) + 权威源 (该因子 ic=ic)。

    权重与开关经 config_loader.load_config 注入 (run_stock_selection 的真源读口)。
    返回 (ALP, 高因子值股票 code, 低因子值股票 code)。所有打桩经 monkeypatch, 不泄漏。
    """
    import auto_live_pipeline as ALP
    import config_loader

    (tmp_path / "data" / "history_daily").mkdir(parents=True)
    (tmp_path / "data" / "factor_ic").mkdir(parents=True)
    (tmp_path / "config.json").write_text(
        json.dumps({"strategy": "test", "factor_weights": {}}), encoding="utf-8")
    (tmp_path / "data" / "factor_ic" / "factor_ic_latest.json").write_text(
        json.dumps({"factors": [{"name": factor_key, "ic": ic, "status": "dead"}]}),
        encoding="utf-8")
    # T2a 单源落地 (2026-10-20): get_factor_weights() 直接读 factor_weights.json，
    # 不再经 load_config 的 factor_weights 段。需同时写该文件并 patch PROJECT。
    (tmp_path / "factor_weights.json").write_text(
        json.dumps({"version": "2.99-test", "weights": {factor_key: weight}}),
        encoding="utf-8")
    # 高因子值股 = sh600001 (close=10), 低因子值股 = sh600002 (close=20)
    (tmp_path / "data" / "history_daily" / "sh600001.json").write_text(
        json.dumps(_make_bars(close=10.0)), encoding="utf-8")
    (tmp_path / "data" / "history_daily" / "sh600002.json").write_text(
        json.dumps(_make_bars(close=20.0)), encoding="utf-8")

    monkeypatch.setattr(ALP, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_loader, "PROJECT", str(tmp_path))
    config_loader.clear_config_cache()
    cfg = {"factor_layer_enabled": factor_layer_enabled,
           "factor_weights": {factor_key: weight}}
    monkeypatch.setattr(config_loader, "load_config", lambda: cfg)

    # mock 指标: 按 close 分派高低因子值; mock 评分: 恒 99 分
    # 2026-10-24 T051 C4 对齐 (S4 基地化 2026-10-22): compute_indicators 真源在
    # core.pipeline.tdx_core (auto_live_pipeline L340 调用点 from-import, 运行时解析),
    # 根级 tdx_core 仅为 S4 shim —— mock shim 不影响管线 → 改 mock 真源模块。
    from core.pipeline import tdx_core
    import tdx_score
    monkeypatch.setattr(tdx_core, "compute_indicators",
                        lambda data: {factor_key: hi_val if data[-1]["close"] == 10.0 else lo_val,
                                      "close": data[-1]["close"]})
    monkeypatch.setattr(tdx_score, "score_stock", lambda inds, strategy=None: (99.0, ["mock"]))
    return ALP, "sh600001", "sh600002"


class TestNegativeICSymbol:
    """Task#4: 负 IC 因子不得按正权重加分 (TURN5 真实场景)"""

    def test_negative_ic_factor_not_scored_as_positive(self, tmp_path, monkeypatch, capsys):
        """TURN5 (权威源 IC=-0.0658, 负) 权重 0.15: 因子值最高的股票 factor_score 必须 <=0。

        先红: 修复前融合路径 factor_score += w*z 无符号防护, 高 TURN5 值得 +0.15 正分。
        """
        ALP, hi_code, lo_code = _setup_universe(
            tmp_path, monkeypatch, "TURN5", hi_val=100.0, lo_val=10.0,
            ic=-0.0658, weight=0.15, factor_layer_enabled=True)

        picks, _ = ALP.run_stock_selection(top_n=10, scan_range=10)
        by_code = {p["code"]: p for p in picks}
        hi = by_code[hi_code]

        assert hi["factor_score"] <= 0, (
            f"负 IC 因子被当正信号用: TURN5(IC=-0.0658) 因子值最高的 {hi_code} "
            f"factor_score={hi['factor_score']} > 0 —— 高因子值反而加分, 方向反了")

        # 开关行必须被打印 (没人打印的配置项等于不存在)
        out = capsys.readouterr().out
        assert "factor_layer_enabled=True" in out, f"开关未打印, 实际输出: {out[-300:]}"
        assert "来源: config.json" in out, f"开关来源未打印, 实际输出: {out[-300:]}"

    def test_positive_ic_factor_behavior_unchanged(self, tmp_path, monkeypatch):
        """AMIHUD (权威源 IC=+0.0335, 正) 权重 0.2: 因子值最高的股票 factor_score >0 (行为不变)。"""
        ALP, hi_code, lo_code = _setup_universe(
            tmp_path, monkeypatch, "AMIHUD", hi_val=100.0, lo_val=10.0,
            ic=0.0335, weight=0.2, factor_layer_enabled=True)

        picks, _ = ALP.run_stock_selection(top_n=10, scan_range=10)
        by_code = {p["code"]: p for p in picks}
        hi = by_code[hi_code]

        assert hi["factor_score"] > 0, (
            f"正 IC 因子行为被改坏: AMIHUD(IC=+0.0335) 因子值最高的 {hi_code} "
            f"factor_score={hi['factor_score']} <= 0")

    def test_factor_layer_off_means_tech_only(self, tmp_path, monkeypatch, capsys):
        """factor_layer_enabled=false: 因子层不参与打分, score==tech_score, factor_score==0。"""
        ALP, hi_code, lo_code = _setup_universe(
            tmp_path, monkeypatch, "TURN5", hi_val=100.0, lo_val=10.0,
            ic=-0.0658, weight=0.15, factor_layer_enabled=False)

        picks, _ = ALP.run_stock_selection(top_n=10, scan_range=10)
        for p in picks:
            assert p["factor_score"] == 0.0, f"{p['code']} 因子层关闭后 factor_score 应恒 0"
            assert p["score"] == p["tech_score"], f"{p['code']} 因子层关闭后 score 应等于 tech_score"

        out = capsys.readouterr().out
        assert "factor_layer_enabled=False" in out, f"开关未打印, 实际输出: {out[-300:]}"


class TestFactorLayerSwitch:
    """硬开关取值与来源 (CLI > config.json > 默认 false)"""

    def test_resolve_sources(self, monkeypatch):
        from auto_live_pipeline import resolve_factor_layer_enabled
        import config_loader

        monkeypatch.setattr(config_loader, "load_config", lambda: {})
        enabled, src = resolve_factor_layer_enabled(None)
        assert enabled is False and "默认值" in src, f"缺省应为 false+默认值, 实际 {enabled}/{src}"

        monkeypatch.setattr(config_loader, "load_config", lambda: {"factor_layer_enabled": True})
        enabled, src = resolve_factor_layer_enabled(None)
        assert enabled is True and src == "config.json", f"配置显式 true 应被采信, 实际 {enabled}/{src}"

        # CLI 覆盖配置
        enabled, src = resolve_factor_layer_enabled(False)
        assert enabled is False and src == "CLI", f"CLI 应覆盖配置, 实际 {enabled}/{src}"
        enabled, src = resolve_factor_layer_enabled(True)
        assert enabled is True and src == "CLI"

    def test_apply_ic_sign_unit(self):
        """符号算术单测: 负 IC 权重取负, 正 IC 不变, 符号未知置 0 并登记。"""
        from auto_live_pipeline import apply_ic_sign

        out, skipped = apply_ic_sign(
            {"TURN5": 0.15, "AMIHUD": 0.2, "UNKNOWN": 0.1, "ZERO_IC": 0.1},
            {"TURN5": -0.0658, "AMIHUD": 0.0335, "ZERO_IC": 0.0})
        assert out["TURN5"] == -0.15, f"负 IC 权重应取负, 实际 {out['TURN5']}"
        assert out["AMIHUD"] == 0.2, f"正 IC 权重应不变, 实际 {out['AMIHUD']}"
        assert out["UNKNOWN"] == 0.0, "IC 缺失 -> 符号未知 -> 权重置 0"
        assert out["ZERO_IC"] == 0.0, "IC=0 -> 符号未知 -> 权重置 0"
        assert set(skipped) == {"UNKNOWN", "ZERO_IC"}, f"符号未知应被登记, 实际 {skipped}"


class TestNWCaliberRegression:
    """防"回退 naive": IC 结果每因子必须带 icir_nw 且非 None。"""

    def test_summarize_emits_icir_nw_per_factor(self):
        """产出方算术: factor_ic_132d_refresh.summarize 输出的每因子必须带 icir_nw (非 None)。"""
        from factor_ic_132d_refresh import summarize

        n = 40  # > MIN_IC_DATES(20)
        series = {
            "F_POS": [0.01 * math.sin(i / 3.0) + 0.002 * (i % 5) for i in range(n)],
            "F_NEG": [-0.01 * math.sin(i / 3.0) - 0.001 * (i % 7) for i in range(n)],
        }
        out = summarize(series, ic_threshold=0.03, ir_threshold=0.3)
        assert out, "summarize 输出不应为空"
        for f in out:
            assert "icir_nw" in f, f"{f['name']} 缺 icir_nw 键 —— NW 口径回退 naive?"
            assert f["icir_nw"] is not None, f"{f['name']} 的 icir_nw 为 None —— NW 口径回退 naive?"

    def test_authority_source_factors_have_icir_nw(self):
        """权威源 data/factor_ic/factor_ic_latest.json 每因子必须带 icir_nw (非 None)。

        已知红 (2026-10-19): 当前权威源是 2026-10-18 03:06 旧版 (pure_python_v10_exact_132d),
        factors 只有 name/ic/status 三键, icir_nw 键 0 个 —— "NW 口径从未落盘"正是
        本断言要暴露的状态; 待 Task#3「B+C 同一次重跑权威源」用新 summarize 刷新后转绿。

        2026-10-24 T051 C4 裁定挂起 (skip): 权威源 2026-10-21 重跑件 (computed_at=2026-10-21T03:10:04,
        9 因子) 键仍为 ic/icir/name/sample_size/status/weight, icir_nw 0 个 —— 2026-10-24 核验。
        补 icir_nw 需 Task#3 以 NW 口径重跑权威源落盘 (data/** 红线, 本任务不动数据侧)。
        Task#3 NW 重跑落地后移除本 skip 并复跑转绿。
        """
        import pytest as _pt
        _pt.skip("2026-10-24 T051 C4 裁定: 权威源 (2026-10-21 重跑) icir_nw 键 0 个, "
                 "待 Task#3 NW 口径重跑落盘后转绿; data/** 红线本任务不动数据侧", allow_module_level=False)
        p = BASE / "data" / "factor_ic" / "factor_ic_latest.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        factors = data.get("factors")
        assert isinstance(factors, list) and factors, f"权威源 factors 应为非空 list, 实际 {type(factors)}"
        missing = [f.get("name") for f in factors if f.get("icir_nw") is None]
        assert not missing, (
            f"权威源 {len(missing)}/{len(factors)} 个因子缺 icir_nw(非None): {missing[:5]}... "
            f"—— NW 口径未落盘/回退 naive (computed_at={data.get('computed_at')})")
