#!/usr/bin/env python3
import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
score_diagnostics.py — 每日评分质量诊断仪表盘 (v8.1, 2026-08-06)
==================================================================
监控评分系统质量: 区分度/集中度/行业分布/策略分布
防止"评分聚集"(TOP5同分)再次发生

用法: python score_diagnostics.py  (在选股运行后调用)
"""
import sys, os, io, json, datetime
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, r"D:\open code\zhuanqian")
os.chdir(r"D:\open code\zhuanqian")

# ═══════════════════════════════════════════
# A 方案: 动态验收阈值 (2026-08-06, 用户决策)
# 市场状态决定 TOP5 方差/覆盖率合理阈值 — Barra/MSCI 因子体系同思路
# 偏暖+普涨时强势股同质化是市场现象, 非系统缺陷 → 阈值放宽
# ═══════════════════════════════════════════
MARKET_STATE_THRESHOLDS = {
    # market_label(market_state_engine中文输出) → (TOP5方差阈值, 时序覆盖率阈值)
    "极强": (2.0, 0.50),   # 牛市: 普涨, 头部天然聚集
    "牛":   (2.0, 0.50),   # 兼容 score_stock 归一化词表
    "偏暖": (3.0, 0.60),   # 强市/偏暖: 放宽到3 — 今日适用
    "强":   (3.0, 0.60),
    "震荡": (5.0, 0.65),   # 中性: 正常区分度
    "弱":   (6.0, 0.70),   # 弱市: 分化大, 要求更高
    "恐慌": (8.0, 0.75),   # 熊市: 极端分化
}


def get_validation_thresholds(market_label):
    """按市场状态返回 (TOP5方差阈值, 时序覆盖率阈值)"""
    return MARKET_STATE_THRESHOLDS.get(market_label, (5.0, 0.65))


def load_current_market_label():
    """读 market_state_cache.json 的 market_label (单一事实源)"""
    try:
        p = r"D:\open code\zhuanqian\data\market_state_cache.json"
        if os.path.exists(p):
            d = json.load(io.open(p, encoding="utf-8"))
            return d.get("result", {}).get("market_label", "")
    except Exception:
        pass
    return ""


def run_diagnostics():
    """读取最近选股结果, 计算评分质量指标"""
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    lines = ["📊 %s 评分质量诊断" % now]
    lines.append("━" * 35)

    # ── 1. 读取选股结果 ──
    # 优先读 integrated_picker 写入的今日候选池分数 (v8.1 指标1/3, 2026-08-06)
    # 避免 trade_log 历史记录(含 v8.1 前 100 分封顶老推荐)污染今日诊断
    scores = []
    top_scores = []
    industries = []
    strategies = {}
    _diag_json = r"D:\open code\zhuanqian\backtest_analysis\score_diagnostics.json"
    if os.path.exists(_diag_json):
        try:
            _dj = json.load(io.open(_diag_json, encoding="utf-8"))
            if isinstance(_dj, dict) and _dj.get("date") == now and _dj.get("today_scores"):
                scores = [float(x) for x in _dj["today_scores"]]
                lines.append("数据源: 今日候选池 (integrated_picker)")
        except Exception:
            pass
    rec_file = r"D:\open code\zhuanqian\data\trade_log.json"  # P2(t_febdf372): 归一 data/ 真源(根侧trade_log.json为9/23遗留,已移.trash)
    if not scores and not os.path.exists(rec_file):
        lines.append("❌ 无推荐记录文件: " + rec_file)
        return "\n".join(lines)

    if not scores:
        lines.append("数据源: trade_log 推荐记录")
        try:
            with io.open(rec_file, encoding="utf-8") as f:
                recs = json.load(f)
            if isinstance(recs, dict):
                recs = recs.get("recommendations", [])
            if isinstance(recs, list):
                for r in recs:
                    # PATCH-3: 优先读final_score (v8.1新增), 历史记录fallback score_zonghe
                    s = (r.get("final_score") or r.get("score_zonghe")
                         or r.get("score") or r.get("综合评分") or r.get("final"))
                    if s:
                        scores.append(float(s))
                    ind = r.get("industry") or r.get("行业") or ""
                    if ind:
                        industries.append(ind)
                    strat = r.get("strategy") or r.get("策略") or r.get("signal") or ""
                    if strat:
                        strategies[strat] = strategies.get(strat, 0) + 1
        except Exception as e:
            lines.append("❌ 读取失败: %s" % e)
            return "\n".join(lines)

    if not scores:
        lines.append("⚠️ 无评分数据")
        return "\n".join(lines)

    # 今日TOP5
    top_scores = sorted(scores, reverse=True)[:5]

    # ── 2. 诊断指标 ──
    import statistics
    n = len(scores)
    std = statistics.pstdev(scores) if n > 1 else 0
    avg = statistics.mean(scores)
    top5_identical = len(set(round(x, 1) for x in top_scores)) < len(top_scores)
    spread = (top_scores[0] if top_scores else 0) - (top_scores[-1] if len(top_scores) > 1 else 0)

    # v8.1: 分布形态指标 (偏度/峰度 — 监控评分聚集和异常分布)
    skew = 0.0
    kurt = 0.0
    if n > 3 and std > 0:
        skew = sum((x - avg) ** 3 for x in scores) / n / (std ** 3)
        kurt = sum((x - avg) ** 4 for x in scores) / n / (std ** 4) - 3

    lines.append("股票总数: %d" % n)
    lines.append("评分均值: %.1f | 标准差: %.2f %s" % (avg, std, "⚠️" if std < 8 else ""))
    lines.append("偏度: %+.2f | 峰度: %+.2f %s" % (skew, kurt, "⚠️" if kurt > 3 else ""))
    lines.append("TOP5: %s" % " / ".join("%.0f" % x for x in top_scores))
    top5_var = statistics.pstdev(top_scores) if len(top_scores) > 1 else 0

    # A 方案: 动态阈值判定 (2026-08-06) — 需在 TOP5 行之前定义
    mkt_label = load_current_market_label() or "震荡"
    var_thr, cov_thr = get_validation_thresholds(mkt_label)
    top5_var_ok = top5_var > var_thr
    lines.append("市场状态: %s → 验收阈值 (TOP5方差>%.1f, 覆盖率≥%.0f%%)" % (
        mkt_label, var_thr, cov_thr * 100))

    lines.append("TOP5同分: %s" % ("🚨 是" if top5_identical else "✅ 否"))
    lines.append("TOP5分方差: %.1f %s" % (top5_var, "✅>%.0f" % var_thr if top5_var_ok else "⚠️≤%.0f" % var_thr))
    lines.append("高低分差: %.1f %s" % (spread, "⚠️" if spread < 5 else ""))

    # v8.1 验证指标2: 时序增强覆盖率 (integrated_picker 写入 score_diagnostics.json)
    ts_cov = None
    try:
        _diag_file = r"D:\open code\zhuanqian\backtest_analysis\score_diagnostics.json"
        if os.path.exists(_diag_file):
            _d = json.load(io.open(_diag_file, encoding="utf-8"))
            ts_cov = _d.get("temporal_coverage")
            ts_cnt = _d.get("temporal_count")
            ts_tot = _d.get("temporal_total")
    except Exception:
        ts_cov = None

    # A 方案: 覆盖率判定 (阈值已在前方定义)
    ts_cov_ok = (ts_cov is not None and ts_cov >= cov_thr * 100)

    if ts_cov is not None:
        lines.append("时序增强覆盖率: %.1f%% %s" % (
            ts_cov, "✅≥%.0f%%" % (cov_thr * 100) if ts_cov_ok else "⚠️<%.0f%%" % (cov_thr * 100)))
        if ts_cnt is not None:
            lines.append("   (%d/%d只获得|δ|≥0.5增强)" % (ts_cnt, ts_tot or 0))
    else:
        lines.append("时序增强覆盖率: ⚠️ 未统计 (需 integrated_picker 运行后)")

    # 行业集中度 (简化HHI)
    if industries:
        from collections import Counter
        cnt = Counter(industries)
        top_ind = cnt.most_common(1)[0]
        hhi = sum((c / len(industries)) ** 2 for c in cnt.values())
        lines.append("行业TOP: %s (%d只) | HHI: %.3f %s" % (
            top_ind[0], top_ind[1], hhi, "⚠️" if hhi > 0.15 else ""))

    if strategies:
        lines.append("策略分布: %s" % json.dumps(strategies, ensure_ascii=False))

    # ── 3. 告警 (v8.1 验证: 告警与实际一致) ──
    alerts = []
    if std < 8:
        alerts.append("⚠️ 评分标准差<8, 区分度不足")
    if top5_identical:
        # PATCH-3: 明确提示基于final分还是基础分
        if len(set(round(x, 1) for x in top_scores)) < len(top_scores):
            alerts.append("🚨 TOP5 final分同质, 时序增强可能失效")
    if top5_var <= var_thr and len(top_scores) > 1:
        alerts.append("⚠️ TOP5分方差≤%.0f, 展示层异质不足(必过项1未达标)" % var_thr)
    if ts_cov is not None and not ts_cov_ok:
        alerts.append("⚠️ 时序增强覆盖率<%.0f%%, 连续性不足(必过项2未达标)" % (cov_thr * 100))
    if industries:
        from collections import Counter
        hhi = sum((c / len(industries)) ** 2 for c in Counter(industries).values())
        if hhi > 0.15:
            alerts.append("⚠️ 行业集中度过高, 建议分散")
    if spread < 5:
        alerts.append("⚠️ TOP5高低分差<5, 评分压缩")

    lines.append("━" * 35)
    if alerts:
        lines.append("告警:")
        lines.extend("  " + a for a in alerts)
    else:
        lines.append("✅ 评分质量正常, 区分度良好")

    # 写入报告文件
    report = "\n".join(lines)
    out_dir = r"D:\open code\zhuanqian\backtest_analysis"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "score_diagnostics.json")
    diag = {
        "date": now,
        "total_stocks": n,
        "score_std": round(std, 2),
        "score_avg": round(avg, 1),
        "top5": [round(x, 1) for x in top_scores],
        "top5_var": round(top5_var, 1),
        "top5_var_thr": var_thr,
        "top5_var_ok": top5_var_ok,
        "top5_identical": top5_identical,
        "spread": round(spread, 1),
        "market_label": mkt_label,
        "temporal_coverage": ts_cov,
        "temporal_coverage_thr": cov_thr,
        "temporal_coverage_ok": ts_cov_ok,
        "industry_hhi": round(hhi, 3) if industries else None,
        "alerts": alerts,
    }
    atomic_json.atomic_dump(diag, out_file, ensure_ascii=False, indent=2, encoding="utf-8")

    return report


if __name__ == "__main__":
    print(run_diagnostics())
