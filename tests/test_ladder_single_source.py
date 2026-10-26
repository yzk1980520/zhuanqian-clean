# -*- coding: utf-8 -*-
"""
双源归一 TDD 测试 — TREND_TP_LADDER 单一真源
=================================================
SOUL#6 等价性锚定 + TDD red→green。

Seam（已确认）：
  A) risk_rules_engine.RiskEngine.calculate_tp_levels(trend) — 5 趋势键行为等价
  B) backtest_pipeline.BacktestConfig().tp_ladder 默认值 = S3 五档
  C) 单一真源 identity: risk_rules_engine.TREND_TP_LADDER 必须 IS risk_rules.TREND_TP_LADDER
     —— 归一前 RED（engine 自带副本 dict），归一后 GREEN（改 from risk_rules import）
  D) 死代码清除: backtest_pipeline.py 源码不得再含内联旧4档 fallback 字面量
     （grep 一手证据, 不进本 pytest; 见任务单 429/双源归一）

所有期望值均为独立手算（从权威源定义逐档算），非回读实现逻辑 → 非 tautological。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import risk_rules as rr
import risk_rules_engine as rre
from risk_rules_engine import RiskEngine
import backtest.backtest_pipeline as bp


# ═══════════════ 独立手算期望（权威源 S3 阶梯逐档） ═══════════════
# TREND_TP_LADDER["up"] = [(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]
# calculate_tp_levels(entry, trend) 返回 [(entry*(1+activate/100), tol/100), ...]
# entry=100 手算：
UP_100 = [(106.0, 0.0015), (110.0, 0.0005), (115.0, 0.0007), (125.0, 0.0009), (1099.0, 0.0012)]
DOWN_100 = [(105.0, 0.0003), (110.0, 0.0004), (115.0, 0.0005), (120.0, 0.0006), (130.0, 0.0008), (1099.0, 0.0010)]
SIDEWAYS_100 = [(103.0, 0.0002), (105.0, 0.0003), (110.0, 0.0004), (120.0, 0.0005), (1099.0, 0.0006)]
SWING_100 = [(110.0, 0.0006), (120.0, 0.0008), (140.0, 0.0010), (1099.0, 0.0012)]
UPCONTRACT_100 = [(108.0, 0.0005), (110.0, 0.0005), (115.0, 0.0007), (125.0, 0.0009), (1099.0, 0.0012)]

# 各趋势键档数（独立源：权威 dict 的键逐个计）
TIER_COUNTS = {"up": 5, "down": 6, "sideways": 5, "swing": 4, "up_contract": 5}

# BacktestConfig 默认 ladder（权威源 up 原样 int,float，非 price 转换）
DEFAULT_LADDER = [(6, 0.15), (10, 0.05), (15, 0.07), (25, 0.09), (999, 0.12)]


def _close(a, b, tol=1e-9):
    return abs(a - b) < tol


def _list_close(l1, l2):
    if len(l1) != len(l2):
        return False
    for (p1, r1), (p2, r2) in zip(l1, l2):
        if not (_close(p1, p2) and _close(r1, r2)):
            return False
    return True


eng = RiskEngine()


# ── A) 5 趋势键行为等价（归一前后恒绿：锚定"没改坏行为"） ──
def test_engine_tp_levels_up_5tiers():
    assert len(eng.calculate_tp_levels(100, "up")) == TIER_COUNTS["up"], "up 应 5 档"
    assert _list_close(eng.calculate_tp_levels(100, "up"), UP_100), f"up 手算不符: {eng.calculate_tp_levels(100, 'up')}"


def test_engine_tp_levels_down_6tiers():
    assert len(eng.calculate_tp_levels(100, "down")) == TIER_COUNTS["down"], "down 应 6 档"
    assert _list_close(eng.calculate_tp_levels(100, "down"), DOWN_100), f"down 手算不符: {eng.calculate_tp_levels(100, 'down')}"


def test_engine_tp_levels_sideways_swing_upcontract():
    assert len(eng.calculate_tp_levels(100, "sideways")) == TIER_COUNTS["sideways"]
    assert _list_close(eng.calculate_tp_levels(100, "sideways"), SIDEWAYS_100)
    assert len(eng.calculate_tp_levels(100, "swing")) == TIER_COUNTS["swing"]
    assert _list_close(eng.calculate_tp_levels(100, "swing"), SWING_100)
    assert len(eng.calculate_tp_levels(100, "up_contract")) == TIER_COUNTS["up_contract"]
    assert _list_close(eng.calculate_tp_levels(100, "up_contract"), UPCONTRACT_100)


def test_engine_unknown_trend_falls_back_to_up():
    # 未知趋势回退 up（独立手算 up 期望）
    assert _list_close(eng.calculate_tp_levels(100, "no_such_trend"), UP_100), "未知趋势应回退 up"


# ── B) BacktestConfig 默认 ladder = S3 五档（归一前后恒绿：锚定默认值） ──
def test_backtest_config_default_ladder_is_s3_five():
    cfg = bp.BacktestConfig(name="probe")
    # 默认（tp_ladder=None）必须 = 权威 up 原样（int,float），非旧4档
    assert cfg.tp_ladder == DEFAULT_LADDER, f"BacktestConfig 默认 ladder 应=S3五档, 实={cfg.tp_ladder}"


# ── C) 单一真源: 无模块级副本 + 可调用无循环（归一前 RED → 归一后 GREEN，本任务 red→green 核心锚） ──
def test_engine_no_module_level_ladder_copy():
    """归一前 engine 有模块级 TREND_TP_LADDER dict 副本(双源) → hasattr True (RED);
       归一后删除副本改延迟 import → 模块级无副本 hasattr False (GREEN)"""
    assert not hasattr(rre, 'TREND_TP_LADDER'), (
        "risk_rules_engine 仍有模块级 TREND_TP_LADDER 副本(双源), 须删除"
    )


def test_engine_no_circular_import_and_tp_levels_callable():
    """延迟 import 打破 risk_rules↔engine 循环, calculate_tp_levels 必须可调用且消费权威源(up 5档)"""
    eng = RiskEngine()
    levels = eng.calculate_tp_levels(100, "up")  # 归一前(模块级 import)会 CircularImportError; 归一后延迟 import 正常
    assert len(levels) == TIER_COUNTS["up"], f"up 应 5 档, 实 {len(levels)}"
    assert _list_close(levels, UP_100), f"up 手算不符: {levels}"
