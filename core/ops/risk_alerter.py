import core.pipeline.atomic_json as atomic_json  # R5 (2026-08-31): 统一 atomic_dump 入口
import sys
# 强制 stdout utf-8(errors=replace), 防 gbk 控制台打印 emoji/特殊字符崩 (同源修复 laowu_monitor)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
"""
risk_alerter.py — 风控告警推送集成 v1.0
===========================================
集成 PushPlus 推送告警，当触发阈值时自动调用 self_audit.py 的 push_alert

功能:
  1. 接收 risk_monitor 生成的风控报告
  2. 按阈值自动判断告警级别（紧急/警告/正常）
  3. 调用 self_audit.push_alert 推送微信消息
  4. 记录告警日志到 data/audit_log.json

用法:
  python risk_alerter.py              # 运行风控检查+推送告警
  python risk_alerter.py --dry-run    # 仅显示告警内容不推送
"""
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys
from datetime import datetime

PROJECT_DIR = PROJECT_ROOT
DATA_DIR = os.path.join(PROJECT_DIR, "data")
RISK_REPORT_FILE = os.path.join(DATA_DIR, "risk_report_latest.json")
AUDIT_LOG_FILE = os.path.join(DATA_DIR, "audit_log.json")

# ─── 告警阈值 ──────────────────────────────────────────────────
# 这些阈值与 risk_monitor.py 保持一致
CONSECUTIVE_LOSS_EMERGENCY = 5
CONSECUTIVE_LOSS_WARN = 3
POSITION_OVER_PCT_WARN = 10    # 超仓超过此值警告
POSITION_OVER_PCT_EMERGENCY = 20  # 超仓超过此值紧急

# PushPlus 推送模板
RISK_ALERT_TEMPLATE = """📊 A股风控告警

📅 日期: {date}
🏆 风控评分: {score}/100 ({level})

📉 账户状态:
  总资产: ¥{total_assets:.2f}
  仓位: {position_pct}%
  总盈亏: {pnl_pct}%

🎯 市场风格: {market_style} | {market_state}

⚠️ 风险信号 ({signal_count}个):

{signals_text}

💡 建议:
{action_text}
"""


# ─── 辅助函数 ──────────────────────────────────────────────────

def load_json(path):
    """安全加载JSON文件"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception):
            pass
    return None


def save_json(path, data):
    """保存JSON文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_json.atomic_dump(data, path, ensure_ascii=False, indent=2, encoding="utf-8")


# ─── 告警判断 ──────────────────────────────────────────────────

def classify_alert_level(report):
    """
    根据风控报告判断告警级别

    返回: "emergency" | "warning" | "normal"
    """
    risk_signals = report.get("risk_signals", [])
    risk_score = report.get("risk_score", 100)

    # 检查是否有紧急信号
    emergency_signals = [s for s in risk_signals if s.get("severity") == "emergency"]
    warning_signals = [s for s in risk_signals if s.get("severity") == "warning"]

    # 检查连续亏损
    losing_streak = report.get("losing_streak", {})
    consecutive_losses = losing_streak.get("consecutive_losses", 0)

    # 检查仓位
    position_control = report.get("position_control", {})
    over_pct = position_control.get("over_pct", 0)

    # 紧急条件
    if emergency_signals:
        return "emergency"
    if consecutive_losses >= CONSECUTIVE_LOSS_EMERGENCY:
        return "emergency"
    if over_pct >= POSITION_OVER_PCT_EMERGENCY:
        return "emergency"
    if risk_score < 60:
        return "emergency"

    # 警告条件
    if warning_signals:
        return "warning"
    if consecutive_losses >= CONSECUTIVE_LOSS_WARN:
        return "warning"
    if over_pct >= POSITION_OVER_PCT_WARN:
        return "warning"
    if risk_score < 80:
        return "warning"

    return "normal"


def format_alert_content(report):
    """
    格式化合告警推送内容
    """
    risk_signals = report.get("risk_signals", [])
    risk_score = report.get("risk_score", 100)
    risk_level = report.get("risk_level", "🟢 低风险")
    account = report.get("account_status", {})
    market = report.get("market", {})
    actions = report.get("recommended_action", [])

    # 格式化信号文本
    if risk_signals:
        signals_lines = []
        for s in risk_signals:
            level = s.get("level", "📊")
            indicator = s.get("indicator", "")
            suggestion = s.get("suggestion", "")
            line = f"  {level} {indicator}"
            if suggestion:
                line += f"\n    └ {suggestion}"
            signals_lines.append(line)
        signals_text = "\n".join(signals_lines)
    else:
        signals_text = "  ✅ 所有指标正常，无风险信号"

    # 格式化建议
    action_text = "\n".join([f"  {a}" for a in actions]) if actions else "  无"

    return RISK_ALERT_TEMPLATE.format(
        date=report.get("report_date", "未知"),
        score=risk_score,
        level=risk_level,
        total_assets=account.get("total_assets", 0),
        position_pct=account.get("position_pct", 0),
        pnl_pct=account.get("total_pnl_pct", 0),
        market_style=market.get("style", "未知"),
        market_state=market.get("market_state", "未知"),
        signal_count=len(risk_signals),
        signals_text=signals_text,
        action_text=action_text,
    )


# ─── 推送函数 ──────────────────────────────────────────────────

def alert_risk(report=None, dry_run=False):
    """
    风控告警推送入口

    1. 加载或接收风控报告
    2. 判断告警级别
    3. 调用 self_audit.push_alert 推送微信
    4. 记录告警日志

    参数:
      report: 风控报告dict（如为None，从文件加载）
      dry_run: 仅显示不推送
    """
    if report is None:
        report = load_json(RISK_REPORT_FILE)
        if not report:
            print("❌ 风控报告不存在，请先运行 risk_monitor.py")
            return None

    # 判断级别
    alert_level = classify_alert_level(report)
    alert_content = format_alert_content(report)

    # 显示
    print("=" * 60)
    print("📤 风控告警推送")
    print(f"级别: {alert_level.upper()}")
    print("=" * 60)
    print(alert_content)

    # 正常级别不推送
    if alert_level == "normal":
        print("\n✅ 所有指标正常，不推送告警（仅记录）")
        return {"alert_level": alert_level, "pushed": False}

    # Dry-run 模式
    if dry_run:
        print(f"\n🔍 Dry-run 模式 - 发现 {alert_level.upper()} 级别告警")
        print("  以下信息将被推送:")
        print(alert_content)
        return {"alert_level": alert_level, "pushed": False, "content": alert_content}

    # 推送到微信
    try:
        sys.path.insert(0, PROJECT_DIR)
        from core.ops.self_audit import push_alert

        severity_map = {"emergency": "high", "warning": "medium", "normal": "low"}
        severity = severity_map.get(alert_level, "medium")

        # 决定推送标题
        if alert_level == "emergency":
            title = f"🚨 风控紧急告警 - {report.get('report_date', '')}"
        elif alert_level == "warning":
            title = f"⚠️ 风控警告 - {report.get('report_date', '')}"
        else:
            title = f"ℹ️ 风控日报 - {report.get('report_date', '')}"

        pushed = push_alert(title, alert_content, severity)

        if pushed:
            print(f"\n✅ PushPlus推送成功! (级别={alert_level})")
        else:
            print(f"\n⚠️ PushPlus推送失败 (检查 PUSHPLUS_TOKEN 是否配置)")

        # 记录告警日志
        alert_log = load_json(AUDIT_LOG_FILE) or {"history": [], "alerts": []}
        alert_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": "risk_alert",
            "alert_level": alert_level,
            "risk_score": report.get("risk_score", 0),
            "signal_count": len(report.get("risk_signals", [])),
            "pushed": pushed,
            "summary": report.get("recommended_action", []),
        }
        alert_log.setdefault("alerts", []).append(alert_entry)
        save_json(AUDIT_LOG_FILE, alert_log)

        return {"alert_level": alert_level, "pushed": pushed}

    except ImportError as e:
        print(f"\n❌ 无法导入 self_audit.push_alert: {e}")
        print("  请确保 self_audit.py 在项目目录中")
        return {"alert_level": alert_level, "pushed": False, "error": str(e)}

    except Exception as e:
        print(f"\n❌ 推送异常: {e}")
        return {"alert_level": alert_level, "pushed": False, "error": str(e)}


def check_and_alert():
    """
    一键运行: 风控检查 + 告警推送
    先运行 risk_monitor 生成报告，再推送
    """
    # 运行风控检查
    print("▶️ 运行风控检查...")
    try:
        from core.ops.risk_monitor import generate_daily_report
        report = generate_daily_report()
    except ImportError:
        print("❌ 无法导入 risk_monitor")
        return None
    except Exception as e:
        print(f"❌ 风控检查异常: {e}")
        return None

    # 推送告警
    print(f"\n▶️ 推送告警...")
    result = alert_risk(report)
    return result


# ─── 命令行入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="风控告警推送系统")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run模式，仅显示不推送")
    parser.add_argument("--check-only", action="store_true", help="仅运行风控检查，不推送")
    args = parser.parse_args()

    if args.check_only:
        # 仅运行风控检查
        try:
            from core.ops.risk_monitor import generate_daily_report
            generate_daily_report()
        except ImportError as e:
            print(f"❌ 导入失败: {e}")
    else:
        # 完整流程：检查+推送
        result = check_and_alert()
        if result:
            print(f"\n{'=' * 60}")
            print(f"完成: 级别={result.get('alert_level', 'unknown')}, 推送={'✅' if result.get('pushed') else '❌'}")
