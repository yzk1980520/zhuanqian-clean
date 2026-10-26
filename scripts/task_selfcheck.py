#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P-T1 连接层任务自检（自愈引擎 v1.0 连接层切片，@老六，只读断言版 10/24）

检测域（全部只读，无网络副作用，无系统变更）:
  T1 看门狗计划任务 Hermes_GatewayHealthCheck:
       State=Disabled          -> P0 (自愈链路断供, 10/23 实案: 7.75h 静默断供)
       LastRun 为空             -> P1 (re-enable 后触发未确认)
       LastRun 龄 >15min       -> P1 (5min 间隔未起跳)
  T2 T7 探测层台账新鲜度 data/self_heal_state.json:
       last_run 龄 >6h -> P1, >24h -> P0 (10/23 实案: 34h 停更)
  T3 supervisor loop 活性 + 代码过期:
       loop pid 死且锁文件龄 >10min -> P1 (loop 停更)
       锁内 script_mtime != 脚本当前 mtime -> P1 (活 loop 代码过期, 10/23 实案 20100)
  T4 gateway 进程活性:
       gateway_supervisor.pid 指向进程死 -> P0 (拉起由 supervisor 负责, 本项仅台账知会)

输出与 carrier_check 同构 {pass,p0,p1,detail,items[]}，exit 0=pass/1=fail。
P-C2 纪律: `--selftest` 跑 8 件合成故障对照组（纯分类函数, 不动系统）, 全命中才准上产。
台账消费: 老六 ledger_schema_v1 (mainline/docs/selfheal/) 直接收 {pass,p0,p1,detail}。
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

HERMES_HOME = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
WATCHDOG_TASK = "Hermes_GatewayHealthCheck"
T7_STATE = r"D:\open code\zhuanqian\data\self_heal_state.json"
LOOP_LOCK = os.path.join(HERMES_HOME, "data", "gateway_supervisor.loop")
SUP_PID = os.path.join(HERMES_HOME, "data", "gateway_supervisor.pid")
SUP_SCRIPT = os.path.join(HERMES_HOME, "scripts", "gateway_supervisor.py")

WATCHDOG_STALE_MIN = 15
T7_STALE_H = 6
T7_FATAL_H = 24
LOOP_STALE_MIN = 10


def _now():
    return datetime.now()


def pid_alive(pid):
    """跨用户进程可见性: 用 Get-Process(PS) 而非 OpenProcess — 10/23 教训: 用户态
    OpenProcess 对 SYSTEM 进程返回 handle 拒绝, 假阴性误判 24h+ (18944 孤儿案)。
    坑 1 (R7 实例): stderr 含 GBK 错误头, 必须按 bytes 收, text 模式解码炸 reader 线程;
    坑 2 (R7 实例): `exit (if ...)` 是 parse error (if 不可作表达式) → 恒非 0 退出码,
    必须语句级 `if (...) { exit 0 } else { exit 1 }` — 02:15 实测该坑让全部 pid 误判 DEAD。"""
    if not pid:
        return False
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "if (Get-Process -Id %d -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" % pid],
        capture_output=True, timeout=30)
    return r.returncode == 0


def find_gateway_pids():
    """T4: gateway 活进程 = 解释器进程 (python/pythonw/hermes/uv) 且命令行含 'gateway run'
    (CIM 只读)。坑 (R7 实例): 10/24 02:18 实测网关真身是 python.exe(pid=15316) 非
    hermes.exe — 模式若锁死 'hermes.exe gateway run' 会假 P0; 查询自身 (bash/powershell
    命令行含模式文本) 靠 Name 白名单排除。"""
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "$p = Get-CimInstance Win32_Process | Where-Object { "
         "$_.Name -in 'python.exe','pythonw.exe','hermes.exe','uv.exe' -and "
         "$_.CommandLine -match 'gateway\\s+run' };"
         "if ($p) { ($p.ProcessId | ForEach-Object { [string]$_ }) -join ',' }"],
        capture_output=True, timeout=60)
    out = r.stdout.decode("ascii", "ignore").strip()
    return [int(x) for x in out.split(",") if x.strip().isdigit()] if out else []


BOARD_URL = "http://127.0.0.1:8666/"


def find_board_pids():
    """T5: board_server 活进程 (CIM 只读, Name 白名单+命令行 'board_server' 双条件,
    R7 坑同 T4: 查询自身 shell 命令行含模式文本, 靠解释器白名单排除)。"""
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "$p = Get-CimInstance Win32_Process | Where-Object { "
         "$_.Name -in 'python.exe','pythonw.exe','hermes.exe','uv.exe','node.exe' -and "
         "$_.CommandLine -match 'board_server' };"
         "if ($p) { ($p.ProcessId | ForEach-Object { [string]$_ }) -join ',' }"],
        capture_output=True, timeout=60)
    out = r.stdout.decode("ascii", "ignore").strip()
    return [int(x) for x in out.split(",") if x.strip().isdigit()] if out else []


def board_http_ok():
    """T5: 面板 HTTP 200 探活 (只读 GET)。返回 (ok, status|'ERR')。
    时点注记 (10/24 实测): board 渲染重载, / 与 /board 首次响应 ~8s — 超时定 30s,
    探活判"服务死"不判"响应慢" (T7 停更型才是 P 级, 慢响应不入告警)。"""
    import urllib.request
    try:
        with urllib.request.urlopen(BOARD_URL, timeout=30) as resp:
            return resp.status == 200, resp.status
    except Exception as e:
        return False, "ERR:" + str(e).split("(")[0][:40]


def classify_board(pids, http_ok, http_code):
    """T5 纯分类 (P-C2 对照组分测对象): 服务死或 HTTP 不通 -> P1 (面板静默死亡型,
    与 T7 停更 34h 同型); 全活 -> OK。"""
    if not pids:
        return "P1", "board_server 进程缺失 — 面板静默死亡 (T7 停更型), 需重启服务"
    if not http_ok:
        return "P1", "board_server 活 (pid=%s) 但 HTTP 探活失败 (code=%s) — 面板不可达" % (pids, http_code)
    return "OK", ""


def board_port_owner():
    """T5 佐证: 8666 端口真持有者 (netstat 只读)。10/24 实测双实例在跑
    (5916 venv py / 12968 系统 py, 均 10/22 06:56 起, 端口归 12968) —
    重载/重启时须双杀, 判活以端口持有者为权威。"""
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=30)
        out = r.stdout.decode("ascii", "ignore")
        pids = set()
        for line in out.splitlines():
            if ":8666" in line and ("LISTENING" in line or "ESTABLISHED" in line):
                p = line.split()[-1].strip()
                if p.isdigit():
                    pids.add(int(p))
        return sorted(pids)
    except Exception:
        return []


def watch_task_state():
    """返回 (state, lastrun_blank, lastrun_age_min|None)。查询失败 -> state='QUERY_FAIL'。"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "$t = Get-ScheduledTask -TaskName '%s';" % WATCHDOG_TASK,
             "if (-not $t) { exit 2 }",
             "Write-Output $t.State;",
             "Write-Output $t.Info.LastRunTime;"],
            capture_output=True, timeout=30)
        lines = r.stdout.decode("utf-8", "ignore").splitlines()
        state = lines[0].strip() if lines else ""
        last_run_raw = lines[1].strip() if len(lines) > 1 else ""
    except Exception:
        return "QUERY_FAIL", None, None
    lastrun_blank = (last_run_raw in ("", "0001-01-01T00:00:00"))
    age = None
    if not lastrun_blank:
        try:
            lt = datetime.fromisoformat(last_run_raw.replace("Z", ""))
            age = (datetime.now() - lt).total_seconds() / 60.0
        except Exception:
            lastrun_blank, age = True, None
    return state, lastrun_blank, age


def corroborate_task_ran():
    """R7 信号免疫: 计划任务 Info.LastRunTime 空 ≠ 没跑 (10/24 实测: 01:18 ensure 实跑
    但 Info 字段恒空)。旁证 = supervisor 日志近 6h 内的 loop 启动/dedup 行。
    返回 (有旁证?, 最近旁证行) — 让台账看到旁证原文, 不假绿也不假红。"""
    try:
        logp = os.path.join(HERMES_HOME, "logs", "gateway_supervisor.log")
        lines = open(logp, "rb").read().decode("utf-8", "ignore").splitlines()
        cutoff = (_now() - __import__("datetime").timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        hits = [l for l in lines if ("loop 启动" in l or "dedup" in l) and l[:11] and l[1:19] >= cutoff]
        if hits:
            return True, hits[-1].strip()
        return False, ""
    except Exception:
        return False, ""


def classify_watchdog(state, lastrun_blank, lastrun_age_min):
    """纯分类函数 (P-C2 对照组分测对象)。"""
    if state == "Disabled":
        return "P0", "看门狗任务 Disabled — 自愈链路断供 (10/23 实案型), 需 /ENABLE + 追禁用来源"
    if state == "QUERY_FAIL":
        return "P1", "看门狗任务查询失败 — 检测层自身异常, 信号免疫件需复核"
    if lastrun_blank:
        return "P1", "看门狗 LastRun 为空 — 触发未确认 (re-enable 后未起跳), 明早批次核"
    if lastrun_age_min is not None and lastrun_age_min > WATCHDOG_STALE_MIN:
        return "P1", "看门狗 LastRun 龄 %.0fmin > %dmin — 5min 间隔疑似未起跳" % (lastrun_age_min, WATCHDOG_STALE_MIN)
    return "OK", ""


def classify_t7(last_run_age_h):
    if last_run_age_h is None:
        return "P1", "T7 台账缺失/不可读 — 探测层盲区"
    if last_run_age_h > T7_FATAL_H:
        return "P0", "T7 探测层停更 %.1fh > %dh — 监控本身失明 (10/23 34h 实案型)" % (last_run_age_h, T7_FATAL_H)
    if last_run_age_h > T7_STALE_H:
        return "P1", "T7 探测层停更 %.1fh > %dh" % (last_run_age_h, T7_STALE_H)
    return "OK", ""


def classify_loop(loop_pid, loop_pid_alive, lock_age_min, code_stale):
    if code_stale:
        return "P1", "活 loop 代码过期 (锁 script_mtime < 脚本当前 mtime) — 需重启 loop (10/23 20100 实案型)"
    if (not loop_pid_alive) and lock_age_min is not None and lock_age_min > LOOP_STALE_MIN:
        return "P1", "supervisor loop pid=%s 死且锁文件龄 %.0fmin — loop 停更" % (loop_pid, lock_age_min)
    return "OK", ""


def classify_gateway(gw_pid, alive):
    if not alive:
        return "P0", "gateway 进程 pid=%s 缺失 (拉起归 supervisor, 本项台账知会)" % gw_pid
    return "OK", ""


def main_selftest():
    """P-C2 对照组: 8 件合成故障全命中, 断言非空转。"""
    cases = [
        ("Disabled 断供", classify_watchdog("Disabled", None, None), "P0"),
        ("LastRun 空", classify_watchdog("Ready", True, None), "P1"),
        ("LastRun 停更 20min", classify_watchdog("Ready", False, 20.0), "P1"),
        ("正常触发", classify_watchdog("Ready", False, 4.0), "OK"),
        ("T7 停更 7h", classify_t7(7.0), "P1"),
        ("T7 停更 34h", classify_t7(34.0), "P0"),
        ("loop 代码过期", classify_loop(123, True, 1.0, True), "P1"),
        ("loop 死锁龄", classify_loop(999, False, 30.0, False), "P1"),
    ]
    hit = 0
    for name, got, want in cases:
        ok = got[0] == want
        hit += 1 if ok else 0
        print("  [%s] %s: 期望=%s 实得=%s" % ("HIT" if ok else "MISS", name, want, got[0]))
    # gateway 死
    g = classify_gateway(4242, False)
    hit += 1 if g[0] == "P0" else 0
    print("  [%s] gateway 缺失: 期望=P0 实得=%s" % ("HIT" if g[0] == "P0" else "MISS", g[0]))
    # T5 board 合成故障 (面板静默死亡型 3 例)
    for name, got, want in [
        ("board 进程死", classify_board([], True, 200), "P1"),
        ("board HTTP 不通", classify_board([777], False, "ERR:connection refused"), "P1"),
        ("board 全活", classify_board([777], True, 200), "OK"),
    ]:
        hit += 1 if got[0] == want else 0
        print("  [%s] %s: 期望=%s 实得=%s" % ("HIT" if got[0] == want else "MISS", name, want, got[0]))
    print("对照组 %d/12 命中" % hit)
    return 0 if hit == 12 else 1


def main():
    p0, p1, detail = [], [], []

    # T1 看门狗任务 (R7: LastRun 空 + 日志旁证 -> info, 不假绿不假红)
    st, lb, la = watch_task_state()
    lvl, msg = classify_watchdog(st, lb, la)
    corroborated, corr_line = (False, "")
    if lb:
        corroborated, corr_line = corroborate_task_ran()
        if corroborated:
            lvl, msg = "INFO", "看门狗 LastRun 空但有日志旁证 (R7 免疫, 不告警): " + corr_line
    detail.append({"item": "T1-watchdog-task", "state": st, "lastrun_blank": lb,
                   "lastrun_age_min": round(la, 1) if la is not None else None,
                   "r7_corroborated": corroborated, "corroboration": corr_line, "level": lvl})
    if lvl == "P0":
        p0.append("P0: " + msg)
    elif lvl == "P1":
        p1.append("P1: " + msg)

    # T2 T7 台账
    t7_age = None
    try:
        d = json.load(open(T7_STATE))
        t7_age = (_now() - datetime.fromisoformat(d["last_run"])).total_seconds() / 3600.0
    except Exception:
        t7_age = None
    lvl, msg = classify_t7(t7_age)
    detail.append({"item": "T2-t7-ledger", "age_h": round(t7_age, 1) if t7_age is not None else None, "level": lvl})
    if lvl == "P0":
        p0.append("P0: " + msg)
    elif lvl == "P1":
        p1.append("P1: " + msg)

    # T3 loop 活性 + 代码过期
    loop_pid, loop_alive, lock_age, code_stale = None, False, None, False
    try:
        lp = json.load(open(LOOP_LOCK))
        loop_pid = lp.get("pid")
        loop_alive = pid_alive(loop_pid)
        lock_age = (time.time() - os.path.getmtime(LOOP_LOCK)) / 60.0
        try:
            code_stale = os.path.getmtime(SUP_SCRIPT) > lp.get("script_mtime", 0)
        except Exception:
            code_stale = False
    except Exception:
        lock_age, code_stale = 9999.0, False
    lvl, msg = classify_loop(loop_pid, loop_alive, lock_age, code_stale)
    detail.append({"item": "T3-supervisor-loop", "pid": loop_pid, "alive": loop_alive,
                   "lock_age_min": round(lock_age, 1) if lock_age is not None else None,
                   "code_stale": code_stale, "level": lvl})
    if lvl == "P0":
        p0.append("P0: " + msg)
    elif lvl == "P1":
        p1.append("P1: " + msg)

    # T4 gateway 活性 (CIM 命令行匹配, 非 pid 文件 — gateway_supervisor.pid 存的是 loop 自身 pid)
    gw_pids = find_gateway_pids()
    lvl, msg = classify_gateway(gw_pids[0] if gw_pids else None, len(gw_pids) > 0)
    detail.append({"item": "T4-gateway-pid", "pids": gw_pids, "alive": len(gw_pids) > 0, "level": lvl})
    if lvl == "P0":
        p0.append("P0: " + msg)
    elif lvl == "P1":
        p1.append("P1: " + msg)

    # T5 board 面板服务存活 (10/24 排程锁件: 面板静默死亡 = 600312 型"服务死无人知"盲区;
    # 只读双探针: 进程 + HTTP 200, 与 carrier_check rank 产物面正交)
    b_pids = find_board_pids()
    b_ok, b_code = board_http_ok()
    lvl, msg = classify_board(b_pids, b_ok, b_code)
    port_owner = board_port_owner()
    detail.append({"item": "T5-board-server", "pids": b_pids, "port_8666_owner": port_owner,
                   "http_200": b_ok, "http_code": b_code, "level": lvl})
    if lvl == "P0":
        p0.append("P0: " + msg)
    elif lvl == "P1":
        p1.append("P1: " + msg)

    result = {"pass": not p0 and not p1, "p0": p0, "p1": p1, "detail": detail,
              "ts": _now().isoformat(timespec="seconds")}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print("\n[P-T1 task_selfcheck] 5 项 | P0=%d P1=%d" % (len(p0), len(p1)))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main_selftest() if "--selftest" in sys.argv else main())
