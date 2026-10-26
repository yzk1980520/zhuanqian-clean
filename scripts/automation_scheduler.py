#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
automation_scheduler.py - zhuanqian 每日自动化调度（重建版 2026-09-26）
================================================================
历史: 原版在 6d96e081 大清理中随其依赖(selector.py / factor_ic_monitor.py /
      mainline/market_adaptation.py)一起被误删, 导致计划任务
      Zhuanqian_DailyAuto → scripts\\daily_auto.bat 断链。
本版: 薄封装设计——负责驱动 walk-forward 衰减门禁与生产入口 orchestrator.py
      (内含门禁 fail-safe→dry_run 防护), 不含任何选股/交易业务逻辑。

用法:
  python automation_scheduler.py                # 每日巡检(默认, 与计划任务对齐)
  python automation_scheduler.py --mode health  # 仅系统健康检查(快速)
  python automation_scheduler.py --mode pick    # 仅选股
  python automation_scheduler.py --json         # 追加输出JSON摘要

输出:
  data/automation_daily.json  本次运行状态(atomic_dump 原子写)
日志:
  mainline/logs/daily_auto_cron.log  (由 daily_auto.bat 重定向)
"""
import sys
import time
import argparse
import subprocess
from datetime import datetime, date

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\automation_scheduler.py] CR-01: except Exception:", file=sys.stderr)
import os
import json
import re
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from core.pipeline.atomic_json import atomic_dump

DATA_DIR = os.path.join(PROJECT, "data")
STATUS_FILE = os.path.join(DATA_DIR, "automation_daily.json")
ORCHESTRATOR = os.path.join(PROJECT, "orchestrator.py")
WALK_FORWARD_GATE = os.path.join(PROJECT, "scripts", "walk_forward_gate.py")
WALK_FORWARD_GATE_TIMEOUT = 120

# 各模式超时(秒): 全量选股耗时较长, 给足余量
MODE_TIMEOUT = {"daily": 3600, "pick": 3600, "health": 600}


def run_orchestrator(mode: str) -> dict:
    """以子进程驱动生产入口 orchestrator.py, 返回运行状态摘要。"""
    print(f"\n[{mode}] 驱动生产入口 orchestrator.py ...")
    t0 = time.time()
    result = {
        "mode": mode,
        "orchestrator": os.path.basename(ORCHESTRATOR),
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        proc = subprocess.run(
            [sys.executable, ORCHESTRATOR, mode],
            cwd=PROJECT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=MODE_TIMEOUT.get(mode, 3600),
            creationflags=CREATE_NO_WINDOW,
        )
        dur = time.time() - t0
        result["exit_code"] = proc.returncode
        result["duration_sec"] = round(dur, 1)
        result["status"] = "ok" if proc.returncode == 0 else "error"
        # 保留输出尾部用于排障(全量输出见 cron 日志)
        tail = (proc.stdout or "")[-1500:]
        result["stdout_tail"] = tail
        if proc.returncode != 0:
            result["stderr_tail"] = (proc.stderr or "")[-1000:]
        print(f"  {'✅' if proc.returncode == 0 else '❌'} "
              f"orchestrator[{mode}] 退出码={proc.returncode}, 耗时{dur:.0f}秒")
    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["error"] = f"timeout({MODE_TIMEOUT.get(mode, 3600)}s)"
        print(f"  ❌ orchestrator[{mode}] 超时")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"  ❌ 驱动失败: {e}")
    return result


def run_walk_forward_gate() -> dict:
    """运行 walk-forward 衰减门禁；其非零退出码进入每日链总退出码。"""
    print("\n[daily] 运行 walk-forward 衰减门禁 ...")
    t0 = time.time()
    result = {
        "task": "walk_forward_decay_gate",
        "script": os.path.relpath(WALK_FORWARD_GATE, PROJECT),
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        proc = subprocess.run(
            [sys.executable, WALK_FORWARD_GATE],
            cwd=PROJECT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=WALK_FORWARD_GATE_TIMEOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        result["exit_code"] = proc.returncode
        result["duration_sec"] = round(time.time() - t0, 1)
        result["status"] = "ok" if proc.returncode == 0 else "error"
        result["stdout"] = proc.stdout or ""
        result["stderr"] = proc.stderr or ""
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        print(f"  {'✅' if proc.returncode == 0 else '❌'} "
              f"walk-forward 衰减门禁退出码={proc.returncode}")
    except subprocess.TimeoutExpired as e:
        result["status"] = "error"
        result["error"] = f"timeout({WALK_FORWARD_GATE_TIMEOUT}s)"
        result["stdout"] = e.stdout or ""
        result["stderr"] = e.stderr or ""
        print(f"  ❌ walk-forward 衰减门禁超时({WALK_FORWARD_GATE_TIMEOUT}s)")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"  ❌ walk-forward 衰减门禁运行失败: {e}")
    return result


def load_gate_flag() -> dict:
    """读取选股冻结旗标。

    单一读取源 = data/review_status.json（老五点名，不复建第二状态文件，
    避免多源仲裁又添一坑）。

    判定（统一走 review_gate, R0b/K47 §二）:
      - 文件存在且 review_gate 判放行 → 正常跑选股
      - review_status 缺失 / 解析失败 / 非 dict / laowu_approved 非 True / findings 硬失败 → 冻结
    **fail-safe 冻结**（取代旧 fail-open）：旗标异常时防护方向=冻结, 打 WARN 不静默吞
    (老五 2026-09-27 点名 + K47 §二 修 fail-open)。
    """
    import review_gate  # R0b 统一读法: 唯一仲裁, 消除 fail-open
    flag_path = os.path.join(DATA_DIR, "review_status.json")
    return review_gate.flag_state(flag_path)


def _freeze_age_days():
    """从 review_status.json 的 _freeze_YYYYMMDD 键名解析冻结起始日。

    返回 (start_date, 距今天数); 键名不存在/解析失败 → (None, None) ——
    文案显示 "?" 并明说无法确定起始日, 不默认 0/1 (宁可存疑不可造假)。
    """
    try:
        with open(os.path.join(DATA_DIR, "review_status.json"), "r", encoding="utf-8-sig") as f:
            status = json.load(f)
    except Exception:
        return None, None
    if not isinstance(status, dict):
        return None, None
    starts = []
    for key in status:
        m = re.fullmatch(r"_freeze_(\d{8})", key)
        if not m:
            continue
        try:
            starts.append(datetime.strptime(m.group(1), "%Y%m%d").date())
        except ValueError as e:
            print(f"🔴 [automation_scheduler.py:178] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 ValueError → 兜底, 异常={e}", file=sys.stderr)
            continue
    if not starts:
        return None, None
    start = max(starts)  # 多次冻结记录取最近一次
    return start, (date.today() - start).days


def _emit_frozen_alert(gate_flag: dict, walk_forward_gate: dict) -> None:
    """选股停摆旁路告警 (2026-10-20 闭环修复, qa-verifier-3 三重断裂结论)。

    病因: automation_daily.json 写了无人读, frozen/walk-forward 门禁红多日
    顶层全绿无人处置 (09-29 双远程停摆 16 天同构)。本函数只补"让人看见"的
    旁路: 触发条件命中 → 经 queue_integration.add_alert 入 message_queue.json
    (唯一触达出口, QSP_MsgDrain 5 分钟内飞书到群); 不改退出码/不改任何既有行为。

    触发 (任一): gate_flag.frozen=True 或 walk_forward_gate.status=="error"。
    去重: 队列中已有未发送的同类条目 → 跳过 (等投递后次日子链才会再报, 不刷屏)。
    """
    frozen = gate_flag.get("frozen") is True
    wf_error = walk_forward_gate.get("status") == "error"
    if not (frozen or wf_error):
        return

    reasons = []
    if frozen:
        reasons.append(str(gate_flag.get("reason") or "frozen"))
    if wf_error:
        reasons.append("walk-forward 门禁阻断(exit_code=%s)" % walk_forward_gate.get("exit_code"))
    reason = "；".join(reasons)

    start, n_days = _freeze_age_days()
    if start:
        n_text, origin_text = str(n_days), "frozen 起始 %s" % start.strftime("%Y-%m-%d")
    else:
        n_text, origin_text = "?", "无法确定起始日"

    content = ("🔴 [选股停摆] 已连续 %s 天未出票（%s）。原因: %s。"
               "请人工处置 data/review_status.json" % (n_text, origin_text, reason))

    alert_type = "stock_pick_frozen"
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        for p in (PROJECT, scripts_dir):
            if p not in sys.path:
                sys.path.insert(0, p)
        from queue_integration import add_alert, load_queue

        # 去重/冷却: 已有未发送的同类告警在排队 → 不重复入队(一天多次跑也不刷屏)
        pending = [m for m in load_queue()
                   if m.get("type") == alert_type and not m.get("sent")]
        if pending:
            print("  ⏭ [选股停摆告警] 队列已有 %d 条未发送的同类告警, "
                  "跳过本次入队(待 QSP_MsgDrain 投递后次日再报)" % len(pending))
            return

        add_alert(alert_type=alert_type, priority="P0", content=content,
                  data={"frozen": frozen,
                        "walk_forward_exit_code": walk_forward_gate.get("exit_code"),
                        "freeze_start": start.isoformat() if start else None,
                        "frozen_days": n_days if start else None,
                        "reason": reason})
        print("  📨 [选股停摆告警] 已入 message_queue.json (P0, QSP_MsgDrain 5 分钟内飞书到群)")
    except Exception as e:
        print("[LOUD][WARN] 选股停摆告警入 message_queue 失败(未触达): %s" % e, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="zhuanqian 每日自动化调度")
    parser.add_argument("--mode", choices=["daily", "pick", "health"],
                        default="daily", help="运行模式: daily=每日巡检, pick=仅选股, health=仅健康检查")
    parser.add_argument("--json", action="store_true", help="追加输出JSON摘要")
    args = parser.parse_args()

    print(f"  zhuanqian 每日调度  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")

    # A2 冻结期旗标门控（老五 2026-09-27 点名）：
    #   daily/pick 在冻结期(laowu_approved=False)时，选股步降级为 health 巡检空转，
    #   数据刷新+门禁+推送仍照跑；解冻后(laowu_approved=True)自动恢复选股。
    #   只跳选股、不碰止损监控链路。fail-open：旗标读失败即正常跑。
    eff_mode = args.mode
    gate = {"read": args.mode}
    if args.mode in ("daily", "pick"):
        gate = load_gate_flag()
        gate["requested_mode"] = args.mode
        if gate.get("frozen"):
            eff_mode = "health"
            gate["effective_mode"] = "health"
            print(f"  🧊 [A2旗标] 冻结中: {gate.get('reason')}")
            print(f"     冻结期选股步空转 → 降级为 health 巡检(数据刷新/门禁/推送照跑, 不烧15min选股)")
        else:
            gate["effective_mode"] = eff_mode
            print(f"  ✅ [A2旗标] {gate.get('reason')} → 正常 {args.mode} 选股")

    # walk-forward 门禁只接入“每日链”（requested mode=daily）。即使 A2 冻结把
    # orchestrator 降为 health，本门禁仍须运行，避免冻结期形成监控盲区。
    if args.mode == "daily":
        walk_forward_gate = run_walk_forward_gate()
    else:
        walk_forward_gate = {
            "task": "walk_forward_decay_gate",
            "status": "skipped",
            "reason": f"requested_mode={args.mode}, 仅每日链执行",
        }

    # 门禁为红也继续完成原有巡检；不改 daily_pick 下单逻辑。最终由调度器总退出码报红。
    result = run_orchestrator(eff_mode)
    overall_ok = (result.get("status") == "ok"
                  and walk_forward_gate.get("status") in ("ok", "skipped"))

    status = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scheduler_version": "2026-10-17-walk-forward-gate",
        "gate_flag": gate,
        "walk_forward_gate": walk_forward_gate,
        "result": result,
        "status": "ok" if overall_ok else "error",
    }
    atomic_dump(status, STATUS_FILE)
    print(f"\n💾 状态已保存: {STATUS_FILE}")
    print(f"📊 本次调度: {status['status'].upper()}")

    # 2026-10-20 闭环告警: frozen/门禁红必须让人看见(旁路, 不影响退出码与既有行为)
    _emit_frozen_alert(gate, walk_forward_gate)

    if args.json:
        import json

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
