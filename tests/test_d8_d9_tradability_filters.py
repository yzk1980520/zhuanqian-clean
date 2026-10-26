# -*- coding: utf-8 -*-
"""
[守卫] D8/D9 选股池排除规则 — 回测侧三项"买入当时可知"过滤 (2026-10-19 老大拍板)

═══ 为什么 ═══
D8: 选股池排除 科创板(688)/创业板(300,301)/ST/退市/待退市。
回测侧**本来就有**: 板块白名单(tdx_data.ALLOWED_PREFIXES_SH/SZ, 688/300/北证/指数已排)
+ ST/*ST(backtest.is_st_only)。**缺的三项**:
  ① 退市整理期过滤(当时名称含"退")
  ② 价格地板 LIQUIDITY_MIN_PRICE = 5.0 元
  ③ ADV 地板 LIQUIDITY_MIN_AMT = 30_000_000 元(近20日均成交额)
实盘侧由 integrated_picker.apply_tradability_filter 把关; 回测不补同口径过滤,
就会买入实盘永远不会碰的票(退市整理期/垃圾价/无流动性) —— 回测结论不可信。

═══ 铁律: 只能排"买入当时可知"的状态 (违反即返工) ═══
回测里这三项都必须是**逐扫描日**判定, 不是整只剔除:
  · 价格/ADV 是逐 bar 量 —— 按"最终价/最终流动性"整只剔除 = 用2025年的状态
    删2021年的候选 = 前视偏差;
  · 名称表只有**最终名称快照**(无逐日名称) —— 按最终名称整只剔除含"退"的票,
    等于把"当时没戴帽、后来才退市"的票删光, 逆转 R9 幸存者偏差修复。
因此正确口径: 名称含"退"的票只禁买其**最后30根K线(退市整理期窗口, A股标准30个
交易日)内的扫描日**; 窗口外(当时未戴帽)必须保留候选资格。
本文件的 test_r9_* 用例就是把这条钉死。

═══ 先红后绿 ═══
本文件先写并确认 FAIL(实现前 filter_tradable_at 不存在 → import 即红),
再实现 backtest_rotation.filter_tradable_at + integrated_picker D9-3 显式化 → 全绿。
"""
import os
import sys
from datetime import date, timedelta

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

import backtest.backtest_rotation as BR  # noqa: E402


def _mk_recs(n, close=10.0, amount=50_000_000, start=date(2021, 1, 4)):
    """合成 n 根日线(日历日近似交易日 — 过滤逻辑只看日期大小与bar数量, 不依赖交易日历)。"""
    recs = []
    d = start
    for _ in range(n):
        recs.append({"date": d, "open": close, "high": close, "low": close,
                     "close": close, "amount": amount, "volume": int(amount / close)})
        d += timedelta(days=1)
    return recs


def _mk_scan_inds(codes):
    return [{"code": c, "inds": {"close": 10.0}, "weekly": {}} for c in codes]


# ── 一、回测侧三项过滤存在且生效(先红后绿的主断言) ──

def test_filters_exist():
    """三项过滤的函数与常量必须存在(实现前本测试 import 即 FAIL — 先红后绿)。"""
    assert hasattr(BR, "filter_tradable_at"), "回测侧缺少 D8/D9 逐扫描日可交易性过滤函数"
    assert BR.LIQUIDITY_MIN_PRICE == 5.0, "价格地板必须是老大口径 5.0, 禁止回测侧自降门槛"
    assert BR.LIQUIDITY_MIN_AMT == 30_000_000, "ADV 地板必须是老大口径 3000万, 禁止自降门槛"


def test_price_floor_excludes_and_boundary():
    """价格地板: 收盘<5元剔除; ==5元保留(与实盘 < 阈值同边界)。"""
    stocks = {"sh600001": _mk_recs(130, close=4.99)}
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600001"]), date(2021, 6, 1), stocks, {"sh600001": "测试甲"})
    assert kept == [] and excluded == [("sh600001", "price")]

    stocks = {"sh600002": _mk_recs(130, close=5.0)}
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600002"]), date(2021, 6, 1), stocks, {"sh600002": "测试乙"})
    assert [i["code"] for i in kept] == ["sh600002"] and excluded == []


def test_adv_floor_excludes_and_boundary():
    """ADV地板: 近20日均额<3000万剔除; ==3000万保留。"""
    stocks = {"sh600003": _mk_recs(130, amount=29_999_999)}
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600003"]), date(2021, 6, 1), stocks, {"sh600003": "测试丙"})
    assert kept == [] and excluded == [("sh600003", "liquidity")]

    stocks = {"sh600004": _mk_recs(130, amount=30_000_000)}
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600004"]), date(2021, 6, 1), stocks, {"sh600004": "测试丁"})
    assert [i["code"] for i in kept] == ["sh600004"] and excluded == []


def test_delisting_window_excluded():
    """退市整理期: 名称含"退"的票, 扫描日落在其最后30根K线窗口内 → 禁买。"""
    recs = _mk_recs(130)  # 2021-01-04 起130根, 末日=2021-05-13
    stocks = {"sh600005": recs}
    cache = {"sh600005": "退市测试"}
    # 窗口起点 = 倒数第30根 = 2021-04-14; 扫描日 2021-05-01 在窗口内
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600005"]), date(2021, 5, 1), stocks, cache)
    assert kept == [] and excluded == [("sh600005", "delisting")]


def test_r9_no_lookahead_outside_window():
    """R9 铁律: 同一只名称含"退"的票, 扫描日**在窗口外**(当时未戴帽) → 必须保留候选资格。
    整只剔除=用"后来退市"的事实删历史=前视偏差, 逆转幸存者偏差修复。"""
    recs = _mk_recs(130)
    stocks = {"sh600005": recs}
    cache = {"sh600005": "退市测试"}
    # 扫描日 2021-03-01 在窗口(2021-04-14起)之外 → 当时名称还没戴"退" → 保留
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600005"]), date(2021, 3, 1), stocks, cache)
    assert [i["code"] for i in kept] == ["sh600005"] and excluded == []


def test_normal_stock_unaffected():
    """普通票(主板/名称干净/价格流动性达标)不受三项过滤影响。"""
    stocks = {"sh600006": _mk_recs(130, close=10.0, amount=50_000_000)}
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600006"]), date(2021, 6, 1), stocks, {"sh600006": "正常票"})
    assert [i["code"] for i in kept] == ["sh600006"] and excluded == []


def test_adv_uses_window_ending_at_scan_date():
    """ADV 必须按"扫描日当时"的20根算, 不是全历史 —— 后来才枯竭的票在枯竭前可买。"""
    # 前120根日均额4000万(高于地板), 后40根枯竭到100万 → 扫描日在枯竭段之前 ADV 达标
    recs = _mk_recs(120, amount=40_000_000) + _mk_recs(
        40, amount=1_000_000, start=date(2021, 1, 4) + timedelta(days=120))
    stocks = {"sh600007": recs}
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600007"]), date(2021, 4, 1), stocks, {"sh600007": "先肥后瘦"})
    assert excluded == [], "枯竭发生前的扫描日不应被未来的枯竭连坐"
    # 扫描日落进枯竭段(最后40根内, 20根窗口全枯竭) → ADV 不达标 → 剔除
    kept, excluded = BR.filter_tradable_at(
        _mk_scan_inds(["sh600007"]), date(2021, 6, 12), stocks, {"sh600007": "先肥后瘦"})
    assert kept == [] and excluded == [("sh600007", "liquidity")]


# ── 二、实盘侧 D9-3「待退市」显式化 ──

def _load_root_picker():
    """按文件路径显式加载根目录 integrated_picker.py。

    为什么不能直接 import: 仓库里 integrated_picker/ 包与 integrated_picker.py 同名,
    包会遮蔽模块 —— 但包的 __init__ 冻结警告明示「生产权威入口 = 根目录
    integrated_picker.py」(python integrated_picker.py 直跑), 包版是 2026-09-23
    拆分未完成的简化版。两处 apply_tradability_filter 必须同口径, 都要测。
    """
    import importlib.util
    p = os.path.join(PROJECT, "integrated_picker.py")
    spec = importlib.util.spec_from_file_location("_integrated_picker_root_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _assert_delisting_explicit(apply_tradability_filter):
    """D9-3 断言: 退市整理期单列 delisting, ST 仍走 st, 排除集合不变。"""
    recs = _mk_recs(130, close=10.0, amount=50_000_000)
    # 名称含"退" → 独立原因 delisting(不再混入 st)
    ok, reason = apply_tradability_filter("sh600008", "退市显式", recs)
    assert ok is False and reason == "delisting", reason
    # ST/*ST 仍走 st
    ok, reason = apply_tradability_filter("sh600008", "*ST显式", recs)
    assert ok is False and reason == "st", reason
    # 正常票照常放行(排除集合不变, 只是原因可区分)
    ok, reason = apply_tradability_filter("sh600008", "正常显式", recs)
    assert ok is True and reason is None, reason


def test_live_side_delisting_reason_explicit_package():
    """包版(import core.pipeline.integrated_picker 实际拿到的)必须显式化。"""
    from core.pipeline.integrated_picker import apply_tradability_filter
    _assert_delisting_explicit(apply_tradability_filter)


def test_live_side_delisting_reason_explicit_root_module():
    """根目录生产权威入口(被包遮蔽, 按文件加载)必须显式化。"""
    _assert_delisting_explicit(_load_root_picker().apply_tradability_filter)
