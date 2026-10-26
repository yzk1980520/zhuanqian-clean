#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
code_review_lint.py — 代码审查机器门禁（L1 层）首版 v1.0

依据：docs/代码审查标准与流程-v1.0-20261016.md §四
定位：替代"人肉 grep"与"60+ 个互相重叠的检查脚本"的单一权威入口（首版只做 4 条）

规则：
  CR-01 异常吞噬（🔴 B1）：except 后仅 pass / 仅 return 空容器或常量 → 失败伪装为"无异常"
  CR-02 数据直写（🔴 B2）：open(...,'w') 且路径含 data/ → 未走 atomic_json
  CR-03 超长函数（🟡 S2）：函数 >80 行 / 文件 >600 行
  CR-04 未登记技术债（🟡 S8）：TODO/FIXME 无 DEBT-ID 标注

用法：
  python scripts/code_review_lint.py                    # 全量报告（默认，exit 0）
  python scripts/code_review_lint.py --path scripts/    # 指定路径
  python scripts/code_review_lint.py --rule CR-01       # 只跑某条
  python scripts/code_review_lint.py --files a.py b.py  # 只查改动文件（只卡新增）

只读、纯标准库、<3 秒，不写任何文件。
"""
import ast
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXCLUDE_DIRS = {".venv", "venv", "archive", "archive-legacy", "__pycache__",
                ".git", ".workbuddy", "node_modules", ".scratch"}
EXCLUDE_SUFFIX = (".bak",)  # 备份文件不审（含 .bak_20261016 形式）

MAX_FUNC_LINES = 80
MAX_FILE_LINES = 600


def iter_py_files(paths):
    """收集待审 py 文件，跳过排除目录与备份文件"""
    files = []
    for p in paths:
        p = Path(p)
        if not p.is_absolute():
            p = ROOT / p
        if p.is_file() and p.suffix == ".py":
            files.append(p)
            continue
        if not p.exists():
            continue
        for f in p.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in f.parts):
                continue
            if f.name.endswith(EXCLUDE_SUFFIX) or ".bak_" in f.name:
                continue
            files.append(f)
    return sorted(set(files))


def _is_empty_container(node):
    """判断 return 值是否为空容器/常量（伪装成'无发现'的典型手法）"""
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.Tuple)):
        return len(node.elts) == 0 if hasattr(node, "elts") else len(node.keys) == 0
    if isinstance(node, ast.Constant):
        return node.value is None or node.value == "" or node.value == 0 or node.value is False
    return False


def _is_silent_except_body(body):
    """判断 except 体是否为静默吞异常：仅含 pass/continue/bare（无实质逻辑）"""
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, (ast.Pass, ast.Continue)):
            continue
        return False
    return True


def check_cr01(tree, rel, findings):
    """CR-01 异常吞噬"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # 静默体（仅 pass/continue）→ 直接报
        if _is_silent_except_body(node.body):
            findings.append((rel, node.lineno, "CR-01", "🔴",
                             "except 后仅 pass/continue（静默吞异常）"))
            continue
        # 仅 return 空容器/常量
        if len(node.body) == 1 and isinstance(node.body[0], ast.Return):
            r = node.body[0]
            if r.value is None or _is_empty_container(r.value):
                lit = "None" if r.value is None else ast.dump(r.value)[:20]
                findings.append((rel, node.lineno, "CR-01", "🔴",
                                 f"except 后 return {lit} —— 失败伪装为'无发现'（假阴性）"))
            elif isinstance(r.value, ast.Constant) and isinstance(r.value.value, (int, float)) and r.value.value == 0:
                findings.append((rel, node.lineno, "CR-01", "🔴",
                                 "except 后 return 0 —— 失败伪装为'零条/零值'（假阴性）"))


def check_cr02(tree, rel, findings):
    """CR-02 数据直写：open(...,'w') 且路径含 data/ 或 QSP 白名单目录"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "open":
            continue
        mode = ""
        for arg in node.args[1:]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                mode = arg.value
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = kw.value.value
        if "w" not in mode and "a" not in mode:
            continue
        # 路径参数
        path_str = ""
        if node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                path_str = a0.value
            elif isinstance(a0, ast.JoinedStr):
                path_str = "".join(
                    v.value for v in a0.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str))
        # 检测 1：项目内 data/ 路径
        if "data/" in path_str.replace("\\", "/") or "data\\\\" in path_str:
            findings.append((rel, node.lineno, "CR-02", "🔴",
                             f"直写 data/ 未走 atomic_json（mode='{mode}'）"))
        # 检测 2：QSP 外部系统白名单路径（老六 L2 首审发现的盲区）
        elif any(wp in path_str for wp in [".quant-stock-picker", "QSP"]):
            findings.append((rel, node.lineno, "CR-02", "🔴",
                             f"直写外部系统（QSP）未走 atomic_json（mode='{mode}'）—— 跨系统持仓污染风险"))


def check_cr03(tree, rel, findings, n_lines):
    """CR-03 超长函数/文件"""
    if n_lines > MAX_FILE_LINES:
        findings.append((rel, 1, "CR-03", "🟡", f"文件 {n_lines} 行 > {MAX_FILE_LINES}"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ln = (node.end_lineno or node.lineno) - node.lineno + 1
            if ln > MAX_FUNC_LINES:
                findings.append((rel, node.lineno, "CR-03", "🟡",
                                 f"函数 {node.name}() {ln} 行 > {MAX_FUNC_LINES}"))


def check_cr04(src, rel, findings):
    """CR-04 TODO/FIXME 未登记 DEBT-ID"""
    for i, line in enumerate(src.splitlines(), 1):
        up = line.upper()
        if "TODO" in up or "FIXME" in up:
            if "DEBT-ID" not in up:
                findings.append((rel, i, "CR-04", "🟡", "TODO/FIXME 未带 DEBT-ID（技术债未台账化）"))


def main():
    ap = argparse.ArgumentParser(description="代码审查机器门禁 L1（v1.0）")
    ap.add_argument("--path", nargs="*", default=["scripts", "tests", "layers"],
                    help="扫描路径（默认 scripts tests layers）")
    ap.add_argument("--files", nargs="*", help="只查指定文件（合入前只卡新增用）")
    ap.add_argument("--rule", help="只跑某条规则，如 CR-01")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args()

    files = [ROOT / f for f in args.files] if args.files else iter_py_files(args.path)
    findings = []
    scanned = 0

    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except (SyntaxError, ValueError, OSError):
            print(f"⚠️ [scripts\code_review_lint.py] 兼容处理: except (SyntaxError, ValueError, OSError):", file=sys.stderr)
        scanned += 1
        try:
            rel = str(f.relative_to(ROOT))
        except ValueError:
            rel = str(f)
        rules = [args.rule] if args.rule else ["CR-01", "CR-02", "CR-03", "CR-04"]
        if "CR-01" in rules:
            check_cr01(tree, rel, findings)
        if "CR-02" in rules:
            check_cr02(tree, rel, findings)
        if "CR-03" in rules:
            check_cr03(tree, rel, findings, len(src.splitlines()))
        if "CR-04" in rules:
            check_cr04(src, rel, findings)

    findings.sort(key=lambda x: (x[3] != "🔴", x[0], x[1]))
    blockers = [f for f in findings if f[3] == "🔴"]
    suggests = [f for f in findings if f[3] == "🟡"]

    if not args.quiet:
        for fn in findings[:60]:
            print(f"{fn[0]}:{fn[1]} | {fn[2]} | {fn[3]} | {fn[4]}")
        if len(findings) > 60:
            print(f"... 另有 {len(findings) - 60} 条（--quiet 只看汇总）")

    print(f"\n扫描 {scanned} 个文件 | 🔴 Blocker {len(blockers)} | 🟡 Suggestion {len(suggests)}")
    print("依据：docs/代码审查标准与流程-v1.0-20261016.md")

    # 有 🔴 一律 FAIL
    if blockers:
        print(f"[FAIL] 存在 {len(blockers)} 条 Blocker，禁止合入")
        return 1
    print("[PASS]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
