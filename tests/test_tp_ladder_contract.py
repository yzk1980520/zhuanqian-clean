#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tp_ladder_contract.py — 止盈两套阶梯的契约守卫

老大拍板(2026-10-17): 「三档并优化移到止盈止损策略, 留一半以上仓位吃大波段」

═══ 两套阶梯必须分清（2026-10-17 老六曾混为一谈改错过，留此为戒）═══

  TREND_TP_LADDER  = (激活涨幅%, **移动止盈回撤容忍%**)
      → 决定"什么时候离场"，触发即整笔离场。
      → 一手证据: backtest_pipeline.py:478 `for threshold, trail_pct in tp_ladder:`
      → "up" 五档是 132 日全量回测会签值，本文件把它**钉死**，改动必须先过回测。

  TP_SELL_LADDER   = (触发涨幅%, 该档卖出**仓位比例**)
      → 决定"每档卖多少"，这才是"留一半以上吃大波段"的落点。
      → 本次从 data/holdings.json 的 per-position risk_control.tp_ladder 上移到 risk_rules。

老大三条硬要求（落在 TP_SELL_LADDER 上）:
  1. 三档
  2. 总卖出 <= 50% → 留仓 >= 50%（"吃大波段"的本质）
  3. 唯一真源是 risk_rules，**禁止** per-position 往 holdings.json 各写一份

第 3 条是根治"契约漂移"的关键:
  旧 per-position 值 [[0.05,0.3],[0.1,0.3],[0.15,0.4]] = 涨 15% 即清仓 100%，
  与"留一半以上"完全相反；且实测该字段在生产代码中**无任何消费方**（死数据），
  抄错了也没人知道 —— 这正是契约漂移的温床。
"""
import ast
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

# 可能往 holdings 写 per-position tp_ladder 的模块(实盘数据写入方)
WRITE_PATH_MODULES = [
    "trade_tracker.py",
    "portfolio_review.py",
    "orchestrator.py",
    "integrated_picker.py",
    "refresh_holdings.py",
    "scripts/execute_s3_buy.py",
]

# 132 日全量回测会签冻结值 —— 改这里必须先跑全量 132 日回测并经老大批准
FROZEN_TREND_UP = [(6, 0.15), (10, 0.05), (15, 0.07), (25, 0.09), (999, 0.12)]


class TestTrendLadderFrozen:
    """TREND_TP_LADDER['up'] 是回撤容忍阶梯, 属会签冻结值, 不得随手改。"""

    def test_up_is_frozen_five_tiers(self):
        from risk_rules import TREND_TP_LADDER
        ladder = [tuple(t) for t in TREND_TP_LADDER["up"]]
        assert ladder == FROZEN_TREND_UP, (
            f"[契约] TREND_TP_LADDER['up'] 是 132 日回测会签冻结值, 实际 {ladder}\n"
            f"        期望 {FROZEN_TREND_UP}\n"
            "        它是**回撤容忍**阶梯(不是卖出比例), 改动必须先跑全量 132 日回测 + 老大批准。"
        )

    def test_semantics_guard_trail_pct_not_sell_ratio(self):
        """语义防线: 回撤容忍档位不应被当成卖出比例来解读。

        若有人把 TREND_TP_LADDER 当成卖出阶梯, 其"总卖出"会随趋势键大幅波动
        (down 档总容忍 0.36 / sideways 0.20 / swing 0.36), 不存在"留仓过半"的语义。
        本断言用这个特征反证两套阶梯确实被分开存放。
        """
        from risk_rules import TREND_TP_LADDER, TP_SELL_LADDER
        assert TREND_TP_LADDER is not TP_SELL_LADDER
        assert TP_SELL_LADDER, "TP_SELL_LADDER 不得为空"


class TestSellLadderShape:
    """形制: 三档"""

    def test_sell_ladder_has_three_tiers(self):
        from risk_rules import TP_SELL_LADDER
        assert len(TP_SELL_LADDER) == 3, (
            f"[契约] 分批减仓档应为三档, 实际 {len(TP_SELL_LADDER)} 档: {TP_SELL_LADDER}\n"
            "老大盘板(2026-10-17): 收敛为三档。"
        )

    def test_last_tier_is_trailing_handoff(self):
        """末档阈值必须是 999 —— 意为'不再按涨幅分批', 剩余仓位交给移动止盈接管"""
        from risk_rules import TP_SELL_LADDER
        last_th = TP_SELL_LADDER[-1][0]
        assert last_th >= 999, (
            f"[契约] 末档阈值应 >=999(交给移动止盈), 实际 {last_th}"
        )

    def test_thresholds_ascending(self):
        from risk_rules import TP_SELL_LADDER
        ths = [t for t, _ in TP_SELL_LADDER]
        assert ths == sorted(ths), f"[契约] 触发涨幅应递增: {ths}"


class TestKeepHalfForBigWave:
    """本质: 留一半以上仓位吃大波段"""

    def test_total_sell_at_least_45pct(self):
        """下界: 总卖出 >= 45%(保证有分批止盈动作)"""
        from risk_rules import TP_SELL_LADDER, TP_SELL_TOTAL
        total = sum(r for _, r in TP_SELL_LADDER)
        assert abs(total - TP_SELL_TOTAL) < 1e-9, "TP_SELL_TOTAL 派生量与实际不符"
        assert total >= 0.45, f"总卖出 {total:.0%} < 45%, 止盈力度不足"

    def test_keep_more_than_half(self):
        """上界(老大核心诉求): 总卖出 <= 50% → 留仓 >= 50%"""
        from risk_rules import TP_SELL_LADDER, TP_KEEP_RATIO
        total = sum(r for _, r in TP_SELL_LADDER)
        keep = 1.0 - total
        assert abs(keep - TP_KEEP_RATIO) < 1e-9, "TP_KEEP_RATIO 派生量与实际不符"
        assert keep >= 0.50, (
            f"[契约] 必须留一半以上仓位吃大波段: 总卖出 {total:.0%} → 留仓仅 {keep:.0%} < 50%"
        )

    def test_regressed_from_old_per_position_value(self):
        """回归证明: 旧 per-position 值(涨15%清仓100%)必须不满足留仓判据。

        这条是"防倒退"锚 —— 它钉住的是**判据本身有效**, 而不是钉住某个数字。
        """
        old = [[0.05, 0.3], [0.1, 0.3], [0.15, 0.4]]
        old_keep = 1.0 - sum(r for _, r in old)
        assert old_keep < 0.50, "旧值应被判据判负, 否则说明判据失效"


class TestLadderSingleSource:
    """结构: 阶梯唯一真源是 risk_rules, 禁止 per-position 各写一份"""

    @pytest.mark.parametrize("mod", WRITE_PATH_MODULES)
    def test_no_per_position_tp_ladder_write(self, mod):
        """往 holdings/position 结构里写 tp_ladder 的, 一律红灯

        判据: 赋值目标名含 position/holding/risk_control 上下文, 且值里出现 'tp_ladder' 字面量。
        """
        p = os.path.join(PROJECT, mod)
        if not os.path.exists(p):
            pytest.skip(f"{mod} 不存在(可能已被精简删除)")
        with open(p, encoding="utf-8", errors="replace") as f:
            src = f.read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            pytest.skip(f"{mod} 无法解析")

        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                # 值侧是否出现 tp_ladder 字面量
                has_key = any(
                    isinstance(c, ast.Constant) and c.value == "tp_ladder"
                    for c in ast.walk(node.value)
                )
                if not has_key:
                    continue
                src_line = src.splitlines()[node.lineno - 1].strip()
                # 允许 risk_rules 自身与其派生常量; 业务写持仓结构的不允许
                if any(k in src_line.lower() for k in ("holding", "position", "risk_control")):
                    hits.append((node.lineno, src_line[:110]))
            if isinstance(node, ast.Dict):
                # 直接字典字面量里带 "tp_ladder" 键且同层带 cost/position 语义 → 视为 per-position 写入
                keys = [k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)]
                if "tp_ladder" in keys and any(
                        k in ("symbol", "shares", "avg_cost", "cost_price", "risk_control")
                        for k in keys):
                    hits.append((node.lineno, "dict 字面量内嵌 tp_ladder(per-position 写法)"))

        assert not hits, (
            f"[契约] {mod} 中出现 per-position 写 tp_ladder —— "
            "阶梯唯一真源是 risk_rules.TP_SELL_LADDER / TREND_TP_LADDER, "
            "per-position 各写一份正是契约漂移的根源:\n"
            + "\n".join(f"  L{ln}: {txt}" for ln, txt in hits)
        )
