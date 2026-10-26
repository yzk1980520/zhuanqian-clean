#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py health
# -*- coding: utf-8 -*-
"""self_heal_check.py — 主动自愈运维引擎 (2026-10-15 老六, Hermes治理方案v1 延伸)

定位: 把"探测->修复->复检->仍败才升级"的闭环动作化。此前所有监控机制都是
detect-only(只告警不修复), 且 HealthCheck L1/L3/L4 全死(目标脚本不存在,
result=2 空跑)无人知 — 本引擎补三件事:
  1. 定时主动探测: 任务级活性(last_result/last_run)/告警链/同步环/远程灾备/
     飞书接口/webhook/卫生/配置死模式/外部数据源/死部署副本/备份垃圾堆积
  2. 已知故障自动修复: schtasks /Run|/Enable, 日志轮转, 构建产物清理
  3. 垃圾回收: 死任务禁用+上报, 死配置扫描, bak/.trash 盘点

告警路由(T2立规): P1/P2 -> message_queue(唯一出口, QSP_MsgDrain 5min到群);
P0 -> 绕过队列 default 应用 bot API 直发(防告警链自己死了告警发不出)。
所有探测/修复动作留痕 data/repair_log.jsonl + data/self_heal_state.json。

纪律边界: 只修 repo 域 + QSP_* 计划任务层; 不碰 hermes gateway daemon
(重启归老大/总管), 不写 trade_log/holdings。

用法:
  python scripts/self_heal_check.py            # 正常模式(探+修)
  python scripts/self_heal_check.py --dry-run  # 只探测不修复(演练)
退出码: 0 全健康无动作 | 1 有修复动作 | 2 有P0告警
"""
import argparse
import datetime as _dt
import glob
import json
import os
import re
import subprocess
import sys
import time

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)  # atomic_json/cron_message_sender 在仓库根(10-15 总管根因修复同款)
try:
    import machine_wake_state  # t_51e04b30 B案: 机器清醒状态双源感知(与 self_heal 同目录)
except ImportError:  # 非脚本直跑场景(如 CI 以其他方式加载): 补 scripts/ 路径后重导入
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import machine_wake_state

DATA = os.path.join(PROJECT, "data")
REPAIR_LOG = os.path.join(DATA, "repair_log.jsonl")
STATE_FILE = os.path.join(DATA, "self_heal_state.json")
WEBHOOK_PROBE_STATE = os.path.join(DATA, "webhook_probe_state.json")
DATASRC_PROBE_STATE = os.path.join(DATA, "datasrc_probe_state.json")
DRAIN_STATE = os.path.join(DATA, "drain_state.json")
GITSYNC_STATE = os.path.join(DATA, "git_sync_state.json")
FRESHNESS_LOG = os.path.join(DATA, "remote_freshness.log")
KNOWN_GAPS = os.path.join(DATA, "known_gaps.json")   # t_51e04b30: 已知缺口台账(写侧=降级登记)
FEISHU_CFG = os.path.join(PROJECT, "config", "feishu_config.json")

# P-11 卫生探针：告警文本中引用的仓库内路径必须真实存在
# 明确列出所有告警字符串中引用的路径（精确清单，非正则扫描）
ALERT_REF_PATHS = [
    "docs/runbook-人工单点.md",   # self_heal_check.py:839（P0 告警活路径, 2026-10-23 基地化误归档后恢复）
    # "docs/规范-静默运行-20261017.md" 已移出 P-11 活路径校验：
    # 该 spec 经基地化清臃肿(e9b22680)归档至 docs/archive/20261022-cleanup/，
    # 其自身为注释口径引用(非 P0 告警文本活路径), 保持归档不动; 仅 runbook 是活路径。
]

PY = r"C:\Users\WIN10\AppData\Local\Programs\Python\Python311\python.exe"
SCHTASKS = "schtasks"

# ---------------------------------------------------------------- 任务活性注册表
# 探测层任务 -> (last_run 最大允许龄[分钟], 是否仅工作日)
# 注: QSP_SelfHeal 不在此表 — 自引用会竞态(自己查自己上次运行); 它的活性由
# QSP_LoopWatch 经 self_heal_state.json 外部盯(与 DrainWatch 盯 MsgDrain 同构)
LIVENESS_TASKS = {
    "QSP_MsgDrain": (10, False),
    "QSP_DrainWatch": (10, False),
    "QSP_RemoteFreshness": (70, False),
    "QSP_GitSync": (26 * 60, True),      # 工作日 09:30, 允许跨周末
    # 2026-10-16 T7-B2 修复: LoopWatch 原日频 09:05, 与其守护的 15min 探测层
    # 节奏失配——探测层死亡最长 23h 才暴露。已改为每 6h(03/09/15/21:05),
    # 窗口=节奏+1h 容差; 同步修正本注册表(原 25h 窗会放任死 LoopWatch 25h)
    "QSP_LoopWatch": (7 * 60, False),
    "QSP_Verify": (25 * 60, False),
    "QSP_Watchdog": (25 * 60, False),
    # 2026-10-20 补看门狗盲区(qa-verifier-3 取证): 生产 daily 选股链此前零任务级覆盖,
    # 门禁阻断多日无人处置。实测每天 20:00 全天候跑(非仅工作日); 窗口 26h 同步频日任务
    # QSP_GitSync 口径(跨一次调度点+容差) —— 漏跑/死亡超窗 -> P-02 异常 -> R-02 /Run 触发一次
    "Zhuanqian_DailyAuto": (26 * 60, False),
}
# 探针任务"按设计"的退出码: 1=探到故障已告警(DrainWatch), 2=有P0(SelfHeal/LoopWatch)
# 这类非零退出是正常工作, 不触发修复; 267009=正在运行(瞬态)
# 注: 含字符串形态 — schtasks 偶返回非 int 原文, 两种形态都放行
BY_DESIGN_EXITS = (1, 2, 267009, "1", "2", "267009")
# 已知死任务族(2026-10-15 审计实锤: 目标 health_monitor_cli.py 不存在, result=2)
# 保留在注册表内是为了让 R-02 持续验证"禁用了就别复活", 而非遗忘
DEAD_TASK_FAMILY = ("HealthCheck_L1_5min", "HealthCheck_L3_Morning",
                    "HealthCheck_L3_Evening", "HealthCheck_L4_Weekly")

LOG_MAX_BYTES = 20 * 1024 * 1024      # 日志轮转阈值 20MB
# P04 远程落后阈值: ahead > 50 commit 视为同步环断流风险(周末正常不push, ahead会缓慢累积)
# 阈值来源: gateway.log P1-ALERT 日志口径(老六 2026-10-16), 与 self_heal_check.py 历史阈值一致
P04_AHEAD_THRESHOLD = 50
LOG_KEEP_LINES = 3000                  # 轮转保留行数
WEBHOOK_PROBE_INTERVAL_MIN = 30        # webhook 静默探针节流
DATASRC_PROBE_INTERVAL_MIN = 240       # 外部数据源探针节流(4h)

# P-10/P-11 (T7 下一版, 2026-10-15): 死部署副本注册表 + 备份堆积阈值
# DEPLOY_DIRS: 仓库根的部署副本目录 — 曾是监控子系统的工作副本, 无活消费者即死部署
DEPLOY_DIRS = ("health_monitor",)
TRASH_MAX_MB = 100                     # .trash 体积告警阈值
BAK_MAX_COUNT = 200                    # .bak* 文件数告警阈值

DRY_RUN = False


def now_iso():
    return _dt.datetime.now().isoformat(timespec="seconds")


def log(action, detail, level="info"):
    entry = {"ts": now_iso(), "level": level, "action": action, "detail": detail}
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(REPAIR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[repair_log] 写失败: " + str(e))
    tag = {"info": "  ", "repair": "🔧", "alert": "🚨", "ok": "✅"}.get(level, "  ")
    print("%s [%s] %s" % (tag, action, detail))


def load_json(path, default=None):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("[state] 写 %s 失败: %s" % (path, e))
        return False


# ---------------------------------------------------------------- 告警出口
ALERT_STATE_FILE = os.path.join(DATA, "self_heal_alert_state.json")
# 2026-10-19: 修复动作冷却台账(防 P-03/P-04 同源重复触发放大成进程风暴)
REPAIR_STATE_FILE = os.path.join(DATA, "self_heal_repair_state.json")


def alert_once(rule_id, text, level="P1", repeat_hours=2):
    """状态变化才告警; 持续坏每 repeat_hours 重告一次(防刷屏)"""
    st = load_json(ALERT_STATE_FILE, {}) or {}
    prev = st.get(rule_id, {})
    sig = text[:120]
    now_ts = time.time()
    changed = prev.get("sig") != sig
    stale = (now_ts - prev.get("last_ts", 0)) > repeat_hours * 3600
    if changed or stale:
        alert(text, level)
        st[rule_id] = {"sig": sig, "last_ts": now_ts}
        save_json(ALERT_STATE_FILE, st)


def alert(text, level="P1"):
    """P1/P2 走队列唯一出口; P0 绕过队列 bot API 直发(复用 T2 通道)。"""
    log("alert-" + level, text, level="alert")
    if level == "P0":
        try:
            from cron_message_sender import send_feishu_bot_api
            ok = send_feishu_bot_api("🔴 [自愈引擎-P0] " + text)
            if not ok:
                log("alert-P0", "bot API 直发失败, 已落 alert_log.jsonl(本地台账)", "alert")
        except Exception as e:
            log("alert-P0", "直发异常: " + str(e), "alert")
        try:
            os.makedirs(DATA, exist_ok=True)
            with open(os.path.join(DATA, "alert_log.jsonl"), "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now_iso(), "alert": "self-heal P0: " + text},
                                   ensure_ascii=False) + "\n")
        except Exception:
            print(f"🔴 [scripts\self_heal_check.py] CR-01: except Exception:", file=sys.stderr)
        return
    # P1/P2: 入队(唯一出口)
    try:
        q = os.path.join(DATA, "message_queue.json")
        items = load_json(q, []) or []
        items.append({"id": "selfheal_%s_%d" % (level.lower(), int(time.time())),
                      "content": "⚠️ [自愈引擎-%s] %s" % (level, text),
                      "platform": "feishu", "ts": time.time()})
        save_json(q, items)
    except Exception as e:
        log("alert-queue", "入队失败: " + str(e), "alert")


# ---------------------------------------------------------------- schtasks 工具
def schtasks_info(task):
    """返回 (last_run_dt|None, last_result|None, action_str|None, enabled|None)"""
    try:
        p = subprocess.run([SCHTASKS, "/Query", "/TN", task, "/FO", "LIST", "/V"],
                           capture_output=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW)
        out = p.stdout.decode("gbk", errors="replace")
    except Exception as e:
        log("schtasks", "%s 查询失败: %s" % (task, e), "alert")
        return None, None, None, None
    last_run, last_result, action, enabled = None, None, None, None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("上次运行时间:"):
            v = s.split(":", 1)[1].strip()
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
                try:
                    parsed = _dt.datetime.strptime(v, fmt)
                    # 1999/11/30 是 schtasks 的"从未运行"占位值, 不当真实时间
                    last_run = None if parsed.year < 2000 else parsed
                    break
                except ValueError:
                    print(f"⚠️ [scripts\self_heal_check.py] 兼容处理: except ValueError:", file=sys.stderr)
        elif s.startswith("上次结果:"):
            v = s.split(":", 1)[1].strip()
            try:
                last_result = int(v)
            except ValueError:
                last_result = v
        elif s.startswith("要运行的任务:"):
            action = s.split(":", 1)[1].strip()
        elif s.startswith("计划任务状态:"):
            enabled = s.split(":", 1)[1].strip()
    return last_run, last_result, action, enabled


def schtasks_run(task):
    if DRY_RUN:
        log("repair-dry", "would schtasks /Run %s" % task, "repair")
        return True
    try:
        p = subprocess.run([SCHTASKS, "/Run", "/TN", task], capture_output=True,
                           timeout=60, creationflags=CREATE_NO_WINDOW)
        ok = p.returncode == 0
        log("repair", "schtasks /Run %s -> rc=%d %s" % (
            task, p.returncode, p.stdout.decode("gbk", errors="replace").strip()[:60]),
            "repair" if ok else "alert")
        return ok
    except Exception as e:
        log("repair", "schtasks /Run %s 异常: %s" % (task, e), "alert")
        return False


def schtasks_set_state(task, enable=True):
    if DRY_RUN:
        log("repair-dry", "would schtasks /Change %s %s" % (task, "Enable" if enable else "Disable"), "repair")
        return True
    flag = "/ENABLE" if enable else "/DISABLE"
    try:
        p = subprocess.run([SCHTASKS, "/Change", "/TN", task, flag],
                           capture_output=True, timeout=60,
                           creationflags=CREATE_NO_WINDOW)
        ok = p.returncode == 0
        log("repair", "schtasks /Change %s %s -> rc=%d" % (task, flag, p.returncode),
            "repair" if ok else "alert")
        return ok
    except Exception as e:
        log("repair", "schtasks /Change %s 异常: %s" % (task, e), "alert")
        return False


def action_target_missing(action_str):
    """从'要运行的任务'提取脚本目标判断是否存在。返回 (missing: bool, target: str)
    兼容三种形态(2026-10-15 实测): 带引号含空格路径 / 无引号含空格路径(D:\\open code\\...)
    / 解释器+相对脚本(python.exe health_monitor_cli.py --mode full)。任一引用脚本存在即非死任务。"""
    if not action_str:
        return False, ""
    s = action_str.strip()
    cands = []
    # 1) 带引号路径(可含空格)
    for q in re.findall(r'"([^"]+)"', s):
        if re.search(r"\.(py|bat|cmd|vbs|ps1)$", q, re.I):
            cands.append(q)
    # 2) 无引号盘符路径(可含空格, 如 D:\open code\...\x.cmd)
    for mt in re.finditer(r"([A-Za-z]:[^\"\n]*?\.(?:py|bat|cmd|vbs|ps1))(?=[\"\s]|$)", s, re.I):
        cands.append(mt.group(1).strip())
    # 3) 无目录相对脚本名(如 health_monitor_cli.py)
    for tok in s.split():
        t = tok.strip("\"")
        if (re.search(r"\.(py|bat|cmd|vbs|ps1)$", t, re.I)
                and not re.match(r"^[A-Za-z]:", t)
                and "/" not in t and "\\" not in t):
            cands.append(t)
    if not cands:
        return False, ""
    for c in cands:
        if os.path.isabs(c):
            if os.path.exists(c):
                return False, c
        else:
            for r in (os.path.expanduser("~/.quant-stock-picker"),
                      os.path.join(PROJECT, "scripts"), PROJECT):
                if os.path.exists(os.path.join(r, c)):
                    return False, c
    return True, cands[0]


# ---------------------------------------------------------------- 探测规则
def probe_p01_drain():
    """P-01 告警投递链活性: drain_state last_run<15min 且 consec_fail==0"""
    st = load_json(DRAIN_STATE)
    if not st or not st.get("last_run"):
        return False, "drain_state.json 缺失或无 last_run"
    try:
        last = _dt.datetime.fromisoformat(st["last_run"])
    except Exception:
        return False, "last_run 解析失败: %r" % st.get("last_run")
    age = (_dt.datetime.now() - last).total_seconds() / 60.0
    if age >= 15:
        return False, "drain last_run 龄 %.1fmin ≥15min" % age
    if int(st.get("consec_fail", 0)) > 0:
        return False, "consec_fail=%s 连续失败" % st.get("consec_fail")
    return True, "last_run 龄 %.1fmin" % age


def probe_p02_task_liveness():
    """P-02 任务级活性: 注册表任务 last_result==0(或按设计退出码) 且 last_run 在窗内"""
    problems = []
    notes = []
    now = _dt.datetime.now()
    weekday = now.weekday() < 5
    for task, (max_age, wd_only) in LIVENESS_TASKS.items():
        if wd_only and not weekday:
            continue
        last_run, last_result, action, enabled = schtasks_info(task)
        if last_run is None:
            if last_result in BY_DESIGN_EXITS or last_result in (0, "0"):
                notes.append("%s: 未运行过(按设计退出码%s, 等首个触发点)" % (task, last_result))
                continue
            problems.append("%s: 无上次运行记录(enabled=%s)" % (task, enabled))
            continue
        if last_result not in (0, "0"):
            missing, target = action_target_missing(action)
            if missing:
                problems.append("%s: result=%s 目标不存在(%s) → 死任务" % (task, last_result, target))
            elif last_result in BY_DESIGN_EXITS:
                notes.append("%s: 退出码%s(探针按设计报故障/运行中), 目标存在, 不修" % (task, last_result))
            else:
                problems.append("%s: result=%s 目标存在(%s) → 异常退出码" % (task, last_result, target))
            continue
        age = (now - last_run).total_seconds() / 60.0
        if age > max_age:
            problems.append("%s: last_run 龄 %.0fmin > 窗 %dmin" % (task, age, max_age))
    # 死任务族: 应保持禁用; 若复活且报错 -> 再禁
    for task in DEAD_TASK_FAMILY:
        last_run, last_result, action, enabled = schtasks_info(task)
        if enabled and "禁用" not in (enabled or ""):
            missing, target = action_target_missing(action)
            if missing or last_result not in (0, "0", None):
                problems.append("%s: 死任务却处于启用态(enabled=%s result=%s)" % (task, enabled, last_result))
    if problems:
        return False, "; ".join(problems + notes)
    return True, "; ".join(notes) if notes else "全部任务活性正常"


def probe_p03_gitsync():
    """P-03 同步环活性: git_sync_state 最近成功 <26h(工作日)"""
    st = load_json(GITSYNC_STATE)
    now = _dt.datetime.now()
    if now.weekday() >= 5:
        return True, "周末跳过"
    if not st:
        return False, "git_sync_state.json 缺失(同步环可能从未跑)"
    ts = st.get("last_success") or st.get("last_run")
    if not ts:
        return False, "git_sync_state 无成功时间戳: keys=%s" % list(st.keys())
    try:
        last = _dt.datetime.fromisoformat(ts)
    except Exception:
        return False, "时间戳解析失败: %r" % ts
    age = (now - last).total_seconds() / 3600.0
    if age > 26:
        return False, "同步环最近成功 %.1fh 前 >26h" % age
    return True, "最近成功 %.1fh 前" % age


def probe_p04_remote():
    """P-04 远程灾备: 复用每小时 freshness 探针的结论(避免重复网络调用)"""
    if not os.path.exists(FRESHNESS_LOG):
        return False, "remote_freshness.log 不存在(探针未跑过)"
    mtime = _dt.datetime.fromtimestamp(os.path.getmtime(FRESHNESS_LOG))
    age = (_dt.datetime.now() - mtime).total_seconds() / 60.0
    if age > 70:
        return False, "freshness 日志 %.0fmin 未更新(探针死了?)" % age
    # P-04 判据: 读 state 文件里双远程 ok 状态(非字符串匹配日志 tail)
    # 日志 tail 格式 "ahead=26" 表示本地领先远程26 commit, 是正常现象(周末不push), 非异常
    state = load_json(os.path.join(DATA, "remote_freshness_state.json"))
    if not state or not state.get("results"):
        # 回退: 日志存在且 <70min 视为 PASS
        return True, "探针 %.0fmin 前更新, 双远程 ✅" % age
    # 检查双远程均 ok
    remotes_ok = all(r.get("ok") for r in state["results"])
    if not remotes_ok:
        bad = [r["remote"] for r in state["results"] if not r.get("ok")]
        return False, "远程 %s 异常: %s" % (",".join(bad),
            "; ".join(a for r in state["results"] for a in r.get("alerts", [])))
    ahead_max = max((r.get("local_ahead") or 0) for r in state["results"])
    if ahead_max > P04_AHEAD_THRESHOLD:
        return False, "ahead=%d > 阈值%d(远程落后超限, 同步环可能断流)" % (ahead_max, P04_AHEAD_THRESHOLD)
    return True, "双远程 ✅ (max ahead=%d, 阈值%d)" % (ahead_max, P04_AHEAD_THRESHOLD)


def probe_p05_feishu_api():
    """P-05 飞书接口活性: default 应用 token + bot 在线"""
    cfg = os.path.join(PROJECT, "config", "feishu_fallback_app.json")
    c = load_json(cfg)
    if not c or not c.get("app_id"):
        return False, "feishu_fallback_app.json 缺失"
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": c["app_id"], "app_secret": c["app_secret"]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        tok = json.loads(urllib.request.urlopen(req, timeout=15).read())
        if tok.get("code") != 0:
            return False, "token 换取失败: %s" % tok.get("msg")
        req2 = urllib.request.Request("https://open.feishu.cn/open-apis/bot/v3/info",
                                      headers={"Authorization": "Bearer " + tok["tenant_access_token"]})
        info = json.loads(urllib.request.urlopen(req2, timeout=15).read())
        if info.get("code") != 0:
            return False, "bot info 失败: %s" % info.get("msg")
        bot = info.get("bot", {}) or {}
        name = bot.get("bot_name") or bot.get("name") or bot.get("app_name") or "?"
        return True, "bot %s 在线" % name
    except Exception as e:
        return False, "飞书接口异常: %s" % str(e)[:80]


def probe_p06_webhook():
    """P-06 webhook 通道: 带签名畸形请求静默探针(缺 content, 拒发不扰民), 节流 30min
    返回码语义(2026-10-15 实测): 19002=活着且健康(参数被拒, 未投递) | 19007=机器人已禁用
    19021=签名密钥缺失/错误(活着但不可用) | 0=异常成功(不应发生)"""
    st = load_json(WEBHOOK_PROBE_STATE, {}) or {}
    last = st.get("last_probe_ts")
    if last and (time.time() - last) < WEBHOOK_PROBE_INTERVAL_MIN * 60:
        return True, "节流中(上次结论: %s)" % st.get("last_code")
    cfg = load_json(FEISHU_CFG, {}) or {}
    url = cfg.get("webhook_url")
    if not url:
        return False, "feishu_config.json 无 webhook_url"
    try:
        import urllib.request
        secret = cfg.get("secret") or ""
        ts = str(int(time.time()))
        body = {"msg_type": "text"}
        if secret:
            import hmac, hashlib, base64
            body["timestamp"] = ts
            body["sign"] = base64.b64encode(
                hmac.new((ts + "\n" + secret).encode("utf-8"),
                         digestmod=hashlib.sha256).digest()).decode("utf-8")
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        code = resp.get("code")
        save_json(WEBHOOK_PROBE_STATE, {"last_probe_ts": int(time.time()), "last_code": code,
                                        "last_msg": resp.get("msg", "")})
        if code in (19002, 0):
            return True, "webhook 健康(活体响应 %s)" % code
        if code == 19007:
            return False, "webhook 机器人已禁用(19007) — 需老大在群重建自定义机器人"
        if code == 19021:
            return False, "webhook 签名校验失败(19021) — secret 缺失或错误, 需老大补密钥"
        return False, "webhook 返回 %s(%s)" % (code, resp.get("msg", "")[:50])
    except Exception as e:
        save_json(WEBHOOK_PROBE_STATE, {"last_probe_ts": int(time.time()), "last_code": "exception",
                                        "last_msg": str(e)[:80]})
        return False, "webhook 探测异常: %s" % str(e)[:80]


def probe_p07_hygiene():
    """P-07 卫生: 大日志/pycache/.coverage"""
    issues = []
    for f in glob.glob(os.path.join(DATA, "*.log")):
        try:
            if os.path.getsize(f) > LOG_MAX_BYTES:
                issues.append("%s %.1fMB" % (os.path.basename(f), os.path.getsize(f) / 1048576))
        except OSError:
            print(f"⚠️ [scripts\self_heal_check.py] 兼容处理: except OSError:", file=sys.stderr)
    # __pycache__ 是 gitignored 构建产物, QSP_MsgDrain 每次跑 python 都再生 → 不算卫生红项
    # 只检查 .coverage 和大日志
    if os.path.exists(os.path.join(PROJECT, ".coverage")):
        issues.append(".coverage")
    return (len(issues) == 0), "; ".join(issues) if issues else "卫生良好"


def probe_p08_config_dead():
    """P-08 配置死模式扫描(hermes 域只报告, repo 域自动标记)"""
    findings = []
    # 1. 死 webhook 引用(010b9197 已实证 19007)
    cfg = load_json(FEISHU_CFG, {}) or {}
    if "010b9197" in (cfg.get("webhook_url") or ""):
        findings.append("repo: feishu_config 仍引用已实证死亡的 webhook 010b9197")
    if not cfg.get("secret") and cfg.get("webhook_url"):
        findings.append("repo: webhook 启用签名校验但 secret 为空(19021 不可用)")
    # 2. hermes 域死模式(只报告, T5 归总管/老大)
    #    注: 相对拼路径(~/../../Hermes agent)在本机 os.path.exists 失效, 用绝对路径
    zg = os.path.join(r"D:\Hermes agent", "Hermes Agent CN Desktop", "data", "hermes-home",
                      "profiles", "zongguan", "config.yaml")
    if os.path.exists(zg):
        txt = open(zg, encoding="utf-8", errors="replace").read()
        n_omt = len(re.findall(r"omt_\w+_channel", txt))
        if n_omt:
            findings.append("hermes: zongguan/config.yaml 假 thread_id x%d(T5 待拍)" % n_omt)
    return (len(findings) == 0), "; ".join(findings) if findings else "无死模式"


def probe_p09_datasrc():
    """P-09 外部数据源探针(东财, 节流4h, 只报告)"""
    st = load_json(DATASRC_PROBE_STATE, {}) or {}
    last = st.get("last_probe_ts")
    if last and (time.time() - last) < DATASRC_PROBE_INTERVAL_MIN * 60:
        return True, "节流中(上次: %s)" % st.get("last_ok")
    try:
        import urllib.request
        t0 = time.time()
        req = urllib.request.Request("http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=1&fs=m:1",
                                     headers={"User-Agent": "Mozilla/5.0"})
        code = urllib.request.urlopen(req, timeout=8).status
        ok = code == 200
        save_json(DATASRC_PROBE_STATE, {"last_probe_ts": int(time.time()),
                                        "last_ok": ok, "latency_ms": int((time.time() - t0) * 1000)})
        return ok, "东财接口 HTTP %s (%.0fms)" % (code, (time.time() - t0) * 1000)
    except Exception as e:
        save_json(DATASRC_PROBE_STATE, {"last_probe_ts": int(time.time()), "last_ok": False})
        return False, "东财接口异常: %s" % str(e)[:80]


# ---------------------------------------------------------------- 死部署/堆积探测(P-10/P-11)
def _task_registry():
    """一次性批量解析全部计划任务 -> [(task_name, enabled: bool, action: str)]
    单次 schtasks 调用覆盖 300+ 任务(避免逐任务子进程); 非 Windows 环境返回 []。"""
    try:
        p = subprocess.run([SCHTASKS, "/Query", "/FO", "LIST", "/V"],
                           capture_output=True, timeout=120,
                           creationflags=CREATE_NO_WINDOW)
    except Exception:
        print(f"🔴 [scripts\self_heal_check.py] CR-01(return): except Exception:", file=sys.stderr)
        return []
    out = p.stdout.decode("gbk", errors="replace")
    tasks, name, enabled, action = [], None, None, None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("任务名:"):
            if name is not None:
                tasks.append((name, enabled, action))
            name, enabled, action = s.split(":", 1)[1].strip(), None, None
        elif s.startswith("计划任务状态:"):
            enabled = "禁用" not in s.split(":", 1)[1]
        elif s.startswith("要运行的任务:"):
            action = s.split(":", 1)[1].strip()
    if name is not None:
        tasks.append((name, enabled, action))
    return tasks


def probe_p10_dead_deploy():
    """P-10 死部署副本: 注册部署目录存在, 但无任何【启用态】计划任务消费它(只报告)
    实证链(2026-10-15): zhuanqian/health_monitor/(15 个 git 跟踪文件, 108K)的假想消费者
    是 HealthCheck_L1/L3x2/L4 四任务, 但其行动指向 health_monitor_cli.py — 该文件在
    repo 副本与 ~/.quant-stock-picker 均不存在(任务已由 GC-03 禁用)。禁用态任务的引用
    不算存活消费者; 无活消费者 = 死部署副本。删/留由老大拍板(GC-04 纪律: 只报告不动手)。"""
    dead = []
    reg = _task_registry()
    if not reg:
        return True, "任务注册表不可用(非 Windows 或 schtasks 缺失), 跳过"
    for d in DEPLOY_DIRS:
        path = os.path.join(PROJECT, d)
        if not os.path.isdir(path):
            continue
        live_refs = [name for name, enabled, action in _task_registry()
                     if enabled and action and d in action]
        if not live_refs:
            try:
                size_mb = sum(os.path.getsize(os.path.join(r, f))
                              for r, _, fs in os.walk(path) for f in fs) / 1048576
            except OSError:
                size_mb = -1.0
            dead.append("%s/ (%.1fMB, 0 个启用态任务引用)" % (d, size_mb))
    if dead:
        return False, ("死部署副本: %s — 无存活消费者, 删/留请老大拍板"
                       % "; ".join(dead))
    return True, "无死部署副本(%d 个注册目录均有活引用或不存在)" % len(DEPLOY_DIRS)


def probe_p11_backup_bloat():
    """P-11 备份/垃圾堆积(GC-04/05 探针化): .bak* 文件数 / .trash 体积超阈 -> P2 报告
    纪律: 只报告不动手 — 备份内容价值待判, 清理由老大拍板"""
    issues = []
    pat = re.compile(r"\.bak($|[_.])")
    n_bak, bak_bytes = 0, 0
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [x for x in dirs
                   if x not in (".git", "node_modules", "__pycache__", ".trash")]
        for f in files:
            if pat.search(f):
                n_bak += 1
                try:
                    bak_bytes += os.path.getsize(os.path.join(root, f))
                except OSError:
                    print(f"⚠️ [scripts\self_heal_check.py] 兼容处理: except OSError:", file=sys.stderr)
    if n_bak >= BAK_MAX_COUNT:
        issues.append(".bak* x%d(%.1fMB)" % (n_bak, bak_bytes / 1048576))
    trash = os.path.join(PROJECT, ".trash")
    if os.path.isdir(trash):
        try:
            trash_mb = sum(os.path.getsize(os.path.join(r, f))
                           for r, _, fs in os.walk(trash) for f in fs) / 1048576
        except OSError:
            trash_mb = 0.0
        if trash_mb >= TRASH_MAX_MB:
            issues.append(".trash/ %.1fMB" % trash_mb)
    if issues:
        return False, ("备份/垃圾堆积: %s — 只报告不自动删(内容价值待判, 清理请老大拍板)"
                       % "; ".join(issues))
    return True, ".bak* x%d, .trash 未超阈" % n_bak


# ---------------------------------------------------------------- 门禁阻断持续探测(P-12)
# 阻断/冻结持续 >2 天视为"无人处置"。阈值沿用 self_audit_checkers.py:748
# _DISPATCH_VIOLATION_THRESHOLD_DAYS=2 先例(M-3 连续 2 日违规→P0), 不自创
P12_GATE_BLOCK_MAX_DAYS = 2


def probe_p12_gate_block(gate_path=None, daily_path=None, review_path=None):
    """P-12 门禁阻断持续监控(2026-10-20 补盲, qa-verifier-3 取证): daily 链被
    walk-forward 衰减门禁 + final_verdict 冻结两道红线阻断时, 任务层看不出异常 —
    daily_auto.bat 末行 echo 把退出码重置为 0(schtasks 上次结果恒 0), 且 P-01~P-11
    无一项读门禁状态 -> 阻断多日无人知晓。本探针直读状态文件, 任一命中即 (False, detail):
      1. walk_forward_gate.json blocked=true 且 mtime 年龄 > 2 天(门禁结论陈旧无人重评);
      2. automation_daily.json gate_flag.frozen=true 且 _freeze_YYYYMMDD 起始日至今 > 2 天。
    年龄一律用文件 mtime / 冻结键日期: data/ 被 gitignore, 无历史可比。
    只告警不修复(repair=None): 解冻需总管人工改 data/review_status.json(独占写口),
    自愈不能代做; detail 内附人工处置路径。
    """
    gate_path = gate_path or os.path.join(DATA, "walk_forward_gate.json")
    daily_path = daily_path or os.path.join(DATA, "automation_daily.json")
    review_path = review_path or os.path.join(DATA, "review_status.json")
    now = _dt.datetime.now()
    hits = []
    # 1) 门禁阻断陈旧化: blocked=true 且文件 mtime 年龄 > 2 天
    gate = load_json(gate_path)
    gate_blocked = bool(gate and gate.get("blocked"))
    if gate_blocked:
        try:
            age_d = (now - _dt.datetime.fromtimestamp(
                os.path.getmtime(gate_path))).total_seconds() / 86400.0
        except OSError:
            age_d = None
        if age_d is not None and age_d > P12_GATE_BLOCK_MAX_DAYS:
            hits.append("walk_forward_gate blocked=true 已 %.1f 天(>%d 天)无人重评, 原因: %s" % (
                age_d, P12_GATE_BLOCK_MAX_DAYS,
                gate.get("block_reason") or gate.get("reason") or "未注明"))
    # 2) 冻结持续化: frozen=true 且 _freeze_YYYYMMDD 起始日至今 > 2 天
    daily = load_json(daily_path)
    frozen = bool(daily and (daily.get("gate_flag") or {}).get("frozen"))
    if frozen:
        review = load_json(review_path, {}) or {}
        starts = []
        for k in review:
            m = re.match(r"^_freeze_(\d{8})$", k)
            if m:
                starts.append(_dt.datetime.strptime(m.group(1), "%Y%m%d").date())
        if not starts:
            # fail-loud: 冻结态但起始日不可解析 = 无法证明未超期, 按命中处置(禁留静默盲区)
            hits.append("automation_daily gate_flag.frozen=true 但 review_status.json "
                        "无 _freeze_YYYYMMDD 键, 冻结起始日不可解析, 无法确认阻断时长")
        else:
            start = max(starts)  # 取最新冻结起始日(旧键可能是历史遗留未清)
            days = (now.date() - start).days
            if days > P12_GATE_BLOCK_MAX_DAYS:
                rec = review.get("_freeze_" + start.strftime("%Y%m%d")) or {}
                reason = rec.get("reason", "") if isinstance(rec, dict) else ""
                hits.append("选股冻结已连续 %d 天(起始 %s, >%d 天), 原因: %s" % (
                    days, start.isoformat(), P12_GATE_BLOCK_MAX_DAYS, str(reason)[:80]))
    if hits:
        return False, ("; ".join(hits)
                       + " — 阻断需人工处置: 总管改 data/review_status.json 解除冻结"
                         "(删 _freeze_* 与 final_verdict 键)或重跑 scripts/walk_forward_gate.py "
                         "重评门禁; runbook: docs/runbook-人工单点.md")
    return True, "门禁无持续阻断(blocked=%s, frozen=%s)" % (gate_blocked, frozen)


# ---------------------------------------------------------------- 机器清醒判定矩阵 (t_51e04b30 B案)
# 判据口径(老六会签①②):
#   ① 双源"取最保守值"=OR 语义: 最近输入<30min 或 最近唤醒<15min -> 判清醒
#      (AND=漏报真 P0, 比误报恶劣, 禁止改回; machine_wake_state.guard_semantics 守卫)
#   ② 第5态: stale 时间戳整体落在休眠窗内 + 机器刚醒 -> P-01 复检不得报 P0
#      (否则每次唤醒来一轮误报风暴, 根因没根治)
#   ③ 降级 INFO 是写侧动作 -> 必须登记已知缺口台账 GAP-003(读侧消费方=
#      self_audit 每日健康报告 + P-01 下轮复检, 铁律#12)
#   fail-safe: 双源全不可用/探测异常 = 不可证明休眠 -> P0 照报(保守)
def p01_stale_ts():
    """P-01 drain_state.last_run (ISO 字符串, 本地时区)。缺失/解析失败 -> None。"""
    st = load_json(DRAIN_STATE)
    if not st or not st.get("last_run"):
        return None
    try:
        return _dt.datetime.fromisoformat(st["last_run"]).isoformat()
    except ValueError:
        return None


def p02_stale_ts_list():
    """P-02 注册表任务 last_run (ISO 字符串) 列表; 无记录=None 元素。
    第5态要求"全部 stale ts < last_wake"; 任一 None 无法证明在休眠窗内 -> 该态不命中。"""
    out = []
    now = _dt.datetime.now()
    weekday = now.weekday() < 5
    for task, (_max_age, wd_only) in LIVENESS_TASKS.items():
        if wd_only and not weekday:
            continue
        last_run, _lr, _act, _en = schtasks_info(task)
        out.append(last_run.isoformat() if last_run else None)
    return out


def wake_matrix_verdict(rid, wake, stale_ts):
    """P-01/P-02 P0 升级点判定矩阵。返回 ("p0"|"info", reason)。
    rid: "P-01"|"P-02"; wake: machine_wake_state.probe_wake_state() dict(异常时 None);
    stale_ts: P-01 为 drain last_run ISO 串, P-02 为 p02_stale_ts_list()。"""
    if not wake or not wake.get("available"):
        return "p0", "wake-state 不可用(fail-safe: 不可证明休眠) -> 保守照报 P0"
    lw = wake.get("last_wake")
    if rid == "P-01" and wake.get("just_woken") and lw and stale_ts and stale_ts < lw:
        # 第5态 (老六会签②): 机器刚醒(just_woken 窗) 且 drain 最后一次运行早于最近唤醒
        # = stale 整体在休眠窗内 -> 刚醒后的复检不升 P0。
        # just_woken 限定是防漏报边界: 唤醒已久(>15min)后若 drain 仍 stale, 走①/④ 照报 P0
        return "info", ("第5态: drain last_run(%s) 早于最近唤醒(%s), stale 整体落在休眠窗内, "
                        "刚醒复检不升 P0" % (stale_ts, lw))
    if rid == "P-02" and wake.get("just_woken") and lw and stale_ts and all(t and t < lw for t in stale_ts):
        return "info", ("第5态: P-02 全部 stale 任务 last_run 均早于最近唤醒(%s), 休眠窗内" % lw)
    if wake.get("awake"):
        return "p0", "机器清醒(双源OR: %s) 且 stale -> P0 照报" % "/".join(wake.get("reasons") or [])
    return "info", ("机器休眠(双源未命中: 输入龄=%smin 唤醒龄=%smin) -> 降级 INFO+台账"
                    % (wake.get("input_age_min"), wake.get("wake_age_min")))


def register_gap_g003(rid, reason):
    """铁律#12 写侧登记: 每次 P-01/P-02 降级 INFO 更新 GAP-003 台账
    (last_downgrade/downgrade_count/最近原因); 台账缺失时幂等自举同 schema 条目。"""
    led = load_json(KNOWN_GAPS)
    if not isinstance(led, dict):
        led = {"schema": 1, "gaps": []}
    gaps = led.get("gaps")
    if not isinstance(gaps, list):
        gaps = []
    entry = next((g for g in gaps if g.get("gap_id") == "GAP-003"), None)
    if entry is None:
        entry = {
            "gap_id": "GAP-003",
            "title": "夜间休眠窗 drain/QSP 静默窗口 (StopOnIdleEnd 设计缺口, B案降级项)",
            "first_discovered": "2026-10-17 00:49",
            "severity": "P1-设计缺口 (降级 INFO; 机器清醒时同症状仍 P0)",
            "owner_scope": "self_heal P-01/P-02 检测层 (scripts/machine_wake_state.py 双源感知)",
            "root_cause": "QSP_MsgDrain/QSP_DrainWatch StopOnIdleEnd=true 空闲即停, 机器夜间休眠时探测/投递/看门狗三层同时静默, self_heal 按15min机械判P0产生误报风暴 (10-17 consec_p0=32 全误报)",
            "downgrade_reason": "stale 且 机器休眠(双源均未命中) 或 刚醒且 stale 整体在休眠窗内 -> 按设计静默, 非真断链",
            "evidence": ["docs/drain告警环-空闲静默窗口诊断-20261017.md §二根因定性"],
            "recovery_assertion": {
                "consumer": "self_audit 每日健康报告 + P-01/P-02 下轮 self_heal 复检",
                "cycle": "15min (self_heal 节奏) / 每日 (self_audit)",
                "failure_path": "机器清醒且 drain/QSP 仍 stale -> 判定矩阵照报 P0 (降级窗口不吞真故障)"
            },
            "status": "open",
            "related_doc": "docs/drain告警环-空闲静默窗口诊断-20261017.md §三B",
        }
        gaps.append(entry)
        led["gaps"] = gaps
    entry["last_downgrade"] = now_iso()
    entry["last_downgrade_rule"] = rid
    entry["last_downgrade_reason"] = reason
    entry["downgrade_count"] = int(entry.get("downgrade_count", 0)) + 1
    led["updated_at_cst"] = now_iso()
    if not save_json(KNOWN_GAPS, led):
        log("gap-ledger", "GAP-003 台账写入失败, 降级动作本身已执行(写侧降级+读侧断言仍生效)", "alert")


# ---------------------------------------------------------------- 修复规则
def repair_r01_drain():
    """R-01 drain 停摆: /Run → 60s 复检 → /Enable+/Run → P0"""
    log("repair", "R-01 drain 停摆修复: schtasks /Run QSP_MsgDrain", "repair")
    schtasks_run("QSP_MsgDrain")
    time.sleep(60)
    ok, detail = probe_p01_drain()
    if ok:
        log("repair", "R-01 复检通过: " + detail, "repair")
        return True
    log("repair", "R-01 一轮 /Run 未恢复, 尝试 /Enable + /Run", "repair")
    schtasks_set_state("QSP_MsgDrain", enable=True)
    schtasks_run("QSP_MsgDrain")
    time.sleep(60)
    ok, detail = probe_p01_drain()
    if ok:
        log("repair", "R-01 二轮复检通过: " + detail, "repair")
        return True
    alert("R-01 drain 修复失败(两轮): %s。同步环/告警触达可能失效, "
          "请检查 lark-cli 登录态(runbook 第4章)" % detail, "P0")
    return False


def repair_r02_tasks(detail):
    """R-02 任务异常修复: 仅对 从未运行(非按设计退出)/超窗漏跑/目标缺失 动手;
    按设计退出码(1/2/267009)是探针正常工作, 不修。死任务(目标不存在)-> 禁用(GC-03)"""
    fixed, dead = [], []
    now = _dt.datetime.now()
    weekday = now.weekday() < 5
    for task, (max_age, wd_only) in LIVENESS_TASKS.items():
        if wd_only and not weekday:
            continue
        last_run, last_result, action, enabled = schtasks_info(task)
        missing, target = action_target_missing(action)
        if missing:
            dead.append("%s(目标缺失 %s)" % (task, target))
            continue
        need_run, why = False, ""
        if last_run is None:
            if last_result not in BY_DESIGN_EXITS:
                need_run, why = True, "从未运行"
        elif (now - last_run).total_seconds() / 60.0 > max_age:
            need_run, why = True, "超窗漏跑(龄 %.0fmin > %dmin)" % (
                (now - last_run).total_seconds() / 60.0, max_age)
        if need_run:
            log("repair", "R-02 %s: %s → schtasks /Run" % (task, why), "repair")
            if schtasks_run(task):
                fixed.append(task)
    # 死任务族: 启用态+目标缺失 -> 禁用(GC-03)
    for task in DEAD_TASK_FAMILY:
        last_run, last_result, action, enabled = schtasks_info(task)
        if enabled and "禁用" not in (enabled or ""):
            missing, target = action_target_missing(action)
            if missing or last_result not in (0, "0", None):
                log("repair", "GC-03 死任务 %s(目标 %s 缺失, result=%s) 处于启用态 → 禁用"
                    % (task, target, last_result), "repair")
                if schtasks_set_state(task, enable=False):
                    dead.append("%s(已禁用)" % task)
    if dead:
        alert_once("R02-dead", "R-02/GC-03 死任务处置: %s。这些任务目标脚本不存在(曾每5min空跑报错无人知), "
                   "已禁用; 是否重建或删除请老大拍板" % "; ".join(dead), "P1")
    return len(fixed) > 0 or len(dead) > 0


def repair_r03_sync(detail):
    """R-03 同步环漏跑/远程落后: /Run QSP_GitSync"""
    log("repair", "R-03 同步环异常(%s): schtasks /Run QSP_GitSync" % detail, "repair")
    ok = schtasks_run("QSP_GitSync")
    if ok:
        log("repair", "R-03 已触发 QSP_GitSync, 结果以下一轮探测为准", "repair")
    else:
        alert("R-03 QSP_GitSync 触发失败: %s" % detail, "P1")
    return ok


def repair_r04_remote(detail):
    """R-04 远程灾备: 独立修复 + >=6h 冷却。

    2026-10-19(老六): 原 P-04 直接复用 repair_r03_sync(无冷却), 而 P-03 与 P-04
    同时红时一轮 self-heal 会触发 2 次 schtasks /Run QSP_GitSync; 叠加 15min 周期
    → 实测单日触发 47 次、连续 36 轮 P0。每次触发都跑一遍 pytest 门禁, 在门禁
    自递归期间(单轮 539s)直接放大成进程风暴。故拆出独立 repair 并加冷却。
    """
    COOLDOWN_H = 6
    st = load_json(REPAIR_STATE_FILE, {}) or {}
    last = st.get("R-04")
    if last:
        try:
            age_h = (_dt.datetime.now() - _dt.datetime.fromisoformat(last)).total_seconds() / 3600.0
        except Exception:
            age_h = None
        if age_h is not None and age_h < COOLDOWN_H:
            log("repair", "R-04 冷却中(上次 %.1fh 前 < %dh): 跳过触发 — %s"
                % (age_h, COOLDOWN_H, detail), "repair")
            return False
    log("repair", "R-04 远程灾备异常(%s): schtasks /Run QSP_GitSync" % detail, "repair")
    ok = schtasks_run("QSP_GitSync")
    if ok:
        st["R-04"] = now_iso()
        save_json(REPAIR_STATE_FILE, st)
        log("repair", "R-04 已触发 QSP_GitSync(下次触发需间隔 %dh)" % COOLDOWN_H, "repair")
    else:
        alert("R-04 QSP_GitSync 触发失败: %s" % detail, "P1")
    return ok


def repair_r06_hygiene(detail):
    """R-06 卫生清理: 日志轮转 + pycache/.coverage"""
    acted = False
    for f in glob.glob(os.path.join(DATA, "*.log")):
        try:
            if os.path.getsize(f) > LOG_MAX_BYTES:
                lines = open(f, encoding="utf-8", errors="replace").readlines()
                keep = lines[-LOG_KEEP_LINES:]
                bak = f + ".1"
                os.replace(f, bak) if not os.path.exists(bak) else None
                with open(f, "w", encoding="utf-8") as w:
                    w.writelines(keep)
                log("repair", "R-06 日志轮转 %s: %d行→%d行" % (os.path.basename(f), len(lines), len(keep)), "repair")
                acted = True
        except Exception as e:
            log("repair", "R-06 轮转 %s 失败: %s" % (f, e), "alert")
    n = 0
    for d in glob.glob(os.path.join(PROJECT, "**", "__pycache__"), recursive=True):
        try:
            subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", d], capture_output=True,
                           timeout=30, creationflags=CREATE_NO_WINDOW)
            n += 1
        except Exception:
            print(f"🔴 [scripts\self_heal_check.py] CR-01: except Exception:", file=sys.stderr)
    cov = os.path.join(PROJECT, ".coverage")
    if os.path.exists(cov):
        try:
            os.remove(cov)
            n += 1
        except OSError:
            print(f"⚠️ [scripts\self_heal_check.py] 兼容处理: except OSError:", file=sys.stderr)
    if n:
        log("repair", "R-06 清理构建产物 x%d" % n, "repair")
        acted = True
    return acted


# ---------------------------------------------------------------- 主流程
def validate_alert_paths():
    """P-11 卫生探针：校验 ALERT_REF_PATHS 中每条路径必须 os.path.exists。

    违反 → alert P1（写 message_queue.json，规则 11 唯一出口）。
    本函数不调用 subprocess，直接检查列表，避免正则误匹配。
    """
    broken = []
    for p in ALERT_REF_PATHS:
        full = os.path.join(PROJECT, p)
        if not os.path.exists(full):
            broken.append(p)
    if broken:
        alert("P-11 告警路径断裂: %s（%d 个路径不存在）" % (", ".join(broken), len(broken)), "P1")
    else:
        log("P-11", "告警路径卫生检查通过（%d 条路径全部存在）" % len(ALERT_REF_PATHS), "audit")


def main():
    global DRY_RUN
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只探测不修复")
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    print("===== self-heal run %s%s =====" % (now_iso(), " [DRY-RUN]" if DRY_RUN else ""))
    validate_alert_paths()  # P-11 卫生探针：告警路径存在性断言
    results = {}
    repairs = 0
    p0 = False

    rules = [
        ("P-01", "告警投递链活性", probe_p01_drain, lambda d: repair_r01_drain()),
        ("P-02", "任务级活性", probe_p02_task_liveness, lambda d: repair_r02_tasks(d)),
        ("P-03", "同步环活性", probe_p03_gitsync, lambda d: repair_r03_sync(d)),
        ("P-04", "远程灾备新鲜度", probe_p04_remote, lambda d: repair_r04_remote(d)),
        ("P-05", "飞书接口活性", probe_p05_feishu_api, None),
        ("P-06", "webhook通道", probe_p06_webhook, None),
        ("P-07", "卫生", probe_p07_hygiene, lambda d: repair_r06_hygiene(d)),
        ("P-08", "配置死模式", probe_p08_config_dead, None),
        ("P-09", "外部数据源", probe_p09_datasrc, None),
        ("P-10", "死部署副本", probe_p10_dead_deploy, None),
        ("P-11", "备份/垃圾堆积", probe_p11_backup_bloat, None),
        ("P-12", "门禁阻断持续监控", probe_p12_gate_block, None),
    ]

    for rid, name, probe, repair in rules:
        try:
            ok, detail = probe()
        except Exception as e:
            ok, detail = False, "探测异常: %s" % str(e)[:100]
        results[rid] = {"name": name, "ok": ok, "detail": detail}
        if ok:
            print("  ✅ %s %s: %s" % (rid, name, detail))
            continue
        print("  ❌ %s %s: %s" % (rid, name, detail))
        # 分级: P-01/P-02/P-03/P-04 有修复; P-05/P-06/P-08/P-09 只告警
        if repair is not None:
            if DRY_RUN:
                log("repair-dry", "%s 将执行修复: %s" % (rid, detail), "repair")
                continue
            try:
                if repair(detail):
                    repairs += 1
            except Exception as e:
                log("repair", "%s 修复异常: %s" % (rid, e), "alert")
        else:
            sev = "P2" if rid in ("P-09", "P-10", "P-11") else "P1"
            alert_once(rid, "%s %s 异常: %s" % (rid, name, detail), sev)

    state = load_json(STATE_FILE, {}) or {}
    state.update({"last_run": now_iso(), "dry_run": DRY_RUN, "results": results,
                  "repairs_this_run": repairs,
                  "consec_p0": state.get("consec_p0", 0)})
    # P0 判定: P-01/P-02/P-03/P-04 修复后仍异常
    still_bad = [r for r in ("P-01", "P-02", "P-03", "P-04")
                 if not results.get(r, {}).get("ok")]
    if still_bad and not DRY_RUN and repairs > 0:
        # /Run 是异步的, 立即复检会假阳性; 等 45s 让任务落地再复检
        print("[recheck] 本轮有修复动作, 等待 45s 后复检...")
        time.sleep(45)
    if still_bad and not DRY_RUN:
        # 复检一次确认(修复可能已生效)
        recheck = {}
        for rid in still_bad:
            try:
                # r[2] 才是 probe 函数; 误取 r[1](规则名)会 TypeError 被下方 except 吞成"复检从未跑"
                ok2, d2 = dict((r[0], r[2]) for r in rules)[rid]()
                recheck[rid] = {"ok": ok2, "detail": d2}
                results[rid]["recheck"] = recheck[rid]
            except Exception as e:
                # 只改可见性不改控制流: 带类型与摘要, 防再次静默吞异常
                print(f"🔴 [scripts\\self_heal_check.py] CR-01(recheck): {type(e).__name__}: {e}",
                      file=sys.stderr)
        still_bad = [r for r in still_bad if not recheck.get(r, {}).get("ok")]
    if still_bad and not DRY_RUN:
        # t_51e04b30 B案: P-01/P-02 挂机器清醒判定矩阵 — 休眠窗降级 INFO+台账 GAP-003,
        # 清醒照报 P0; 双源全不可用 fail-safe 保守照报。P-03/P-04 不在降级域(口径不变)。
        try:
            wake = machine_wake_state.probe_wake_state()
        except Exception as e:
            wake = None
            log("wake-state", "双源探测异常: %s -> fail-safe 保守照报 P0" % e, "alert")
        for rid in list(still_bad):
            if rid not in ("P-01", "P-02"):
                continue
            stale_ts = p01_stale_ts() if rid == "P-01" else p02_stale_ts_list()
            verdict, reason = wake_matrix_verdict(rid, wake, stale_ts)
            if verdict == "p0":
                log("wake-matrix", "%s 仍 P0 升级: %s" % (rid, reason), "info")
                continue
            still_bad.remove(rid)
            results[rid]["downgraded"] = {"gap": "GAP-003", "reason": reason, "ts": now_iso()}
            log("P-0x-downgrade", "%s 降级 INFO: %s (台账 GAP-003; 复检断言=self_audit 日报+下轮复检)"
                % (rid, reason), "info")
            register_gap_g003(rid, reason)
    if still_bad:
        p0 = True
        state["consec_p0"] = int(state.get("consec_p0", 0)) + 1
        cp0 = state["consec_p0"]
        # P0 节流: 前2轮必发, 之后每4轮(≈1h@15min节奏)重发一次
        if cp0 <= 2 or cp0 % 4 == 0:
            alert("核心链路修复后仍异常: %s(连续第%d轮)。请立即人工介入, "
                  "runbook: docs/runbook-人工单点.md" % (", ".join(still_bad), cp0), "P0")
        else:
            log("alert-P0-throttled", "核心链路仍异常(第%d轮), 节流不重发" % cp0, "alert")
    else:
        state["consec_p0"] = 0
    save_json(STATE_FILE, state)

    print("===== done: repairs=%d p0=%s =====" % (repairs, p0))
    return 2 if p0 else (1 if repairs else 0)


if __name__ == "__main__":
    sys.exit(main())
