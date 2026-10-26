#!/usr/bin/env python3
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
gap_channel.py — 断层策略独立通道 (v8.1, 2026-08-06)
=====================================================
断层是事件驱动型alpha(业绩跳空), 不应与连续型评分混合。
本通道独立维护"断层观察池", 推荐时断层池优先, 常规评分补充。

核心逻辑:
  1. detect_gap: 净利润跳空 + 量价确认 + 均线共振 → 85~100分
  2. update_pool: 每日更新断层池 (最多3只)
  3. should_exit: 持有20日/缺口回补/放量长阴 → 退出
"""
import sys, os

# 基地化S3 (2026-10-22): 迁 core/scoring/ 后锚点漂移两级 → 注入仓库根(迁前语义: 脚本所在根目录)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class GapStrategyChannel:
    """断层独立通道 — 事件驱动alpha不与连续评分混合"""

    def __init__(self, max_holdings=3, hold_days=20):
        self.gap_pool = {}       # {code: gap_info}
        self.max_holdings = max_holdings
        self.hold_days = hold_days

    def detect_gap(self, recs, inds=None):
        """
        断层检测: 跳空缺口 + 量价确认 + 均线共振

        返回 gap_info dict 或 None:
            - code: 股票代码
            - gap_date: 缺口日期
            - gap_pct: 跳空幅度%
            - support: 缺口支撑
            - volume_ratio: 量比
            - score: 85~100 (缺口越大+量越强分越高)
        """
        try:
            from core.scoring.earnings_gap import detect_gaps
        except Exception:
            return None

        gaps = detect_gaps(recs)
        if not gaps:
            return None

        # 取最近一个未回补缺口
        gap = None
        for g in gaps:
            if not g.get("gap_filled", False):
                gap = g
                break
        if not gap:
            return None

        gap_pct = gap.get("gap_pct", 0)
        if gap_pct < 3.0:
            return None  # 缺口<3% 不够强

        # 量价确认 (v8.1: 1.5倍量)
        vr = gap.get("volume_ratio", 0) or 0
        if vr < 1.5:
            return None

        # 均线共振: 收盘>MA20>MA60 (用现成indicators)
        ma_ok = True
        if inds:
            price = inds.get("price")
            ma20 = inds.get("ma20")
            ma60 = inds.get("ma60")
            if price and ma20 and ma60:
                ma_ok = price > ma20 > ma60

        # 断层强度评分: 85基础 + 缺口加分 + 量能加分
        score = 85.0
        score += min(gap_pct * 2, 10)    # 缺口每1%+2分, 封顶+10
        score += min((vr - 1.5) * 5, 5)  # 量能1.5倍以上每0.1+0.5分, 封顶+5
        score = min(score, 100)
        if not ma_ok:
            score -= 5  # 均线不共振降权

        return {
            "code": gap.get("code", ""),
            "gap_date": gap.get("date", ""),
            "gap_pct": gap_pct,
            "support": gap.get("support", 0),
            "volume_ratio": vr,
            "score": round(score, 1),
            "ma_resonance": ma_ok,
        }

    def update_pool(self, candidates):
        """
        每日更新断层池
        candidates: [{code, recs, inds}, ...]
        返回: gap_pool dict
        """
        new_gaps = []
        for c in candidates:
            gap_signal = self.detect_gap(c.get("recs"), c.get("inds"))
            if gap_signal:
                gap_signal["code"] = c["code"]
                new_gaps.append(gap_signal)

        # 按断层强度排序, 取前max_holdings
        new_gaps.sort(key=lambda x: -x["score"])
        self.gap_pool = {g["code"]: g for g in new_gaps[:self.max_holdings]}
        return self.gap_pool

    def should_exit(self, code, recs, days_since=0):
        """
        退出条件: 持有超期/缺口回补/放量长阴
        """
        gap_info = self.gap_pool.get(code)
        if not gap_info:
            return True, "不在断层池"

        if days_since >= self.hold_days:
            return True, "持有超期"

        if not recs:
            return False, ""

        last = recs[-1]
        support = gap_info.get("support", 0)
        if support and last.get("low", 0) <= support:
            return True, "缺口回补"

        # 放量长阴
        if last.get("close", 0) < last.get("open", 0) and last.get("volume", 0) > 0:
            vol_ma = sum(r.get("volume", 0) for r in recs[-6:-1]) / 5 if len(recs) >= 6 else 0
            if vol_ma > 0 and last["volume"] > vol_ma * 2:
                return True, "放量长阴"

        return False, ""

    def top_recommendations(self, limit=3):
        """断层池排序推荐"""
        pool = sorted(self.gap_pool.values(), key=lambda x: -x["score"])
        return pool[:limit]


# 模块级单例 (供integrated_picker复用)
_gap_channel = GapStrategyChannel()


def get_gap_channel():
    return _gap_channel


if __name__ == "__main__":
    # 自测
    gc = GapStrategyChannel()
    print("✅ GapStrategyChannel 初始化OK")
    print("  max_holdings:", gc.max_holdings, "| hold_days:", gc.hold_days)
