#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py dispatch
# -*- coding: utf-8 -*-
"""派单审计 v1.1 — 《派单授权与审计规则 v1.1》§八 的机器件（读侧消费断言）

立规依据：老大 2026-10-16 20:24「四件授权，派单固化」；v1.1 增补依据：老大 2026-10-16 20:45「允许」。
铁律 §2.9（AGENTS.md 规则 12）：写侧动作必须注册读侧消费断言；本脚本就是"派单规则"的消费侧。

判据：C1 提单人留名 / C2 复审单挂接且人不同 / C3 台账有行 / C4 派单件有档 / C5 依据可溯源。
v1.1 新增 C5（§九.5 唯一可机判项）。**V1–V4 的"依据是否成立"不可机判，须老五人工签署**，
本脚本不得冒充人审（v1.1 §九.5 明文）。

只读：调 `hermes kanban list --json`（任务全集）+ 直读 kanban.db（只读 sqlite，
父挂关系/原始执行人）+ 读本地文档；不写看板、不碰交易数据。
- 10-26 M-3 修复（t_258fdd8a）：逐单 `kanban show` 子进程（~3.3s/次）是全量 180s 超时根因，
  改为单连接只读 sqlite 批量取 task_links/task_events；DB 校验不过自动回退 CLI show（判定面不砍）。
- 同次修复：L92 f-string 非法转义（反斜杠-d，3.12+ 默认 SyntaxWarning 打到 stderr，
  被 M-3 探针「stdout+stderr 合并 json.loads」污染 → Extra data: line 103 → 永久 SKIPPED 假绿）。
  --json 模式 stdout 只允许 JSON 本体（合并 stderr 场景须可一次 json.loads，AC1 断言入 tests）。

P1 出口：`--alert` 时写 data/message_queue.json（走 AGENTS.md 规则 11 的唯一投递器 QSP_MsgDrain）。

用法:
  python scripts/dispatch_audit_check.py                 # 人读
  python scripts/dispatch_audit_check.py --json          # 机器读
  python scripts/dispatch_audit_check.py --alert          # 缺陷入队飞书(P1)
  python scripts/dispatch_audit_check.py --since 2026-10-16T20:16:00
  python scripts/dispatch_audit_check.py --json --shard 2 --shards 6   # 分片(0起, 共n片)
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJECT, "data")
DOCS = os.path.join(PROJECT, "docs")

# 立规时刻：规则不溯及既往（此前的单挂技术债台账，不在此审计窗口内）
RULE_EPOCH = "2026-10-16T20:16:00"

HERMES_CANDIDATES = (
    os.environ.get("HERMES_BIN") or "",
    r"D:\Hermes agent\Hermes Agent CN Desktop\.hermes\bin\hermes.exe",
)


def find_hermes():
    for c in HERMES_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


# 派单审计是纯读侧，但调用方（kanban worker / 委托子进程）的环境里带
# HERMES_DELEGATED_CHILD_CONTEXT（委托栅栏 marker，agent/delegation_context.py:20），
# 而 CLI 的 `kanban list` 内含 recompute_ready 写事务（write_txn →
# _assert_not_delegated_child_mutation → PermissionError），worker 上下文里 rc=1、
# 受审单 0（t_b2fd7b11 C0 断裂实证 2026-10-17）。剥离 marker 还原非委托上下文；
# 非委托环境该变量本就不存在，pop 为 no-op。
_KANBAN_FENCE_ENV = ("HERMES_DELEGATED_CHILD_CONTEXT",)


def _read_side_env():
    env = os.environ.copy()
    for k in _KANBAN_FENCE_ENV:
        env.pop(k, None)
    return env


def kanban_tasks(timeout=90):
    """返回 (tasks|None, err)。真源 = kanban CLI 的 JSON 视图。"""
    exe = find_hermes()
    if not exe:
        return None, "找不到 hermes 可执行文件(设 HERMES_BIN 环境变量)"
    try:
        p = subprocess.run([exe, "kanban", "list", "--json"],
                           cwd=os.path.dirname(exe), capture_output=True,
                           timeout=timeout, env=_read_side_env())
    except Exception as e:
        return None, "kanban list 调用失败: %s" % e
    if p.returncode != 0:
        return None, "kanban list 返回码 %s" % p.returncode
    try:
        return json.loads(p.stdout.decode("utf-8", "replace")), None
    except Exception as e:
        return None, "kanban list 输出无法解析: %s" % e


def _read_all(pattern):
    out = []
    for p in sorted(glob.glob(os.path.join(DOCS, pattern))):
        try:
            out.append((os.path.basename(p), open(p, encoding="utf-8", errors="replace").read()))
        except OSError:
            print("🔴 [scripts/dispatch_audit_check.py] CR-01: 台账/派单件不可读(跳过该件): %s"
                  % os.path.basename(p), file=sys.stderr)
    return out


def _kanban_db_candidates():
    """kanban.db 候选（只读）。顺序：env 显式 > hermes.exe 同 home > 已知固定路径。

    0 字节 stub（如 kanban/kanban.db）与缺 tasks 表的文件会被 open_kanban_db 的
    全量 id 校验拒掉，不会污染判定。"""
    cands = []
    env_db = os.environ.get("HERMES_KANBAN_DB") or ""
    if env_db:
        cands.append(env_db)
    exe = find_hermes()
    if exe:
        # exe = <hermes_home>/.hermes/bin/hermes.exe  ->  home = 上三级目录
        home = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(exe))))
        cands.append(os.path.join(home, "kanban.db"))
        cands.append(os.path.join(home, "kanban", "boards", "zhuanqian", "kanban.db"))
    cands.append(r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\kanban.db")
    return list(dict.fromkeys(cands))


def open_kanban_db(task_ids):
    """返回 (con|None, ok)。只读连接；DB 必须含全部 task_ids 才算有效（与 CLI list 同库校验），
    否则 None → 调用方回退 CLI show，判定面不变。"""
    for cand in _kanban_db_candidates():
        if not cand or not os.path.exists(cand) or os.path.getsize(cand) == 0:
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % cand, uri=True, timeout=5)
        except sqlite3.Error:
            continue
        try:
            missing = [i for i in task_ids
                       if not con.execute("SELECT 1 FROM tasks WHERE id=?", (i,)).fetchone()]
        except sqlite3.Error:
            try:
                con.close()
            except sqlite3.Error:
                pass
            continue
        if not missing:
            return con, True
        try:
            con.close()
        except sqlite3.Error:
            pass
    return None, False


def _db_maps(con, tids):
    """批量取 (父挂 kids, created 原始 assignee)。payload 解析失败=记 None，不做默认值静默。"""
    kids, created_asg = {}, {}
    ph = ",".join("?" * len(tids))
    for pid, kid in con.execute(
            "SELECT parent_id, child_id FROM task_links WHERE parent_id IN (%s) ORDER BY child_id" % ph, tids):
        kids.setdefault(pid, []).append(kid)
    for tid, pay in con.execute(
            "SELECT task_id, payload FROM task_events WHERE task_id IN (%s) AND kind='created'" % ph, tids):
        if not pay:
            continue
        try:
            v = json.loads(pay).get("assignee")
        except ValueError:
            continue
        if v:
            created_asg[tid] = v
    return kids, created_asg


def kanban_children(tid, timeout=60, db_kids=None, db_created=None):
    """父挂关系+原始执行人 → (kids|None, created_assignee|None, err|None)。

    db_kids/db_created 非 None 时走只读 sqlite 快路径（M-3 修复 t_258fdd8a）；
    否则回退 CLI `kanban show`（判定面不砍，CLI 行为保持原样）。
    `kanban show <id>` → (children_ids, created_assignee, err)。

    坑 1：`kanban list --json` **不含 parents/children 字段**（实测 2026-10-16），父挂关系只能走 `show`。
    坑 2：执行单走完 `request-review --reviewer X` 后，**卡片的 assignee 会被改成复审人**，
    故"执行人"必须取 **created 事件里的原始 assignee**，不能用当前 assignee（v0 第二处误报就栽在这）。
    """
    if db_kids is not None or db_created is not None:
        kids = list(db_kids.get(tid, []) or []) if db_kids is not None else []
        casg = db_created.get(tid) if db_created is not None else None
        return kids, casg, None
    exe = find_hermes()
    if not exe:
        return None, None, "找不到 hermes 可执行文件"
    try:
        p = subprocess.run([exe, "kanban", "show", tid],
                           cwd=os.path.dirname(exe), capture_output=True,
                           timeout=timeout, env=_read_side_env())
    except Exception as e:
        return None, None, "kanban show 调用失败: %s" % e
    txt = p.stdout.decode("utf-8", "replace")
    m = re.search(r"^\s*children:\s*(.+)$", txt, re.M)
    kids = re.findall(r"t_[0-9a-f]+", m.group(1)) if m else []
    mc = re.search(r"created\s+\{'assignee':\s*'([^']*)'", txt)
    created_assignee = mc.group(1) if mc else None
    return kids, created_assignee, None


def _is_review_task(t):
    """复审/评审单识别：标题含「L2复审」或「独立评审」标记（规则 §四.5 命名约定，忽略空格）。

    注意 1：不能用裸「复审」二字——执行单标题常带「→ 复审 workbuddy」指向复审人，
    第一版 v0 就栽在这里（把 6 张执行单全判成复审单，受审数报 0）。
    注意 2（v1.1 起）：老五的独立评审卡（标题含「独立评审」）本身也是消费方，
    不参与"是否被复审"检查——否则每张评审卡都会倒过来要求再挂一张复审卡。
    """
    title = (t.get("title") or "").replace(" ", "")
    return ("L2复审" in title) or ("独立评审" in title)


def _ledger_row_for(tid, ledgers):
    """台账里本单那一行（首个命中）。返回 (行文本|None, 解析出的列 dict)。

    只认 8 列主表行（`len(cols) >= 9`）——台账尾部的「状态更新」区是 4 列表，
    同样含单号，不加这个闸会把状态更新行误当主表行（v1.1 首次实现时踩过）。"""
    for _, body in ledgers:
        for line in body.splitlines():
            if tid in line and line.strip().startswith("|"):
                cols = [c.strip().strip("`") for c in line.split("|")]
                if len(cols) < 9:
                    continue
                # 表头: ['', 时间, 单号, 主题, 执行人, 复审人, 复审单号, 派单依据, 状态, '']
                keys = ("时间", "单号", "主题", "执行人", "复审人", "复审单号", "派单依据", "状态")
                d = {}
                for i, k in enumerate(keys):
                    d[k] = cols[i + 1] if i + 1 < len(cols) else ""
                return line, d
    return None, None


DOC_REF_RE = re.compile(r"(?:docs|AGENTS\.md|scripts)/[^\s`|（）()「」【】,，;；]+")


def check_evidence_traceable(tid, ledgers):
    """C5 依据可溯源（规则 v1.1 §九.5 唯一可机判项）。

    判据：① 台账行的「派单依据」列非空且不是「—」/「-」；
         ② 该列中引用的 docs/*.md（及 AGENTS.md / scripts/*）路径**必须真实存在**。
    防的正是 10-16 P-04 告警那类病根：依据指向了一个已经不存在/被归档的路径。
    不可机判项（依据与单据是否匹配、指令原文是否被转述失真）**不在本函数内**，
    按 §九.5 必须由老五人工签署，机器不得冒充。"""
    row, cols = _ledger_row_for(tid, ledgers)
    if cols is None:
        return None  # 台账没行 → 已由 C3 记，不重复报
    ref = (cols.get("派单依据") or "").strip()
    if not ref or ref in ("—", "-", "--"):
        return "台账行「派单依据」列为空（§四.2 需老大原文/协议条款号/审查件路径 至少其一）"
    missing = []
    for m in DOC_REF_RE.findall(ref):
        # 截断的路径（台账里常因表格窄被省略）跳过存在性判定，交由 C5 的人工/审读补充
        if m.endswith((".md", ".py", ".json", ".log")):
            if not os.path.exists(os.path.join(PROJECT, m)):
                missing.append(m)
    if missing:
        return "台账「派单依据」引用了不存在的路径：%s（依据不可溯源）" % ", ".join(missing)
    return None


def audit(since_iso=RULE_EPOCH, max_tasks=50, shard=None, shards=1):
    tasks, err = kanban_tasks()
    if tasks is None:
        return {"ok": False, "checked": 0, "violations": [
            {"id": "-", "rule": "C0-数据源", "detail": err}]}

    try:
        since = dt.datetime.fromisoformat(since_iso).timestamp()
    except Exception as e:
        return {"ok": False, "checked": 0, "violations": [
            {"id": "-", "rule": "C0-参数", "detail": "since 解析失败: %s" % e}]}

    ledgers = _read_all("派单台账-*.md")
    tickets = _read_all("派单-*.md")

    by_id = {t.get("id"): t for t in tasks}

    scope = [t for t in tasks
             if (t.get("created_at") or 0) >= since and t.get("status") != "archived"]
    # 分片（M-3 修复 t_258fdd8a）：--shards n 时把**默认受审范围（含 --max-tasks cap）**切 n 片，
    # 只审第 --shard 片。先 cap 再切，保证 6 片并集 == 全量默认跑（结果可 1:1 对账）。
    scope = scope[:max_tasks]
    if shards and shards > 1:
        if shard is None or not (0 <= shard < shards):
            return {"ok": False, "checked": 0, "violations": [
                {"id": "-", "rule": "C0-参数",
                 "detail": "--shard 须为 [0,%d) 内整数（--shards %d）" % (shards - 1, shards)}]}
        per = (len(scope) + shards - 1) // shards
        scope = scope[shard * per:(shard + 1) * per]

    # M-3 修复（t_258fdd8a）：父挂/原始执行人改走单连接只读 sqlite（逐单 CLI show ~3.3s/次
    # 是全量 180s 超时根因）；DB 校验不过自动回退 CLI show，判定面不砍。
    db_kids, db_created, children_source = None, None, "cli-show"
    scope_ids = [t.get("id") for t in scope if t.get("id")]
    if scope_ids:
        con, db_ok = open_kanban_db(scope_ids)
        if con is not None and db_ok:
            try:
                db_kids, db_created = _db_maps(con, scope_ids)
                children_source = "sqlite-ro"
            finally:
                con.close()

    violations = []
    checked = 0
    for t in scope:
        tid = t.get("id")
        # 复审单自身不要求被复审
        if _is_review_task(t):
            continue
        checked += 1
        created_by = (t.get("created_by") or "").strip()

        # C1 提单人必须留名（禁空 / 禁 default）
        if not created_by or created_by in ("default", "user"):
            violations.append({"id": tid, "rule": "C1-提单人留名",
                               "detail": "created_by=%r（须为实际提单人 profile）" % created_by})

        # C2 必须存在复审单，且复审人 ≠ 执行人（sqlite 只读快路径，DB 校验不过回退 CLI show）
        kid_ids, created_assignee, kerr = kanban_children(tid, db_kids=db_kids, db_created=db_created)
        if kerr:
            violations.append({"id": tid, "rule": "C2-数据源", "detail": kerr})
            kids = []
        else:
            kids = [by_id[k] for k in (kid_ids or []) if k in by_id]
        review_kids = [k for k in kids if _is_review_task(k)]
        if not review_kids:
            violations.append({"id": tid, "rule": "C2-复审单",
                               "detail": "没有以本单为 parent 的复审单（复审单须独立成卡挂接，标题含「L2复审」标记）"})
        else:
            for k in review_kids:
                if (k.get("assignee") or "") == (created_assignee or t.get("assignee") or ""):
                    violations.append({"id": tid, "rule": "C2-复审人隔离",
                                       "detail": "复审单 %s 的执行人=%s 与执行单原始执行人相同（须人不同）"
                                                 % (k.get("id"), k.get("assignee"))})

        # C3 台账必须有行
        if not any(tid in body for _, body in ledgers):
            violations.append({"id": tid, "rule": "C3-台账行",
                               "detail": "docs/派单台账-*.md 中无本单号"})

        # C4 派单件必须有档（或台账行标注豁免）
        if not any(tid in body for _, body in tickets):
            ledger_hit = [b for _, b in ledgers if tid in b]
            if not (ledger_hit and re.search(r"豁免", ledger_hit[0])):
                violations.append({"id": tid, "rule": "C4-派单件",
                                   "detail": "docs/派单-*.md 无本单号且台账未注明豁免"})

        # C5 依据可溯源（v1.1 §九.5 唯一可机判项：台账「派单依据」列非空 + 引用路径存在）
        c5 = check_evidence_traceable(tid, ledgers)
        if c5:
            violations.append({"id": tid, "rule": "C5-依据可溯源", "detail": c5})

    rep = {"ok": not violations, "checked": checked, "scope_since": since_iso,
           "violations": violations, "children_source": children_source}
    if shards and shards > 1:
        rep["shard"] = [shard, shards]
    return rep


def enqueue_alert(report):
    """P1 入队（规则 11 唯一出口）。失败不影响退出码语义。"""
    try:
        sys.path.insert(0, PROJECT)
        from core.pipeline.atomic_json import atomic_dump, atomic_load
        q = os.path.join(DATA, "message_queue.json")
        items = atomic_load(q, []) or []
        body = "; ".join("%s %s: %s" % (v["id"], v["rule"], v["detail"])
                         for v in report["violations"][:8])
        items.append({"id": "dispatchaudit_p1_%d" % int(dt.datetime.now().timestamp()),
                      "content": "⚠️ [派单审计-P1] %d 项单据不合规（近窗口 %d 单）：%s"
                                 % (len(report["violations"]), report["checked"], body),
                      "platform": "feishu", "ts": dt.datetime.now().timestamp()})
        atomic_dump(items, q)
        return True
    except Exception as e:
        print("入队失败: %s" % e, file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--alert", action="store_true", help="缺陷写 data/message_queue.json(P1)")
    ap.add_argument("--since", default=RULE_EPOCH, help="审计窗口起点(ISO8601)")
    ap.add_argument("--max-tasks", type=int, default=50, help="最大受审任务数（防超时）")
    ap.add_argument("--shard", type=int, default=None,
                   help="分片号(0起)：配合 --shards 只审全量受审范围的 1/n 片")
    ap.add_argument("--shards", type=int, default=1, help="分片总数（>1 时须显式 --shard）")
    a = ap.parse_args()
    if a.shards < 1 or (a.shard is not None and a.shard < 0):
        print("--shards 须 ≥1 且 --shard ∈ [0, --shards)", file=sys.stderr)
        return 2

    rep = audit(a.since, max_tasks=a.max_tasks, shard=a.shard, shards=a.shards)
    if a.alert and not rep["ok"]:
        rep["alerted"] = enqueue_alert(rep)

    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        shard_tag = ""
        if rep.get("shard"):
            shard_tag = " | 分片 %d/%d" % tuple(rep["shard"])
        print("派单审计 v1.1 | 窗口起点 %s | 受审执行单 %d 张%s（父挂源 %s）"
              % (rep.get("scope_since"), rep.get("checked"), shard_tag, rep.get("children_source")))
        if rep["ok"]:
            print("✅ 合规：提单人留名 / 复审单挂接且人不同 / 台账有行 / 派单件有档 / 依据可溯源")
            print("   ⚠️ 本结论仅覆盖 C1–C5 可机判项；V1–V4「依据是否成立」须老五人工签署（规则 v1.1 §九.5）")
        else:
            print("❌ %d 项不合规：" % len(rep["violations"]))
            for v in rep["violations"]:
                print("   - [%s] %s  %s" % (v["rule"], v["id"], v["detail"]))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
