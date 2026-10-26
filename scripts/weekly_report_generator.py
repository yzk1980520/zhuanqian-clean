#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
御龙决周报自动生成器
====================
功能：自动汇总系统健康度、回测性能、因子IC、异常事件，生成周报Markdown
运行：python scripts/weekly_report_generator.py [--week YYYY-Www] [--output DIR]
定时：每周一09:00通过cron自动执行

依赖数据源：
  - data/audit/health_report_*.json (系统健康度)
  - data/audit/factor_ic_rolling_20d_*.json (因子IC)
  - data/audit/backtest-validation-summary_*.json (回测结果)
  - data/audit/s3_daily_report_*.json (S3日报)
  - data/audit/system_audit_*.json (系统审计)
  - data/alert_log.jsonl (告警日志)
  - backtest_result.json (回测原始数据)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

# ── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = PROJECT_ROOT / "templates" / "weekly_report.md"
OUTPUT_DIR = PROJECT_ROOT / "output" / "reports"
DATA_DIR = PROJECT_ROOT / "data" / "audit"
LOGS_DIR = PROJECT_ROOT / "logs"


# ── 工具函数 ────────────────────────────────────────────────────────────────

def get_latest_json(pattern: str, directory: Path = DATA_DIR) -> tuple[Optional[dict], Optional[Path]]:
    """查找目录中匹配pattern的最新JSON文件并返回内容"""
    files = sorted(directory.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None, None
    with open(files[0], encoding="utf-8") as f:
        return json.load(f), files[0]


def get_week_label(date: datetime) -> str:
    """计算ISO周标签，如 2026-W41"""
    iso = date.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def get_week_range(week_label: str) -> tuple[str, str]:
    """根据周标签计算周期起始/结束日期（周一~周日）"""
    # 支持 "2026-W41" 或 "2026-41" 格式
    m = re.match(r"(\d{4})-W?(\d{2})", week_label)
    if not m:
        raise ValueError(f"Invalid week label: {week_label}")
    year, week = int(m.group(1)), int(m.group(2))
    # ISO周第一天（周一）
    jan4 = datetime(year, 1, 4)
    start_of_week1 = jan4 - timedelta(days=jan4.isoweekday() - 1)
    mon = start_of_week1 + timedelta(weeks=week - 1)
    sun = mon + timedelta(days=6)
    return mon.strftime("%Y-%m-%d"), sun.strftime("%Y-%m-%d")


def parse_ts(ts_str: str) -> Optional[datetime]:
    """解析 ISO 类时间戳字符串，失败返回 None"""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            print(f"⚠️ [scripts\weekly_report_generator.py] 兼容处理: except ValueError:", file=sys.stderr)
    return None


def read_alert_log(limit: int = 100) -> list[dict]:
    """读取告警日志"""
    alerts = []
    log_path = DATA_DIR.parent / "alert_log.jsonl"
    if not log_path.exists():
        return alerts
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                alerts.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"🔴 [scripts\weekly_report_generator.py] CR-01: except json.JSONDecodeError:", file=sys.stderr)
    return alerts[-limit:]


def read_s3_reports() -> list[dict]:
    """读取所有S3日报"""
    reports = []
    for f in sorted(DATA_DIR.glob("s3_daily_report_*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                reports.append(json.load(fh))
        except Exception:
            print(f"🔴 [scripts\weekly_report_generator.py] CR-01: except Exception:", file=sys.stderr)
    return reports


# ── 数据采集函数 ────────────────────────────────────────────────────────────

def collect_fake_positive_data(week_label: str) -> dict:
    """采集假绿检查结果"""
    log_path = PROJECT_ROOT / "data" / "fake_positive_log.jsonl"

    # 三态处理
    if not log_path.exists():
        return {
            "status": "FILE_MISSING",
            "count": 0,
            "section": "假绿检查: 文件不存在",
            "detail": f"路径: {log_path}",
        }

    # 读取所有条目
    entries: list[dict] = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                print(
                    f"[weekly_report] ⚠️ 跳过坏行: {line[:80]}...",
                    file=sys.stderr,
                )
                continue

    if not entries:
        return {
            "status": "NO_ENTRIES",
            "count": 0,
            "section": "假绿检查: 无新项目",
            "detail": "文件存在但无记录",
        }

    # 按周过滤：取本周内的条目
    week_start, week_end = get_week_range(week_label)
    week_start_dt = datetime.strptime(week_start, "%Y-%m-%d")
    week_end_dt = datetime.strptime(week_end, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

    weekly_entries: list[dict] = []
    for entry in entries:
        ts_str = entry.get("ts", "")
        ts = parse_ts(ts_str)
        if ts and week_start_dt <= ts <= week_end_dt:
            weekly_entries.append(entry)

    count = len(weekly_entries)
    if count == 0:
        return {
            "status": "NO_NEW",
            "count": 0,
            "section": "假绿检查: 无新项目",
            "detail": f"文件有{len(entries)}条历史，本周无新增",
        }

    # 生成详细列表
    details: list[str] = []
    for e in weekly_entries:
        details.append(
            f"- {e.get('stock_code', '?')} {e.get('stock_name', '?')} "
            f"score={e.get('score_at_decision', '?')} "
            f"pnl={e.get('pnl_pct', '?')}% ratio={e.get('ratio', '?')}"
        )

    return {
        "status": "FOUND",
        "count": count,
        "section": f"假绿检查: {count} 条",
        "detail": "\n".join(details),
        "entries": weekly_entries,
    }


def collect_health_data() -> dict:
    """采集系统健康度数据"""
    result, path = get_latest_json("health_report_*.json") or ({}, Path(""))
    if not result:
        return {
            "score": 0, "status": "UNKNOWN",
            "gateway_status": "DATA_MISSING", "gateway_detail": "无健康报告",
            "cron_status": "DATA_MISSING", "cron_detail": "无健康报告",
            "gate_status": "DATA_MISSING", "gate_detail": "无健康报告",
            "data_status": "DATA_MISSING", "data_detail": "无健康报告",
            "ic_status": "DATA_MISSING", "ic_detail": "无健康报告",
            "source_file": str(path),
        }

    modules = result.get("modules", {})
    gate = modules.get("gate", {})
    data_mod = modules.get("data", {})
    ic_mod = modules.get("ic", {})
    cron_mod = modules.get("cron", {})
    gw = modules.get("gateway", {})

    return {
        "score": result.get("score", 0),
        "status": result.get("status", "unknown"),
        "issues": result.get("issues", []),
        "gateway_status": gw.get("status", "unknown").upper(),
        "gateway_detail": f"pid={gw.get('pid', '-')}, channel={gw.get('channel_dir', 'N/A')}",
        "cron_status": "OK" if cron_mod.get("failed", 0) == 0 else "WARN",
        "cron_detail": f"总任务={cron_mod.get('total', 0)}, 活跃={cron_mod.get('active', 0)}, 失败={cron_mod.get('failed', 0)}",
        "gate_status": "OPEN" if gate.get("gate_open") else "CLOSED",
        "gate_detail": f"模式={gate.get('mode', '-')}, 上证={gate.get('details', {}).get('sh_close', '-')}, MA250={gate.get('details', {}).get('ma250', '-')}",
        "data_status": "OK" if not data_mod.get("issues") else "WARN",
        "data_detail": f"股票文件={data_mod.get('stocks', {}).get('total_files', '-')}, 最新={data_mod.get('stocks', {}).get('latest_date', '-')}, 滞后={data_mod.get('stocks', {}).get('lag_days', '-')}天",
        "ic_status": "OK" if not ic_mod.get("alerts") else "WARN",
        "ic_detail": f"总因子={ic_mod.get('total_factors', '-')}, 有效={ic_mod.get('valid', '-')}, 失效={ic_mod.get('dead', '-')}",
        "source_file": str(path.name),
    }


def collect_ic_data() -> dict:
    """采集因子IC数据"""
    result, path = get_latest_json("factor_ic_rolling_20d_*.json") or ({}, Path(""))
    if not result:
        return {
            "valid_factors": 0, "total_factors": 0, "alert_count": 0,
            "worst_factor": "N/A", "worst_ic": "N/A",
            "table_rows": "| 无数据 |",
            "trend_analysis": "无IC数据",
            "source_file": str(path.name) if path else "无",
            "data_date": "N/A",
        }

    factors = result.get("factors", {})
    alerts = result.get("alerts", [])
    n_valid = result.get("n_valid_factors", 0)
    n_total = len(factors)

    # 找出IC绝对值最小的因子（最弱）- 考虑方向后取绝对值
    worst_name, worst_ic = "N/A", 999.0
    for name, info in factors.items():
        ic = info.get("rolling20_ic_mean", 0)
        if abs(ic) < worst_ic:
            worst_ic = ic
            worst_name = name

    worst_ic_str = f"{worst_ic:.4f}" if worst_name != "N/A" else "—"

    # 生成表格行
    rows = []
    for name, info in factors.items():
        ic = info.get("rolling20_ic_mean", 0)
        ic_std = info.get("ic_std", 0)
        ir = info.get("ir", 0)
        direction = "稳定" if not info.get("direction_flip") else "翻转"
        alert_flag = "🔴" if info.get("alert") else "✅"
        rows.append(f"| {name} | {ic:.4f} | {ic_std:.4f} | {ir:.3f} | {direction} | {alert_flag} |")

    table_rows = "\n".join(rows) if rows else "| 无因子数据 |"

    # IC趋势分析
    alert_factors = [f for f in factors if factors[f].get("alert")]
    if len(alert_factors) == 0:
        trend = "所有因子IC稳定，无告警。"
    elif len(alert_factors) <= 2:
        trend = f"⚠️ {len(alert_factors)}个因子告警：{', '.join(alert_factors)}，需人工复核。"
    else:
        trend = f"🔴 大量因子告警（{len(alert_factors)}个），建议暂停相关因子并重新校准。"

    return {
        "valid_factors": n_valid,
        "total_factors": n_total,
        "alert_count": len(alerts),
        "worst_factor": worst_name,
        "worst_ic": worst_ic_str,
        "table_rows": table_rows,
        "trend_analysis": trend,
        "source_file": str(path.name),
        "data_date": result.get("generated", "N/A")[:10],
        "alerts": alerts,
        "all_factors": factors,
    }


def collect_backtest_data() -> dict:
    """采集回测性能数据"""
    benchmark = {
        "annual_return": "22.13%",
        "win_rate": "48.57%",
        "max_drawdown": "—"
    }

    # 读取回测验证总结
    bt_summary, _ = get_latest_json("backtest-validation-summary_*.json") or (None, None)
    if bt_summary:
        s3 = bt_summary.get("summary", {}).get("s3_main_candidate", {})
        gates = s3.get("gate_check", {})
        passed = sum(1 for v in gates.values() if v is True)
        total = len(gates)
        failed_list = [k for k, v in gates.items() if v is not True]
        return {
            "win_rate": f"{s3.get('win_rate', 0) * 100:.1f}",
            "win_rate_comp": f"+{s3.get('win_rate', 0) * 100 - 48.57:.1f}pp vs 基准",
            "max_dd": f"{s3.get('max_drawdown', 0) * 100:.1f}",
            "dd_comp": "达标" if s3.get('max_drawdown', 1) < 0.5 else "超标",
            "sharpe": f"{s3.get('pf', 0):.2f}",
            "sharpe_comp": "达标" if s3.get('pf', 0) > 1.5 else "待提升",
            "trade_count": s3.get("trades", 0),
            "avg_hold": f"{s3.get('avg_hold_days', 0):.1f}",
            "gates_passed": passed,
            "gates_total": total,
            "gates_failed": len(failed_list),
            "verdict": "✅ 通过" if not failed_list else f"⚠️ {', '.join(failed_list)}",
            "benchmark": benchmark,
            "source": _.name if _ else "N/A",
        }

    # 读取原始回测结果
    bt_path = PROJECT_ROOT / "backtest_result.json"
    if bt_path.exists():
        try:
            with open(bt_path, encoding="utf-8") as f:
                d = json.load(f)
            return {
                "win_rate": f"{d.get('胜率', 0):.1f}",
                "win_rate_comp": f"{d.get('胜率', 0) - 48.57:+.1f}pp vs 基准",
                "max_dd": "—",
                "dd_comp": "—",
                "sharpe": "—",
                "sharpe_comp": "—",
                "trade_count": d.get("总交易次数", 0),
                "avg_hold": "—",
                "gates_passed": "—",
                "gates_total": "—",
                "gates_failed": "—",
                "verdict": "原始回测数据（无S3门禁汇总）",
                "benchmark": benchmark,
                "source": "backtest_result.json",
            }
        except Exception:
            print(f"🔴 [scripts\weekly_report_generator.py] CR-01: except Exception:", file=sys.stderr)
    return {
        "win_rate": "—", "win_rate_comp": "—", "max_dd": "—", "dd_comp": "—",
        "sharpe": "—", "sharpe_comp": "—", "trade_count": "—", "avg_hold": "—",
        "gates_passed": "—", "gates_total": "—", "gates_failed": "—",
        "verdict": "无回测数据", "benchmark": benchmark, "source": "无",
    }


def collect_alert_events() -> dict:
    """采集异常事件"""
    alerts = read_alert_log(limit=50)
    s3_reports = read_s3_reports()

    p0_events = []
    p1_events = []
    p2_events = []
    resolved = []

    # 解析告警日志
    for a in alerts:
        level = a.get("level", "INFO")
        msg = a.get("message", "")
        ts = a.get("timestamp", "")
        entry = f"**[{ts}]** {msg}"
        if level == "P0":
            p0_events.append(entry)
        elif level == "WARN" or level == "P1":
            p1_events.append(entry)
        else:
            p2_events.append(entry)

    # 从S3日报提取风险标记
    for r in s3_reports:
        for flag in r.get("risk_flags", []):
            severity = flag.get("severity", "low")
            entry = f"**{flag.get('flag', '')}** — {flag.get('detail', '')}"
            if severity == "high":
                p0_events.append(entry)
            elif severity == "medium":
                p1_events.append(entry)
            else:
                p2_events.append(entry)

    # 从system_audit提取
    audit, _ = get_latest_json("system_audit_*.json") or (None, None)
    if audit:
        for issue in audit.get("critical_issues", []):
            p0_events.append(f"**{issue.get('id')}**: {issue.get('issue')} (状态: {issue.get('status')})")
        for issue in audit.get("normal_issues", []):
            if issue.get("level") == "warning":
                p1_events.append(f"**{issue.get('id')}**: {issue.get('issue')}")

    return {
        "p0": p0_events[-5:] if p0_events else ["本周无P0级事件"],
        "p1": p1_events[-5:] if p1_events else ["本周无P1级事件"],
        "p2": p2_events[-5:] if p2_events else ["本周无P2级事件"],
        "resolved": resolved[-5:] if resolved else ["本周无已解决事项"],
    }


def collect_weekly_plan(week_label: str) -> list[dict]:
    """生成下周计划（基于当前阻塞任务）"""
    plan = [
        {"priority": "P0", "task": "国庆后门控自动检测 + S3门禁重跑验证", "owner": "@总管", "deadline": "2026-10-09", "status": "待触发"},
        {"priority": "P0", "task": "S3首笔交易标的确认 + 实盘执行（待R0授权）", "owner": "@老大", "deadline": "2026-10-09", "status": "阻塞"},
        {"priority": "P1", "task": "overnight_sum20 IC持续监控（已连续5日低于阈值）", "owner": "系统", "deadline": "持续", "status": "告警中"},
        {"priority": "P1", "task": "PurgedKFold + Walk-Forward集成到回测流水线", "owner": "@老三", "deadline": "2026-10-16", "status": "代码就绪"},
        {"priority": "P1", "task": "因子权重优化方案B回测验证（chg10/vol_shrink20/fund_flow增强）", "owner": "@老六", "deadline": "2026-10-16", "status": "待验证"},
        {"priority": "P2", "task": "Gateway Channel问题联系Hermes官方支持", "owner": "@总管", "deadline": "待决策", "status": "待D1拍板"},
        {"priority": "P2", "task": "RiskOptima安装（VaR/CVaR增强风控）", "owner": "@老三", "deadline": "2026-10-16", "status": "待D4决策"},
    ]
    return plan


# ── 模板渲染 ────────────────────────────────────────────────────────────────

def render_report(week_label: str, health: dict, ic: dict, bt: dict,
                  events: dict, plan: list[dict], fake_pos: Optional[dict] = None) -> str:
    """渲染周报Markdown"""
    period_start, period_end = get_week_range(week_label)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()

    # P0/P1/P2事件列表
    def fmt_events(items: list[str]) -> str:
        if not items or (len(items) == 1 and "无" in items[0]):
            return "暂无"
        return "\n".join(f"- {e}" for e in items)

    # 计划表格行
    plan_rows = []
    for p in plan:
        plan_rows.append(
            f"| {p['priority']} | {p['task']} | {p['owner']} | {p['deadline']} | {p['status']} |"
        )

    # IC健康状态
    ic_health = "✅ 正常" if ic["alert_count"] <= 2 else "⚠️ 告警"
    alert_status = "✅ 正常" if ic["alert_count"] == 0 else f"🔴 {ic['alert_count']}个因子告警"

    # 替换占位符
    replacements = {
        "{{WEEK_LABEL}}": week_label,
        "{{GENERATED_AT}}": now,
        "{{PERIOD_START}}": period_start,
        "{{PERIOD_END}}": period_end,
        # 健康度
        "{{GATEWAY_STATUS}}": health.get("gateway_status", "—"),
        "{{GATEWAY_DETAIL}}": health.get("gateway_detail", "—"),
        "{{CRON_STATUS}}": health.get("cron_status", "—"),
        "{{CRON_DETAIL}}": health.get("cron_detail", "—"),
        "{{GATE_STATUS}}": health.get("gate_status", "—"),
        "{{GATE_DETAIL}}": health.get("gate_detail", "—"),
        "{{DATA_STATUS}}": health.get("data_status", "—"),
        "{{DATA_DETAIL}}": health.get("data_detail", "—"),
        "{{IC_STATUS}}": health.get("ic_status", "—"),
        "{{IC_DETAIL}}": health.get("ic_detail", "—"),
        "{{HEALTH_SCORE}}": str(health.get("score", "—")),
        "{{OVERALL_STATUS}}": health.get("status", "—").upper(),
        # 回测
        "{{WIN_RATE}}": bt.get("win_rate", "—"),
        "{{WIN_RATE_COMP}}": bt.get("win_rate_comp", "—"),
        "{{MAX_DD}}": bt.get("max_dd", "—"),
        "{{DD_COMP}}": bt.get("dd_comp", "—"),
        "{{SHARPE}}": bt.get("sharpe", "—"),
        "{{SHARPE_COMP}}": bt.get("sharpe_comp", "—"),
        "{{TRADE_COUNT}}": str(bt.get("trade_count", "—")),
        "{{AVG_HOLD}}": bt.get("avg_hold", "—"),
        "{{GATES_PASSED}}": str(bt.get("gates_passed", "—")),
        "{{GATES_TOTAL}}": str(bt.get("gates_total", "—")),
        "{{GATES_FAILED}}": str(bt.get("gates_failed", "—")),
        "{{BACKTEST_VERDICT}}": bt.get("verdict", "—"),
        # IC
        "{{VALID_FACTORS}}": str(ic.get("valid_factors", "—")),
        "{{TOTAL_FACTORS}}": str(ic.get("total_factors", "—")),
        "{{ALERT_COUNT}}": str(ic.get("alert_count", "—")),
        "{{IC_HEALTH}}": ic_health,
        "{{ALERT_STATUS}}": alert_status,
        "{{Worst_IC_FACTOR}}": ic.get("worst_factor", "—"),
        "{{Worst_IC}}": ic.get("worst_ic", "—"),
        "{{WORST_IC_STATUS}}": "⚠️ 偏弱" if ic.get("worst_factor") != "N/A" else "—",
        "{{IC_TABLE_ROWS}}": ic.get("table_rows", ""),
        "{{IC_TREND_ANALYSIS}}": ic.get("trend_analysis", "—"),
        # 异常事件
        "{{P0_EVENTS}}": fmt_events(events.get("p0", [])),
        "{{P1_EVENTS}}": fmt_events(events.get("p1", [])),
        "{{P2_EVENTS}}": fmt_events(events.get("p2", [])),
        "{{RESOLVED_EVENTS}}": fmt_events(events.get("resolved", [])),
        # 下周计划
        "{{PLAN_ROWS}}": "\n".join(plan_rows),
        # 附录
        "{{DATA_FRESHNESS}}": health.get("source_file", "—"),
        "{{IC_DATA_DATE}}": ic.get("data_date", "—"),
        "{{BACKTEST_DATE}}": bt.get("source", "—"),
        "{{S3_DATE}}": "—",
        "{{ALERT_LOG_DATE}}": "—",
        # 假绿检查（消费侧闭环）
        "{{FAKE_POSITIVE_SECTION}}": fake_pos.get("section", "假绿检查: 无数据") if fake_pos else "假绿检查: 无数据",
        "{{FAKE_POSITIVE_DETAIL}}": fake_pos.get("detail", "") if fake_pos else "",
    }

    for placeholder, value in replacements.items():
        template = template.replace(placeholder, str(value))

    return template


# ── 主程序 ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="御龙决周报自动生成器")
    parser.add_argument("--week", help="周标签，格式 YYYY-Www（默认：本周）")
    parser.add_argument("--output", help="输出目录（默认：output/reports）")
    parser.add_argument("--dry-run", action="store_true", help="仅打印不写入文件")
    args = parser.parse_args()

    # 确定周标签
    if args.week:
        week_label = args.week
    else:
        # 上周（周一~周日）
        today = datetime.now()
        # 找上周一
        days_since_monday = today.weekday()
        last_monday = today - timedelta(days=days_since_monday + 7)
        week_label = get_week_label(last_monday)

    period_start, period_end = get_week_range(week_label)
    print(f"[周报生成器] 周期: {period_start} ~ {period_end} ({week_label})")

    # 采集数据
    print("  → 采集系统健康度...")
    health = collect_health_data()

    print("  → 采集因子IC数据...")
    ic = collect_ic_data()

    print("  → 采集回测性能数据...")
    bt = collect_backtest_data()

    print("  → 采集异常事件...")
    events = collect_alert_events()

    print("  → 采集假绿检查结果...")
    fake_pos = collect_fake_positive_data(week_label)
    print(f"    {fake_pos['section']}")

    print("  → 生成下周计划...")
    plan = collect_weekly_plan(week_label)

    # 渲染
    print("  → 渲染周报...")
    report = render_report(week_label, health, ic, bt, events, plan, fake_pos)

    # 输出
    if args.dry_run:
        print("\n" + "=" * 60)
        print("周报内容（预览）：")
        print("=" * 60)
        print(report)
        return

    out_dir = Path(args.output) if args.output else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"weekly_{week_label}.md"
    out_file.write_text(report, encoding="utf-8")
    print(f"  ✓ 周报已生成: {out_file}")
    print(f"  ✓ 文件大小: {out_file.stat().st_size} bytes")


if __name__ == "__main__":
    main()
