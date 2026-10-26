#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_laosi_audit_task_contract.py — 规则14「契约块在位」对账回归（t_330700bd，老四 2026-10-21）

覆盖 5 项:
1. GREEN 基线: 合成 kanban DB 窗口内任务全带契约块 → check_task_contract rc=0
2. RED 注入: DB 副本注入缺块单（HERMES_KANBAN_DB 指向合成库，零生产副作用）→ rc=1 + R0 违规在案
3. 级别判定: 违规>0 → P1（含 R0 违规）/ P2（其余），None=合规（纯函数）
4. 24h 去重守卫: 09:30 cron 条目（content 内嵌 t_id）/ 自写条目（dedup_fp）/ 超 24h 过期 / 空队列
5. check_all dispatch 映射: check_task_contract 在 SUBCOMMANDS['dispatch'] + AUTO_RUN(300s)

所有 DB 测试用临时合成库（tasks 表，结构与 check_task_contract.find_kanban_db 读取的
6 字段兼容）+ HERMES_KANBAN_DB 环境变量覆盖，绝不触碰生产 hermes-home/kanban.db。
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import laosi_audit  # noqa: E402  模块级仅类定义+纯函数，无副作用


# ---------------------------------------------------------------- 合成库工具

COMPLIANT_BODY = """## 背景
测试单（合成）。

## 【契约块】
- input_contract: 独立任务
- acceptance_criteria:
  1. `python -m py_compile scripts/x.py` → exit=0
- output_contract: 改动清单 + 一手证据 + 回滚点
- retry_budget: 2
- degradation_path: ① 截短窗口复现 → ② 单变量定位 → 仍败 block kind=needs_input
"""


def _make_kanban_db(path, tasks):
    """建与生产同构的最小 tasks 表（check_task_contract 只读这 6 列）。"""
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT,"
        " status TEXT, assignee TEXT, created_at REAL)")
    con.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?)", tasks)
    con.commit()
    con.close()


def _run_checker(db_path):
    env = dict(os.environ)
    env["HERMES_KANBAN_DB"] = str(db_path)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_task_contract.py"),
         "--json", "--no-snapshot"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60)
    rep = json.loads((r.stdout or "").strip() or "{}")
    return r.returncode, rep


class TestContractCheckGreenRed(unittest.TestCase):
    """1+2: 合成库 GREEN 基线与 RED 注入（DB 副本 + HERMES_KANBAN_DB，零生产副作用）。"""

    def _tmp_db(self, tasks):
        fd, path = tempfile.mkstemp(prefix="kc_test_", suffix=".db")
        os.close(fd)
        _make_kanban_db(path, tasks)
        self.addCleanup(os.remove, path)
        return path

    def test_green_baseline_all_compliant(self):
        now = time.time()
        db = self._tmp_db([
            ("t_grn00001", "【R0】risk_rules 调参", COMPLIANT_BODY, "ready", "laosan", now),
            ("t_grn00002", "【P2】日报脚本修路径", COMPLIANT_BODY, "running", "laosi", now),
        ])
        rc, rep = _run_checker(db)
        self.assertEqual(rc, 0, rep)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["violations"], [])
        self.assertEqual(len(rep["compliant"]), 2)

    def test_red_injection_missing_block(self):
        now = time.time()
        db = self._tmp_db([
            ("t_red00001", "【R0】risk_rules 调参", COMPLIANT_BODY, "ready", "laosan", now),
            ("t_red00002", "【R0】trade_log 合并", "无契约块的裸单", "ready", "laosan", now),
            ("t_red00003", "【P2】脚本路径修正", "无契约块的裸单", "running", "laosi", now),
        ])
        rc, rep = _run_checker(db)
        self.assertEqual(rc, 1, rep)
        self.assertFalse(rep["ok"])
        vset = {v["id"] for v in rep["violations"]}
        self.assertEqual(vset, {"t_red00002", "t_red00003"})
        self.assertEqual(rep["r0_violations"], 1)
        self.assertEqual(rep["compliant"], ["t_red00001"])


class TestViolationLevel(unittest.TestCase):
    """3: 违规>0 → P1（含 R0）/ P2（其余）/ None=合规（纯函数判定）。"""

    def test_compliant_is_none(self):
        self.assertIsNone(laosi_audit.contract_violation_level(
            {"violations": [], "r0_violations": 0}))

    def test_r0_violation_is_p1(self):
        rep = {"violations": [{"id": "t_a", "r0": True}], "r0_violations": 1}
        self.assertEqual(laosi_audit.contract_violation_level(rep), "P1")

    def test_non_r0_violation_is_p2(self):
        rep = {"violations": [{"id": "t_b", "r0": False}], "r0_violations": 0}
        self.assertEqual(laosi_audit.contract_violation_level(rep), "P2")


class TestDedupGuard(unittest.TestCase):
    """4: 24h 去重守卫（防与 09:30 QSP_TaskContractCheck 重复入队）。"""

    def _item(self, **kw):
        base = {"id": "taskcontract_p1_1", "platform": "feishu", "ts": time.time()}
        base.update(kw)
        return base

    def test_zero_cron_style_content_match(self):
        # 09:30 cron 条目无 dedup_fp，靠 content 内嵌 t_id 匹配
        it = self._item(content=("⚠️ [任务契约审计-P1] 2 个在途单缺契约项: "
                                 "t_aaaa1111(R0)缺[C1-契约块]; t_bbbb2222(R1/R2)缺[C1-契约块]"))
        fp = laosi_audit.contract_queue_fingerprint(
            [{"id": "t_aaaa1111"}, {"id": "t_bbbb2222"}])
        self.assertTrue(laosi_audit.contract_dedup_hit([it], fp))

    def test_own_item_fp_exact_match(self):
        fp = "t_cccc3333|t_ddd4444"
        it = self._item(dedup_fp=fp)
        self.assertTrue(laosi_audit.contract_dedup_hit([it], fp))

    def test_expired_over_24h_not_hit(self):
        fp = "t_cccc3333"
        it = self._item(dedup_fp=fp, ts=time.time() - 90000)
        self.assertFalse(laosi_audit.contract_dedup_hit([it], fp))

    def test_empty_queue_no_hit(self):
        self.assertFalse(laosi_audit.contract_dedup_hit([], "t_cccc3333"))
        self.assertFalse(laosi_audit.contract_dedup_hit(None, "t_cccc3333"))

    def test_other_violation_set_no_hit(self):
        it = self._item(content="⚠️ ... t_cccc3333(R0)缺[C1-契约块] ...")
        fp = "t_aaaa1111"  # 不同的违规集
        self.assertFalse(laosi_audit.contract_dedup_hit([it], fp))


class TestCheckAllDispatchMapping(unittest.TestCase):
    """5: check_all dispatch 域接入记录（规则14 审计进必跑门禁，300s 预算同 dispatch_audit_check）。"""

    def test_dispatch_mapping_and_autorun(self):
        import importlib
        ca = importlib.import_module("check_all")
        self.assertIn("scripts/check_task_contract.py", ca.SUBCOMMANDS["dispatch"])
        self.assertEqual(ca.AUTO_RUN.get("scripts/check_task_contract.py"), 300)
        # 自检断言（模块导入即执行）：40 映射全覆盖，多一少一都会 ImportError
        # 2026-10-24 T051 C4 对齐: check_all.py 真源 SUBCOMMANDS 已收敛为 40 映射
        # (源 L219-222 import-time 断言 == 40; 旧 57 口径对应 S4 前的映射全集, 2026-10-24 核 40)
        self.assertEqual(len(ca._ALL_MAPPED), 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
