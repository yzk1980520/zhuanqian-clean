#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scoring_engine.py — 统一 final 评分引擎 (P0-1, 2026-08-08)
============================================================
目的: 消除"回测 ≠ 实盘"——把 integrated_picker 的 final 公式抽成共享纯函数,
      backtest 与 integrated_picker 调用同一套评分, 回测验证的才是实盘会用的评分。

来源: integrated_picker.py:558-566 (final公式) + :604 (风控×0.85) + :706/:750 (Layer6/7加分)

公式 (与 integrated_picker 逐字对齐, P2重构后 confidence 不折半):
    fin_weight: 默认0.15, 趋势0.08, 抄底0.20
    veto_penalty = 20 if fin_fatal else 0
    chase_exempt = min(gap_score*0.5, 6) if gap_score>0 else 0
    final = confidence*1.0 + gap*0.8 + max(0,nb)*0.6 + heat*0.6 + fin_bonus*fin_weight
            + chan_bonus*0.5 + chase_exempt*0.5 - veto_penalty - min(max(0,risk),30)*0.05
    rank_score = clamp(final * (1.0 if pass_risk else 0.85) + flow_bonus + pattern_bonus, 0, 100)

回测因子可得性 (2026-08-08):
    ✅ 可算: confidence/risk/pass_risk(score_stock) gap(断层) fin_bonus/fin_fatal(财务缓存)
    ✅ 常量: nb=0 (北向2024停披露已熔断)
    ⚠️ 无历史: heat(板块) flow(资金流) pattern(形态可选) → 传0, 回测报告标注缺失
    ⚠️ 近似: chan_bonus(断层通道池是实盘运行时概念, 回测用0)
"""

def compute_fin_bonus(fin_health, fin_penalty):
    """综合财务加分: 健康分直接转换, 舞弊扣分叠加 (integrated_picker.py:508 对齐)

    fin_health: 0~40 (financial_health)
    fin_penalty: -30~0 (fraud_penalty)
    return: -10~+20
    """
    return max(-10, min(20, int(fin_health / 2) + fin_penalty))

def compute_fin_weight(primary_strategy="综合"):
    """财务因子策略降权 (v8.1): 趋势选技术强, 抄底要基本面"""
    if primary_strategy == "趋势":
        return 0.08
    if primary_strategy == "抄底":
        return 0.20
    return 0.15

def compute_chase_exempt(gap_score):
    """断层追高豁免 (v8.2): 断层股(跳空高开天然偏离MA20)豁免追高惩罚, 最多6分"""
    if gap_score > 0:
        return min(gap_score * 0.5, 6.0)
    return 0.0

def compute_final_score(confidence, risk, pass_risk,
                        gap_score=0.0, nb_score=0.0, heat_bonus=0.0,
                        fin_bonus=0.0, fin_fatal=False,
                        chan_bonus=0.0, primary_strategy="综合",
                        flow_bonus=0.0, pattern_bonus=0.0,
                        fin_weight_override=None,
                        base_override=None,
                        gap_weight=0.8, heat_weight=0.6, nb_weight=0.6,
                        chan_weight=0.5, chase_weight=0.5):
    """统一 final 评分 — 实盘(integrated_picker)与回测(backtest)共用 (P0-1)

    Args:
        confidence: min(综合分, 全仓分) (0~100)
        risk: 综合分 - 全仓分 (追高/超买风险)
        pass_risk: 风控是否通过 (全仓分 >= 综合分*0.7)
        gap_score: 净利润断层评分 (0~n, 每个打分点=1分)
        nb_score: 北向资金评分 (已熔断→实盘恒0)
        heat_bonus: 板块热度加分 (integrated_picker 内 ×3 后 ×0.20)
        fin_bonus: 财务净加分 (compute_fin_bonus 产出, -10~+20)
        fin_fatal: 舞弊一票否决
        chan_bonus: 断层独立通道加成 (实盘 gap_pool 命中=5)
        primary_strategy: 主策略 (趋势/抄底/综合) → fin_weight
        flow_bonus: Layer6 主力资金流加分 (实盘 ±10, 回测无历史=0)
        pattern_bonus: Layer7 技术形态加分 (实盘 +2~5, 回测可选)
        fin_weight_override: 显式覆盖 fin_weight (调试用)
        base_override: P0-2 (2026-10-21) — 实盘传 DL 混合分(sc_zh*(1-W)+dl*W),
            回测传 None(用 confidence)。统一公式结构，保留实盘独有输入。
        gap_weight/heat_weight/nb_weight/chan_weight/chase_weight:
            加分项权重 (T-20260817-heatgap 敏感性分析新增, 默认=生产现状值,
            传入不同值不改生产行为, 仅用于敏感性回测对比)

    Returns:
        (final, rank_score): final=原始分, rank_score=排序分(含风控折扣+加分+clamp)
    """
    # 派生因子
    fin_weight = compute_fin_weight(primary_strategy) if fin_weight_override is None else fin_weight_override
    veto_penalty = 20.0 if fin_fatal else 0.0
    chase_exempt = compute_chase_exempt(gap_score)

    # P0-2 (2026-10-21): base_override 让实盘传 DL 混合分, 回测传 None 用 confidence
    base = base_override if base_override is not None else confidence

    # final 公式 (统一公式结构, 实盘/回测共用)
    final = (base * 1.0
             + gap_score * gap_weight
             + max(0.0, nb_score) * nb_weight
             + heat_bonus * heat_weight
             + fin_bonus * fin_weight
             + chan_bonus * chan_weight
             + chase_exempt * chase_weight
             - veto_penalty
             - min(max(0.0, risk), 30.0) * 0.05)

    # 排序分: final × 风控折扣(0.85) + Layer6/7 加分, clamp ≤ 100 (604/706/750行对齐)
    rank_score = final * (1.0 if pass_risk else 0.85)
    rank_score = min(100.0, rank_score + flow_bonus + pattern_bonus)
    rank_score = max(0.0, rank_score)

    # P0-1 评分归一化 (2026-09-04 老大拍板): 使用百分位排名替代绝对分数
    # 问题: 原rank_score导致TOP5方差=0.0, 所有候选挤压在100分, 选股退化为主题随机
    # 方案: percentile ranking, 保留相对排序信息, 避免顶部挤压
    # 注意: 此函数本身不计算百分位(需批量调用), 返回原始rank_score供上层统一归一化
    # 上层调用示例:
    #   scores = [compute_final_score(...)[1] for ...]
    #   normalized = [percentile_rank(s, scores) for s in scores]

    return round(final, 4), round(rank_score, 4)


def percentile_rank(score, all_scores):
    """计算分数在列表中的百分位排名 (0-100)

    Args:
        score: 当前分数
        all_scores: 所有待比较的分数列表

    Returns:
        百分位排名 (0-100), 100表示最高分
    """
    if not all_scores:
        return 50.0
    n = len(all_scores)
    # 计算低于当前分数的比例
    below_count = sum(1 for s in all_scores if s < score)
    # 处理并列情况: 取平均排名
    equal_count = sum(1 for s in all_scores if s == score)
    rank = below_count + 0.5 * equal_count
    return round(rank / n * 100, 2)

def linear_scale(score, all_scores):
    """线性缩放分数到 [5, 100] 区间，保留绝对区分度

    替代 percentile_rank 用于选股输出，避免顶部挤压。
    公式: score' = clamp((score - min) / (max - min) * 90 + 5, 5, 100)
    - 最低分 → 5分，最高分 → 100分
    - 中等分保留线性区分度
    - 并列分数映射到相同值

    Args:
        score: 当前原始分数
        all_scores: 所有待比较的分数列表

    Returns:
        线性缩放后的分数 (5-100)
    """
    if not all_scores:
        return 50.0
    min_s = min(all_scores)
    max_s = max(all_scores)
    if max_s == min_s:
        # 所有分数相同，均分到中值
        return 50.0
    scaled = (score - min_s) / (max_s - min_s) * 90.0 + 5.0
    return round(max(5.0, min(100.0, scaled)), 2)


# 回测因子可得性标注 (给报告/日志引用)
BACKTEST_FACTOR_AVAILABILITY = {
    "confidence": "可算(score_stock综合分)",
    "risk/pass_risk": "可算(score_stock双策略)",
    "gap": "可算(has_recent_gap/断层检测)",
    "fin": "可算(financial_cache+detect_fraud, 当前财务近似历史)",
    "nb": "常量0(北向2024停披露熔断)",
    "heat": "无历史(传0, 回测未覆盖板块热度)",
    "flow": "无历史(传0, 回测未覆盖资金流)",
    "pattern": "可选(形态识别可用历史K线, v2纳入)",
    "chan": "近似0(断层通道池是实盘运行时概念)",
}
