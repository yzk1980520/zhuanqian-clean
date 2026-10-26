import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
position_alerts.py — 持仓监控提醒模块 (2026-08-02)
===========================================
任务2+3合并: 只监控当前持仓(holdings.json), 已卖出不监控。

监控项:
  1. 止损提醒: 现价 <= 止损价 → 推送"止损触发!"
  2. 目标减仓: 现价 >= TP1 → 推送"到达减仓目标"
  3. 移动止盈: 从持仓期最高价回撤 >= 7% → 推送"移动止盈触发"
  4. 破位提醒: 跌破关键支撑(MA20) → 推送"破位预警"

用法:
  python position_alerts.py          # 检查并输出提醒
  python position_alerts.py --push   # 检查并微信推送(通过wechat_pusher)
"""
import os, sys, json
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date

# P1-1修复: 硬编码绝对路径 → 相对, 换目录即跪风险解除
PROJECT = PROJECT_ROOT
HOLDINGS_FILE = os.path.join(PROJECT, "data", "holdings.json")  # 2026-09-09 Bug2
ALERT_STATE_FILE = os.path.join(PROJECT, "data", "position_alerts_state.json")
QUEUE_FILE = os.path.join(PROJECT, "data", "message_queue.json")
COOLDOWN_FILE = os.path.join(PROJECT, "data", "alert_cooldown.json")

MOVING_TP_PCT = 0.08   # 【已废弃 2026-09-29 T1收敛】统一使用 TREND_TP_LADDER 单源
                       # 原值 8% 仅为历史参考，实盘已改为动态阶梯 (5/7/10/12%)
BREAK_MA = 20          # 破位判断用 MA20
COOLDOWN_SECONDS = 7200  # 2小时冷却期


def _write_to_queue(alerts):
    """将告警写入消息队列供 cron_message_sender 消费"""
    import time
    from core.pipeline.atomic_json import atomic_dump
    now = time.time()
    new_items = []
    for a in alerts:
        item = {
            "id": f"pos_{a['code']}_{a['type']}_{now:.0f}",
            "content": f"🔔 持仓告警 [{a['level']}] {a['message']}",
            "platform": "feishu",
            "ts": now,
        }
        new_items.append(item)

    # 读取现有队列
    queue = []
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                queue = json.load(f)
        except Exception:
            queue = []

    # 追加新消息
    queue.extend(new_items)

    # 原子写回
    try:
        atomic_dump(queue, QUEUE_FILE, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[alert_queue] 写入失败: {e}")


def load_holdings():
    """读取当前持仓(只监控这个)"""
    if not os.path.exists(HOLDINGS_FILE):
        return []
    with open(HOLDINGS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("holdings", [])
    return data


def load_state():
    """加载提醒状态(避免重复推送同一触发)"""
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"triggered": {}, "high_prices": {}}


def save_state(state):
    """保存提醒状态 — 2026-08-11修复: 改用atomic_json原子写(FileLock)
    P0-1二次修复: 移除兜底裸open(并发覆盖危害>丢一次状态), atomic失败打warning直接抛
    原裸open("w")无锁 → 与orchestrator/position_tracker并发时互相覆盖
    症状: 高点57.5被覆盖成54.62, triggered被清 (外部writer幽灵)"""
    import logging as _logging
    _logger = _logging.getLogger("position_alerts")
    os.makedirs(os.path.dirname(ALERT_STATE_FILE), exist_ok=True)
    try:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(state, ALERT_STATE_FILE)
    except Exception as _e:
        _logger.warning("【P0-1修复】position_alerts_state.json 原子写失败, 放弃本次写入避免并发覆盖: %s", _e, exc_info=True)
        # 不再退到裸open("w"), 防止并发互覆盖 → cron下一轮再写即可


def load_buy_dates():
    """从 trade_log 获取每个持仓的买入日期 {code: 最早买入日}
    2026-08-10 修复: ①读 buys+trades 双源(trades 里有恒瑞8/6买入, buys 缺失) ②取最早买入日(后买的不覆盖先买的)"""
    try:
        log_path = os.path.join(PROJECT, "data", "trade_log.json")  # P2(t_febdf372): 归一 data/ 真源(根侧trade_log.json为9/23遗留,已移.trash)
        if not os.path.exists(log_path):
            return {}
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
        buy_dates = {}
        def _merge(records):
            for b in records:
                if b.get("type") not in (None, "buy"):
                    continue
                code = str(b.get("code", ""))
                # 归一化: sh600712 → 600712, 与 holdings 的 code 匹配
                clean = code[2:] if code[:2].isalpha() else code
                d = str(b.get("date", ""))
                if d and (clean not in buy_dates or d < buy_dates[clean]):
                    buy_dates[clean] = d
        _merge(log.get("buys", []))
        _merge(log.get("trades", []))
        return buy_dates
    except Exception:
        return {}


def check_position_alerts(push=False):
    """检查当前持仓的所有提醒条件

    Returns:
        list[dict]: 触发的提醒列表 [{code, name, type, level, message, price, trigger}]
    """
    holdings = load_holdings()
    if not holdings:
        print("  ℹ️  无当前持仓, 跳过监控")
        return []

    state = load_state()
    triggered = state.get("triggered", {})
    high_prices = state.get("high_prices", {})
    today = str(date.today())

    sys.path.insert(0, PROJECT)
    from core.pipeline.tdx_core import get_tdx_data
    buy_dates = load_buy_dates()

    alerts = []
    for h in holdings:
        code = h.get("code", "")
        name = h.get("name", "")
        cost = h.get("cost_price") or h.get("cost", 0) or 0  # 兼容新旧字段名
        shares = h.get("shares", 0) or 0

        # 获取现价 + 历史数据
        recs = get_tdx_data(code, 120)
        if not recs or len(recs) < 20:
            continue
        closes = [r["close"] for r in recs]
        dates = [str(r["date"]) for r in recs]
        current = closes[-1]

        # ── 移动止盈基准: 持仓期高点(买入后的最高价) ──
        # 修复(2026-08-02): 不能用买入前的高点(南宁5月6.52, 误报回撤20%)
        # 用 trade_log 的买入日期过滤, 只统计买入后的最高价
        clean_code = code[2:] if code[:2].isalpha() else code
        buy_date = buy_dates.get(clean_code, "")
        if buy_date:
            after_buy = [c for d, c in zip(dates, closes) if d >= buy_date]
            hist_high = max(after_buy) if after_buy else max(closes[-60:])
        else:
            hist_high = max(closes[-60:])
        initial_high = max(hist_high, cost) if cost > 0 else hist_high
        prev_high = high_prices.get(code, initial_high)
        # 高点只会向上更新, 且至少不低于成本 (2026-08-11: 若state被外部降值, 用历史/60日高点恢复)
        restored = max(prev_high, current, cost)
        if restored < initial_high:
            restored = initial_high  # state被污染(降值)时, 恢复为买入后真实高点
        high_prices[code] = restored

        # ── 分级移动止盈 (TREND_TP_LADDER 唯一权威源, 2026-09-29 T1收敛) ──
        # 浮盈<6%→回撤5% / <10%→7% / <20%→10% / ≥20%→12% (顶格12%)
        # GRADED_TP_LADDER (8/12/18/25) 已废弃归档，本文件硬编码改为引用单一源
        from risk_rules import TREND_TP_LADDER
        pnl_from_cost = (current / cost - 1) * 100 if cost > 0 else 0
        tp_threshold = TREND_TP_LADDER["up"][0][1]  # 默认首档 (6%, 5%)
        for profit_thresh, dd_thresh in TREND_TP_LADDER["up"]:
            if pnl_from_cost < profit_thresh:
                tp_threshold = dd_thresh
                break
        else:
            tp_threshold = TREND_TP_LADDER["up"][-1][1]  # 末档 (999%, 12%)
        drawdown = (high_prices[code] - current) / high_prices[code]
        if drawdown >= tp_threshold and code not in triggered.get("moving_tp", []):
            alerts.append({
                "code": code, "name": name, "type": "moving_tp",
                "level": "🔴", "message": f"移动止盈触发: 从高点{high_prices[code]:.2f}回撤{drawdown*100:.1f}% (盈利{pnl_from_cost:.1f}%档位{int(tp_threshold*100)}%)",
                "price": current, "trigger": f"<={high_prices[code]*(1-tp_threshold):.2f}",
            })
            triggered.setdefault("moving_tp", []).append(code)

        # ── 止损: 现价 <= 止损价(用买入成本-8%或持仓记录) ──
        # 2026-08-20 对齐: 老大拍板统一8%止损(risk_rules.STRATEGY_STOP_LOSS_PCT, P17最优)
        stop_loss = h.get("stop_loss") or (cost * 0.92)
        if current <= stop_loss and code not in triggered.get("stop_loss", []):
            alerts.append({
                "code": code, "name": name, "type": "stop_loss",
                "level": "🔴", "message": f"止损触发! 现价{current:.2f} <= 止损{stop_loss:.2f} (成本{cost:.2f})",
                "price": current, "trigger": f"<={stop_loss:.2f}",
            })
            triggered.setdefault("stop_loss", []).append(code)

        # ── 目标减仓: 现价 >= TP1 (成本+5%) ──
        # 注: TP1预警线(5%)≠移动止盈TP1(10%)。预警线用于提示减仓，移动止盈用于实际止盈。
        # 移动止盈使用 TREND_TP_LADDER=[(6,0.05),(10,0.07),(20,0.10),(999,0.12)] (T1 2026-09-29 统一)
        # GRADED_TP_LADDER (8/12/18/25) 已废弃，见 risk_rules.py:259-262
        tp1 = h.get("tp1") if h.get("tp1") is not None else (cost * 1.05)
        pnl_pct = (current / cost - 1) * 100 if cost > 0 else 0
        if current >= tp1 and code not in triggered.get("tp1", []):
            alerts.append({
                "code": code, "name": name, "type": "tp1",
                "level": "🟡", "message": f"到达减仓目标TP1: 现价{current:.2f} >= {tp1:.2f} (+{pnl_pct:.1f}%)",
                "price": current, "trigger": f">={tp1:.2f}",
            })
            triggered.setdefault("tp1", []).append(code)

        # ── 破位: 跌破 MA20 ──
        ma20 = sum(closes[-BREAK_MA:]) / BREAK_MA
        if current < ma20 and code not in triggered.get("break_ma", []):
            alerts.append({
                "code": code, "name": name, "type": "break_ma",
                "level": "🟡", "message": f"破位预警: 现价{current:.2f} 跌破MA20({ma20:.2f})",
                "price": current, "trigger": f"<{ma20:.2f}",
            })
            triggered.setdefault("break_ma", []).append(code)

    # ── 信号衰减退出 (2026-09-04 方案B): 评分下降≥15分触发 ──
    # 从 trade_log 读取入场时评分
    try:
        import json as _json
        tl_path = os.path.join(PROJECT, "data", "trade_log.json")
        if os.path.exists(tl_path):
            with open(tl_path, 'r', encoding='utf-8') as _f:
                tl = _json.load(_f)
            for rec in tl.get("recommendations", []):
                code = rec.get("code", "")
                entry_score = rec.get("entry_score")
                if entry_score is not None and code in [h.get("code") for h in holdings]:
                    # 重新计算当前评分（简化：用TDX数据快速估算）
                    # 实际应调用 scoring_engine，此处用市场状态替代
                    # TODO(P2): 接入完整评分重算（scoring_engine.batch_score）
                    pass
    except Exception as _e:
        pass  # 信号衰减检测失败不影响其他监控

    # 保存状态(已触发的不重复推送)
    state["triggered"] = triggered
    state["high_prices"] = high_prices
    state["last_check"] = today
    save_state(state)

    # 触发推送 - 优先写入消息队列(飞书)
    if push and alerts:
        # 写入消息队列供 cron_message_sender 消费
        _write_to_queue(alerts)
        # 兼容旧版微信推送作为降级
        try:
            from scripts.wechat import add as wx_push
            txt = "🔔 持仓提醒\n" + "\n".join(a["message"] for a in alerts)
            wx_push(txt)
        except ImportError:
            pass  # 微信已退役，静默跳过

    return alerts


def main():
    import argparse
    parser = argparse.ArgumentParser(description="持仓监控提醒")
    parser.add_argument("--push", action="store_true", help="触发时微信推送")
    args = parser.parse_args()

    print("=" * 60)
    print(f"  📡 持仓监控 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    alerts = check_position_alerts(push=args.push)

    if not alerts:
        print("\n  ✅ 持仓健康, 无触发信号")
    else:
        print(f"\n  🔔 触发 {len(alerts)} 条提醒:")
        for a in alerts:
            print(f"    {a['level']} [{a['name']}({a['code']})] {a['message']}")

    # ── 显示持仓策略价位表 ──
    print("\n" + "=" * 80)
    print("  📊 实盘持仓策略价位表 (移动止损/止盈)")
    print("=" * 80)
    holdings = load_holdings()
    if not holdings:
        print("  无持仓")
    else:
        for h in holdings:
            code = h.get("code", "")
            name = h.get("name", "")
            cost = h.get("cost_price") or h.get("cost", 0) or 0
            shares = h.get("shares", 0)
            # 获取现价
            try:
                from core.pipeline.tdx_core import get_tdx_data
                recs = get_tdx_data(code, 60)
                current = recs[-1].get("close", cost) if recs else cost
                closes = [r["close"] for r in recs[-20:]]
                ma20 = sum(closes) / len(closes) if closes else cost
            except Exception:
                current = cost
                ma20 = cost
            if cost == 0:
                print(f"\n  ⚠️ {name} ({code}): 成本为0，跳过计算")
                continue
            pnl_pct = (current / cost - 1) * 100

            # 止损价: 成本-8% (2026-08-20 对齐统一口径 P17最优, 原-6%旧口径)
            stop_loss = cost * 0.92

            # 移动止盈触发价 (分级, 与 check_position_alerts 触发逻辑一致)
            from risk_rules import TREND_TP_LADDER
            tp_threshold = TREND_TP_LADDER["up"][0][1]
            for profit_thresh, dd_thresh in TREND_TP_LADDER["up"]:
                if pnl_pct <= profit_thresh:
                    tp_threshold = dd_thresh
                    break
            else:
                tp_threshold = TREND_TP_LADDER["up"][-1][1]
            tp_label = f"{int(tp_threshold*100)}%"
            # 用60日高点计算
            highs = [r.get("high", 0) for r in recs[-60:]] if recs else [current]
            high_price = max(highs) if highs else current
            trailing_trigger = high_price * (1 - tp_threshold)

            # 输出详细表格
            print(f"\n  📈 {name} ({code})")
            print(f"     持仓: {shares}股 @ {cost:.2f} | 现价: {current:.2f} | 盈亏: {pnl_pct:+.2f}%")
            print(f"     止损价: {stop_loss:.2f} (成本-8%) | 距现价: {(current-stop_loss)/current*100:+.1f}%")
            print(f"     移动止盈: 高点{high_price:.2f} 回撤{tp_label}触发 → {trailing_trigger:.2f}")
            print(f"     MA20: {ma20:.2f} | 距现价: {(current-ma20)/current*100:+.1f}%")
            print(f"     策略: {'突破MA20可持有' if current > ma20 else '跌破MA20需警惕'}")
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
