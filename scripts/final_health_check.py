#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py health
# -*- coding: utf-8 -*-
"""
系统最终健康检查 - P0任务完成后
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\\final_health_check.py] CR-01: except Exception:", file=sys.stderr)
PROJECT = Path(__file__).parent.parent.resolve()

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def run_cmd(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd=str(PROJECT))
        return result.stdout, result.stderr, result.returncode
    except Exception as e:
        return "", str(e), 1

def main():
    log("=" * 60)
    log("系统最终健康检查（P0任务完成后）")
    log("=" * 60)
    
    results = {}
    
    # 1. 代码库
    stdout, stderr, rc = run_cmd("git log --oneline -3")
    if rc == 0:
        results["代码库"] = ("PASS", f"最近提交: {stdout.split(chr(10))[0][:60]}")
    else:
        results["代码库"] = ("FAIL", stderr)
    
    # 2. 数据完整性
    data_files = ["holdings.json", "trade_log.jsonl", "s3_execution_record.json", "s3_monitor_status.json"]
    data_ok = all((PROJECT / "data" / f).exists() for f in data_files)
    results["数据完整性"] = ("PASS" if data_ok else "FAIL", f"{sum(1 for f in data_files if (PROJECT/'data'/f).exists())}/{len(data_files)}")
    
    # 3. 脚本部署
    scripts = ["pipeline_scheduler.py", "pipeline_main_controller.py", "s3_live_monitor.py", "s3_failure_trigger.py", "execute_s3_buy.py"]
    scripts_ok = all((PROJECT / "scripts" / s).exists() for s in scripts)
    results["脚本部署"] = ("PASS" if scripts_ok else "FAIL", f"{sum(1 for s in scripts if (PROJECT/'scripts'/s).exists())}/{len(scripts)}")
    
    # 4. S3配置
    try:
        sys.path.insert(0, str(PROJECT))
        from risk_rules import TREND_TP_LADDER, STRATEGY_STOP_LOSS_PCT
        if TREND_TP_LADDER['up'] == [(6, 0.15), (10, 0.05), (15, 0.07), (25, 0.09), (999, 0.12)] and STRATEGY_STOP_LOSS_PCT['全仓'] == 0.10:
            results["S3配置"] = ("PASS", "五档阶梯+止损10%正确")
        else:
            results["S3配置"] = ("FAIL", "配置不匹配")
    except Exception as e:
        results["S3配置"] = ("FAIL", str(e))
    
    # 5. 技能安装
    stdout, stderr, rc = run_cmd("hermes skills list")
    if rc == 0:
        p0_skills = ["backtest-data-integrity", "live-trade-reconciliation", "quant-pipeline-execution", "kimi-webbridge-stock-screening"]
        installed = sum(1 for s in p0_skills if s in stdout)
        results["技能安装"] = ("PASS" if installed == 4 else "WARN", f"{installed}/4 P0技能已安装")
    else:
        results["技能安装"] = ("FAIL", "hermes命令失败")
    
    # 6. 账户状态
    holdings_file = PROJECT / "data" / "holdings.json"
    if holdings_file.exists():
        try:
            with open(holdings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            total = data.get("total_assets", 0)
            results["账户状态"] = ("PASS", f"总资产{total:,.2f}元")
        except (FileNotFoundError, IOError, KeyError, PermissionError, json.JSONDecodeError) as e:
            results["账户状态"] = ("FAIL", "JSON解析失败")
    else:
        results["账户状态"] = ("FAIL", "文件不存在")
    
    # 7. 待执行任务
    task_file = PROJECT / "mainline" / "docs" / "s3-task-order-20260930.md"
    if task_file.exists():
        content = task_file.read_text(encoding="utf-8")
        pending = content.count("- [ ]")
        results["待执行任务"] = ("PASS", f"{pending}项待执行")
    else:
        results["待执行任务"] = ("WARN", "任务单文件不存在")
    
    # 汇总
    log("\n审查结果:")
    passed = 0
    for name, (status, detail) in results.items():
        icon = "✅" if status == "PASS" else ("⚠️" if status == "WARN" else "❌")
        log(f"  {icon} {name}: {detail}")
        if status == "PASS":
            passed += 1
    
    total = len(results)
    score = passed * 100 // total
    
    log(f"\n综合评分: {score}/{100} ({passed}/{total})")
    
    if score >= 90:
        log("\n🎉 系统健康，可执行S3首笔买入")
    elif score >= 70:
        log("\n⚠️ 系统基本健康，建议修复失败项后执行")
    else:
        log("\n🔴 系统存在严重问题，需修复后再执行")
    
    # 保存报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "results": {k: {"status": v[0], "detail": v[1]} for k, v in results.items()},
        "score": score
    }
    
    report_file = PROJECT / "data" / "final_health_check.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    log(f"\n✅ 报告已保存: {report_file}")

if __name__ == "__main__":
    main()
    # P0: score<70 应非零退出；读取 main() 写入的报告判断
    # 修正(2026-10-21): 路径统一用 PROJECT(根目录)，与 main() 写 report 的路径一致
    _report = PROJECT / "data" / "final_health_check.json"
    if _report.exists():
        try:
            _score = json.loads(_report.read_text(encoding="utf-8")).get("score", 100)
            if _score < 70:
                sys.exit(1)
        except Exception as e:
            print(f"🔴 [final_health_check.py:140] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
            pass
    sys.exit(0)
