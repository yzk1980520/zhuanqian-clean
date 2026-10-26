# DEPRECATED → use scripts/check_all.py health
# -*- coding: utf-8 -*-
"""check_remote_main_freshness.py — 远程 main 新鲜度监控 (2026-10-15 老六)

背景: 2026-09-29 起 GitHub 通道静默停摆 16 天, 本地积压 379 提交无人发现 —
根因是没人监控"远程 main 时间戳", 只监控 push 退出码(而 push 根本没被执行)。

判据(老大 2026-10-15 指定): 远程 main 尖端的提交时间, 而非 push 退出码。

检查逻辑:
  1. git ls-remote <remote> refs/heads/main 拿远程尖端 SHA
  2. 拿本地已知的该 SHA 提交时间(git log -1 --format=%cI)
     (SHA 不在本地时回退用 gitcode 对照或标记 unknown)
  3. 与本地 HEAD 比对: 落后提交数 + 尖端时间龄
  4. 超阈值 → data/alert_log.jsonl + stdout 🚨 + exit 1

用法:
  python scripts/check_remote_main_freshness.py            # 检查全部远程
  python scripts/check_remote_main_freshness.py --remote origin
  MAX_AGE_HOURS=48 python scripts/check_remote_main_freshness.py
"""
import os
import sys
import json
import subprocess
import datetime as _dt

# W3 2026-10-17 静默运行: Windows 下宿主若无控制台, 子进程会被分配新可见控制台(弹黑框)。
# 派生一律带 CREATE_NO_WINDOW; 非 Windows 回落 0。见 docs/规范-静默运行-20261017.md
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALERT_LOG = os.path.join(PROJECT, "data", "alert_log.jsonl")
STATE_FILE = os.path.join(PROJECT, "data", "remote_freshness_state.json")

REMOTES = ["origin", "gitcode"]           # origin=GitHub, gitcode=gitcode.com
DEFAULT_MAX_AGE_HOURS = 48                # 远程尖端提交时间龄阈值(小时)
DEFAULT_MAX_BEHIND = 50                   # 本地领先远程提交数阈值


def _git(args, timeout=60):
    r = subprocess.run(["git"] + args, cwd=PROJECT, capture_output=True,
                       text=True, encoding="utf-8", timeout=timeout,
                       creationflags=CREATE_NO_WINDOW)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def remote_main_sha(remote, retries=3):
    """拿远程 main 尖端 SHA; DNS/网络瞬时失败重试(2026-10-15 实测 gitcode.com
    存在间歇性解析失败, 单次失败即告警会产生假阳性)"""
    last_err = ""
    for attempt in range(retries):
        rc, out, err = _git(["ls-remote", remote, "refs/heads/main"])
        if rc == 0 and out:
            return out.split()[0], None
        last_err = err[:120]
        if attempt < retries - 1:
            import time as _time
            _time.sleep(5)
    return None, "ls-remote失败(重试%d次): %s" % (retries, last_err)


def commit_time_iso(sha):
    rc, out, _ = _git(["log", "-1", "--format=%cI", sha])
    if rc != 0 or not out:
        return None
    return out


def ahead_count(remote_sha):
    """本地 HEAD 领先 remote_sha 的提交数; remote_sha 不在本地历史返回 None"""
    rc, out, _ = _git(["rev-list", "--count", remote_sha + "..HEAD"])
    if rc != 0:
        return None
    try:
        return int(out)
    except ValueError:
        print(f"🔴 [scripts\check_remote_main_freshness.py] CR-01(return): except ValueError:", file=sys.stderr)
        return None
def check_remote(remote, max_age_hours, max_behind):
    result = {"remote": remote, "ok": False, "alerts": []}
    sha, err = remote_main_sha(remote)
    if err:
        result["alerts"].append(f"{remote}: {err}")
        return result
    result["remote_sha"] = sha[:12]
    result["remote_sha_full"] = sha

    ts = commit_time_iso(sha)
    if ts is None:
        result["alerts"].append(
            f"{remote}: main 尖端 {sha[:12]} 不在本地历史(可能是他人推送或历史断层), 需人工核对")
        result["unknown"] = True
        return result

    commit_dt = _dt.datetime.fromisoformat(ts)
    age_hours = (_dt.datetime.now(commit_dt.tzinfo) - commit_dt).total_seconds() / 3600
    result["remote_tip_time"] = ts
    result["age_hours"] = round(age_hours, 1)

    behind = ahead_count(sha)
    result["local_ahead"] = behind
    if behind is not None and behind > max_behind:
        result["alerts"].append(
            f"{remote}: 本地领先 {behind} 提交(阈值 {max_behind}) — 推送通道疑似停摆")

    if age_hours > max_age_hours:
        result["alerts"].append(
            f"{remote}: main 尖端提交时间龄 {age_hours:.1f}h(阈值 {max_age_hours}h) "
            f"= {ts[:19]} — 远程同步疑似停摆")

    result["ok"] = not result["alerts"]
    return result


def _emit_alert(msg):
    """本地告警(alert_log.jsonl + stdout) + 飞书触达(写 message_queue,
    QSP_MsgDrain 每5分钟消费推送, 最迟5分钟到群 — 379积压16天无人知的
    根因就是告警无触达, 2026-10-15 老大指定远程main时间戳判据时强调)"""
    line = json.dumps({
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "alert": "remote-main-freshness: " + msg,
    }, ensure_ascii=False)
    try:
        os.makedirs(os.path.dirname(ALERT_LOG), exist_ok=True)
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print("[alert] 写 alert_log.jsonl 失败: " + str(e))
    # 飞书触达: 入消息队列 (OPS-2 2026-10-17 写口收敛: 统一经 queue_integration.add_alert(),
    # 契约 {id,type,priority,content,data,ts,sent}; 队列路径由 queue_integration.QUEUE_FILE 单源持有)
    try:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        for p in (PROJECT, scripts_dir):
            if p not in sys.path:
                sys.path.insert(0, p)
        from queue_integration import add_alert
        add_alert(alert_type="remote_main_freshness", priority="P1",
                  content="🚨 [远程同步告警] " + msg,
                  data={"alert": "remote-main-freshness: " + msg})
    except Exception as e:
        print("[alert] 写 message_queue 失败(不影响本地告警): " + str(e))
    print("🚨 [P1-ALERT] " + msg)


def main():
    max_age_hours = float(os.environ.get("MAX_AGE_HOURS", DEFAULT_MAX_AGE_HOURS))
    max_behind = int(os.environ.get("MAX_BEHIND", DEFAULT_MAX_BEHIND))
    only = None
    if "--remote" in sys.argv:
        only = sys.argv[sys.argv.index("--remote") + 1]

    print("===== remote main freshness %s =====" %
          _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    results, has_alert = [], False
    for remote in REMOTES:
        if only and remote != only:
            continue
        try:
            r = check_remote(remote, max_age_hours, max_behind)
        except Exception as e:
            r = {"remote": remote, "ok": False, "alerts": [f"{remote}: 检查异常 {e}"]}
        results.append(r)
        status = "✅" if r.get("ok") else ("⚠️" if r.get("unknown") else "🚨")
        print("%s %s: tip=%s age=%sh ahead=%s" % (
            status, r["remote"], r.get("remote_sha", "?"),
            r.get("age_hours", "?"), r.get("local_ahead", "?")))
        for a in r["alerts"]:
            _emit_alert(a)
            has_alert = True

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_run": _dt.datetime.now().isoformat(timespec="seconds"),
                       "results": results}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[state] 写 remote_freshness_state.json 失败: " + str(e))

    return 1 if has_alert else 0


if __name__ == "__main__":
    sys.exit(main())
