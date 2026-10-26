import os
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
trade_tracker.py — 交易日志系统 v1.0
======================================
定位 (T5 2026-09-29 拍板, 单源纪律): **记录层, 非执行层**。
  - 职责: 推荐→实盘→结果全链路记录 + 止损提醒 + 自我进化数据积累。
  - **不接移动止盈**: 移动止盈实盘唯一执行路径 = position_alerts.py
    (已统一引用 risk_rules.TREND_TP_LADDER 单源, T1 收敛); 本文件零调用
    evaluate_trailing_exit / TREND_TP_LADDER 是设计事实, 非半死状态。
  - 复核口径: 下轮审查按"记录层=止损提醒, 不接移动止盈"认定, 勿再提接线。
每次推荐/买入/卖出自动记录，追踪推荐→实盘→结果全链路。
自动计算实际收益率 vs 预期风报比，积累自我进化数据。

用法:
  python trade_tracker.py                # 查看交易日志摘要
  python trade_tracker.py --recommend     # 交互式记录新的推荐
  python trade_tracker.py --buy           # 交互式记录买入
  python trade_tracker.py --sell          # 交互式记录卖出
  python trade_tracker.py --dashboard     # 生成业绩看板
  python trade_tracker.py --check         # 检查未了结的推荐
"""
import json, os, sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

# 2026-09-09 P0-4: 持仓/日志真源统一为 data/ (写方对齐读方)
# P1修复(20261023): S5迁移core/ops/后误指core/ops/, data/在仓库根
LOG_FILE = os.path.join(PROJECT_ROOT, "data", "trade_log.json")
HOLDINGS_FILE = os.path.join(PROJECT_ROOT, "data", "holdings.json")


# ========== 数据模型 ==========

def make_recommendation(code, name, score, strategy, entry_price, stop_loss,
                         tp1, tp2, tp3, tp4, market_state, reason, entry_score=None):
    """创建一条推荐记录"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "type": "recommendation",
        "timestamp": now,
        "date": now[:10],
        "code": code,
        "name": name,
        "score": score,
        "entry_score": entry_score if entry_score is not None else score,  # 入场时评分，用于信号衰减检测
        "strategy": strategy,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp4": tp4,
        "market_state": market_state,
        "reason": reason,
        "followed": None,       # True/False/None(未知)
        "buy_date": None,
        "buy_price": None,
        "buy_shares": None,
        "sell_date": None,
        "sell_price": None,
        "actual_return_pct": None,
        "holding_days": None,
        "max_drawdown_pct": None,
        "notes": "",
    }


def make_buy_event(recommend_id, code, name, buy_price, shares, note=""):
    """创建买入记录（关联到某条推荐）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "type": "buy",
        "timestamp": now,
        "date": now[:10],
        "recommend_id": recommend_id,
        "code": code,
        "name": name,
        "buy_price": buy_price,
        "shares": shares,
        "cost_total": round(buy_price * shares, 2),
        "note": note,
    }


def make_sell_event(code, name, sell_price, shares, pnl, return_pct, holding_days, note="", buy_date=None, buy_price=None):
    """创建卖出记录"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return {
        "type": "sell",
        "timestamp": now,
        "date": now[:10],
        "code": code,
        "name": name,
        "sell_price": sell_price,
        "shares": shares,
        "pnl": round(pnl, 2),
        "return_pct": round(return_pct, 2),
        "holding_days": holding_days,
        "buy_date": buy_date,
        "buy_price": buy_price,
        "actual_return_pct": round(return_pct, 2) if return_pct else None,
        "note": note,
    }


# ========== 存储 ==========

def load_log():
    """读取交易日志（本地优先——本地是权威源; 云端可能因同步失败/截断不完整）

    R4 修复(P0-3): 原 Supabase 优先导致"写本地/读云端"读-写不一致
    (同步失败读旧丢记录, 同步成功读重复)。改为本地权威 + 云端仅兜底。
    """
    # 本地优先(权威源)
    if os.path.exists(LOG_FILE):
        try:
            from core.pipeline.atomic_json import atomic_load
            data = atomic_load(LOG_FILE)
            if isinstance(data, dict) and "recommendations" in data:
                return data
        except Exception:
            pass
    # 云端兜底(本地缺失/损坏时)
    try:
        from supabase_data import load_trade_log as sb_load, is_connected
        if is_connected():
            data = sb_load()
            if data and isinstance(data, list) and len(data) > 0:
                return {"recommendations": [r for r in data if isinstance(r, dict) and r.get("type") == "recommendation"],
                        "buys": [r for r in data if isinstance(r, dict) and r.get("type") == "buy"],
                        "sells": [r for r in data if isinstance(r, dict) and r.get("type") == "sell"],
                        "meta": {"created": data[0].get("created_at", "") if isinstance(data[0], dict) else "", "source": "supabase"}}
    except ImportError:
        pass
    return {"recommendations": [], "buys": [], "sells": [], "meta": {"created": datetime.now().strftime("%Y-%m-%d %H:%M")}}


def _dedup_log(log):
    """按 (code + date + price) 三元组去重
    R3 修复: buy/sell 价格字段按类型取(buy_price/sell_price), 原取 entry_price 导致
    同日同 code 的 buy 记录全部折叠丢失(supabase_data._dedup 已正确, 此处对齐)。
    """
    for key in ("recommendations", "buys", "sells"):
        items = log.get(key, [])
        seen = set()
        deduped = []
        for item in items:
            if key == "buys":
                price = item.get("buy_price", "")
            elif key == "sells":
                price = item.get("sell_price", "")
            else:
                price = item.get("entry_price", "")
            dedup_key = (item.get("code", ""), str(item.get("date", "")), str(price))
            if dedup_key not in seen:
                seen.add(dedup_key)
                deduped.append(item)
        log[key] = deduped
    return log


def _mutate_log(mutator):
    """跨进程安全的读-改-写(FileLock + 原子写): mutator(data)返回新data

    PDCA-R R2: 替代 load_log→改→save_log 的裸读-改-写(跨进程并发会丢记录, 历史事故)。
    """
    from core.pipeline.atomic_json import update_json, atomic_dump
    try:
        return update_json(LOG_FILE, mutator, default={
            "recommendations": [], "buys": [], "sells": [],
            "meta": {"created": datetime.now().strftime("%Y-%m-%d %H:%M")}})
    except Exception:
        # 兜底: 旧行为(读-改-写 + 原子写), 保持不中断
        log = load_log()
        mutator(log)
        atomic_dump(log, LOG_FILE)
        return log


def _push_to_supabase(entry):
    """增量推送单条到 Supabase(失败静默降级, 不干扰主程序)

    R4(P0-3 Option B): 替代全量重推——原 _sync_to_supabase 遍历整个 log 重推,
    云端无 dedup 导致重复行累积, 且触发 limit=100 截断。
    """
    try:
        from supabase_data import append_trade_log
        append_trade_log(entry)
    except Exception:
        pass  # Supabase 不可用时静默降级


def save_log(log):
    """保存交易日志(全量写, 锁内替换; 兼容旧调用方)"""
    try:
        from core.pipeline.atomic_json import update_json
        update_json(LOG_FILE, lambda _: _dedup_log(log), default={
            "recommendations": [], "buys": [], "sells": [],
            "meta": {"created": datetime.now().strftime("%Y-%m-%d %H:%M")}})
    except Exception:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(_dedup_log(log), LOG_FILE)
    # 兼容旧调用方: 全量同步(低频; 新 append_* 走增量 _push_to_supabase)
    try:
        from supabase_data import append_trade_log
        for rec in log.get("recommendations", []):
            append_trade_log({**rec, "type": "recommendation"})
        for buy in log.get("buys", []):
            append_trade_log({**buy, "type": "buy"})
        for sell in log.get("sells", []):
            append_trade_log({**sell, "type": "sell"})
    except Exception:
        pass  # Supabase 不可用时静默降级


def append_recommendation(rec):
    """追加一条推荐记录(跨进程锁读-改-写)"""
    def mutate(log):
        log.setdefault("recommendations", []).append(rec)
        return _dedup_log(log)
    log = _mutate_log(mutate)
    _push_to_supabase({**rec, "type": "recommendation"})  # 增量: 只推本次
    return len(log["recommendations"]) - 1  # 返回 index 作为 recommend_id


def append_buy(buy):
    """追加一条买入记录(跨进程锁读-改-写)"""
    def mutate(log):
        log.setdefault("buys", []).append(buy)
        return _dedup_log(log)
    log = _mutate_log(mutate)
    _push_to_supabase({**buy, "type": "buy"})  # 增量: 只推本次


def append_sell(sell):
    """追加一条卖出记录(跨进程锁读-改-写)"""
    def mutate(log):
        log.setdefault("sells", []).append(sell)
        return _dedup_log(log)
    log = _mutate_log(mutate)
    _push_to_supabase({**sell, "type": "sell"})  # 增量: 只推本次


def update_recommendation(idx, updates):
    """更新推荐记录（如：标记已跟进、追加卖出结果）(跨进程锁读-改-写)

    R4: 不推送云端——云端 append_trade_log 无 update 语义, 推送会新增重复行。
    本地是权威源(load_log 已本地优先), 云端行保持原样。
    """
    def mutate(log):
        if 0 <= idx < len(log["recommendations"]):
            log["recommendations"][idx].update(updates)
        return log
    _mutate_log(mutate)


# ========== 分析函数 ==========

def get_open_recommendations():
    """获取未了结的推荐（已推荐但未卖出）"""
    log = load_log()
    open_recs = []
    for i, rec in enumerate(log["recommendations"]):
        if rec.get("sell_date") is None:
            open_recs.append((i, rec))
    return open_recs


def get_closed_recommendations():
    """获取已了结的推荐"""
    log = load_log()
    closed = []
    for i, rec in enumerate(log["recommendations"]):
        if rec.get("sell_date") is not None:
            closed.append((i, rec))
    return closed


def calc_performance():
    """计算历史推荐的整体性能指标"""
    closed = get_closed_recommendations()
    if not closed:
        return None

    returns = []
    win_count = 0
    for _, rec in closed:
        r = rec.get("actual_return_pct")
        if r is not None:
            returns.append(r)
            if r > 0:
                win_count += 1

    if not returns:
        return None

    total = len(returns)
    win_rate = win_count / total * 100
    avg_return = sum(returns) / total
    max_return = max(returns)
    min_return = min(returns)
    gains = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    avg_gain = sum(gains) / len(gains) if gains else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    profit_factor = abs(sum(gains) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

    return {
        "total_trades": total,
        "win_rate": round(win_rate, 1),
        "avg_return_pct": round(avg_return, 2),
        "max_return_pct": round(max_return, 2),
        "min_return_pct": round(min_return, 2),
        "avg_gain_pct": round(avg_gain, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
    }


def calc_expected_vs_actual():
    """计算推荐预期的风报比 vs 实际收益率（评估评分体系有效性）"""
    closed = get_closed_recommendations()
    if not closed:
        return None

    comparisons = []
    for _, rec in closed:
        entry = rec.get("entry_price")
        sl = rec.get("stop_loss")
        tp3 = rec.get("tp3")
        actual = rec.get("actual_return_pct")
        if entry and sl and tp3 and actual is not None:
            risk_pct = (entry - sl) / entry * 100
            reward_pct = (tp3 - entry) / entry * 100
            expected_rr = reward_pct / risk_pct if risk_pct > 0 else 0
            comparisons.append({
                "code": rec.get("code"), "name": rec.get("name"),
                "score": rec.get("score"), "strategy": rec.get("strategy"),
                "expected_rr": round(expected_rr, 1),
                "expected_reward_pct": round(reward_pct, 1),
                "actual_return_pct": actual,
                "accurate": abs(actual - reward_pct) < reward_pct * 0.5,
            })

    return comparisons


def calc_strategy_performance():
    """按策略统计性能"""
    closed = get_closed_recommendations()
    strat_stats = {}
    for _, rec in closed:
        strat = rec.get("strategy", "综合")
        r = rec.get("actual_return_pct")
        if r is None:
            continue
        if strat not in strat_stats:
            strat_stats[strat] = {"trades": [], "wins": 0}
        strat_stats[strat]["trades"].append(r)
        if r > 0:
            strat_stats[strat]["wins"] += 1

    result = {}
    for strat, data in strat_stats.items():
        n = len(data["trades"])
        result[strat] = {
            "trades": n,
            "win_rate": round(data["wins"] / n * 100, 1) if n > 0 else 0,
            "avg_return": round(sum(data["trades"]) / n, 2) if n > 0 else 0,
        }
    return result


def calc_market_state_performance():
    """按推荐时的市场状态统计性能"""
    closed = get_closed_recommendations()
    state_stats = {}
    for _, rec in closed:
        state = rec.get("market_state", "未知")
        r = rec.get("actual_return_pct")
        if r is None:
            continue
        if state not in state_stats:
            state_stats[state] = {"trades": [], "wins": 0}
        state_stats[state]["trades"].append(r)
        if r > 0:
            state_stats[state]["wins"] += 1

    result = {}
    for state, data in state_stats.items():
        n = len(data["trades"])
        result[state] = {
            "trades": n, "win_rate": round(data["wins"] / n * 100, 1) if n > 0 else 0,
            "avg_return": round(sum(data["trades"]) / n, 2) if n > 0 else 0,
        }
    return result


# ========== 输出 ==========

def print_dashboard():
    """打印业绩看板"""
    perf = calc_performance()
    strat_perf = calc_strategy_performance()
    state_perf = calc_market_state_performance()
    eva = calc_expected_vs_actual()

    print("=" * 62)
    print("  📊 交易日志 · 业绩看板")
    print("=" * 62)

    if perf:
        print(f"\n  📈 整体业绩")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"  总交易次数:  {perf['total_trades']}")
        print(f"  胜率:        {perf['win_rate']}%")
        print(f"  平均收益率:  {perf['avg_return_pct']:+.2f}%")
        print(f"  最大收益:    {perf['max_return_pct']:+.2f}%")
        print(f"  最大亏损:    {perf['min_return_pct']:+.2f}%")
        print(f"  平均盈利:    {perf['avg_gain_pct']:+.2f}%")
        print(f"  平均亏损:    {perf['avg_loss_pct']:+.2f}%")
        print(f"  盈亏比:      1:{perf['profit_factor']:.2f}")
    else:
        print("\n  📭 暂无已了结的交易记录")

    open_recs = get_open_recommendations()
    if open_recs:
        print(f"\n  🔄 未了结推荐 ({len(open_recs)} 条)")
        for i, rec in open_recs:
            print(f"  [{i}] {rec.get('name','')}({rec.get('code','')}) "
                  f"评分{rec.get('score','')} 策略:{rec.get('strategy','')} "
                  f"推荐日:{rec.get('date','')}")

    if strat_perf:
        print(f"\n  🎯 各策略表现")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for strat, data in sorted(strat_perf.items(), key=lambda x: x[1]["win_rate"], reverse=True):
            print(f"  {strat}: 胜率{data['win_rate']}% 均收益{data['avg_return']:+.2f}% ({data['trades']}次)")

    if state_perf:
        print(f"\n  🌤️ 各市场状态表现")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for state, data in sorted(state_perf.items(), key=lambda x: x[1]["win_rate"], reverse=True):
            print(f"  {state}: 胜率{data['win_rate']}% 均收益{data['avg_return']:+.2f}% ({data['trades']}次)")

    if eva:
        print(f"\n  🎯 预期vs实际偏差")
        print(f"  ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        accurate = sum(1 for e in eva if e["accurate"])
        print(f"  预期准确率: {accurate}/{len(eva)} ({round(accurate/len(eva)*100,1)}%)")
        score_buckets = {}
        for e in eva:
            bucket = f"{e['score']//10*10}-{e['score']//10*10+9}"
            score_buckets.setdefault(bucket, []).append(e["actual_return_pct"])
        for bucket in sorted(score_buckets.keys()):
            vals = score_buckets[bucket]
            avg = sum(vals) / len(vals)
            print(f"  评分 {bucket}分: {len(vals)}次 均收益率{avg:+.2f}%")
        print()

    # 推荐记录详细列表
    log = load_log()
    if log["recommendations"]:
        print(f"\n  📋 完整推荐记录")
        print(f"  {'#':<3} {'股票':<14} {'评分':<6} {'策略':<6} {'推荐日':<12} {'结果':<10}")
        print(f"  {'-'*55}")
        for i, rec in enumerate(reversed(log["recommendations"])):
            idx = len(log["recommendations"]) - 1 - i
            r = rec.get("actual_return_pct")
            result_str = f"{r:+.2f}%" if r is not None else "进行中"
            print(f"  {idx:<3} {rec.get('name',''):<6}({rec.get('code','')}) "
                  f"{rec.get('score',0):<6} {rec.get('strategy',''):<6} "
                  f"{rec.get('date',''):<12} {result_str:<10}")


def auto_log_recommendation(code, name, score, strategy, entry_price, stop_loss,
                             tp1, tp2, tp3, tp4, market_state, reason):
    """
    stock_picker_v3.py 调用的便捷接口:
    自动创建推荐记录并返回 recommend_id
    """
    rec = make_recommendation(code, name, score, strategy, entry_price,
                               stop_loss, tp1, tp2, tp3, tp4, market_state, reason)
    rec_id = append_recommendation(rec)
    print(f"\n  📝 已记录推荐 #{rec_id} → trade_log.json")
    return rec_id


def auto_log_buy(code, name, buy_price, shares, recommend_id=None):
    """买入时调用 — 自动三源同步(trade_log + holdings + Supabase)"""
    buy = make_buy_event(recommend_id, code, name, buy_price, shares)
    append_buy(buy)
    if recommend_id is not None:
        update_recommendation(recommend_id, {
            "followed": True,
            "buy_date": buy["date"],
            "buy_price": buy_price,
            "buy_shares": shares,
        })
    # 同步 holdings.json + Supabase (实盘三源规范)
    _sync_holdings_add(code, name, buy_price, shares, buy["date"])
    print(f"\n  📝 已记录买入 → trade_log.json + holdings.json + Supabase")
    return buy


def auto_log_sell(code, name, sell_price, shares, pnl, return_pct, holding_days,
                  recommend_id=None, note="", buy_date=None, buy_price=None):
    """卖出时调用 — 自动三源同步(trade_log + holdings + Supabase)"""
    sell = make_sell_event(code, name, sell_price, shares, pnl, return_pct, holding_days, note, buy_date, buy_price)
    append_sell(sell)
    if recommend_id is not None:
        update_recommendation(recommend_id, {
            "sell_date": sell["date"],
            "sell_price": sell_price,
            "actual_return_pct": round(return_pct, 2),
            "holding_days": holding_days,
            "notes": note,
        })
    # 同步 holdings.json + Supabase
    _sync_holdings_remove(code, sell_price, shares)
    print(f"\n  📝 已记录卖出 → trade_log.json + holdings.json + Supabase")


def _load_local_holdings():
    """读取本地 holdings.json (dict 格式)"""
    if os.path.exists(HOLDINGS_FILE):
        try:
            with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {"holdings": [], "available_cash": 0, "total_assets": 0, "updated": ""}


def _save_local_holdings(data):
    """保存本地 holdings.json (原子写)"""
    # 休眠路径 (2026-08-13 任务2③): 调用方不存在 (_sync_holdings_* 已改 update_json),
    # 若启用需改 update_json 加跨进程 FileLock, 否则与 record_trade 并发会互覆盖.
    try:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(data, HOLDINGS_FILE)
    except Exception:
        atomic_json.atomic_dump(data, HOLDINGS_FILE, ensure_ascii=False, indent=2, encoding="utf-8")


def _sync_holdings_add(code, name, price, shares, date_str):
    """买入后: holdings 加持仓 + 扣现金 → 同步 Supabase
    (2026-08-11 任务5.1修复: 原 _load_local_holdings+_save_local_holdings 裸读-改-写,
     无跨进程FileLock → 改 update_json, 与 record_trade 并发写 holdings 不再互覆盖)"""
    try:
        from core.pipeline.atomic_json import update_json

        def _mutate(data):
            if not isinstance(data, dict):
                data = {"holdings": [], "available_cash": 0.0}
            holdings = data.get("holdings", [])
            clean = code[2:] if code[:2].isalpha() else code
            for h in holdings:
                if str(h.get("code", "")).endswith(clean):
                    old_shares = h.get("shares", 0)
                    old_cost = h.get("cost", h.get("cost_price", 0))
                    total_shares = old_shares + shares
                    h["cost"] = round((old_cost * old_shares + price * shares) / total_shares, 3) if total_shares else old_cost
                    h["shares"] = total_shares
                    break
            else:
                holdings.append({"code": code, "name": name, "cost_price": price,
                                 "shares": shares, "buy_date": date_str})
            data["holdings"] = holdings
            data["available_cash"] = round(float(data.get("available_cash", 0) or 0) - price * shares, 2)
            data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return data

        update_json(HOLDINGS_FILE, _mutate,
                    default={"holdings": [], "available_cash": 0.0})
        # 注: 原此处有向 Supabase 推送持仓的同步块, 已于 2026-10-17 按红线 O-3 移除
        #     (实盘持仓不得出本机)。本地 data/holdings.json 即为唯一权威源, 无待补动作。
    except Exception as e:
        print(f"  ⚠️ holdings 同步失败: {e}")


def _sync_holdings_remove(code, sell_price, shares):
    """卖出后: holdings 减持仓 + 加现金 → 同步 Supabase
    (2026-08-11 任务5.1修复: 原裸读-改-写 → update_json FileLock, 同上)"""
    try:
        from core.pipeline.atomic_json import update_json

        def _mutate(data):
            if not isinstance(data, dict):
                data = {"holdings": [], "available_cash": 0.0}
            holdings = data.get("holdings", [])
            clean = code[2:] if code[:2].isalpha() else code
            remaining = []
            for h in holdings:
                if str(h.get("code", "")).endswith(clean):
                    old_shares = h.get("shares", 0)
                    new_shares = old_shares - shares
                    if new_shares > 0:
                        h["shares"] = new_shares
                        remaining.append(h)
                    # 全部卖出则移除
                else:
                    remaining.append(h)
            data["holdings"] = remaining
            data["available_cash"] = round(float(data.get("available_cash", 0) or 0) + sell_price * shares, 2)
            data["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            return data

        update_json(HOLDINGS_FILE, _mutate,
                    default={"holdings": [], "available_cash": 0.0})
        # 注: 原此处有向 Supabase 推送持仓的同步块, 已于 2026-10-17 按红线 O-3 移除
    except Exception as e:
        print(f"  ⚠️ holdings 同步失败: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "--dashboard":
            print_dashboard()
        elif cmd == "--check":
            open_recs = get_open_recommendations()
            if open_recs:
                print(f"未了结推荐 ({len(open_recs)} 条):")
                for i, rec in open_recs:
                    print(f"  [{i}] {rec.get('name')}({rec.get('code')}) "
                          f"推荐日:{rec.get('date')} 买入价:{rec.get('buy_price','-')}")
            else:
                print("✅ 没有未了结的推荐")
        elif cmd == "--recommend":
            print("交互式记录推荐 (暂未实现CLI模式, 请通过 auto_log_recommendation 调用)")
        else:
            print(f"未知命令: {cmd}")
    else:
        print_dashboard()
