"""
止盈止损计算模块 — 从 tdx_score.py 提取 (2026-09-23)
"""
from tdx_indicators import calc_atr_stop, calc_atr, calc_sma
from config_loader import load_contract


def calc_trailing_stop(records, trail_drawdown=0.08, atr_multiplier=2.0):
    """
    计算移动止盈止损线。
    records: 日线列表，含close/high/low
    trail_drawdown: 回撤阈值（默认8%）
    atr_multiplier: ATR倍数（默认2.0）
    返回 dict 或 None
    """
    if not records or len(records) < 5:
        return None
    
    c = [r["close"] for r in records]
    h = [r["high"] for r in records]
    l = [r["low"] for r in records]
    entry = c[-1]
    
    # P0-2026-08-23 老大拍板: 止损统一8%, 修正hardcode 7% → 读config
    # O-2修复(2026-10-17): 原为 contract.get("stop_loss_pct", 0.08)。
    #   0.08 是 2026-09-30 三方会签(8%→10%)之前的旧口径; contract 缺失时会**静默**退回 8%,
    #   既不报错也无告警 —— 与契约 10% 打架且无从察觉, 是典型的静默兜底反模式。
    #   现改为: 优先 contract, 缺失则回退 risk_rules 真源并 loud 提示, 消灭第二口径。
    contract = load_contract()
    stop_pct = contract.get("stop_loss_pct")
    if stop_pct is None:
        from risk_rules import STRATEGY_STOP_LOSS_PCT
        stop_pct = STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10)
        print("  ⚠️ contract 缺 stop_loss_pct, 已回退 risk_rules 真源 %.0f%%"
              " (旧代码此处静默兜底 8%%, 与契约不符)" % (stop_pct * 100))
    fixed = entry * (1 - stop_pct)
    
    atr_s, atr_v = calc_atr_stop(records, atr_multiplier)
    final = max(fixed, atr_s) if atr_s else fixed
    rh = max(h[-20:]) if len(h) >= 20 else max(h)
    rl = min(l[-20:]) if len(l) >= 20 else min(l)
    ts = rh * (1 - trail_drawdown)
    # P0-2026-09-25 修复: calc_atr 期望K线dict列表, 传close浮点列表必TypeError;
    # 对齐 tdx_score_original.calc_trailing_stop 改用 calc_sma ( WorkBuddy 体检 P0-1 )
    m10 = calc_sma(c, 10)
    sup = max(m10 or 0, rl * 0.98, final)

    # P0-2026-09-25 修复: 返回键对齐 tdx_score_original 版本 —
    # compute_swing_analysis 读取 stop_loss / tp3_15% (原包版缺这些键必KeyError),
    # 同时保留旧键 entry_price 兼容既有调用方
    return {
        "entry": entry,
        "entry_price": entry,
        "stop_loss": round(final, 2),
        "fixed_stop": round(fixed, 2),
        "atr_stop": round(atr_s, 2) if atr_s else None,
        "atr": round(atr_v, 3) if atr_v else None,
        "support": round(sup, 2),
        "trailing_stop": round(max(ts, sup), 2),
        "tp1_5%": round(entry * 1.05, 2), "tp2_10%": round(entry * 1.10, 2),
        "tp3_15%": round(entry * 1.15, 2), "tp_final_20%": round(entry * 1.20, 2),
        "resistance": round(rh, 2),
    }


def format_stop_advice(stop_info, price, strategy="综合"):
    """格式化止损建议"""
    if not stop_info:
        return "数据不足, 无法计算止损"
    
    ts = stop_info.get("trailing_stop", 0)
    fixed = stop_info.get("fixed_stop", 0)
    atr_s = stop_info.get("atr_stop", 0)
    
    lines = [f"当前价: {price:.2f}"]
    
    if fixed > 0:
        loss_pct = (price - fixed) / price * 100
        lines.append(f"固定止损: {fixed:.2f} (-{loss_pct:.1f}%)")
    
    if ts > 0:
        lines.append(f"移动止盈: {ts:.2f}")
    
    if atr_s > 0:
        lines.append(f"ATR止损: {atr_s:.2f}")
    
    return "\n".join(lines)


def compute_swing_analysis(inds, records=None):
    """
    swing分析: 计算风险/回报比
    返回 dict
    """
    from tdx_score.trailing import calc_trailing_stop
    
    price = inds.get("price", 0)
    if not price:
        return None
    
    ts = calc_trailing_stop(records, atr_multiplier=2.0) if records else None
    
    if ts:
        risk_pct = (price - ts["stop_loss"]) / price * 100
        reward_pct = (ts["tp3_15%"] - price) / price * 100
        rr = reward_pct / risk_pct if risk_pct > 0 else 0
    else:
        risk_pct = reward_pct = rr = 0
    
    return {
        "risk_pct": risk_pct,
        "reward_pct": reward_pct,
        "rr": rr,
        "trailing_stop": ts,
    }
