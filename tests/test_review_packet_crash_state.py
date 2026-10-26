#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
review_packet 崩态自测（P0 修复验证，2026-10-16 老三）

验收依据：老六 L2 二审报告 §4 P0
  - tuple/dict 形状失配 → render_md L308 崩
  - 修：_norm 归一化（命中项统一为 dict 再渲染）
  - 崩态自测：构造 1 例非空 CR 命中 → 包正常渲染，非 traceback

本文件为独立自测用例，直接 import review_packet 模块调用 render_md，
不依赖 git / code_review_lint，确保崩态修复可复验。
"""
import sys
import os

# 项目根目录
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import review_packet as rp


def test_render_md_with_tuple_findings_no_crash():
    """P0: tuple findings → render_md 不崩，表格正常渲染"""
    # 模拟 code_review_lint 产出的 5 元组格式 findings
    findings = [
        ("scripts/tdx_batch_converter.py", 68, "CR-01", "🔴",
         "except 后 return None —— 失败伪装为'无发现'"),
        ("scripts/foo.py", 10, "CR-04", "🟡",
         "TODO/FIXME 未带 DEBT-ID"),
    ]
    meta = {"title": "P0 crash-state self-test", "ts": "2026-10-16", "base": "HEAD"}
    files = [("scripts/tdx_batch_converter.py", None, None)]
    audits = []

    md = rp.render_md(meta, files, audits, findings, None)

    # 断言1: 不崩（已正常返回字符串）
    assert isinstance(md, str), "render_md 应返回 str"
    # 断言2: L1 门禁表格已渲染
    assert "## 三、L1 机器门禁" in md, "缺少 L1 门禁章节"
    # 断言3: CR-01 🔴 在输出中
    assert "CR-01" in md, "CR-01 应在输出中"
    # 断言4: CR-04 🟡 在输出中
    assert "CR-04" in md, "CR-04 应在输出中"
    # 断言5: 位置信息正确
    assert "tdx_batch_converter.py:68" in md, "位置信息应正确"
    # 断言6: L2 checklist 预填项1显示命中1项（🔴计数）
    assert "L1 命中 1 项" in md, "checklist 应显示 🔴 命中数"

    print("✅ P0: render_md 接受 tuple findings 不崩，表格渲染正确")


def test_render_md_with_dict_findings_no_crash():
    """P0 对照: dict findings 同样正常（回归）"""
    findings = [
        {"file": "scripts/foo.py", "line": 5, "rule": "CR-02", "sev": "🔴",
         "msg": "直写 data/ 未走 atomic_json"},
    ]
    meta = {"title": "dict findings test", "ts": "2026-10-16", "base": "HEAD"}
    files = [("scripts/foo.py", None, None)]
    audits = []

    md = rp.render_md(meta, files, audits, findings, None)

    assert "CR-02" in md
    assert "foo.py:5" in md
    print("✅ P0 对照: dict findings 渲染正常")


def test_render_md_empty_findings_no_crash():
    """P0 边界: 空 findings 走 ✅ 分支（回归）"""
    meta = {"title": "empty test", "ts": "2026-10-16", "base": "HEAD"}
    files = []
    audits = []

    md = rp.render_md(meta, files, audits, [], None)

    assert "✅ 无 CR-01~CR-04 命中" in md
    print("✅ P0 边界: 空 findings 正常")


if __name__ == "__main__":
    test_render_md_with_tuple_findings_no_crash()
    test_render_md_with_dict_findings_no_crash()
    test_render_md_empty_findings_no_crash()
    print("\n✅ P0 review_packet 崩态自测 全部通过")
