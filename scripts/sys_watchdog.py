# -*- coding: utf-8 -*-
"""sys_watchdog.py — 选股系统主动自愈看门狗 (2026-10-15 总管, 自主运维闭环)

定位: 把 Hermes 从"被动响应"翻成"主动闭环"。每 15min 由计划任务 QSP_SysWatchdog 执行:
  P1 活性层: 网关 api_server 端口 / 告警 drain 活性 / QSP 计划任务健康
  P2 数据层: TDX 日线新鲜度 / 因子缓存 / kanban 僵尸 worker
  P3 接口层: 飞书 bot 凭据 / GitHub CI 最新状态(PAT) / 双远程可达
  P4 日志层: 网关/agent 日志今日新错误签名(基线台账 data/watchdog_seen_errors.json)
  P5 配置层: risk_rules 哈希==git HEAD(红线) / omt_* 占位符回潮 / weixin.enabled
自愈白名单(仅幂等+可回滚动作自动执行, 其余只告警+给修复命令):
  R1 drain 停摆>=30min → schtasks /run QSP_MsgDrain (每轮最多1次, 记 repair 日志)
告警出口: 一律 data/message_queue.json (T2 唯一出口) + data/alert_log.jsonl 本地台账
meta 监督: drain_meta_check.py 同时盯 drain_state + watchdog_state 双环活性
退出码: 0=正常(含已告警), 1=自身崩溃(meta 将升级 P0)
"""
import json
import os
import re
import socket
import struct
import subprocess
import sys
import hashlib

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
import datetime as dt

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HH = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
DATA = os.path.join(PROJECT, "data")
REPORT = os.path.join(DATA, "watchdog_report.json")
STATE = os.path.join(DATA, "watchdog_state.json")
SEEN = os.path.join(DATA, "watchdog_seen_errors.json")
REPAIR_LOG = os.path.join(DATA, "watchdog_repairs.jsonl")
ALERT_LOG = os.path.join(DATA, "alert_log.jsonl")
QUEUE = os.path.join(DATA, "message_queue.json")
DRAIN_STATE = os.path.join(DATA, "drain_state.json")

TDX_SAMPLE = r"D:\TDX\vipdoc\sh\lday\sh600519.day"
KANBAN_MAIN = os.path.join(HH, "kanban.db")
GATEWAY_PORT = 8642
QSP_TASKS = ["QSP_GitSync", "QSP_DrainWatch", "QSP_MsgDrain", "QSP_RemoteFreshness",
             "QSP_SelfHeal", "QSP_LoopWatch", "QSP_SysWatchdog", "QSP_ConfigGC"]
# T7 双源整合(2026-10-15 总管): 修复权威 = QSP_SelfHeal(老六引擎, 11规则+93测试+repair_log留痕),
# 本引擎定位 = 数据/配置层独占探测(C4/C5/C9/C10) + 全层只读复核; 不自执行修复动作(防双修冲突)
AUTO_REPAIR_ENABLED = False
# 队列告警范围: 仅本引擎独占检查项入队; 与 SelfHeal P-01~P-06 重叠项只写报告不告警(防双报刷屏)
ALERT_UNIQUE_CHECKS = {"C4_tdx_freshness", "C5_kanban_zombie_worker",
                      "C9_log_new_signatures", "C10_config_drift"}


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def is_trading_aware_days_since(date_int):
    """粗判: 周末/节假日容忍度用日历天近似(长假最多连3休息日, 用300ms内判定不阻塞)"""
    d = dt.datetime(date_int // 10000, (date_int // 100) % 100, date_int % 100)
    return (dt.datetime.now() - d).days


# ---------- P1 活性层 ----------
def check_gateway():
    c = {"check": "C1_gateway_api_server", "level": "P0"}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("127.0.0.1", GATEWAY_PORT))
        s.close()
        c.update(status="ok", evidence="TCP 127.0.0.1:%d 可达" % GATEWAY_PORT)
    except Exception as e:
        c.update(status="fail", evidence="网关 api_server 端口不可达: %s (网关挂=全系统瘫)" % e)
    return c


def check_drain():
    c = {"check": "C2_msgdrain_liveness", "level": "P0"}
    st = load_json(DRAIN_STATE)
    if not st or not st.get("last_run"):
        c.update(status="fail", evidence="drain_state.json 缺失 — 告警投递环从未跑")
        return c
    age = (dt.datetime.now() - dt.datetime.fromisoformat(st["last_run"])).total_seconds() / 60.0
    c["evidence"] = "drain last_run 龄 %.0fmin" % age
    if age < 15:
        c["status"] = "ok"
    elif age < 30:
        c["status"] = "warn"
    else:
        c["status"] = "fail"
        c["auto_repair"] = "R1_run_msgdrain"
    return c


def _decode_schtasks(raw):
    """schtasks 输出为 UTF-16LE (可能带BOM), 交互环境是 GBK — 两种都试"""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in raw[:40]:
        return raw.decode("utf-16", errors="replace")
    return raw.decode("gbk", errors="replace")


def check_scheduled_tasks():
    c = {"check": "C3_qsp_schtasks", "level": "P1"}
    bad = []
    for name in QSP_TASKS:
        try:
            out = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "list"],
                                 capture_output=True, timeout=30,
                                 creationflags=CREATE_NO_WINDOW).stdout
            txt = _decode_schtasks(out)
            low = txt.lower()
            if "does not exist" in low or "不存在" in txt or "系统找不到" in txt:
                bad.append("%s=任务不存在" % name)
            elif "Disabled" in txt:
                bad.append("%s=Disabled" % name)
            elif "Ready" in txt or "就绪" in txt:
                pass  # 正常
            else:
                bad.append("%s=状态无法解析" % name)
        except Exception as e:
            bad.append("%s=查询异常:%s" % (name, e))
    if bad:
        c.update(status="warn" if len(bad) == 1 else "fail", evidence="; ".join(bad))
        c["fix_hint"] = "schtasks /create 或 /enable 对应 QSP 任务(见 runbook)"
    else:
        c.update(status="ok", evidence="%d 个 QSP 任务均 Ready/存在" % len(QSP_TASKS))
    return c


# ---------- P2 数据层 ----------
def check_tdx():
    c = {"check": "C4_tdx_freshness", "level": "P1"}
    if not os.path.exists(TDX_SAMPLE):
        c.update(status="fail", evidence="TDX 样本文件缺失 %s (TDX_ROOT 未恢复?)" % TDX_SAMPLE)
        return c
    with open(TDX_SAMPLE, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        n = size // 32
        if n == 0:
            c.update(status="fail", evidence="TDX 文件 0 记录")
            return c
        f.seek((n - 1) * 32)
        # P0修复2026-10-18: 第6字段成交额是 float32(此处只用 vals[0], 但保留正确结构防误用)
        vals = struct.unpack("<IIIIIfII", f.read(32))
        date_int = vals[0]
    days = is_trading_aware_days_since(date_int)
    c["evidence"] = "sh600519 末记录=%d (%d天前)" % (date_int, days)
    if days <= 5:
        c["status"] = "ok"
    elif days <= 10:
        c["status"] = "warn"
        c["fix_hint"] = "检查 TDX 客户端更新链; 恢复: 见 tdx-data-restore 技能"
    else:
        c["status"] = "fail"
        c["fix_hint"] = "P0 数据层: TDX 数据停更>10天, 回测/选股全失真; 走 tdx-data-restore 技能"
    return c


# ---------------------------------------------------------------- C5 根因修复 (OPS-2 2026-10-17)
# 一手证据 (kanban.db 实读 2026-10-17): last_heartbeat_at 为 **epoch 秒** (如 1792203265),
# worker_started_at 为 '|' 前缀毫秒串 (如 '|179220252129'); 旧代码一律按毫秒 /1000 解析
# → 1970 基线 → 心跳龄 29840130min(57年) 误报 (审计单称 "null/epoch 0", 实为秒/毫秒单位错位)。
# 修复: 单位自动判别 + shape 宽容; 脏值阈值与 cron_message_sender 层4 对齐 (10080min)。
HB_DIRTY_MAX_MIN = 7 * 24 * 60   # 10080: 心跳龄 >7 天判脏值 (与 drain 层4 验收判据对齐)
HB_MS_THRESHOLD = 1e12          # ≥1e12 视为毫秒(毫秒纪年2001年后才可能≥1e12, 之前无歧义)


def _hb_parse_ts(ts):
    """kanban 心跳/启动时间戳 → 本地 naive datetime; 缺失/epoch-0/不可解析 → None。
    宽容 shape: epoch秒 / epoch毫秒 / '|'-前缀毫秒串 / ISO 文本; 0/'0'/0.0 一律视为 epoch-0。"""
    if ts is None:
        return None
    try:
        if isinstance(ts, str):
            s = ts.strip().lstrip("|").strip()
            if not s:
                return None
            if s.lstrip("-").isdigit():
                ts = int(s)
            else:
                return dt.datetime.fromisoformat(s.replace("Z", ""))
        v = float(ts)
        if v <= 0:
            return None
        v = v / 1000.0 if v >= HB_MS_THRESHOLD else v
        return dt.datetime.fromtimestamp(v)
    except Exception as e:
        print(f"🔴 [sys_watchdog.py:196] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return None


def check_kanban_zombie(db_path=KANBAN_MAIN):
    """C5 kanban 僵尸 worker: last_heartbeat_at 为唯一活性信号 (worker_started_at 仅佐证,
    其 shape 不稳 — '|'前缀/ISO/秒/毫秒 — 参与判龄曾致 57 年天文误报, 不再参与)。
    判据 (OPS-2 2026-10-17):
      hb 缺失/epoch-0/不可解析 → P0「心跳缺失(epoch)」loud 输出 (真因=心跳写链断或DB缺省值, 非真僵尸)
      hb 龄 >7 天 (10080min)   → P0「心跳脏值」(与 drain 层4 对齐, 不再输出天文年龄)
      45min < hb 龄 ≤ 7 天     → P1 stale (真僵尸, dispatcher 自动 reap)"""
    c = {"check": "C5_kanban_zombie_worker", "level": "P1"}
    try:
        import sqlite3
        con = sqlite3.connect(db_path, timeout=8)
        con.execute("PRAGMA busy_timeout=8000")
        cur = con.cursor()
        cur.execute("SELECT id, assignee, last_heartbeat_at, worker_started_at FROM tasks WHERE status='running'")
        rows = cur.fetchall()
        con.close()
    except Exception as e:
        c.update(status="warn", evidence="主 kanban.db 不可读(锁竞争): %s" % e)
        return c
    if not rows:
        c.update(status="ok", evidence="无 running 任务")
        return c
    epoch_missing, dirty, stale = [], [], []
    for tid, who, hb, started in rows:
        hb_dt = _hb_parse_ts(hb)
        if hb_dt is None:
            note = ""
            st_dt = _hb_parse_ts(started)
            if st_dt is not None:
                note = " started龄%.0fmin" % ((dt.datetime.now() - st_dt).total_seconds() / 60.0)
            epoch_missing.append("%s(%s) 心跳缺失(epoch) hb=%r%s" % (tid, who, hb, note))
            continue
        age_min = (dt.datetime.now() - hb_dt).total_seconds() / 60.0
        if age_min > HB_DIRTY_MAX_MIN:
            dirty.append("%s(%s) 心跳脏值(hb=%r 龄>10080min)" % (tid, who, hb))
        elif age_min > 45:
            stale.append("%s(%s) 心跳龄%.0fmin" % (tid, who, age_min))
    if epoch_missing:
        print("🔴 [scripts\\sys_watchdog.py] C5 P0 心跳缺失(epoch): " + "; ".join(epoch_missing), file=sys.stderr)
    if dirty:
        print("🔴 [scripts\\sys_watchdog.py] C5 P0 心跳脏值(>10080min): " + "; ".join(dirty), file=sys.stderr)
    if epoch_missing or dirty:
        c["level"] = "P0"
        c.update(status="fail",
                 evidence="心跳缺失(epoch)/脏值 %d 项: %s" % (len(epoch_missing) + len(dirty), "; ".join((epoch_missing + dirty)[:4])),
                 fix_hint="epoch-0/null/1970基线 = 心跳写链断或单位/shape异常(非真断链): 查 dispatcher 心跳写入 + last_heartbeat_at 列单位; 脏值>7天与 drain 层4(10080min)对齐, 不再输出天文年龄")
    elif stale:
        c.update(status="fail", evidence="; ".join(stale),
                 fix_hint="dispatcher 会自动 reap 僵尸 pid; 若连续3轮仍 stale 手动查 worker 日志 kanban/logs/ (R2 仅告警, 不自动杀)")
    else:
        c.update(status="ok", evidence="%d 个 running 任务心跳新鲜" % len(rows))
    return c


# ---------- P3 接口层 ----------
def check_feishu_creds():
    c = {"check": "C6_feishu_bot_token", "level": "P0"}
    cred = load_json(os.path.join(PROJECT, "config", "feishu_fallback_app.json"))
    if not cred:
        c.update(status="fail", evidence="config/feishu_fallback_app.json 缺失 — 告警通道凭据丢失")
        return c
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=json.dumps({"app_id": cred["app_id"], "app_secret": cred["app_secret"]}).encode(),
            headers={"Content-Type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if d.get("code") == 0:
            c.update(status="ok", evidence="default 应用 tenant token 获取成功")
        else:
            c.update(status="fail", evidence="token 接口返回 code=%s %s — 告警通道全断" % (d.get("code"), d.get("msg")))
    except Exception as e:
        c.update(status="fail", evidence="飞书 token 接口异常: %s (网络断或凭据失效)" % e)
    return c


def check_github_ci():
    c = {"check": "C7_github_ci", "level": "P2"}
    envp = os.path.join(HH, ".env")
    pat = None
    if os.path.exists(envp):
        for line in open(envp, encoding="utf-8"):
            if line.startswith("GH_PAT_ZHUANQIAN="):
                pat = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    if not pat:
        c.update(status="warn", evidence="GH_PAT_ZHUANQIAN 不在 HH/.env — CI 核验降级跳过(PAT 未配置)")
        return c
    try:
        import urllib.request
        r = urllib.request.Request(
            "https://api.github.com/repos/yzk1980520/zhuanqian/actions/runs?per_page=1",
            headers={"Authorization": "Bearer " + pat, "Accept": "application/vnd.github+json",
                     "User-Agent": "qsp-watchdog"})
        d = json.loads(urllib.request.urlopen(r, timeout=15).read())
        runs = d.get("workflow_runs", [])
        if not runs:
            c.update(status="warn", evidence="GitHub 无 CI run(仓库未启 Actions?)")
        else:
            run = runs[0]
            c["evidence"] = "CI #%s %s/%s @%s" % (run["run_number"], run["status"], run["conclusion"], run["updated_at"])
            c["status"] = "fail" if (run["conclusion"] == "failure") else "ok"
            if c["status"] == "fail":
                c["fix_hint"] = "CI 红: 看 actions 日志定位(常见=新代码依赖未入库); PAT 可查 https://github.com/yzk1980520/zhuanqian/actions"
    except Exception as e:
        c.update(status="warn", evidence="CI 查询异常(PAT 失效或网络): %s" % e)
    return c


def check_remotes():
    c = {"check": "C8_remotes_reachable", "level": "P1"}
    bad = []
    for name in ("gitcode", "origin"):
        try:
            subprocess.run(["git", "-C", PROJECT, "ls-remote", "--exit-code", "--heads", name, "main"],
                           capture_output=True, timeout=45,
                           creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            bad.append("%s=超时" % name)
        except Exception as e:
            bad.append("%s=%s" % (name, e))
    if bad:
        c.update(status="fail", evidence="; ".join(bad),
                 fix_hint="远程不可达: 双远程同步+CI 核验全盲; 查网络/PAT/SSH key")
    else:
        c.update(status="ok", evidence="gitcode+origin ls-remote 均通")
    return c


# ---------- P4 日志层 ----------
# C9 签名归一化 + 台账自愈 (t_f630eb92, 2026-10-26 R1 告警层, 老三):
# 根因 = 旧签名取"原始日志行截断120字符"(含时间戳/conn_id/PID/会话id) → 同类错误每次
# 出现都误判"新签名"(每日 P1 风暴: Lark WS ~04:55 断连, AGNES 429); 台账 append-only
# 不去重不封顶 → 重复行+无界增长。
# 归一化 5 规则(固定顺序): ①剥行首时间戳 YYYY-MM-DD HH:MM:SS[,mmm] ②[conn_id=...]→[conn_id=*]
# ③(PID \d+)→(PID *) ④[20261025_014437_93240b]→[sess_id] ⑤归一化后再截断120字符
# (幂等; 台账存量原始行加载时经同规则迁移, 旧台账条目不会因格式变化而全量"重新变新")。
# 台账自愈: 加载时去重(保首次出现顺序)+封顶 LEDGER_CAP(裁最旧=裁前部)+原子写(tmp+replace);
# 格式保持 append-only JSON 字符串数组。
RE_C9_TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d{3})?\s*")
# t_df0af4fa P1-1: 日期前缀判定 — 命中=带日期行(历史块重置/今日 commit-line 冲刷),
# 未命中=裸续行(Traceback/堆栈/缩进文本)走 continuation 语义(保挂起签名, 不重置不冲刷)。
RE_C9_DATED_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}")
RE_C9_CONN_ID = re.compile(r"\[conn_id=[^\]]*\]?")
RE_C9_PID = re.compile(r"\(PID \d+\)")
RE_C9_SESSID = re.compile(r"\[\d{8}_\d{6}_[0-9a-fA-F]+\]")
LEDGER_CAP = 500  # 台账封顶: 超出裁最旧(前部); 去重后条目数为准


def normalize_error_line(line):
    """C9 签名归一化(纯函数, 无 I/O, 幂等): 同类错误行折叠为同一签名。"""
    s = line.strip()
    s = RE_C9_TS_PREFIX.sub("", s)
    s = RE_C9_CONN_ID.sub("[conn_id=*]", s)
    s = RE_C9_PID.sub("(PID *)", s)
    s = RE_C9_SESSID.sub("[sess_id]", s)
    return s[:120]


def _heal_ledger_entries(raw):
    """台账自愈: 存量原始签名归一化迁移 + 去重(保序) + 封顶 LEDGER_CAP(裁前部)。
    非 list 输入(缺失/损坏) → []; 非字符串垃圾条目丢弃且 loud 报出(禁静默)。"""
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    junk = 0
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            junk += 1
            continue
        sig = normalize_error_line(entry)
        if sig not in seen:
            seen.add(sig)
            out.append(sig)
    if junk:
        print("🔴 [sys_watchdog.C9] 台账含 %d 条非字符串/空条目, 已丢弃(loud 不静默)" % junk, file=sys.stderr)
    return out[-LEDGER_CAP:]


def _atomic_write_json(path, obj):
    """原子写(tmp+os.replace): 优先复用仓根 atomic_json.atomic_dump(含 fsync);
    import 失败回落手工实现 + loud。绝不留下半写台账 (P0 纪律)。"""
    if PROJECT not in sys.path:
        sys.path.insert(0, PROJECT)
    try:
        from atomic_json import atomic_dump
        atomic_dump(obj, path)
        return
    except ImportError as e:
        print("🔴 [sys_watchdog._atomic_write_json] atomic_json 不可用(%s) → 手工 tmp+os.replace(loud)" % e,
              file=sys.stderr)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_seen_ledger(path=None):
    """加载基线台账 + 自愈(去重/封顶/归一化迁移); 脏时原子回写。返回清洗后 list。"""
    p = path if path is not None else SEEN
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        moved = p + ".corrupt_%s" % dt.datetime.now().strftime("%Y%m%d%H%M%S")
        try:
            os.replace(p, moved)
            print("🔴 [sys_watchdog.C9] 台账读取失败(%s) → 已移至 %s 重建新台账(保留证据)" % (e, moved),
                  file=sys.stderr)
        except OSError:
            print("🔴 [sys_watchdog.C9] 台账读取失败(%s) 且移存失败, 直接重建新台账(原文件保留)" % e,
                  file=sys.stderr)
        return []
    healed = _heal_ledger_entries(raw)
    if isinstance(raw, list):
        if healed != raw:
            _atomic_write_json(p, healed)
    else:
        print("🔴 [sys_watchdog.C9] 台账非 JSON 数组(type=%s) → 空台账起步, 原文件保留作证据"
              % type(raw).__name__, file=sys.stderr)
    return healed


def save_seen_ledger(entries, path=None):
    """台账写入 = 自愈规则(去重/封顶/归一化) + 原子写。返回落盘后的清洗 list。"""
    p = path if path is not None else SEEN
    cleaned = _heal_ledger_entries(entries)
    _atomic_write_json(p, cleaned)
    return cleaned


def check_log_errors(log_paths=None, seen_path=None):
    """C9 日志新错误签名: 仅扫描今日行; 签名经 5 规则归一化(同类错误折叠);
    log_paths/seen_path 缺省=生产路径(HH logs + SEEN), 测试可注入 tmp 路径。
    t_f630eb92: 双日志文件共享同一 seen 集(跨文件同错只记 1 条, 消重) +
    文件尾 EOF 挂起签名冲刷(文件末行是 ERROR 且无后续提交行时, 旧码签名永不入台账 → 每轮再报新)。
    t_df0af4fa P1-1: 裸续行(无日期前缀 Traceback/堆栈/缩进文本)continuation 语义 —
    不重置也不冲刷挂起签名; 只有 带日期行(非今日=历史块重置, 今日=commit-line 冲刷) 与 EOF 能终结挂起签名。"""
    c = {"check": "C9_log_new_signatures", "level": "P1"}
    logs = log_paths if log_paths is not None else (os.path.join(HH, "logs", "gateway.log"),
                                                    os.path.join(HH, "logs", "agent.log"))
    today = dt.date.today().isoformat()
    new_sigs, scanned = [], 0
    seen = set(load_seen_ledger(seen_path))
    for logf in logs:
        if not os.path.exists(logf):
            continue
        cur_sig = None
        with open(logf, encoding="utf-8", errors="replace") as f:
            for line in f:
                if RE_C9_DATED_LINE.match(line):
                    if not line.startswith(today):
                        # ① 带日期且非今日: 历史块重置(旧行为保留)
                        cur_sig = None
                        continue
                    scanned += 1
                    if "ERROR" in line or "FATAL" in line:
                        cur_sig = normalize_error_line(line)
                    elif cur_sig and line.strip().startswith("Traceback"):
                        cur_sig = (cur_sig + " | " + normalize_error_line(line)[:80])[:200]
                    elif cur_sig and line.strip() and not line.startswith(" "):
                        if cur_sig not in seen:
                            new_sigs.append(cur_sig)
                            seen.add(cur_sig)
                        cur_sig = None
                else:
                    # ② 无日期前缀行 = 裸续行(Traceback/堆栈/缩进文本): continuation 语义 —
                    # 保 cur_sig 不重置也不冲刷; 只有 ③今日日期行(commit-line) 与 ④EOF 能终结挂起签名。
                    # (t_df0af4fa P1-1: 旧码把裸续行当"非今日行"重置 → 带堆栈签名静默丢失, EOF 冲刷失效)
                    continue
        if cur_sig and cur_sig not in seen:
            new_sigs.append(cur_sig)
            seen.add(cur_sig)
    if scanned == 0:
        c.update(status="ok", evidence="今日无日志行(新的一天正常)")
        return c
    if new_sigs:
        base = load_seen_ledger(seen_path)  # 写前重载最新台账(避免覆盖他进程新写条目)
        save_seen_ledger(base + new_sigs, seen_path)
        c.update(status="fail", evidence="新错误签名 %d 个: %s" % (len(new_sigs), new_sigs[:2]),
                 fix_hint="新签名=未见过故障: 总管/老三按签名回查日志上下文(首条24h内人工定性, 定性后自动入基线)")
    else:
        c.update(status="ok", evidence="今日日志 %d 行, 无新错误签名" % scanned)
    return c


# ---------- P5 配置层 ----------
def check_config_drift():
    c = {"check": "C10_config_drift", "level": "P0"}
    issues = []
    # 1) risk_rules.py 工作区 == git HEAD (红线只读文件)
    try:
        head_hash = subprocess.run(["git", "-C", PROJECT, "rev-parse", "HEAD:risk_rules.py"],
                                   capture_output=True, timeout=20,
                                   creationflags=CREATE_NO_WINDOW).stdout.decode().strip()
        blob = subprocess.run(["git", "-C", PROJECT, "hash-object", os.path.join(PROJECT, "risk_rules.py")],
                              capture_output=True, timeout=20,
                              creationflags=CREATE_NO_WINDOW).stdout.decode().strip()
        if head_hash and blob and head_hash != blob:
            issues.append("risk_rules.py 工作区!=git HEAD (红线只读文件被改! blob %s vs %s)" % (blob[:8], head_hash[:8]))
    except Exception as e:
        issues.append("risk_rules 哈希比对异常: %s" % e)
    # 2) omt_* 假 thread 占位符回潮 (纯Python扫描, 不依赖 shell grep)
    omt_hits = []
    cfgs = [os.path.join(HH, "config.yaml")] + [
        os.path.join(HH, "profiles", d, "config.yaml") for d in sorted(os.listdir(os.path.join(HH, "profiles")))
        if os.path.isdir(os.path.join(HH, "profiles", d))]
    for p in cfgs:
        if not os.path.isfile(p):
            continue
        for i, line in enumerate(open(p, encoding="utf-8", errors="replace"), 1):
            s = line.strip()
            if s.startswith("#"):
                continue  # 整行注释不提占位符
            code_part = s.split("#")[0]  # 尾注释不算值(T5清理记录注释含 omt_ 字样, 防误报)
            if "omt_" in code_part and "_channel" in code_part:
                omt_hits.append("%s:%d" % (os.path.basename(os.path.dirname(p)) if p != os.path.join(HH, "config.yaml") else "root", i))
    if omt_hits:
        issues.append("omt_*_channel 假占位符回潮 %d 处: %s" % (len(omt_hits), omt_hits[:3]))
    # 3) weixin.enabled 必须 false (已弃用通道)
    root_cfg = os.path.join(HH, "config.yaml")
    if os.path.exists(root_cfg):
        txt = open(root_cfg, encoding="utf-8").read()
        m = re.search(r"weixin:\n\s*enabled:\s*(\w+)", txt)
        if m and m.group(1) != "false":
            issues.append("weixin.enabled 非 false (已弃用通道复活=启动告警源)")
    if issues:
        c.update(status="fail", evidence="; ".join(issues[:3]),
                 fix_hint="配置回潮: 按证据定位文件, 改回基线并查是谁写的(profile 变更需走约定)")
    else:
        c.update(status="ok", evidence="risk_rules==HEAD, 无 omt_ 占位符, weixin=false")
    return c


# ---------- 自愈白名单 ----------
def auto_repair_R1_run_msgdrain(checks):
    """drain 停摆>=30min → 触发 QSP_MsgDrain 跑一轮 (幂等: drain 自己会去重)"""
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", "QSP_MsgDrain"], capture_output=True,
                           timeout=60, creationflags=CREATE_NO_WINDOW)
        ok = (r.returncode == 0)
        msg = "R1 自愈: 触发 QSP_MsgDrain rc=%d %s" % (r.returncode, "成功" if ok else "失败")
        with open(REPAIR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now_iso(), "repair": "R1_run_msgdrain", "ok": ok}, ensure_ascii=False) + "\n")
        return msg
    except Exception as e:
        with open(REPAIR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now_iso(), "repair": "R1_run_msgdrain", "ok": False, "error": str(e)}, ensure_ascii=False) + "\n")
        return "R1 自愈失败: %s" % e


def enqueue_alert(alerts):
    """告警唯一出口: data/message_queue.json (QSP_MsgDrain 每5min投递飞书)。
    OPS-2 2026-10-17 写口收敛: 一律经 queue_integration.add_alert() 入队 —
    旧直写 shape {msg_type,content,severity} 退役, 统一契约 {id,type,priority,content,data,ts,sent}
    (消费侧层2 按 content 渲染; 层4 抑制key 解析 content 内 [Pn] 段, 行为不变)。"""
    sys.path.insert(0, PROJECT)
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    priority = "P0" if any(a["level"] == "P0" for a in alerts) else "P1"
    content = "\n".join(a["text"] for a in alerts)
    write_ok = True
    try:
        from queue_integration import add_alert
        add_alert(alert_type="sys_watchdog", priority=priority, content=content,
                  data={"checks": [a["check"] for a in alerts], "levels": [a["level"] for a in alerts]})
    except Exception as e:
        write_ok = False
        print("❌ [watchdog] add_alert 入队失败(loud): %s" % e, file=sys.stderr)
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        for a in alerts:
            f.write(json.dumps({"ts": now_iso(), "checker": "sys_watchdog", "severity": a["level"],
                                "queue_write_ok": write_ok,
                                "message": a["text"][:200]}, ensure_ascii=False) + "\n")


def main():
    t0 = dt.datetime.now()
    checks = [c for c in (check_gateway(), check_drain(), check_scheduled_tasks(),
                          check_tdx(), check_kanban_zombie(), check_feishu_creds(),
                          check_github_ci(), check_remotes(), check_log_errors(),
                          check_config_drift()) if c]
    # 自愈白名单执行 (T7双源整合后默认关闭: 修复权威归 QSP_SelfHeal, 本引擎只探测+告警)
    repairs = []
    if AUTO_REPAIR_ENABLED:
        for c in checks:
            if c.get("auto_repair") == "R1_run_msgdrain":
                repairs.append(auto_repair_R1_run_msgdrain(checks))
    # 告警聚合: 仅本引擎独占检查项入队(与 SelfHeal P-01~P-06 重叠项只写报告, 防双报刷屏)
    alerts, dup_suppressed = [], 0
    for c in checks:
        if c["status"] == "fail":
            text = "🔴 [%s] %s — %s%s" % (c["level"], c["check"], c.get("evidence", ""),
                                          ("\n修复提示: " + c["fix_hint"]) if c.get("fix_hint") else "")
            a = {"level": c["level"], "text": text, "check": c["check"]}
            if c["check"] in ALERT_UNIQUE_CHECKS:
                alerts.append(a)
            else:
                dup_suppressed += 1
        elif c["status"] == "warn" and c["check"] in ALERT_UNIQUE_CHECKS:
            alerts.append({"level": "P2", "text": "🟡 [%s] %s — %s" % (c["level"], c["check"], c.get("evidence", "")), "check": c["check"]})
    p0p1 = [a for a in alerts if a["level"] in ("P0", "P1")]
    if p0p1:
        enqueue_alert(p0p1)
    report = {"ts": now_iso(), "elapsed_s": round((dt.datetime.now() - t0).total_seconds(), 1),
              "checks": checks, "repairs": repairs,
              "alerted": len(p0p1), "p2_recorded": len(alerts) - len(p0p1),
              "dup_suppressed_vs_selfheal": dup_suppressed,
              "note": "T7双源整合: 修复权威=QSP_SelfHeal, 本引擎独占C4/C5/C9/C10数据配置层探测"}
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    state = {"last_run": now_iso(), "state": "degraded" if p0p1 else "healthy",
             "failing": [c["check"] for c in checks if c["status"] == "fail"],
             "last_report": os.path.basename(REPORT)}
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print("[watchdog] %s: fail=%d warn=%d p2=%d repairs=%s" % (
        state["state"], len(state["failing"]),
        sum(1 for c in checks if c["status"] == "warn"), report["p2_recorded"],
        ";".join(repairs) if repairs else "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
