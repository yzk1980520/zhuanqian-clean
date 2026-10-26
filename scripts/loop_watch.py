#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_watch.py — 看门狗的看门狗 (2026-10-15 老六, 自愈闭环最后一环)

为什么需要它: HealthCheck L1/L3/L4 整套死了 16+ 天无人知 — 因为没有任何机制
验证"探测机制本身在运行"。本脚本每 6h 跑(03/09/15/21:05; 2026-10-16 T7-B2
修复: 原日频 09:05 与 15min 探测层节奏失配, 探测层死亡最长 23h 才暴露;
也可被 self_heal 的 P-02 15min 持续盯), 验证探测层每个任务的活性 + 自愈引擎自身状态:

  - QSP_SelfHeal      last_run < 20min   (死了则 /Enable+/Run, 仍败 P0)
  - QSP_DrainWatch    last_run < 10min
  - QSP_MsgDrain      last_run < 10min
  - QSP_RemoteFreshness last_run < 70min
  - data/self_heal_state.json 存在且 last_run < 20min
  - data/repair_log.jsonl mtime < 20min(引擎在留痕)

结论入 message_queue(唯一出口); 探到死任务且修复无效 -> P0 绕过队列直发。
退出码: 0 探测层全活 | 1 有修复 | 2 有P0
"""
import datetime as _dt
import json
import os
import subprocess
import sys
import time

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

DATA = os.path.join(PROJECT, "data")
SELF_HEAL_STATE = os.path.join(DATA, "self_heal_state.json")
REPAIR_LOG = os.path.join(DATA, "repair_log.jsonl")
LOOP_LOG = os.path.join(DATA, "loop_watch.log")

# (任务名, last_run 最大允许龄[分钟])
PROBE_TASKS = [
    ("QSP_SelfHeal", 20),
    ("QSP_DrainWatch", 10),
    ("QSP_MsgDrain", 10),
    ("QSP_RemoteFreshness", 70),
]


def now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def log(msg):
    line = "[%s] %s" % (now_iso(), msg)
    print(line)
    try:
        with open(LOOP_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        print(f"🔴 [scripts\loop_watch.py] CR-01: except Exception:", file=sys.stderr)
def task_info(task):
    try:
        p = subprocess.run(["schtasks", "/Query", "/TN", task, "/FO", "LIST", "/V"],
                           capture_output=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW)
        out = p.stdout.decode("gbk", errors="replace")
    except Exception as e:
        return None, None, "查询失败: %s" % e
    last_run, last_result = None, None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("上次运行时间:"):
            v = s.split(":", 1)[1].strip()
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
                try:
                    parsed = _dt.datetime.strptime(v, fmt)
                    # 1999/11/30 是"从未运行"占位值, 不当真实时间
                    last_run = None if parsed.year < 2000 else parsed
                    break
                except ValueError:
                    print(f"⚠️ [scripts\loop_watch.py] 兼容处理: except ValueError:", file=sys.stderr)
        elif s.startswith("上次结果:"):
            try:
                last_result = int(s.split(":", 1)[1].strip())
            except ValueError:
                last_result = s.split(":", 1)[1].strip()
    return last_run, last_result, None


def schtasks_run(task):
    # D-6 P0-2 契约: 异常必须传播(loud fail), 不得吞成 return False
    # (W3 静默化改造曾回退本修复, 2026-10-17 OPS-2 再修复: 保留 CREATE_NO_WINDOW + 恢复传播)
    p = subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True,
                       timeout=60, creationflags=CREATE_NO_WINDOW)
    return p.returncode == 0


def schtasks_enable(task):
    # D-6 P0-2 契约: 异常必须传播(loud fail), 不得吞成 return False
    # (W3 静默化改造曾回退本修复, 2026-10-17 OPS-2 再修复: 保留 CREATE_NO_WINDOW + 恢复传播)
    p = subprocess.run(["schtasks", "/Change", "/TN", task, "/ENABLE"],
                       capture_output=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    return p.returncode == 0


def alert_queue(text):
    # 2026-10-17 OPS-2 写口收敛: 统一经 queue_integration.add_alert() 入队 (契约 {id,type,priority,content,data,ts,sent})
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        for p in (PROJECT, scripts_dir):
            if p not in sys.path:
                sys.path.insert(0, p)
        from queue_integration import add_alert
        add_alert(alert_type="loop_watch", priority="P1",
                  content="⚠️ [看门狗看门狗] " + text,
                  data={"text": text})
    except Exception as e:
        log("入队失败(loud): %s" % e)


def alert_p0(text):
    try:
        from cron_message_sender import send_feishu_bot_api
        ok = send_feishu_bot_api("🔴 [看门狗看门狗-P0] " + text)
        log("P0 直发: %s" % ("成功" if ok else "失败(已落 alert_log)"))
        if not ok:
            with open(os.path.join(DATA, "alert_log.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now_iso(), "alert": "loopwatch P0: " + text},
                                   ensure_ascii=False) + "\n")
    except Exception as e:
        log("P0 直发异常: %s" % e)


def main():
    log("===== loop watch 开始 =====")
    problems = []
    repaired = []
    p0 = False
    now = _dt.datetime.now()

    for task, max_age in PROBE_TASKS:
        last_run, last_result, err = task_info(task)
        if err:
            problems.append("%s: %s" % (task, err))
            continue
        if last_run is None:
            # 从未运行: 若非按设计退出码(1/2=探到故障已告警, 267009=运行中)才是问题
            if last_result not in (1, 2, 267009, "1", "2", "267009", None):
                problems.append("%s: 从未运行且 result=%s" % (task, last_result))
            else:
                log("%s 尚未运行(按设计退出码%s, 等触发点)" % (task, last_result))
            continue
        if last_result not in (0, "0"):
            # 探针任务退出码 1/2 = 按设计报故障(已自行告警), 不是崩溃; 267009=运行中
            if last_result in (1, 2, 267009, "1", "2", "267009"):
                log("%s 退出码%s(按设计报故障), 目标存在, 不判死" % (task, last_result))
            else:
                problems.append("%s: last_result=%s(异常退出码)" % (task, last_result))
                continue
        age = (now - last_run).total_seconds() / 60.0
        if age > max_age:
            log("%s 停摆(龄 %.0fmin > %dmin), 尝试 /Enable+/Run" % (task, age, max_age))
            schtasks_enable(task)
            time.sleep(2)
            if schtasks_run(task):
                repaired.append(task)
                log("%s 已触发重跑" % task)
            else:
                problems.append("%s: 停摆且重跑触发失败(龄 %.0fmin)" % (task, age))
        else:
            log("%s 活性正常(龄 %.0fmin)" % (task, age))

    # 自愈引擎自身状态文件
    if not os.path.exists(SELF_HEAL_STATE):
        problems.append("self_heal_state.json 不存在(引擎可能从未跑)")
    else:
        try:
            st = json.load(open(SELF_HEAL_STATE, encoding="utf-8"))
            last = _dt.datetime.fromisoformat(st.get("last_run", ""))
            age = (now - last).total_seconds() / 60.0
            if age > 20:
                problems.append("self_heal_state last_run 龄 %.0fmin >20min" % age)
            else:
                log("self_heal_state 正常(龄 %.0fmin)" % age)
        except Exception as e:
            problems.append("self_heal_state 解析失败: %s" % e)

    # 留痕活性
    if os.path.exists(REPAIR_LOG):
        age = (now - _dt.datetime.fromtimestamp(os.path.getmtime(REPAIR_LOG))).total_seconds() / 60.0
        if age > 20:
            problems.append("repair_log.jsonl %.0fmin 未更新(引擎不留痕?)" % age)
        else:
            log("repair_log 留痕正常(%.0fmin 前)" % age)
    else:
        problems.append("repair_log.jsonl 不存在")

    if problems:
        if repaired:
            log("已修复重跑: %s, 但仍有问题: %s" % (repaired, problems))
        # 探测层死亡=自愈闭环断裂=最高级
        alert_p0("探测层异常: %s%s。自愈闭环可能断裂, 请立即人工介入。"
                 % ("; ".join(problems), "(已尝试重跑: %s)" % repaired if repaired else ""))
        alert_queue("探测层异常(已P0直发): %s" % "; ".join(problems))
        p0 = True
    else:
        log("探测层全部存活, 自愈闭环运转正常%s" % ("(本轮修复: %s)" % repaired if repaired else ""))

    log("===== loop watch 结束: problems=%d repaired=%d p0=%s =====" % (len(problems), len(repaired), p0))
    return 2 if p0 else (1 if repaired else 0)


if __name__ == "__main__":
    sys.exit(main())
