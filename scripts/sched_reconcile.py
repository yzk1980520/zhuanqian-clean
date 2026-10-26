#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sched_reconcile.py — 双调度层三方对账脚本 v0.2
=================================================
v0.1 → v0.2 变更（老三 P1 假绿缺陷修复，老五 5 条门禁口径）：
  1. 显式别名映射表 data/audit/sched_alias_map.json（独立配置，不进脚本硬编码，
     机制文档 v2.1 §三行102 指定；映射表本身进台账 C 配置漂移类监控）。
     —— v0.1 按原始名称精确 join，三层命名零交集（hermes 中文名 / cron 事件名 /
        schtasks \\Zhuanqian_* 前缀）→ 交叉检查全 no-op，"差异=0"恒真（假绿）。
  2. 对照组自测（control test）：对真实解析数据做 2 条 in-memory 注入漂移，
     必须各报 ≥1 差异且命中注入项；对照组不通过 → exit 2（结果不可信，
     禁止当"无漂移"上报）。
  3. schtasks 列名解析修正：v0.1 模糊匹配（"状态" in h）先命中"模式"列而非
     "计划任务状态"列 → enabled 判定失真；v0.2 按精确表头名取列，
     列解析失败 → 大声报错 exit 2，不静默吞掉（防假绿守卫同构：坏输出=未对账）。

职责：
  读取三方调度现状（Hermes jobs.json 实物 / Windows schtasks 实物 / 项目 cron_config.json 声明）
  按别名映射表三层对照，输出差异清单 + gate_pending_since 超期 48h 项
  只出"差异清单+证据路径"，接管/定级决策留总管（机制 §二规则 3 同构）

用法：
    python scripts/sched_reconcile.py

输出：
    data/audit/sched_reconcile_<timestamp>.json（含 control_test 自测结果）

exit 语义（假绿守卫锚点）：
    0 = 正常完成（差异数量不定，对照组已通过）
    2 = 对照组失败 / 映射表缺失 / schtasks 列解析失败（结果不可信，不得作为"无漂移"证据）
"""
import sys
import json
import subprocess
import csv
import io
import copy
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
# 双活仓（2026-10-23 P2#7 微调）: gateway 脚本型 job 现由 default profile 仓 +
# zongguan profile 仓两个调度器共同承载（两仓 executions.db 均活跃）。
# v0.2 原版只读 zongguan 仓 → 缺 default 仓 17 job（含 financial_refresh 活 job
# 8e9e77d9），三方对账缺 hermes 层实物。现两仓并读，缺仓大声 WARN 不静默。
HERMES_JOBS_FILE = Path("D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/cron/jobs.json")
HERMES_JOBS_FILE_ALT = Path("D:/Hermes agent/Hermes Agent CN Desktop/data/hermes-home/profiles/zongguan/cron/jobs.json")
CRON_CONFIG_FILE = PROJECT / "cron_config.json"
AUDIT_DIR = PROJECT / "data" / "audit"
LEDGER_FILE = AUDIT_DIR / "defect_ledger.json"
ALIAS_MAP_FILE = AUDIT_DIR / "sched_alias_map.json"
OVERDUE_HOURS = 48

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\sched_reconcile.py] CR-01: except Exception:", file=sys.stderr)
def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def parse_hermes_jobs() -> list[dict]:
    """读取 Hermes 两活仓 jobs.json（实物侧: default profile + zongguan profile）"""
    jobs = []
    for store_name, jobs_file in (("default", HERMES_JOBS_FILE), ("zongguan", HERMES_JOBS_FILE_ALT)):
        if not jobs_file.exists():
            print(f"[WARN] Hermes jobs.json 不存在: {jobs_file}（store={store_name}，该仓跳过，不静默吞掉）")
            continue
        with open(jobs_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for job in data.get("jobs", []):
            sched = job.get("schedule") or job.get("cron") or ""
            run_at = ""
            if isinstance(sched, dict):
                run_at = sched.get("run_at") or ""
                sched = sched.get("expr") or ""
            jobs.append({
                "source": "hermes",
                "store": store_name,
                "job_id": job.get("id", ""),
                "name": job.get("name", ""),
                "enabled": bool(job.get("enabled", False)),
                "state": job.get("state", ""),
                "schedule": sched,
                "run_at": run_at,
                "last_run": job.get("lastRun") or job.get("last_run") or "",
                "last_status": job.get("last_status") or "",
                "prompt": job.get("prompt") or "",
                "script_field": job.get("script") or "",
            })
    return jobs


def parse_schtasks():
    """读取 Windows Task Scheduler 注册任务（实物侧）。
    返回 (tasks, error)；列解析失败时 error 非空（调用方必须 exit 2，不静默）。"""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/V", "/FO", "CSV"],
            capture_output=True, encoding="gbk", errors="replace", timeout=60
        )
    except Exception as e:
        return [], f"schtasks 查询失败: {e}"

    reader = csv.reader(io.StringIO(result.stdout))
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return [], "schtasks CSV 无表头"

    # 精确表头名取列（v0.1 模糊匹配取错列 → enabled 判定失真；v0.2 不允许回退）
    col = {}
    for i, h in enumerate(header):
        if h == "任务名":
            col["name"] = i
        elif h == "计划任务状态":
            col["status"] = i
        elif h == "上次运行时间":
            col["last_run"] = i
        elif h == "上次结果":
            col["last_result"] = i
        elif h == "要运行的任务":
            col["command"] = i
    if "name" not in col or "status" not in col:
        return [], f"schtasks 表头列解析失败（需精确命中 任务名/计划任务状态）：{header}"

    # 项目相关任务关键词（v0.1 有、v0.2 丢失，回归修复：系统任务不进对账）
    PROJECT_KWS = ["zhuanqian", "aoci", "sanity", "icmonitor", "healthcheck",
                   "ylj", "hermes_gateway", "hermesgateway", "hermes_stockboard",
                   "qsp_", "driftmonitor", "mainline-retry", "选股", "闭环"]

    tasks = []
    for row in reader:
        if len(row) <= col["status"]:
            continue
        raw_name = row[col["name"]].strip().lstrip("\\")
        # 去脏行：CSV 偶发把"任务名"表头当数据行 + 系统任务不进项目对账
        if not raw_name or raw_name in ("任务名", "") :
            continue
        if raw_name.startswith("Microsoft"):
            continue
        lname = raw_name.lower()
        if not any(k in lname for k in PROJECT_KWS):
            continue  # 仅保留项目相关任务（与 v0.1 同构，防系统任务噪声）
        status = row[col["status"]].strip()
        t = {
            "source": "schtasks",
            "name": raw_name,
            "status": status,
            "enabled": (status == "已启用"),
        }
        for key in ("last_run", "last_result", "command"):
            if key in col and len(row) > col[key]:
                t[key] = row[col[key]].strip()
        tasks.append(t)
    return tasks, ""


def parse_cron_config() -> list[dict]:
    """读取项目 cron_config.json（声明侧）"""
    if not CRON_CONFIG_FILE.exists():
        print(f"[WARN] cron_config.json 不存在: {CRON_CONFIG_FILE}")
        return []
    with open(CRON_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    events = []
    for name, cfg in data.get("events", {}).items():
        events.append({
            "source": "cron_config",
            "name": name,
            "enabled": bool(cfg.get("enabled", False)),
            "schedule": str(cfg.get("schedule", "")),
            "command": str(cfg.get("command", "")),
        })
    return events


def load_alias_map() -> dict:
    if not ALIAS_MAP_FILE.exists():
        raise FileNotFoundError(f"别名映射表缺失: {ALIAS_MAP_FILE}（机制 §三行102：映射表为对账必要组件，缺失=未对账）")
    with open(ALIAS_MAP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def reconcile_core(jobs: list[dict], tasks: list[dict], events: list[dict], alias_map: dict) -> dict:
    """纯函数：三方数据 + 别名映射 → 差异清单。
    v0.2 核心修复：对照轴从"原始名称精确 join"（零交集恒真）改为"别名组内跨层比较"。"""
    task_by_name = {t["name"]: t for t in tasks}
    job_by_name = {j["name"]: j for j in jobs}
    event_by_name = {e["name"]: e for e in events}

    discrepancies = []
    consistency = []

    # ── 别名组内跨层对照 ─────────────────────────────
    for grp in alias_map.get("aliases", []):
        gname = grp.get("group", "?")
        st_expected = [n.lstrip("\\") for n in grp.get("schtasks", [])]
        hm_expected = [n for n in grp.get("hermes", [])]
        ev_expected = [n for n in grp.get("cron_config", [])]
        st_present = [n for n in st_expected if n in task_by_name]
        hm_present = [n for n in hm_expected if n in job_by_name]
        ev_present = [n for n in ev_expected if n in event_by_name]
        st_missing = [n for n in st_expected if n not in task_by_name]
        expects_physical = bool(st_expected)  # 映射表登记了 schtasks 任务 = 该组应有实物

        # 组内三层启用状态对照（仅对组内"实际存在"的层比较）
        layer_states = []
        for n in st_present:
            layer_states.append((f"schtasks:{n}", task_by_name[n]["enabled"], task_by_name[n].get("status", "")))
        for n in hm_present:
            layer_states.append((f"hermes:{n}", job_by_name[n]["enabled"], ""))
        for n in ev_present:
            layer_states.append((f"cron_config:{n}", event_by_name[n]["enabled"], ""))
        if len(layer_states) >= 2:
            # 仅跨层比较 enabled（同层内 job/任务间启用混合是正常运维态，不构成漂移）
            distinct_layers = {s[0].split(":", 1)[0] for s in layer_states}
            if len(distinct_layers) > 1:
                flags = {s[1] for s in layer_states}
                if len(flags) > 1:
                    discrepancies.append({
                        "type": "status_mismatch",
                        "group": gname,
                        "layers": [list(s) for s in layer_states],
                        "evidence": "别名映射表组内跨层 enabled 不一致",
                    })
                else:
                    consistency.append({"group": gname, "layers": [list(s) for s in layer_states],
                                        "note": "跨层启用状态一致"})

        # 映射表登记了实物任务但 schtasks 查无 → 实物缺失（映射表过时）
        if st_missing:
            discrepancies.append({
                "type": "alias_stale_missing_physical",
                "group": gname,
                "tasks": st_missing,
                "evidence": "别名映射表登记 schtasks 任务但 schtasks /Query 未命中",
            })

        # 声明侧 enabled 但无实物支撑（组登记了 schtasks 预期且组内无实物存在）
        if expects_physical and not st_present:
            for n in ev_present:
                if event_by_name[n]["enabled"]:
                    discrepancies.append({
                        "type": "declared_without_physical",
                        "group": gname,
                        "event": n,
                        "evidence": f"cron_config 声明 {n} enabled=True 但组内无 schtasks 实物任务",
                    })

        # 实物任务近期失败（last_result 异常）——只上报，定级留开单人
        # v0.2.1 修: 从未运行任务 LastResult=哨兵 1799-12-31/n/a, 非失败, 不报（原版误报 P1）
        for n in st_present:
            lr = str(task_by_name[n].get("last_result", ""))
            if lr and lr not in ("0", "已禁用", "", "n/a", "N/A") and "1799" not in lr:
                discrepancies.append({
                    "type": "task_failure_recent",
                    "group": gname,
                    "task": n,
                    "last_run": task_by_name[n].get("last_run", ""),
                    "last_result": lr,
                    "severity_candidate": "P1",
                    "evidence": "schtasks /Query /V 一手输出（LastRun/LastResult）",
                })

    # ── 未映射项（映射表覆盖缺口本身即 C 配置漂移候选）────
    mapped_st, mapped_hm, mapped_ev = set(), set(), set()
    for grp in alias_map.get("aliases", []):
        mapped_st |= {n.lstrip("\\") for n in grp.get("schtasks", [])}
        mapped_hm |= set(grp.get("hermes", []))
        mapped_ev |= set(grp.get("cron_config", []))
    watchlist = set()
    for w in alias_map.get("physical_only_watchlist", []):
        watchlist |= {s.lstrip("\\") for s in str(w.get("task", "")).split("|")}

    for t in tasks:
        if t["name"] not in mapped_st and t["name"] not in watchlist:
            discrepancies.append({
                "type": "unmapped_schtasks_task",
                "task": t["name"],
                "enabled": t["enabled"],
                "severity_candidate": "P2",
                "evidence": "未见于别名映射表任何组/watchlist → 未登记实物任务候选",
            })
    for j in jobs:
        if j["name"] not in mapped_hm:
            discrepancies.append({
                "type": "unmapped_hermes_job",
                "job": j["name"],
                "enabled": j["enabled"],
                "severity_candidate": "P2",
                "evidence": "未见于别名映射表 → 映射覆盖缺口",
            })
    for e in events:
        if e["name"] not in mapped_ev:
            discrepancies.append({
                "type": "unmapped_cron_event",
                "event": e["name"],
                "enabled": e["enabled"],
                "severity_candidate": "P2",
                "evidence": "未见于别名映射表 → 映射覆盖缺口",
            })

    # ── hermes 层抽检（机制 §三「三方对账+假绿抽检」; v0.2.1 补件）────
    script_ref_re = re.compile(r"scripts/([A-Za-z0-9_\-\.]+?\.(?:py|sh|bat|cmd|vbs|ps1))")
    now_dt = datetime.now(timezone.utc)
    for j in jobs:
        last_status = j.get("last_status", "")
        # 真失败: last_status=error 如实报（真失败信号, 非假绿, 定级留开单人）
        if last_status == "error":
            discrepancies.append({
                "type": "hermes_job_last_error",
                "job": j.get("name"),
                "job_id": j.get("job_id"),
                "store": j.get("store"),
                "last_run": j.get("last_run"),
                "severity_candidate": "P1",
                "evidence": "jobs.json last_status=error（一手源）, 真实任务失败, 待总管研判",
            })
        if not j.get("enabled"):
            continue
        # 假绿抽检: 启用 job 的 prompt/script 引用的 scripts/ 脚本实物缺失
        refs = {r.split()[0] for r in script_ref_re.findall(j.get("prompt") or "")}
        sf = j.get("script_field")
        if sf:
            # script_field 可能带参数（"dl_retrain_pipeline.py --trigger cron"）→ 取脚本名本体判存在
            refs.add(Path(sf.split()[0]).name)
        missing = sorted(r for r in refs if not (PROJECT / "scripts" / r).is_file())
        if missing:
            if last_status == "ok":
                discrepancies.append({
                    "type": "fake_green_dangling_script",
                    "job": j.get("name"),
                    "job_id": j.get("job_id"),
                    "store": j.get("store"),
                    "missing_refs": missing,
                    "severity_candidate": "P1",
                    "evidence": "任务 last_status=ok 但 prompt 引用脚本实物缺失 → 任务ok但核心步骤未执行（e09f04a8c297 型假绿）",
                })
            elif not j.get("last_run"):
                discrepancies.append({
                    "type": "dangling_script_never_ran",
                    "job": j.get("name"),
                    "job_id": j.get("job_id"),
                    "store": j.get("store"),
                    "missing_refs": missing,
                    "severity_candidate": "P2",
                    "evidence": "任务从未运行且引用脚本缺失 → 启动即假绿",
                })
        # 一次性任务（无 expr）: 按 run_at 到期状态判, 不得误报差异（机制 §三 兼容性要求）
        if not j.get("schedule") and j.get("run_at"):
            raw_run_at = str(j["run_at"])
            try:
                ran = datetime.fromisoformat(raw_run_at.replace("Z", "+00:00"))
                if ran.tzinfo is None:
                    ran = ran.replace(tzinfo=timezone.utc)
                if j.get("state") == "scheduled" and ran <= now_dt:
                    discrepancies.append({
                        "type": "one_shot_stale",
                        "job": j.get("name"),
                        "job_id": j.get("job_id"),
                        "run_at": raw_run_at,
                        "severity_candidate": "P2",
                        "evidence": "一次性任务 run_at 已过期但 state=scheduled/enabled（应已完成或已停用）",
                    })
            except ValueError:
                # run_at 不可解析 → 显式报不可判, 不静默吞（异常吞噬=P0 缺陷）
                discrepancies.append({
                    "type": "one_shot_runat_unparseable",
                    "job": j.get("name"),
                    "job_id": j.get("job_id"),
                    "run_at": raw_run_at,
                    "severity_candidate": "P3",
                    "evidence": "run_at 非 ISO-8601, 到期状态不可判（如实报, 不静默）",
                })

    return {
        "total_tasks": len(set(task_by_name) | set(job_by_name) | set(event_by_name)),
        "hermes_count": len(jobs),
        "schtasks_count": len(tasks),
        "cron_config_count": len(events),
        "discrepancies": discrepancies,
        "consistency_records": consistency,
    }


def control_test(tasks: list[dict], events: list[dict], jobs: list[dict], alias_map: dict) -> dict:
    """对照组自测：对真实数据做 in-memory 注入漂移，重跑 reconcile_core。
    每条注入必须命中 ≥1 差异，否则 v0.2 自身不可信（防"对账脚本假绿"）。"""
    results = []

    # 注入 1：翻转正 sanity_gate 组某 schtasks 任务的启用状态 → 必须报 status_mismatch@sanity_gate
    mut1 = copy.deepcopy(tasks)
    inj_target = None
    for grp in alias_map.get("aliases", []):
        if grp.get("group") == "sanity_gate":
            for n in [x.lstrip("\\") for x in grp.get("schtasks", [])]:
                if n in {t["name"] for t in mut1}:
                    inj_target = n
                    break
            break
    inj1_ok = False
    if inj_target:
        for t in mut1:
            if t["name"] == inj_target:
                t["enabled"] = not t["enabled"]
                t["status"] = "已启用" if t["enabled"] else "已禁用"
                break
        res1 = reconcile_core(jobs, mut1, events, alias_map)
        inj1_ok = any(d["type"] == "status_mismatch" and d.get("group") == "sanity_gate"
                      for d in res1["discrepancies"])
    results.append({
        "injection": "flip_schtasks_status",
        "target": inj_target,
        "expect": "status_mismatch@sanity_gate",
        "hit": inj1_ok,
    })

    # 注入 2：抽掉 sanity_gate 组全部 schtasks 实物 → 必须报 declared_without_physical/alias_stale@sanity_gate
    sg_names = set()
    for grp in alias_map.get("aliases", []):
        if grp.get("group") == "sanity_gate":
            sg_names |= {n.lstrip("\\") for n in grp.get("schtasks", [])}
    mut2 = [t for t in tasks if t["name"] not in sg_names]
    res2 = reconcile_core(jobs, mut2, events, alias_map)
    inj2_ok = any(d["type"] in ("declared_without_physical", "alias_stale_missing_physical")
                  and d.get("group") == "sanity_gate" for d in res2["discrepancies"])
    results.append({
        "injection": "remove_schtasks_physical",
        "target": sorted(sg_names),
        "expect": "declared_without_physical|alias_stale_missing_physical@sanity_gate",
        "hit": inj2_ok,
    })

    # 注入 3（v0.2.1 假绿抽检件）: 启用 hermes job 的 prompt 引用不存在的脚本且 last_status=ok
    # → 必须报 fake_green_dangling_script 且命中注入项
    mut3 = copy.deepcopy(jobs)
    mut3.append({
        "source": "hermes", "store": "zongguan", "job_id": "cg_inject_fakegreen",
        "name": "CG注入假绿Job", "enabled": True, "state": "scheduled",
        "schedule": "0 21 * * 0", "run_at": "", "last_run": "2026-10-25T21:00:00",
        "last_status": "ok", "prompt": "运行 .venv\\Scripts\\python.exe scripts/cg_inject_missing_xyz.py",
        "script_field": "",
    })
    res3 = reconcile_core(mut3, tasks, events, alias_map)
    inj3_ok = any(d["type"] == "fake_green_dangling_script" and d.get("job") == "CG注入假绿Job"
                  for d in res3["discrepancies"])
    results.append({
        "injection": "fake_green_dangling_script",
        "target": "CG注入假绿Job (prompt 引用不存在的 scripts/cg_inject_missing_xyz.py, last_status=ok)",
        "expect": "fake_green_dangling_script 命中注入项",
        "hit": inj3_ok,
    })

    return {
        "all_passed": (all(r["hit"] for r in results) and len(results) == 3
                       and inj_target is not None and bool(sg_names)),
        "injections": results,
    }


def check_gate_overdue(ledger_path: Path) -> list[dict]:
    """检查台账超期未评审项（gate_pending_since 超 48h）"""
    if not ledger_path.exists():
        return []
    with open(ledger_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    overdue = []
    now = datetime.now().astimezone()
    for entry in data.get("entries", []):
        pending_since = entry.get("gate_pending_since")
        if not pending_since:
            continue
        try:
            ts = str(pending_since)
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            try:
                pending_dt = datetime.fromisoformat(ts)
            except ValueError:
                pending_dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            if pending_dt.tzinfo is None:
                pending_dt = pending_dt.replace(tzinfo=timezone(timedelta(hours=8)))
            hours_pending = (now - pending_dt).total_seconds() / 3600
            if hours_pending > OVERDUE_HOURS:
                overdue.append({
                    "def_id": entry.get("id"),
                    "gate_pending_since": entry.get("gate_pending_since"),
                    "hours_overdue": round(hours_pending - OVERDUE_HOURS, 1),
                    "owner": entry.get("owner"),
                    "gate_level": entry.get("gate_level"),
                })
        except Exception as e:
            print(f"[WARN] gate_pending_since 解析失败: {pending_since}, {e}")
    return overdue


def main() -> int:
    print(f"[sched_reconcile v0.2] 项目根: {PROJECT}")

    jobs = parse_hermes_jobs()
    print(f"[1/3] Hermes jobs.json: {len(jobs)} 条（实物侧）")
    tasks, sch_err = parse_schtasks()
    if sch_err:
        print(f"[FATAL] {sch_err}")
        return 2
    print(f"[2/3] schtasks: {len(tasks)} 条（实物侧，已过滤 Microsoft 系统任务）")
    events = parse_cron_config()
    print(f"[3/3] cron_config.json: {len(events)} 条（声明侧）")

    try:
        alias_map = load_alias_map()
    except FileNotFoundError as e:
        print(f"[FATAL] {e}")
        return 2
    print(f"[alias] 映射表: {len(alias_map.get('aliases', []))} 组 / "
          f"{len(alias_map.get('physical_only_watchlist', []))} watchlist 条目: {ALIAS_MAP_FILE.name}")

    # 对照组自测（v0.2 假绿守卫）
    ctl = control_test(tasks, events, jobs, alias_map)
    print(f"[control] 对照组自测: {'全部命中 ✓' if ctl['all_passed'] else '失败 ✗'}")
    for r in ctl["injections"]:
        print(f"  - {r['injection']} target={r['target']} → hit={r['hit']} (expect {r['expect']})")
    if not ctl["all_passed"]:
        return 2

    result = reconcile_core(jobs, tasks, events, alias_map)
    overdue = check_gate_overdue(LEDGER_FILE)
    result.update({
        "reconciled_at": _now_iso(),
        "version": "0.2.1",
        "control_test": ctl,
        "overdue_gates": overdue,
        "overdue_count": len(overdue),
        "alias_map": ALIAS_MAP_FILE.name,
    })

    print(f"\n{'='*60}\n对账结果（v0.2，对照组已通过）\n{'='*60}")
    print(f"总任务数: {result['total_tasks']}（hermes {result['hermes_count']} + "
          f"schtasks {result['schtasks_count']} + cron_config {result['cron_config_count']}）")
    print(f"差异数: {len(result['discrepancies'])}")
    print(f"跨层一致记录: {len(result['consistency_records'])}")
    print(f"超期 gate 项: {result['overdue_count']}")

    if result["discrepancies"]:
        for d in result["discrepancies"]:
            if "layers" in d:
                print(f"  - [{d['type']}] 组 {d.get('group')}：" +
                      "; ".join(f"{l[0]}={l[1]}" for l in d["layers"]))
            elif "task" in d and "last_result" in d:
                print(f"  - [{d['type']}] {d['task']} last_run={d.get('last_run')} "
                      f"last_result={d.get('last_result')} ({d.get('severity_candidate')})")
            else:
                label = d.get("group") or d.get("task") or d.get("event") or d.get("job") or ""
                print(f"  - [{d['type']}] {label} ({d.get('severity_candidate', '')}) "
                      f"{str(d.get('evidence', ''))[:60]}")

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    out = AUDIT_DIR / f"sched_reconcile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 完整结果已保存: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
