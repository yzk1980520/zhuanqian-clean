"""
startup_detector.py — 主升浪加速检测因子 (P1#5 老三实现, 2026-10-10)
=====================================================================

理论依据：唯识学种子理论
- 主升浪启动 = 加速度 > 前期涨幅 + 阈值
- 加速度 = 近期涨幅 - 前期涨幅 (5日 vs 20日)

核心信号：
  1. 加速度检测：chg5 - chg20 > threshold (默认1%)
  2. 均线共振：price > MA5 > MA20 > MA60
  3. 量能确认：volume_ratio > 1.5
  4. 趋势延续：连续N日上涨

评分公式：
  score = base(50) + accel_bonus + ma_resonance + volume_bonus
  range: 0-100

返回：
  (accel_score, is_starting, signals)
  - accel_score: 0-100
  - is_starting: bool (是否主升浪启动)
  - signals: list[str] (信号描述)
"""
import sys
from typing import List, Tuple, Optional


def calculate_startup_score(
    recs: List[dict],
    market_label: Optional[str] = None,
    threshold: float = 1.0,
    min_lookback: int = 20,
) -> Tuple[float, bool, List[str]]:
    """
    主升浪加速检测

    参数:
        recs: TDX日线数据 (最新在前或从旧到新均可)
        market_label: 市场状态 (强/偏暖/震荡/弱/恐慌)
        threshold: 加速度阈值 (%)
        min_lookback: 最小回看天数

    返回:
        (accel_score, is_starting, signals)
        - accel_score: 0-100 加速分数
        - is_starting: bool 是否主升浪启动
        - signals: list[str] 信号列表
    """
    if not recs or len(recs) < min_lookback:
        return 0.0, False, ["数据不足"]

    # 确保按时间升序（旧→新）
    if recs[-1]["date"] > recs[0]["date"]:
        recs_sorted = recs
    else:
        recs_sorted = list(reversed(recs))

    signals = []
    score = 50.0  # 基础分

    # ── 1. 加速度检测 ──
    try:
        close_5d_ago = recs_sorted[-6]["close"] if len(recs_sorted) >= 6 else recs_sorted[0]["close"]
        close_20d_ago = recs_sorted[-21]["close"] if len(recs_sorted) >= 21 else recs_sorted[0]["close"]
        current_close = recs_sorted[-1]["close"]

        if close_5d_ago > 0 and close_20d_ago > 0 and current_close > 0:
            chg5 = (current_close / close_5d_ago - 1) * 100
            chg20 = (current_close / close_20d_ago - 1) * 100
            acceleration = chg5 - chg20  # 加速度

            signals.append(f"加速度{acceleration:+.2f}%")

            # 加速度加分
            if acceleration > threshold:
                accel_bonus = min(acceleration * 2, 20)  # 每1%加2分, 封顶20
                score += accel_bonus
                signals.append(f"✅加速(>{threshold}%)")
            elif acceleration > 0:
                score += acceleration  # 小幅加分
        else:
            signals.append("收盘价异常")
    except Exception as e:
        signals.append(f"加速度计算失败: {e}")

    # ── 2. 均线共振检测 ──
    try:
        from core.scoring.tdx_indicators import compute_indicators
        inds = compute_indicators(recs_sorted)
        if inds:
            price = inds.get("price", 0) or recs_sorted[-1]["close"]
            ma5 = inds.get("ma5", 0)
            ma20 = inds.get("ma20", 0)
            ma60 = inds.get("ma60", 0)

            if price > 0 and ma5 > 0 and ma20 > 0 and ma60 > 0:
                # 多头排列: price > ma5 > ma20 > ma60
                if price > ma5 > ma20 > ma60:
                    score += 15
                    signals.append("📈均线多头排列")
                elif price > ma5 and ma5 > ma20:
                    score += 8
                    signals.append("⚠️部分多头排列")
                else:
                    signals.append("❌均线空头")
            else:
                signals.append("MA数据缺失")
        else:
            signals.append("指标计算失败")
    except Exception as e:
        signals.append(f"均线检测失败: {e}")

    # ── 3. 量能确认 ──
    try:
        recent_vols = [r["volume"] for r in recs_sorted[-21:-1]] if len(recs_sorted) >= 21 else []
        current_vol = recs_sorted[-1].get("volume", 0)

        if recent_vols and current_vol > 0:
            avg_vol = sum(recent_vols) / len(recent_vols)
            vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0

            if vol_ratio > 1.5:
                score += min(vol_ratio * 2, 10)  # 量比加分, 封顶10
                signals.append(f"📊量能放大({vol_ratio:.2f}x)")
            elif vol_ratio > 1.0:
                score += vol_ratio  # 小幅加分
            else:
                signals.append("⚠️量能不足")
        else:
            signals.append("量能数据不足")
    except Exception as e:
        signals.append(f"量能检测失败: {e}")

    # ── 4. 趋势延续性 ──
    try:
        if len(recs_sorted) >= 10:
            recent_closes = [r["close"] for r in recs_sorted[-10:]]
            up_days = sum(1 for i in range(1, len(recent_closes)) if recent_closes[i] > recent_closes[i-1])
            trend_ratio = up_days / 9  # 上涨天数比例

            if trend_ratio > 0.6:
                score += 5
                signals.append(f"📈趋势延续({trend_ratio:.0%})")
            else:
                signals.append("⚠️趋势不明显")
        else:
            signals.append("趋势数据不足")
    except Exception as e:
        signals.append(f"趋势检测失败: {e}")

    # ── 5. 市场状态修正 ──
    if market_label:
        if market_label in ("强", "偏暖"):
            score += 5
            signals.append(f"✅市场{market_label}")
        elif market_label in ("弱", "恐慌"):
            score -= 5
            signals.append(f"⚠️市场{market_label}")

    # 限制范围 0-100
    score = max(0.0, min(100.0, score))

    # 判断是否主升浪启动
    is_starting = score >= 60 and any("✅" in s for s in signals)

    return round(score, 1), is_starting, signals


def batch_score_startup(
    codes: List[str],
    recs_dict: dict,
    market_label: Optional[str] = None,
    **kwargs,
) -> dict:
    """
    批量评分 (供 integrated_picker.py 调用)

    返回:
        {code: (score, is_starting, signals)}
    """
    results = {}
    for code in codes:
        recs = recs_dict.get(code, [])
        if not recs:
            continue
        score, is_starting, signals = calculate_startup_score(recs, market_label, **kwargs)
        results[code] = (score, is_starting, signals)
    return results


if __name__ == "__main__":
    # 自测
    from core.pipeline.tdx_core import get_tdx_data
    recs = get_tdx_data("sh600519", 60)
    if recs:
        score, is_start, signals = calculate_startup_score(recs, "偏暖")
        print(f"茅台: score={score}, starting={is_start}")
        for s in signals:
            print(f"  - {s}")
