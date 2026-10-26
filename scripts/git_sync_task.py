# -*- coding: utf-8 -*-
"""git_sync_task.py — 代码同步环 T1 (Hermes治理方案v1, 2026-10-15 总管)

背景: 双远程 2026-09-29 起静默停摆 16 天、本地积压 379 提交无人发现
(根因: 只盯 push 退出码、不盯远程 main 时间戳, 且根本没有自动 push 机制)。
根治 = 同步环例行化: 工作日 09:30 计划任务 QSP_GitSync 执行本脚本。

流程(老六方案 T1 第2步):
  0. 非工作日跳过(--force 可手工强制)
  1. git status --porcelain: 脏树 → 记录但【不自动 commit】
     (策略: 跳过+记录。当前脏树含 88 未跟踪+25 修改, 其中 .gitignore
      白名单实盘数据 P0 止血未闭环, 自动 commit 会扩大泄漏面;
      脏树不阻塞已提交工作的推送)
  2. pytest 门禁: scripts/test_*.py 全绿才推, 不绿不推(F4 语义)
  3. git push gitcode github-main:main + git push origin github-main:main
  4. 推后验收: ls-remote 双远程 tip == 本地 HEAD (ahead=0) 才算成功
     (远程 main 时间戳判据, 非 push 退出码 — 2026-10-15 老大指定)
  5. 失败重试 1 次, 仍失败 → P0 写 alert_log.jsonl + 入 message_queue
     (QSP_MsgDrain 5分钟内飞书到群; 唯一出口=队列, T2 立规)

产出: data/git_sync_state.json (供 09:00 监督核验 + QSP_DrainWatch meta)
退出码: 0=成功/跳过, 1=失败(门禁红或双远程验收未过)
"""
import glob
import json
import os
import subprocess
import sys
import datetime as _dt

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(PROJECT, "data", "git_sync_state.json")
ALERT_LOG = os.path.join(PROJECT, "data", "alert_log.jsonl")
# OPS-2 2026-10-17: 队列路径统一由 queue_integration.QUEUE_FILE 持有, 本文件不再自定义写口
LOCAL_BRANCH = "github-main"
REMOTE_BRANCH = "main"
REMOTES = ["gitcode", "origin"]
PYTEST_TIMEOUT = 600
GIT_TIMEOUT = 300
RETRY = 1
# P1-D 2026-10-19 门禁单点解耦(保留强度, 只修"冻结不可见"):
#   连续判红 N 轮 → 冻结升 P0; 冻结持续 > N 小时 → 升 P0(首冻结/既存红为 P1)。
#   既存红 = 上次成功同步基线 gate_red_baseline 内的红; 新红 = 基线外(改动引入) → 一律阻断。
#   基线只在上次成功同步时刷新 ⇒ 回归新红跨轮不逃逸(阻断不解除就一直比基线)。
FREEZE_P0_AFTER_ROUNDS = 2
FREEZE_P0_AFTER_HOURS = 2.0
# 契约真源守卫(在 tests/ 下, 不在 scripts/test_*.py 的 glob 里)。
# 2026-10-19: 这两个守卫从未进过任何门禁执行面, 导致真源戳漂移无人发现。
# 实测 3.2s, 显式并入推前门禁。变更此列表须同步 scripts/test_git_sync_gate_guard.py。
CONTRACT_GUARD_TESTS = [
    "tests/test_contract_docs_consistency.py",
    "tests/test_doc_freshness.py",
]

# P1-D 2026-10-19: git_sync_state.json 读写走 atomic_json(规则8 原子写, 防 drain/写者并发覆盖);
# 缺失时降级 plain json + os.replace(仍原子)。基线/冻结态字段全落此文件, 跨轮判新旧全靠它。
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
try:
    from core.pipeline.atomic_json import atomic_dump as _atomic_dump, atomic_load as _atomic_load
    _ATOMIC_OK = True
except Exception:
    _atomic_dump = _atomic_load = None
    _ATOMIC_OK = False


def _iso(dt=None):
    return (dt or _dt.datetime.now()).isoformat(timespec="seconds")


def parse_failing_nodes(out):
    """从 pytest `-rf` short summary 解析失败 node id(去重保序)。
    行形如 'FAILED scripts/test_x.py::test_a - AssertionError...' / 'FAILED scripts/test_x.py::test_a'。
    P1-D: 这是"区分既存红/新红"的原料 — 只取 node id, 去掉 reason。"""
    nodes, seen = [], set()
    for line in (out or "").splitlines():
        s = line.strip()
        if s.startswith("FAILED"):
            nid = s[len("FAILED"):].strip().split(" - ")[0].strip()
            if nid and nid not in seen:
                seen.add(nid)
                nodes.append(nid)
    return nodes


def classify_reds(now_nodes, prev_nodes):
    """纯函数: 区分红测试来源。
    now_nodes = 本轮门禁实测失败 node; prev_nodes = 上次成功同步基线 gate_red_baseline。
    new = 本轮新增(改动引入, 应阻断); preexisting = 基线内既存(与本轮无关, 可放行+告警)。"""
    now = list(dict.fromkeys(now_nodes or []))
    prev = set(prev_nodes or [])
    new = [n for n in now if n not in prev]
    preexisting = [n for n in now if n in prev]
    return {"new": new, "preexisting": preexisting}


def _freeze_age_hours(frozen_since, now=None):
    """冻结已持续多少小时(供 >2h 升级 P0 判断)。无/解析失败 → None。"""
    if not frozen_since:
        return None
    try:
        since = _dt.datetime.fromisoformat(frozen_since)
        now = now or _dt.datetime.now()
        return round((now - since).total_seconds() / 3600.0, 2)
    except Exception as e:
        print(f"🔴 [git_sync_task.py:109] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
        return None


def decide_gate(gate, state, now_iso=None):
    """P1-D 门禁单点解耦决策(纯函数, 保留门禁强度)。
    输入: gate=run_pytest_gate 结果, state=上一轮 git_sync_state(含 gate_red_baseline/frozen_*)。
    输出决策 dict: proceed/freeze/alert_priority/frozen_reason/frozen_since/
      consecutive_rounds/ledger/baseline_after/new_red/preexisting_red。
    强度不变: 任何"新红"(相对上次成功同步基线) 一律阻断; 仅基线内既存红放行(且 P1 告警+台账)。"""
    now_iso = now_iso or _iso()
    state = state or {}
    now_all = gate.get("failing_nodes", []) or []
    c = classify_reds(now_all, state.get("gate_red_baseline") or [])
    new, preexisting = c["new"], c["preexisting"]

    d = {"proceed": False, "freeze": False, "alert_priority": None,
         "frozen_reason": None, "frozen_since": None,
         "consecutive_rounds": int(state.get("frozen_consecutive_rounds") or 0),
         "ledger": None, "new_red": new, "preexisting_red": preexisting,
         "baseline_after": now_all}

    # 1) 异常/超时 = 判红(不绿不推)。超时比红更坏(挂死无人知) → 直接 P0, 冻结可见。
    if gate.get("timed_out") or ((gate.get("rc") == -1) and not gate.get("ok")):
        reason = gate.get("note") or (
            "pytest 门禁超时>%ds" % PYTEST_TIMEOUT if gate.get("timed_out")
            else "门禁异常(rc=-1), 不绿不推")
        rounds = int(state.get("frozen_consecutive_rounds") or 0) + 1
        d.update(freeze=True, alert_priority="P0", frozen_reason=reason,
                 frozen_since=state.get("frozen_since") or now_iso,
                 consecutive_rounds=rounds)
        return d

    # 2) D1 强度洞封堵(复审 2026-10-19): 门禁非绿(ok=False)但解析不到 FAILED 节点
    #    = error 形态(collection/import error、pytest 内部错; rc≠0、failed=0、无 FAILED 行)。
    #    无法枚举红集 ⇒ 无法证明"只有既存红" ⇒ 严格差于已知红 → 阻断 + P0 + 冻结可见。
    #    P0 自足判定: 与 timed_out 同类(门禁基建坏), 升级口径不再叠加(P0 已顶格)。
    #    旧代码"全绿"分支仅凭 failing_nodes 为空放行 → error 形态漏"失败也推", 违反 §二。
    if not gate.get("ok") and not now_all:
        detail = gate.get("note") or ("rc=%s failed=%s" % (gate.get("rc"), gate.get("failed")))
        d.update(freeze=True, alert_priority="P0",
                 frozen_reason=("门禁非绿但解析不到 FAILED 节点(error 形态: collection/import "
                                "或 pytest 内部错; %s) 不绿不推" % detail),
                 frozen_since=state.get("frozen_since") or now_iso,
                 consecutive_rounds=int(state.get("frozen_consecutive_rounds") or 0) + 1)
        return d

    # 3) 全绿(门禁跑 ok 且无 FAILED 节点, 双条件同时满足; error 形态已在 2) 拦下)
    if gate.get("ok") and not now_all:
        d.update(proceed=True, alert_priority=None, baseline_after=[])
        return d

    # 4) 有红: 新红一律阻断(强度不变), 冻结可见, 按轮次/时长升级
    if new:
        rounds = int(state.get("frozen_consecutive_rounds") or 0) + 1
        age = _freeze_age_hours(state.get("frozen_since"))
        escalate = (rounds >= FREEZE_P0_AFTER_ROUNDS) or (
            age is not None and age > FREEZE_P0_AFTER_HOURS)
        d.update(freeze=True,
                 alert_priority="P0" if escalate else "P1",
                 frozen_reason=("本轮新增 %d 条红测试(改动引入) 不绿不推: %s"
                                % (len(new), "; ".join(new[:5]))),
                 frozen_since=state.get("frozen_since") or now_iso,
                 consecutive_rounds=rounds)
        return d

    # 4) 仅基线内既存红 → 放行, P1 告警 + 台账"带着 N 条既存红推送"
    d.update(proceed=True, alert_priority="P1",
             ledger=("带着 %d 条既存红推送(与本轮改动无关, 已入 gate_red_baseline): %s"
                     % (len(preexisting), "; ".join(preexisting[:5]))))
    return d


def _load_state():
    """读上一轮 git_sync_state.json(基线/冻结态判断)。
    文件缺失/损坏 → {}: 首跑基线空, 保守把全部红视为'新红'→阻断(绝不放行未知红)。"""
    if _ATOMIC_OK:
        return _atomic_load(STATE_FILE, default={}) or {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception as e:
        log_line("⚠️ 读 git_sync_state.json 失败 → 基线空(保守阻断): %s" % e)
        return {}


def _save_state(state):
    """原子写 git_sync_state.json。保留 last_run(P-03 探针读侧依赖)。"""
    state.setdefault("last_run", _iso())
    if _ATOMIC_OK:
        _atomic_dump(state, STATE_FILE)
        return
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def _git(args, timeout=GIT_TIMEOUT):
    r = subprocess.run(["git"] + args, cwd=PROJECT, capture_output=True,
                       text=True, encoding="utf-8", timeout=timeout,
                       creationflags=CREATE_NO_WINDOW)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def log_line(msg):
    print("[%s] %s" % (_dt.datetime.now().strftime("%H:%M:%S"), msg))


def check_dirty():
    rc, out, _ = _git(["status", "--porcelain"], timeout=60)
    if rc != 0:
        return {"ok": False, "count": -1, "note": "git status 失败"}
    lines = [l for l in out.splitlines() if l.strip()]
    return {"ok": True, "count": len(lines),
            "note": "跳过自动commit(策略: 防扩大实盘数据白名单泄漏面, 见模块docstring)",
            "sample": lines[:5]}


def run_pytest_gate():
    """推前门禁: scripts/test_*.py 全绿。无测试文件 = 不绿(0/1假绿教训)。

    2026-10-19 fork 弹护栏(老六): 本函数会派生 pytest, 而派生的目标集合正是
    scripts/test_*.py。一旦其中某个测试直接调用本函数(曾为
    test_git_sync_gate_logic.py::TestGateFunctionDirectly, 现隔离至
    deliverables/_quarantine/), 即形成 pytest -> 本函数 -> pytest 的无限自递归:
    实测 34 层、单轮 539s、49 个 python.exe 并发。
    护栏 = 环境变量哨兵 ZQ_PYTEST_GATE: 已在门禁子进程内则拒绝二次派生。
    """
    if os.environ.get("ZQ_PYTEST_GATE") == "1":
        return {"ok": False, "passed": 0, "failed": 0, "rc": -1,
                "timed_out": False, "failing_nodes": [],
                "note": "ZQ_PYTEST_GATE 哨兵生效: 拒绝在门禁子进程内二次派生 pytest(防自递归 fork 弹)"}
    files = sorted(glob.glob(os.path.join(PROJECT, "scripts", "test_*.py")))
    # 2026-10-19 老六架构审查: 契约真源守卫在 tests/ 下, 而 glob 只认 scripts/
    # ⇒ 两个守卫(会 FAIL 的那种)从未进过门禁, 真源漂移无人知。
    # 实测这两个 3.2s, 够快, 显式并入。tests/ 全域 21min+ 故不整体并入。
    for rel in CONTRACT_GUARD_TESTS:
        p = os.path.join(PROJECT, *rel.split("/"))
        if os.path.exists(p) and p not in files:
            files.append(p)
    if not files:
        return {"ok": False, "passed": 0, "failed": 0, "rc": -1, "failing_nodes": [],
                "note": "scripts/test_*.py 一个测试文件都没有 — 门禁不通过(不绿不推)"}
    env = {**os.environ, "PYTHONPATH": "", "ZQ_PYTEST_GATE": "1"}
    timed_out = False
    # -rf: 输出 short test summary 的 FAILED node id 行, 供 P1-D 区分"既有红/新红"
    p = subprocess.Popen([sys.executable, "-m", "pytest"] + files + ["-q", "-rf"],
                         cwd=PROJECT, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", creationflags=CREATE_NO_WINDOW,
                         env=env)
    try:
        out, err = p.communicate(timeout=PYTEST_TIMEOUT)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        # Windows: subprocess.run(timeout=) 只 kill 直接子进程, pytest 的孙进程
        # 会成孤儿继续跑。故显式 taskkill /T /F 杀整树。
        timed_out = True
        try:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            print(f"🔴 [git_sync_task.py:271] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 Exception → 兜底, 异常={e}", file=sys.stderr)
            pass
        try:
            out, err = p.communicate(timeout=30)
        except Exception:
            out, err = "", ""
        rc = -9
    out = (out or "") + (err or "")
    passed = failed = 0
    import re
    m = re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", out)
    if m:
        failed = int(m.group(1))
    ok = (rc == 0) and failed == 0
    failing_nodes = parse_failing_nodes(out)
    return {"ok": ok, "passed": passed, "failed": failed,
            "rc": rc, "timed_out": timed_out, "failing_nodes": failing_nodes,
            "tail": out[-400:]}


def remote_tip_and_ahead(remote):
    rc, out, err = _git(["ls-remote", remote, "refs/heads/%s" % REMOTE_BRANCH], timeout=120)
    if rc != 0 or not out:
        return {"remote": remote, "reachable": False, "error": err[:200]}
    sha = out.split()[0]
    rc2, out2, _ = _git(["rev-list", "--count", "%s..HEAD" % sha], timeout=60)
    ahead = int(out2) if (rc2 == 0 and out2.isdigit()) else None
    rc3, out3, _ = _git(["log", "-1", "--format=%cI", sha], timeout=60)
    tip_time = out3 or None
    age_h = None
    if tip_time:
        try:
            age_h = round((_dt.datetime.now(_dt.timezone.utc) -
                           _dt.datetime.fromisoformat(tip_time)).total_seconds() / 3600, 1)
        except Exception:
            print(f"🔴 [scripts\git_sync_task.py] CR-01: except Exception:", file=sys.stderr)
    return {"remote": remote, "reachable": True, "tip": sha[:12],
            "tip_time": tip_time, "age_hours": age_h, "local_ahead": ahead}


def push_once(remote):
    rc, out, err = _git(["push", remote, "%s:%s" % (LOCAL_BRANCH, REMOTE_BRANCH)])
    return rc == 0, (out + " " + err)[:300]


def refresh_source_branch():
    """D-21 方案A (2026-10-26 t_eecab269): 推送源分支 github-main 刷新到 main 的 tip(防推送源陈旧累积 → non-FF P0 复发)。
    仅由 main() 双远程推送成功+验收通过分支调用; 刷新失败仅记日志, 不阻断本次推送成功(本地 ref 操作, 下轮重验)。"""
    rc, out, err = _git(["branch", "-f", LOCAL_BRANCH, "main"], timeout=60)
    if rc != 0:
        log_line("[SYNC] ⚠️ github-main 刷新失败 (rc=%s): %s" % (rc, (err or out)[:120]))
        return False
    log_line("[SYNC] github-main 刷新→main tip=%s" % _git(["rev-parse", "main"], timeout=60)[1][:12])
    return True


def emit_alerts(msg, state, priority="P0", alert_type="gitsync_p0"):
    """唯一出口=队列(规则11 唯一投递器 QSP_MsgDrain); alert_log.jsonl 为本地台账, 不代表触达。
    P1-D: priority 由门禁决策决定(P1 既存红/首冻结轮; P0 升级/推送失败/验收未过), 不再硬编码 P0。"""
    prefix = "🚨" if priority == "P0" else "⚠️"
    entry = json.dumps({"ts": _dt.datetime.now().isoformat(timespec="seconds"),
                        "alert": "%s: %s" % (alert_type, msg), "priority": priority,
                        "state": state}, ensure_ascii=False)
    try:
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
        log_line("已写 alert_log.jsonl (%s)" % priority)
    except Exception as e:
        log_line("写 alert_log.jsonl 失败: " + str(e))
    try:
        # 2026-10-17 OPS-2 写口收敛: 统一经 queue_integration.add_alert() 入队 (契约 {id,type,priority,content,data,ts,sent})
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        for p in (PROJECT, scripts_dir):
            if p not in sys.path:
                sys.path.insert(0, p)
        from queue_integration import add_alert
        add_alert(alert_type=alert_type, priority=priority,
                  content="%s [代码同步环%s] %s | 双远程验收: " % (prefix, priority, msg)
                          + json.dumps(state.get("remotes", {}), ensure_ascii=False),
                  data={"remotes": state.get("remotes", {}),
                         "failing_nodes": state.get("gate", {}).get("failing_nodes", []),
                         "frozen_reason": state.get("frozen_reason")})
        log_line("已入 message_queue [%s] (QSP_MsgDrain 唯一投递器, 5分钟内飞书到群)" % priority)
    except Exception as e:
        log_line("写 message_queue 失败: " + str(e))


def main():
    force = "--force" in sys.argv
    force_reason = None
    for i, a in enumerate(sys.argv):
        if a == "--force-with-reason" and i + 1 < len(sys.argv):
            force_reason = sys.argv[i + 1]
    today = _dt.date.today()
    if today.weekday() >= 5 and not force:
        log_line("非工作日(%s) 跳过同步环" % today)
        prev = _load_state()
        prev["last_run"] = _iso()
        prev["ok"] = True
        prev["skipped"] = "weekend"
        _save_state(prev)
        return 0

    log_line("===== QSP_GitSync 代码同步环开始 =====")
    now_iso = _iso()
    prev_state = _load_state()

    state = {"last_run": now_iso, "ok": False, "dry": None, "gate": None, "remotes": {}}

    # Step 1: 脏树检查(记录, 不自动commit)
    state["dry"] = check_dirty()
    log_line("脏树: %d 个待处理 — %s" % (
        state["dry"]["count"], state["dry"]["note"]))

    # Step 2: pytest 门禁(不绿不推) + P1-D 单点解耦决策
    state["gate"] = run_pytest_gate()
    g = state["gate"]
    log_line("pytest 门禁: ok=%s passed=%s failed=%s rc=%s reds=%d" % (
        g["ok"], g["passed"], g["failed"], g.get("rc"),
        len(g.get("failing_nodes", []))))

    decision = decide_gate(g, prev_state, now_iso)
    log_line("门禁决策: proceed=%s freeze=%s prio=%s 新红=%d 既存红=%d" % (
        decision["proceed"], decision["freeze"], decision["alert_priority"],
        len(decision["new_red"]), len(decision["preexisting_red"])))

    # 兜底通道(c): 人工审计强推(仅当门禁阻断且显式给原因)
    if not decision["proceed"] and force_reason:
        decision = dict(decision)
        decision["proceed"] = True
        decision["forced"] = True
        log_line("🛠 强制推送(--force-with-reason): %s — 写审计留痕" % force_reason)

    if not decision["proceed"]:
        # 阻断 + 冻结可见(b): 落 frozen_* 字段 + 经唯一投递器入 message_queue
        msg = decision["frozen_reason"] or "门禁判红, 不推(F4 语义)"
        state["frozen_since"] = decision["frozen_since"]
        state["frozen_reason"] = msg
        state["frozen_consecutive_rounds"] = decision["consecutive_rounds"]
        state["frozen_alert_level"] = decision["alert_priority"]
        # 基线【不刷新】: 仍钉在'上次成功同步', 回归新红跨轮不逃逸
        state["gate_red_baseline"] = prev_state.get("gate_red_baseline") or []
        _save_state(state)
        emit_alerts(msg, state, priority=decision["alert_priority"] or "P1",
                    alert_type="gitsync_freeze")
        log_line("🚨 冻结(可见): " + msg + " [%s]" % (decision["alert_priority"] or "P1"))
        return 1

    # 放行(全绿 / 仅基线内既存红 → P1 告警+台账)
    if decision.get("alert_priority") == "P1" and not decision.get("forced"):
        emit_alerts(decision.get("ledger") or "带既存红推送", state,
                    priority="P1", alert_type="gitsync_preexisting_red")

    # Step 3: 双远程推送 + 重试1次
    for attempt in range(RETRY + 1):
        failed = []
        for remote in REMOTES:
            ok, detail = push_once(remote)
            state.setdefault("push_log", []).append(
                {"attempt": attempt + 1, "remote": remote,
                 "ok": ok, "detail": detail})
            log_line("push %s (第%d次): %s" % (remote, attempt + 1,
                                               "✅" if ok else "❌ " + detail[:120]))
            if not ok:
                failed.append(remote)
        if not failed:
            break
    if failed:
        msg = "git push 失败(重试%d次后): %s" % (RETRY, ", ".join(failed))
        log_line("🚨 " + msg)
        # 推送失败: 基线不刷新(仍钉上次成功同步), 冻结保持可见
        state["frozen_reason"] = msg
        state["frozen_since"] = prev_state.get("frozen_since") or now_iso
        state["gate_red_baseline"] = prev_state.get("gate_red_baseline") or []
        _save_state(state)
        emit_alerts(msg, state, priority="P0", alert_type="gitsync_p0")
        return 1

    # Step 4: 推后验收(远程 main 时间戳判据: tip==HEAD 且 ahead=0)
    all_ok = True
    for remote in REMOTES:
        info = remote_tip_and_ahead(remote)
        state["remotes"][remote] = info
        if info.get("reachable") and info.get("local_ahead") == 0:
            log_line("验收 %s: ✅ tip=%s age=%sh ahead=0" % (
                remote, info.get("tip"), info.get("age_hours")))
        else:
            all_ok = False
            log_line("验收 %s: ❌ %s" % (remote, json.dumps(info, ensure_ascii=False)))

    state["ok"] = all_ok

    if not all_ok:
        # 验收未过: P0, 基线不刷新, 冻结保持可见
        msg = "双远程推后验收未过: " + json.dumps(state["remotes"], ensure_ascii=False)
        log_line("🚨 " + msg)
        state["frozen_reason"] = msg
        state["frozen_since"] = prev_state.get("frozen_since") or now_iso
        state["frozen_consecutive_rounds"] = \
            (prev_state.get("frozen_consecutive_rounds") or 0) + 1
        state["frozen_alert_level"] = "P0"
        state["gate_red_baseline"] = prev_state.get("gate_red_baseline") or []
        _save_state(state)
        emit_alerts(msg, state, priority="P0", alert_type="gitsync_p0")
        return 1

    # D-21: 双远程推送成功+验收通过 → 刷新源分支 github-main 到 main tip(防下轮推送源陈旧累积 → non-FF P0 复发)
    refresh_source_branch()

    # 推送成功 + 验收过: 重钉基线 + 清冻结态(b 恢复) + 记 last_success(P-03 读侧)
    state["gate_red_baseline"] = decision.get("baseline_after")
    for _k in ("frozen_since", "frozen_reason",
               "frozen_consecutive_rounds", "frozen_alert_level"):
        state.pop(_k, None)
    if decision.get("forced"):
        who = (os.environ.get("USERNAME") or os.environ.get("USER")
               or os.environ.get("LOGNAME") or "unknown")
        reds = g.get("failing_nodes", []) or []
        # D2(复审 2026-10-19): what 补 commit range(本地 remote-tracking 口径, 已标注) + 当前红集
        range_info = {}
        for remote in REMOTES:
            rc, out, _ = _git(["rev-list", "--count",
                               "%s/%s..HEAD" % (remote, REMOTE_BRANCH)],
                              timeout=60)
            range_info[remote] = int(out) if (rc == 0 and out.isdigit()) else None
        head_sha = _git(["rev-parse", "HEAD"], timeout=60)[1][:12]
        what = ("commit range: 本地 remote-tracking 口径 %s(提交数), 至本地 HEAD=%s; "
                "强制放行红集=%s"
                % (json.dumps(range_info, ensure_ascii=False), head_sha,
                   json.dumps(reds, ensure_ascii=False)))
        state["force_push_audit"] = {
            "who": who,
            "why": force_reason,
            "what": what,
            "ts": now_iso,
        }
        # D2: 强推审计留痕强制经唯一投递器: alert_log.jsonl(本地台账) +
        # message_queue.json(QSP_MsgDrain 飞书), P0。08:27 口径承诺三处写齐, 此处补齐。
        emit_alerts("强制推送审计 who=%s why=%s what=%s" % (who, force_reason, what),
                    state, priority="P0", alert_type="gitsync_force_push")
    state["last_success"] = now_iso
    _save_state(state)

    log_line("===== 同步环完成: 双远程 tip==HEAD, ahead=0 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
