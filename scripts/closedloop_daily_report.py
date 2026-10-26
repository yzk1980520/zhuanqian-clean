#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/closedloop_daily_report.py - 闭环健康度日报登记

目的: 每日 after_close 后生成日报，登记A1-A4断言完整率
输出: data/daily_reports/closedloop_daily_YYYY-MM-DD.json

告警: 任一断言false → 写 message_queue.json → QSP_MsgDrain投递

使用方法:
$ python scripts/closedloop_daily_report.py --generate
$ python scripts/closedloop_daily_report.py --verify  # 读侧断言
"""
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_DIR = PROJECT_ROOT / "data" / "daily_reports"


def generate_daily_report() -> Dict:
    """生成闭环健康度日报"""
    
    # 调用 closedloop_health.py 的断言检查
    import scripts.closedloop_health as clh
    
    # P2#5(a) 2026-10-25 @opencode 消费键对齐 (单权威源 = health 侧):
    # clh.check_aX() 权威契约返回 {"status": "PASS"/"PARTIAL"/"FAIL", "detail": "..."}
    # (无 pass/description/id 键)。旧消费面读 a.get("pass")/a.get("description")/a.get("id")
    # 恒 None/""/"unknown" → 5 断言恒判 fail → alert_triggered 恒 true → 每次日报必发 5 条空告警,
    # 经 write_alerts_to_queue 入队列后被 drain 判 unrenderable 死信 (10/24 A2×27 风暴根因之一)。
    # 现: 显式绑定断言 id + 按 status/detail 权威契约消费。
    _spec = [
        ("A1", clh.check_a1_contract),
        ("A2", clh.check_a2_single_source),
        ("A3", clh.check_a3_feedback_write),
        ("A4", clh.check_a4_feedback_read),
        ("A5", clh.check_a5_false_green),
    ]
    assertions = []
    for _aid, _fn in _spec:
        _r = _fn()
        if not isinstance(_r, dict):
            _r = {"status": "FAIL", "detail": str(_r)}
        assertions.append({
            "id": _aid,
            "status": _r.get("status", "FAIL"),
            "detail": _r.get("detail", ""),
        })

    # 计算完整率 (PASS=通过; 任一非 PASS 触发告警)
    total = len(assertions)
    passed = sum(1 for a in assertions if a.get("status") == "PASS")
    health_ratio = passed / total if total > 0 else 0.0
    
    report = {
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(),
        "assertions": assertions,
        "health_metrics": {
            "total_assertions": total,
            "passed": passed,
            "failed": total - passed,
            "health_ratio": health_ratio
        },
        "alert_triggered": passed < total,  # 任一非 PASS 即告警
        "alerts": []
    }
    
    # 收集告警 (读 status/detail 键, 挂显式 id; description 取 detail)
    if report["alert_triggered"]:
        for a in assertions:
            if a.get("status") != "PASS":
                report["alerts"].append({
                    "id": a.get("id", "unknown"),
                    "description": a.get("detail", ""),
                    "status": a.get("status", "FAIL"),
                    "severity": "P2"
                })
        
        # 写入消息队列
        write_alerts_to_queue(report)
    
    # 落盘
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = REPORTS_DIR / f"closedloop_daily_{report['report_date']}.json"
    
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    logger.info(f"日报生成完成: {report_file}")
    logger.info(f"完整率: {report['health_metrics']['health_ratio']:.1%} ({passed}/{total})")
    
    return report


def write_alerts_to_queue(report: Dict):
    """告警写入消息队列
    10/25 P2#5(c) 老六: ① 按 QSP_MsgDrain 渲染契约出 content 字段
    (写侧契约 content/msg/title+body, 裸 message 项会被死信 unrenderable 静默丢失——
     10/24 A2×27 死信风暴根因之一; content 缺失描述时兜底指向日报文件, 指向而非造数);
    ② 同日去重抑制窗: 同 alert_id+同 date 队列内只留最新 1 条 (日报重跑不重复堆积);
    ③ 队列写回改 atomic_json 原子写 (防并发覆盖)。
    注: L63-70 断言消费键对齐 (pass→status) 归 @opencode P2#5(a), 本函数不依赖其落地——
    description 缺失时按兜底文案渲染, 两版键名都出可读 content。"""
    if not report["alert_triggered"]:
        return

    from core.pipeline import atomic_json as _aj

    queue_file = PROJECT_ROOT / "data" / "message_queue.json"

    # 读现有队列 (原子读; 损坏/缺失按空队列)
    queue = _aj.atomic_load(str(queue_file), default=[])
    if not isinstance(queue, list):
        queue = []

    # 同日去重: 同 alert_id + 同 date 的存量项由本次新件替换, 不重复堆积
    new_ids = {a["id"] for a in report["alerts"]}
    queue = [
        q for q in queue
        if not (isinstance(q, dict)
                and q.get("type") == "closedloop_alert"
                and q.get("alert_id") in new_ids
                and q.get("date") == report["report_date"])
    ]

    report_rel = "data/daily_reports/closedloop_daily_%s.json" % report["report_date"]
    for alert in report["alerts"]:
        sev = alert.get("severity", "P2")
        desc = (alert.get("description")
                or "(描述缺键, 详见 %s)" % report_rel)
        queue.append({
            "type": "closedloop_alert",
            "alert_id": alert["id"],
            "message": alert.get("description", ""),
            "content": "🟡 [%s] 闭环健康度日报 %s · 断言 %s: %s"
                       % (sev, report["report_date"], alert["id"], desc),
            "severity": sev,
            "date": report["report_date"],
            "timestamp": datetime.now().isoformat()
        })

    # 原子写回
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    _aj.atomic_dump(queue, str(queue_file))

    logger.info(f"写入告警: {len(report['alerts'])} 条 → {queue_file}")


def verify_read_side() -> Dict:
    """
    读侧断言: 验证日报是否被定期消费
    消费方: 总管每日看板检查 + 老六复审批判
    周期: 每日after_close
    告警: 连续3天无新日报 → P1告警
    """
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = REPORTS_DIR / f"closedloop_daily_{today}.json"
    
    if not report_file.exists():
        return {
            "status": "alert",
            "message": f"无今日日报({today})，检查生成任务",
            "severity": "P2"
        }
    
    # 读日报
    with open(report_file) as f:
        report = json.load(f)
    
    # 验证结构
    required_fields = ["report_date", "assertions", "health_metrics"]
    missing = [f for f in required_fields if f not in report]
    
    if missing:
        return {
            "status": "alert",
            "message": f"日报字段缺失: {missing}",
            "severity": "P2"
        }
    
    return {
        "status": "ok",
        "report": report,
        "health_ratio": report["health_metrics"]["health_ratio"]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate', action='store_true', help='生成日报')
    parser.add_argument('--verify', action='store_true', help='读侧断言验证')
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    if args.generate:
        report = generate_daily_report()
        print(json.dumps(report["health_metrics"], ensure_ascii=False, indent=2))
        
        if report["alert_triggered"]:
            print(f"⚠️ 告警触发: {len(report['alerts'])} 项")
            for alert in report["alerts"]:
                print(f"  • {alert['id']}: {alert['description']}")
    
    elif args.verify:
        result = verify_read_side()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        if result["status"] == "alert":
            logger.warning(f"读侧告警: {result['message']}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
