# -*- coding: utf-8 -*-
"""test_evolution_loop_seams.py — 终审裁定 1/§三 的两个新 seam TDD

seam（public interface, 纯函数）:
  - oos_purity_check(fit_dates, oos_dates, tuned_on_dates)  裁定1: walk-forward 纯OOS 接缝隔离
  - redline_pointer_compliant(text)  §三: 红线只写指针(不写具体数值)机器校验

期望值来源: docs/evolution_loop_v1_schema.md §三 walk-forward 铁律 + 老大多审裁定 1/§三 现值。
裁定1 硬约束: OOS 段必须在**接缝层断言**保证未参与 fit/选参, 不靠自觉。
§三裁定: 任何文档/提示词出现红线具体数值(且该行未带真源指针 risk_rules.XXX)= 判漂移。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core.ops.evolution_loop as el  # noqa: E402

# ── walk-forward 纯 OOS 接缝隔离 (裁定 1) ─────────────────────
def test_oos_pure_when_tail_disjoint():
    # 132d 确认窗: 前段 fit, 末 20d OOS(从未参与 fit/选参), 纯 OOS
    # fit = 2026-09 全月(30日), oos = 2026-10 前20日(在 fit 之后, 零交集), 选参只用 fit
    fit = [f"2026-09-{d:02d}" for d in range(1, 31)]
    oos = [f"2026-10-{d:02d}" for d in range(1, 21)]
    r = el.oos_purity_check(fit, oos, tuned_on_dates=fit)   # 选参只用 fit 段
    assert r["pure"] is True
    assert r["violations"] == []


def test_oos_violation_when_overlap_fit():
    # OOS 与 fit 有交集 = 数据泄漏 → 不纯
    fit = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
    oos = ["2026-10-03", "2026-10-04"]   # 重叠 03/04
    r = el.oos_purity_check(fit, oos)
    assert r["pure"] is False
    assert any("与 fit 重叠" in v for v in r["violations"])


def test_oos_violation_when_used_for_tuning():
    # OOS 参与选参/调优 = 最严重泄漏 → 不纯(即便与 fit 无交集)
    fit = ["2026-10-01", "2026-10-02"]
    oos = ["2026-10-05", "2026-10-06"]
    tuned = ["2026-10-06"]   # 选参用过 OOS 的 10-06
    r = el.oos_purity_check(fit, oos, tuned_on_dates=tuned)
    assert r["pure"] is False
    assert any("参与选参" in v for v in r["violations"])


def test_oos_violation_when_not_tail():
    # OOS 段早于 fit 末日(非 walk-forward 末段"未见未来") → 不纯
    fit = ["2026-10-01", "2026-10-20", "2026-10-21"]   # fit 含 10-21
    oos = ["2026-10-05"]                                  # OOS 早于 fit 末日 10-21
    r = el.oos_purity_check(fit, oos)
    assert r["pure"] is False
    assert any("早于 fit 末日" in v for v in r["violations"])


def test_oos_empty_is_pure():
    # 无 OOS 段(冒烟级) = 无泄漏可言, 视为纯(不阻止冒烟)
    r = el.oos_purity_check(["2026-10-01"], [], [])
    assert r["pure"] is True


# ── 红线"只写指针"机器校验 (§三裁定) ──────────────────────────
def test_compliant_when_pointer_present():
    # 红线数值行若同带 risk_rules.XXX 常量指针 → 合规
    text = "止损=risk_rules.STRATEGY_STOP_LOSS_PCT[全仓]\n阶梯=TREND_TP_LADDER['up'] 五档\n"
    r = el.redline_pointer_compliant(text)
    assert r["compliant"] is True
    assert r["violations"] == []


def test_violation_when_naked_value():
    # 红线数值行**未**带真源指针 → 判漂移(违规)
    text = "硬止损 10%, 追高关闭 4%, 时间止损 120日\n阶梯 6-10-20\n"
    r = el.redline_pointer_compliant(text)
    assert r["compliant"] is False
    assert r["violations"]        # 至少一条违规行
    assert all(not v["has_pointer"] for v in r["violations"])


def test_pointer_line_counts_as_pointer():
    # 单独一行就是常量名指针(无数值) → 合规
    text = "CHASE_BAN_PCT / TIME_STOP_TRADING_DAYS / TREND_TP_LADDER\n"
    r = el.redline_pointer_compliant(text)
    assert r["compliant"] is True


def test_clean_text_no_redline_lines():
    # 普通文本(不含红线数值) → 0 数值行, 合规
    r = el.redline_pointer_compliant("因子动量权重再平衡, 网格 20 点\n")
    assert r["compliant"] is True
    assert r["value_line_count"] == 0


def test_redline_value_lines_marks_has_pointer():
    # 直接验 redline_value_lines 的逐行判定(has_pointer 字段正确)
    # 行1: "止损 0.10" 数值紧贴关键字(12字符窗内) 且带指针 → 数值行+has_pointer True
    # 行2: "止损 8%" 数值紧贴关键字, 裸值无指针 → 数值行+has_pointer False
    text = "止损 0.10 (risk_rules.STRATEGY_STOP_LOSS_PCT)\n止损 8% 裸值断言\n"
    lines = el.redline_value_lines(text)
    by = {l["line_no"]: l for l in lines}
    assert by[1]["has_pointer"] is True
    assert by[2]["has_pointer"] is False
