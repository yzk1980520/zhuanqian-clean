#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_dispatch_audit_check.py — 派单审计 v1.1 判据纯函数回归（t_b07a0064，老三 2026-10-21）

只测可隔离的纯函数/正则（不 subprocess 调 kanban CLI，零生产副作用）：
1. _is_review_task: 复审单标记识别（「L2复审」/「独立评审」，忽略空格；裸「复审」/「→ 复审 x」不误判）
2. _ledger_row_for: 8 列主表行解析 + 4 列状态更新行闸门（v1.1 踩坑回归）
3. check_evidence_traceable: C5 四态（无行→None / 空列→违规 / —列→违规 / 引用不存在路径→违规 / 引用存在路径→None）
4. DOC_REF_RE: docs/*.md 路径引用提取（截断路径与裸 AGENTS.md 条款号不误提取）
5. _read_all: 台账 glob 读取（tmp DOCS 重定向，不碰真实 docs/）
"""
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dispatch_audit_check as dac  # noqa: E402


class TestIsReviewTask(unittest.TestCase):
    def _mk(self, title):
        return {"id": "t_x", "title": title}

    def test_l2_marker(self):
        self.assertTrue(dac._is_review_task(self._mk("【L2复审】P1 复审")))

    def test_l2_marker_ignore_spaces(self):
        self.assertTrue(dac._is_review_task(self._mk("【L2 复审】P1 复审")))

    def test_independent_review_marker(self):
        self.assertTrue(dac._is_review_task(self._mk("老五 独立评审 卡")))

    def test_bare_review_not_matched(self):
        self.assertFalse(dac._is_review_task(self._mk("执行单 → 复审 workbuddy")))

    def test_rework_card_no_marker(self):
        # t_369502f1 先例：返工卡标题含「L2复审」字样即被误判（v0 教训），
        # 去标记后须不再识别为复审单
        self.assertFalse(dac._is_review_task(self._mk("【P1-E 返工·E4打回】打回4项修复")))


class TestLedgerRowFor(unittest.TestCase):
    ROW = ("| 19:50 | `t_aaaaaaaa` | 主题A | laosan | laowu | `t_bbbbbbbb` | "
           "`docs/派单授权与审计规则-v1.0-20261016.md` §四 | 补录 |")

    def test_main_row_parsed(self):
        ledgers = [("派单台账-x.md", self.ROW + "\n")]
        line, d = dac._ledger_row_for("t_aaaaaaaa", ledgers)
        self.assertIsNotNone(line)
        self.assertEqual(d["单号"], "`t_aaaaaaaa`".strip("`"))
        self.assertEqual(d["执行人"], "laosan")
        self.assertEqual(d["复审单号"], "t_bbbbbbbb")
        self.assertIn("派单授权", d["派单依据"])

    def test_status_update_row_gated(self):
        # 状态更新区 4 列表同样含单号，不加 len>=9 闸会误当主表行（v1.1 首实现踩过）
        body = self.ROW + "\n| 20:00 | t_cccccccc | 更新 | 证据 |\n"
        ledgers = [("派单台账-x.md", body)]
        line, d = dac._ledger_row_for("t_cccccccc", ledgers)
        self.assertIsNone(line)
        self.assertIsNone(d)

    def test_missing_tid(self):
        line, d = dac._ledger_row_for("t_99999999", [("派单台账-x.md", self.ROW)])
        self.assertIsNone(line)


class TestEvidenceTraceable(unittest.TestCase):
    def _ledger(self, basis):
        row = ("| 19:50 | `t_aaaaaaaa` | 主题A | laosan | laowu | `t_bbbbbbbb` | %s | 补录 |" % basis)
        return [("派单台账-x.md", row)]

    def test_no_row_returns_none(self):
        # 台账没行 → 由 C3 记，不重复报
        self.assertIsNone(dac.check_evidence_traceable("t_aaaaaaaa", [("派单台账-x.md", "无关内容")]))

    def test_empty_basis(self):
        err = dac.check_evidence_traceable("t_aaaaaaaa", self._ledger("—"))
        self.assertIsNotNone(err)
        self.assertIn("派单依据", err)

    def test_dash_basis(self):
        self.assertIsNotNone(dac.check_evidence_traceable("t_aaaaaaaa", self._ledger("-")))

    def test_missing_path(self):
        err = dac.check_evidence_traceable("t_aaaaaaaa", self._ledger("`docs/不存在-噪声-9999.md` 依据"))
        self.assertIsNotNone(err)
        self.assertIn("不存在", err)

    def test_existing_path(self):
        # 真实存在路径（读侧只 os.path.exists，不改盘）
        # 2026-10-24 T051 C4 对齐: 规则文档 2026-10-22 归档至 docs/archive/historical-20261015-16/
        err = dac.check_evidence_traceable("t_aaaaaaaa",
                                           self._ledger("`docs/archive/historical-20261015-16/派单授权与审计规则-v1.0-20261016.md` §四"))
        self.assertIsNone(err)


class TestDocRefRe(unittest.TestCase):
    def test_doc_path_extracted(self):
        m = dac.DOC_REF_RE.findall("依据 docs/派单授权与审计规则-v1.0-20261016.md §四 与 scripts/x.py")
        self.assertEqual(m, ["docs/派单授权与审计规则-v1.0-20261016.md", "scripts/x.py"])

    def test_bare_agents_md_clause_not_matched(self):
        # 裸「AGENTS.md 规则 12」无斜杠路径 → 不提取（不触发存在性判定）
        self.assertEqual(dac.DOC_REF_RE.findall("AGENTS.md 规则 12"), [])

    def test_truncated_path_still_captured(self):
        m = dac.DOC_REF_RE.findall("docs/派单-批量-派单固化与四件授")
        self.assertEqual(len(m), 1)
        self.assertFalse(m[0].endswith(".md"))  # 截断路径交人工审读（§九.5 设计）


class TestReadAll(unittest.TestCase):
    def test_glob_and_read(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="dac_test_docs_"))
        f1 = tmp / "派单台账-9999.md"
        f1.write_text("内容一\n", encoding="utf-8")
        f2 = tmp / "派单-9999.md"
        f2.write_text("内容二\n", encoding="utf-8")
        old_docs = dac.DOCS
        try:
            dac.DOCS = str(tmp)
            ledgers = dac._read_all("派单台账-*.md")
            self.assertEqual([n for n, _ in ledgers], ["派单台账-9999.md"])
            tickets = dac._read_all("派单-*.md")
            self.assertEqual([b for _, b in tickets], ["内容二\n"])
        finally:
            dac.DOCS = old_docs
            f1.unlink(missing_ok=True)
            f2.unlink(missing_ok=True)
            tmp.rmdir()


if __name__ == "__main__":
    unittest.main(verbosity=2)
