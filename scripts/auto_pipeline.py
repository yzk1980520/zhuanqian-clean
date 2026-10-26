#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_pipeline.py — 御龙决A股量化系统自动化流水线
版本: v0.1
作者: 老三
日期: 2026-10-03

功能:
  1. 启动132日线全量回测（后台）
  2. 监控回测进度
  3. 验证anchor写入
  4. 更新TASK-BOARD状态
  5. 生成执行报告

使用:
  python auto_pipeline.py [--monitor] [--report]
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ROOT = r"D:/open code/zhuanqian"
LOG_DIR = os.path.join(ROOT, ".scratch")
BOARD = os.path.join(ROOT, ".agent", "TASK-BOARD.json")
FLAGS = os.path.join(ROOT, ".agent", "TASK-BOARD.flags.json")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def run_backtest(wait=False):
    """启动132日线全量回测。

    wait=False(默认): Popen 拉起后父进程立即返回 —— 历史行为，现有调用方依赖，不可改。
    wait=True (--wait): 阻塞等待子进程真正结束，并把子进程的返回码作为 auto_pipeline 的退出码。
        用途: 计划任务内串联验收（回测不结束就不跑 check_backtest_sanity.py，
        否则验收读到的是上一轮的旧结果文件，门禁变假绿）。

    返回: (pid_or_returncode, log_file) —— wait=True 时第一个元素是子进程返回码。
    """
    log("启动132日线全量回测...")
    log_file = os.path.join(LOG_DIR, f"backtest_132d_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    cmd = [
        os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
        os.path.join(ROOT, "backtest", "backtest_rotation.py")
    ]
    
    with open(log_file, "w", encoding="utf-8") as f:
        proc = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            creationflags=CREATE_NO_WINDOW
        )
    
    log(f"回测进程已启动 PID={proc.pid}")
    log(f"日志文件: {log_file}")
    
    if wait:
        rc = proc.wait()
        log(f"回测进程已结束 returncode={rc}（--wait 同步模式）")
        return rc, log_file
    
    return proc.pid, log_file


def check_backtest_progress(log_file):
    """检查回测进度"""
    if not os.path.exists(log_file):
        return "未开始"
    
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
        
        # 解析关键指标
        lines = content.strip().split("\n")
        if lines:
            return f"运行中 ({len(lines)}行)"
        return "等待输出"
    except Exception as e:
        return f"读取失败: {e}"


def verify_anchor(result_file):
    """验证anchor写入"""
    if not os.path.exists(result_file):
        return False, "结果文件不存在"
    
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        anchor = data.get("engine_equivalence_anchor")
        commit = data.get("engine_commit")
        
        if not anchor:
            return False, "anchor字段缺失"
        
        return True, f"anchor={anchor[:50]}..., commit={commit[:8]}"
    except Exception as e:
        return False, f"验证失败: {e}"


def update_task_board(task_id, state, note=""):
    """更新TASK-BOARD状态"""
    try:
        with open(BOARD, "r", encoding="utf-8") as f:
            board = json.load(f)
        
        for t in board["tasks"]:
            if t["id"] == task_id:
                t["state"] = state
                if note:
                    t["note"] = note
                break
        
        with open(BOARD, "w", encoding="utf-8") as f:
            json.dump(board, f, ensure_ascii=False, indent=2)
        
        log(f"✅ TASK-BOARD #{task_id} 已更新为 {state}")
        return True
    except Exception as e:
        log(f"❌ 更新失败: {e}")
        return False


def refresh_flags():
    """刷新flags"""
    refresh_script = os.path.join(ROOT, "scripts", "refresh_task_board.py")
    if os.path.exists(refresh_script):
        subprocess.run(
            [os.path.join(ROOT, ".venv", "Scripts", "python.exe"), refresh_script],
            cwd=ROOT,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW
        )
        log("✅ flags已刷新")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="御龙决自动化流水线")
    parser.add_argument("--monitor", action="store_true", help="监控回测进度")
    parser.add_argument("--report", action="store_true", help="生成执行报告")
    parser.add_argument("--wait", action="store_true",
                        help="阻塞等待回测子进程结束，并把子进程返回码作为本进程退出码"
                             "（默认 False: Popen 后父进程立即返回，保持历史行为）")
    args = parser.parse_args()
    
    log("=" * 60)
    log("御龙决A股量化系统 · 自动化流水线 v0.1")
    log("=" * 60)
    
    if args.monitor:
        # 监控模式
        log_file = os.path.join(LOG_DIR, "backtest_132d_*.log")
        import glob
        logs = glob.glob(log_file)
        if logs:
            latest = max(logs, key=os.path.getmtime)
            log(f"监控: {latest}")
            while True:
                status = check_backtest_progress(latest)
                log(f"状态: {status}")
                if "完成" in status or "失败" in status:
                    break
                time.sleep(60)
        else:
            log("无回测日志文件")
    
    elif args.report:
        # 报告模式
        result_file = os.path.join(ROOT, "data", "rotation_backtest_result.json")
        ok, msg = verify_anchor(result_file)
        log(f"Anchor验证: {'✅' if ok else '❌'} {msg}")
        
        refresh_flags()
        
        # 生成汇总报告
        report = {
            "generated": datetime.now().isoformat(),
            "anchor_verified": ok,
            "anchor_detail": msg,
            "task_board_updated": True
        }
        report_file = os.path.join(LOG_DIR, f"pipeline_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log(f"报告已保存: {report_file}")
    
    else:
        # 默认: 启动回测
        rc_or_pid, log_file = run_backtest(wait=args.wait)
        if args.wait:
            log(f"回测同步结束, 子进程退出码={rc_or_pid}")
            log(f"日志: {log_file}")
            return rc_or_pid
        log("使用 --monitor 监控进度")
        log("使用 --report 生成报告")
    
    log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
