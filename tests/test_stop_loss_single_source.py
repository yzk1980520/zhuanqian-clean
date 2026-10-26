#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_stop_loss_single_source.py — 硬止损「单一真源」守卫

背景(2026-10-17 红线处置 O-2):
    硬止损契约真源是 risk_rules.STRATEGY_STOP_LOSS_PCT = 0.10(全策略),
    2026-09-30 三方会签由 8% 上调为 10%。
    但全场另有**三处**各写各的旧口径:
      - tdx_score_original.py  _get_stop_loss_pct() 硬编码 return 8
      - tdx_score/market_state.py  _get_stop_loss_pct() 硬编码 return 8
      - cron/daily_monitor.py  `if 震荡: 真源 else 0.08` —— 给真源开了个旁路
    后果: 改一处不生效、改错地方以为已生效; 实盘在持仓位实际跑的是 8% 而非契约 10%。
    这正是本项目"改了没反应"型事故的标准温床。

老大拍板: 契约 10%, 立即同步在持仓。
    - 代码侧(本守卫覆盖): 三处统一引用 risk_rules 真源 —— 已完成
    - 数据侧(总管独占写): data/holdings.json sh603727 0.08→0.10 —— kanban t_4f87459c

判据:
    任何以 stop 命名的变量赋值或函数返回, 不得再出现 8 / 0.08 字面量。
    risk_rules.py 本身是真源, 豁免。
"""
import ast
import os
import re
import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 活跃链路模块(生产入口 orchestrator 及其依赖); risk_rules.py 是真源, 单独豁免
# 基地化S3 (2026-10-22): tdx_score_original.py 已迁入 core/scoring/, 路径随迁(守卫不降覆盖)
ACTIVE_MODULES = [
    "core/scoring/tdx_score_original.py",
    "tdx_score/market_state.py",
    "cron/daily_monitor.py",
    "orchestrator.py",
    "portfolio_review.py",
    "trade_tracker.py",
    "integrated_picker.py",
    "risk_monitor.py",
    "health_check.py",
    "config_loader.py",
]

# 旧口径字面量: 8(百分数) / 0.08(小数)
LEGACY_VALUES = {8, 8.0, 0.08}


def _scan_legacy_stop_literals(path):
    """AST 扫描: 名字含 stop 的赋值/返回里是否残留旧口径字面量 8 / 0.08"""
    with open(path, encoding="utf-8", errors="replace") as f:
        src = f.read()
    tree = ast.parse(src)
    hits = []

    def _is_legacy(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and node.value in LEGACY_VALUES

    def _has_legacy_in(node):
        """在整棵值子树里找旧口径字面量

        不能只看直接常量: 实战写法是 `stop_pct = A if 震荡 else 0.08`(三元表达式),
        字面量藏在 IfExp 的 orelse 里, 只看顶层会漏判。
        """
        return any(_is_legacy(sub) for sub in ast.walk(node))

    for node in ast.walk(tree):
        # 赋值: xxx_stop_xxx = 8 / 0.08 / (A if cond else 0.08)
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                # 只取具名目标: 元组解包里可能有 *rest / 下标 / 属性, 一律跳过
                if isinstance(tgt, ast.Tuple):
                    names = [t.id for t in tgt.elts if isinstance(t, ast.Name)]
                elif isinstance(tgt, ast.Name):
                    names = [tgt.id]
                else:
                    names = []
                for n in names:
                    if "stop" in n.lower() and _has_legacy_in(node.value):
                        hits.append((getattr(node, "lineno", 0), f"{n} = <含旧口径字面量 8 / 0.08>"))
        # 返回: def *_get_stop_*(): return 8
        if isinstance(node, ast.FunctionDef) and "stop" in node.name.lower():
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value is not None and _is_legacy(sub.value):
                    hits.append((sub.lineno, f"{node.name} -> return {sub.value.value}"))
    return hits


class TestStopLossSingleSource:
    """硬止损必须是单一真源, 不得有第二口径"""

    @pytest.mark.parametrize("mod", ACTIVE_MODULES)
    def test_no_legacy_stop_literal(self, mod):
        path = os.path.join(PROJECT, mod)
        if not os.path.exists(path):
            pytest.skip(f"{mod} 不存在(可能已被精简删除)")
        hits = _scan_legacy_stop_literals(path)
        assert not hits, (
            f"[O-2] {mod} 残留旧止损口径 8%/0.08, 与契约 10% 打架:\n"
            + "\n".join(f"  L{ln}: {txt}" for ln, txt in hits)
            + "\n\n正确做法: from risk_rules import STRATEGY_STOP_LOSS_PCT, 引用真源而非写字面量。"
        )

    def test_both_accessors_return_contract_value(self):
        """两处 _get_stop_loss_pct 必须返回真源值(百分数口径 10.0)"""
        import sys
        if PROJECT not in sys.path:
            sys.path.insert(0, PROJECT)
        from risk_rules import STRATEGY_STOP_LOSS_PCT

        expect = round(STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10) * 100, 2)

        from core.scoring.tdx_score_original import _get_stop_loss_pct as f1
        from tdx_score.market_state import _get_stop_loss_pct as f2
        assert f1("震荡") == expect, f"tdx_score_original 止损 {f1('震荡')} != 契约 {expect}"
        assert f2("震荡") == expect, f"tdx_score.market_state 止损 {f2('震荡')} != 契约 {expect}"

    def test_true_source_is_ten_percent(self):
        """真源本身必须是 10% —— 若有人改了真源, 这条先红, 提示需重走会签"""
        import sys
        if PROJECT not in sys.path:
            sys.path.insert(0, PROJECT)
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        assert STRATEGY_STOP_LOSS_PCT.get("全仓") == 0.10, (
            f"risk_rules 真源止损已变为 {STRATEGY_STOP_LOSS_PCT.get('全仓')}, "
            "非契约值 0.10 —— 变更需重走三方会签, 禁止静默改数"
        )

    def test_market_adjust_table_intact(self):
        """MARKET_STOP_ADJUST 系数表必须与真源一并冻结(实际生效 = 基准 × 系数)"""
        import sys
        if PROJECT not in sys.path:
            sys.path.insert(0, PROJECT)
        from risk_rules import MARKET_STOP_ADJUST
        # 只冻结"恐慌必须是最紧的一档"这一序关系, 不冻结具体数值(后续可会签调整)
        assert MARKET_STOP_ADJUST["恐慌"] == min(MARKET_STOP_ADJUST.values()), (
            "MARKET_STOP_ADJUST 中『恐慌』不是最紧的一档, 违背『恐慌=最防御、本金安全第一』"
        )
