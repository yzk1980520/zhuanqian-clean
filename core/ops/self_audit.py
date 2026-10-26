import os
import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import sys
"""
self_audit.py — 自省告警系统 v2.0
======================================
每日自动检查选股系统表现，发现问题立即告警（含微信推送）

核心功能:
1. 检查最近N次推荐的胜率
2. 如果胜率<40% → 推送告警
3. 分析错误模式（评分虚高/止损太宽/策略选错）
4. 生成诊断报告
5. 微信实时推送（集成iLinkAI）

用法:
  python self_audit.py              # 运行自检
  python self_audit.py --watch      # 持续监控模式（每小时检查一次）
  python self_audit.py --report     # 生成详细诊断报告
"""
import json, os, urllib.request, urllib.error
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

PROJECT_DIR = PROJECT_ROOT
# P2(t_2a4a5b94): 根侧 trade_log.json 为 9/23 遗留(trades=[])，真源在 data/ 下；
# 读错路径=假阳性根因（与 HOLDINGS_FILE/AUDIT_LOG_FILE 对齐 data/ 前缀）
TRADE_LOG_FILE = os.path.join(PROJECT_DIR, "data", "trade_log.json")
HOLDINGS_FILE = os.path.join(PROJECT_DIR, "data", "holdings.json")
AUDIT_LOG_FILE = os.path.join(PROJECT_DIR, "data", "audit_log.json")

# 推送配置 (PushPlus — 微信消息推送)
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_API = "https://www.pushplus.plus/send/"
PUSH_ENABLED = True  # 开关

# 告警阈值
WIN_RATE_THRESHOLD = 40.0      # 胜率低于此触发告警
RECOMMENDATION_WINDOW = 10     # 检查最近N次推荐
MIN_FOLLOWED = 3               # 至少N笔跟进才计算胜率
HOLDING_RISK_THRESHOLD = 95.0  # 仓位高于此触发风险告警

# 辅助函数
def _http_post_json(url, data):
    import json, urllib.request
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'),
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode('utf-8')
    except Exception as e:
        return None

def push_alert(title, content, severity="info"):
    """通过 PushPlus 推送微信消息"""
    if not PUSH_ENABLED or not PUSHPLUS_TOKEN:
        return False
    try:
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "ℹ️")
        data = {
            "token": PUSHPLUS_TOKEN,
            "title": f"{emoji} {title}",
            "content": content,
            "template": "txt",
        }
        _http_post_json(PUSHPLUS_API, data)
        return True
    except Exception:
        return False

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

def save_json(path, data):
    atomic_json.atomic_dump(data, path, ensure_ascii=False, indent=2, encoding="utf-8")

def get_recent_recommendations(n=RECOMMENDATION_WINDOW):
    """获取最近N条推荐"""
    log = load_json(TRADE_LOG_FILE)
    if not log or "recommendations" not in log:
        return []

    recs = sorted(
        log["recommendations"],
        key=lambda x: x.get("timestamp", ""),
        reverse=True,
    )
    return recs[:n]

def compute_audit_metrics():
    """计算自检指标"""
    recs = get_recent_recommendations()
    if not recs:
        return None

    metrics = {
        "total_recommendations": len(recs),
        "followed": 0,
        "wins": 0,
        "losses": 0,
        "unknown": 0,
        "win_rate": 0,
        "avg_return": 0,
        "returns": [],
        "recency_issues": [],
        "error_patterns": [],
        "score_vs_performance": [],
    }

    for r in recs:
        followed = r.get("followed")
        ret = r.get("actual_return_pct")
        score = r.get("score", 0)
        strategy = r.get("strategy", "未知")
        code = r.get("code", "")
        name = r.get("name", "")

        if followed is True:
            metrics["followed"] += 1
            if ret is not None:
                metrics["returns"].append(ret)
                if ret > 0:
                    metrics["wins"] += 1
                else:
                    metrics["losses"] += 1

                # 记录评分vs实际表现
                metrics["score_vs_performance"].append({
                    "date": r.get("date", ""),
                    "code": code,
                    "name": name,
                    "score": score,
                    "strategy": strategy,
                    "predicted": "positive" if score > 70 else "neutral",
                    "actual_return": ret,
                    "correct": ret > 0,
                })
        elif followed is False:
            metrics["unknown"] += 1
        else:
            metrics["unknown"] += 1

    if metrics["followed"] > 0:
        metrics["win_rate"] = round(metrics["wins"] / metrics["followed"] * 100, 1)
        metrics["avg_return"] = round(
            sum(metrics["returns"]) / len(metrics["returns"]), 2
        )

    return metrics

def analyze_error_patterns(metrics):
    """分析错误模式"""
    patterns = []
    svp = metrics.get("score_vs_performance", [])

    # 模式1: 高评分推荐频繁亏损（评分虚高）
    high_score_losses = [
        s for s in svp if s["score"] >= 80 and s["actual_return"] < 0
    ]
    if len(high_score_losses) >= 2:
        codes = [s["code"] for s in high_score_losses]
        patterns.append({
            "type": "score_overconfidence",
            "description": f"高评分推荐({codes})频繁亏损，评分可能虚高",
            "count": len(high_score_losses),
            "severity": "high",
        })
        metrics["error_patterns"].append(patterns[-1])

    # 模式2: 弱市用了趋势策略
    weak_trend_loss = [
        s for s in svp
        if s.get("strategy") == "趋势" and s["actual_return"] < 0
    ]
    if len(weak_trend_loss) >= 2:
        patterns.append({
            "type": "wrong_strategy_for_market",
            "description": "弱市使用趋势策略频繁亏损，应切换为抄底策略",
            "count": len(weak_trend_loss),
            "severity": "medium",
        })
        metrics["error_patterns"].append(patterns[-1])

    # 模式3: 连续亏损
    consecutive_losses = 0
    max_consecutive = 0
    for r in sorted(svp, key=lambda x: x.get("date", "")):
        if r["actual_return"] < 0:
            consecutive_losses += 1
            max_consecutive = max(max_consecutive, consecutive_losses)
        else:
            consecutive_losses = 0

    if max_consecutive >= 3:
        patterns.append({
            "type": "consecutive_losses",
            "description": f"连续{max_consecutive}次推荐亏损，需检查评分公式",
            "count": max_consecutive,
            "severity": "high",
        })
        metrics["error_patterns"].append(patterns[-1])

    # 模式4: 实际收益与预测方向相反
    wrong_direction = [
        s for s in svp if (s["score"] > 70 and s["actual_return"] < -2)
        or (s["score"] < 50 and s["actual_return"] > 3)
    ]
    if len(wrong_direction) >= 2:
        patterns.append({
            "type": "prediction_inversion",
            "description": "预测方向与实际相反出现多次，评分逻辑需校准",
            "count": len(wrong_direction),
            "severity": "high",
        })
        metrics["error_patterns"].append(patterns[-1])

    return patterns

def check_holding_risk():
    """检查持仓风险"""
    holdings = load_json(HOLDINGS_FILE)
    if not holdings:
        return None

    warnings = []
    total_value = holdings.get("total_value", 0)
    if total_value <= 0:
        return None

    cash = holdings.get("cash", 0)
    total_invested = total_value - cash
    position_pct = round(total_invested / total_value * 100, 1)

    if position_pct > HOLDING_RISK_THRESHOLD:
        warnings.append({
            "type": "high_position",
            "description": f"仓位{position_pct}%超过{HOLDING_RISK_THRESHOLD}%警戒线",
            "value": position_pct,
            "severity": "high",
        })

    # 检查个股盈亏
    for k, v in holdings.items():
        if k.startswith("sz") or k.startswith("sh"):
            stock = v
            pnl_pct = stock.get("pnl_pct", 0)
            if pnl_pct < -5:
                warnings.append({
                    "type": "stock_loss",
                    "code": k,
                    "name": stock.get("name", ""),
                    "description": f"{k} {stock.get('name','')} 盈亏{pnl_pct}%，接近止损线",
                    "value": pnl_pct,
                    "severity": "medium",
                })

    return warnings if warnings else None

def generate_audit_report(send_push=False):
    """生成自检报告"""
    print("=" * 60)
    print("🔍 自省告警系统 v2.0")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # Step 1: 计算指标
    print("\n📊 指标概览")
    metrics = compute_audit_metrics()
    if metrics is None or metrics["total_recommendations"] == 0:
        print("   ⚠️ 暂无推荐记录，无法自省")
        return {"status": "no_data"}

    print(f"   总推荐: {metrics['total_recommendations']}次")
    print(f"   已跟进: {metrics['followed']}次")
    print(f"   胜率: {metrics['win_rate']}%")
    print(f"   平均收益: {metrics['avg_return']}%")

    # Step 2: 告警检查
    print("\n🚨 告警检查")
    alerts = []
    if metrics["win_rate"] < WIN_RATE_THRESHOLD and metrics["followed"] >= MIN_FOLLOWED:
        alerts.append({
            "type": "low_win_rate",
            "description": f"胜率{metrics['win_rate']}%低于{WIN_RATE_THRESHOLD}%底线",
            "severity": "high",
        })
        print(f"   🔴 告警: 胜率过低 ({metrics['win_rate']}% < {WIN_RATE_THRESHOLD}%)")

    if metrics["avg_return"] < -0.5 and metrics["followed"] >= MIN_FOLLOWED:
        alerts.append({
            "type": "negative_avg_return",
            "description": f"平均收益{metrics['avg_return']}%为负",
            "severity": "medium",
        })
        print(f"   🟡 警告: 平均收益为负 ({metrics['avg_return']}%)")

    if not alerts:
        print("   ✅ 无告警，性能正常")

    # Step 3: 错误模式分析
    print("\n🔬 错误模式分析")
    patterns = analyze_error_patterns(metrics)
    if patterns:
        for p in patterns:
            print(f"   ⚠️ [{p['severity']}] {p['description']}")
    else:
        print("   ✅ 未发现明显错误模式")

    # Step 4: 持仓风险检查
    print("\n💼 持仓风险检查")
    holding_warnings = check_holding_risk()
    if holding_warnings:
        for w in holding_warnings:
            print(f"   {'🔴' if w['severity']=='high' else '🟡'} {w['description']}")
    else:
        print("   ✅ 仓位正常")

    # Step 5: 记录审计日志
    audit_entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "metrics": {
            "total": metrics["total_recommendations"],
            "followed": metrics["followed"],
            "win_rate": metrics["win_rate"],
            "avg_return": metrics["avg_return"],
        },
        "alerts": alerts,
        "error_patterns": patterns,
        "holding_warnings": holding_warnings or [],
    }

    audit_log = load_json(AUDIT_LOG_FILE) or {"history": []}
    audit_log["history"].append(audit_entry)
    save_json(AUDIT_LOG_FILE, audit_log)

    # Step 6: 微信推送告警
    if send_push and (alerts or patterns or holding_warnings):
        send_push_alerts(alerts, patterns, holding_warnings)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"🔍 自检完成: {len(alerts)}告警, {len(patterns)}错误模式")
    print("=" * 60)

    return {
        "status": "ok" if not alerts else "alert",
        "alerts_count": len(alerts),
        "patterns_count": len(patterns),
        "alerts": alerts,
        "patterns": patterns,
    }

def send_push_alerts(alerts, patterns, holding_warnings):
    """发送 PushPlus 推送"""
    lines = [f"📊 自省告警系统报告", f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

    if alerts:
        lines.append("🔴 告警:")
        for a in alerts:
            lines.append(f"  - {a['description']}")

    if patterns:
        lines.append("")
        lines.append("⚠️ 错误模式:")
        for p in patterns:
            lines.append(f"  - {p['description']}")

    if holding_warnings:
        lines.append("")
        lines.append("💼 持仓风险:")
        for w in holding_warnings:
            lines.append(f"  - {w['description']}")

    if not alerts and not patterns and not holding_warnings:
        lines.append("✅ 系统正常，无异常")

    content = "\n".join(lines)
    push_alert("自省告警", content, "high" if alerts else "medium")

def watch_mode():
    """持续监控模式"""
    print("👁️ 持续监控模式启动 (按Ctrl+C退出)")
    print(f"每小时自动自检一次，告警阈值: 胜率<{WIN_RATE_THRESHOLD}%\n")

    while True:
        try:
            result = generate_audit_report(send_push=True)
            if result.get("alerts_count", 0) > 0:
                print(f"\n⚠️ 发现{result['alerts_count']}个告警，需关注！\n")
            import time
            time.sleep(3600)  # 每小时检查一次
        except KeyboardInterrupt:
            print("\n监控已停止")
            break

if __name__ == "__main__":
    import time, argparse
    parser = argparse.ArgumentParser(description="自省告警系统")
    parser.add_argument("--watch", action="store_true", help="持续监控模式")
    parser.add_argument("--report", action="store_true", help="详细诊断报告")
    parser.add_argument("--audit", action="store_true",
                        help="运行自审 Agent R0 检查器（C-1/C-2/D-1/A-1/R1/M-1/M-2/M-3/M-4；"
                             "M-4=因子衰减监控挂表 P2-O3, 2026-10-20）")
    args = parser.parse_args()

    if args.audit:
        # 自审 Agent R0：契约漂移/假绿/口径漂移检测（只读不写）
        from core.ops.self_audit_checkers import run_all_checkers, print_summary
        results = run_all_checkers(send_alerts=True)
        print_summary(results)
        sys.exit(1 if any(r.status == "FAIL" for r in results) else 0)
    elif args.watch:
        watch_mode()
    else:
        generate_audit_report(send_push=False)
