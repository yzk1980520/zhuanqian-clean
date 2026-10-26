#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cron_dispatcher.py - 可观测性告警Cron调度器

用法:
  python scripts/cron_dispatcher.py                    # 运行一次检查
  python scripts/cron_dispatcher.py --hourly           # 每小时检查
  python scripts/cron_dispatcher.py --daily            # 每日汇总
  python scripts/cron_dispatcher.py --event weekly_ic  # 周度 IC + 假绿检测
"""
import sys
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(r'D:/open code/zhuanqian')


def main():
    args = sys.argv[1:]

    # --event 路由
    if '--event' in args:
        idx = args.index('--event')
        if idx + 1 < len(args):
            event = args[idx + 1]
            return dispatch_event(event)
        else:
            print("ERROR: --event 需要参数")
            return 2

    mode = 'check'
    if '--hourly' in args:
        mode = 'hourly'
    elif '--daily' in args:
        mode = 'daily'

    print(f"🕐 [{datetime.now().strftime('%H:%M')}] 启动检查模式: {mode}")

    # 导入并运行告警引擎
    from alert_engine import run_checks, send_alert, log_alert

    alerts = run_checks()

    if not alerts:
        return 0

    print(f"⚠️ 发现 {len(alerts)} 条告警:")
    for a in alerts:
        if isinstance(a, dict):
            send_alert(a.get('level', 'P1'), a.get('message', ''), a.get('source', 'cron'))
        else:
            send_alert('P1', a, 'cron')

    return 0


def dispatch_event(event_name):
    """按事件名分发到对应处理器"""
    handlers = {
        'weekly_ic': _handle_weekly_ic,
    }
    handler = handlers.get(event_name)
    if handler is None:
        print(f"[cron_dispatcher] 未知事件: {event_name}")
        return 2
    return handler()


def _handle_weekly_ic():
    """
    weekly_ic 事件处理：
    1. 假绿周期检测（fake_positive_detector）
    2. 因子 IC 监控（占位，后续接入）
    3. 输出摘要供周报消费

    回授断言（老六 §三）：
    - 写入侧：fake_positive_detector → data/fake_positive_log.jsonl
    - 消费侧：weekly_report_generator 须在周报中引用 fake_positive_log.jsonl 条目数
    - 消费不到处理：周报标注"假绿检查: 无新条目"或"文件不存在"
    """
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[weekly_ic] {ts} 启动周度 IC + 假绿检测")

    # Step 1: 假绿检测
    from fake_positive_detector import run as run_fake_detector
    try:
        count, findings, integrity = run_fake_detector()
        print(f"[weekly_ic] 假绿检查: 发现 {count} 条")
        if not integrity:
            print(f"[weekly_ic] ⚠️ 假绿检查数据不完整 (data_integrity=false)")
        fake_summary = f"假绿样本={count}"
    except Exception as e:
        count = 0
        findings = []
        fake_summary = f"假绿检查异常: {e}"
        print(f"[weekly_ic] {fake_summary}")

    # Step 2: 因子 IC（占位）
    ic_summary = "因子IC: 待接入"

    # Step 3: 输出汇总（供周报消费）
    print(f"[weekly_ic] 汇总: {fake_summary}; {ic_summary}")
    print(f"[weekly_ic] fake_positive_log.jsonl 读取路径: data/fake_positive_log.jsonl")
    print(f"[weekly_ic] ⚠️ 回授断言: weekly_report_generator 须在周报中引用 fake_positive_log.jsonl 条目数")
    print(f"[weekly_ic] ⚠️ 消费不到处理: 周报标注'假绿检查: 无新条目'或'文件不存在'")

    return 0


if __name__ == '__main__':
    sys.exit(main())
