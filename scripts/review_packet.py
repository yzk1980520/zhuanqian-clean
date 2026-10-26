#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
L2 审查输入包生成器（v1.0，2026-10-16）

定位：代码审查标准与流程 v1.1 §四 —— 审查人固定为老六后，审查质量依赖
"输入是否完整稳定"。本工具把每次 L2 审查必须看到的证据一次性打包，
杜绝"临时拼证据 → 漏判"（2026-10-16 R0-1 放行漏掉 fake_positive_detector.py:110
except→return [] 即因无稳定输入包）。

做什么：
  1. 改动清单（git diff --numstat / 或 --files 指定）
  2. 自动六查：
     A. 改动脚本是否有对应测试（tests/ 内是否引用该模块名）
     B. 红线区命中（止损/止盈/持仓/成交/风控类）
     C. 数据写入是否走 atomic_json（复用 CR-02）
     D. L1 门禁结果（复用 code_review_lint 的 CR-01~CR-04）
     E. 是否新增写侧动作（cron/数据文件/通知）→ 触发 §2.9 回授断言提醒
     F. 回滚点是否在位（.bak / commit 锚点 / 文件已入版本库）
  3. 输出 L2 checklist 预填（Markdown 底稿）

不做什么：不做判断、不修改任何文件、不代替 L2 人工审查。
只解决"证据完整性"，判断权在审查人。

用法：
  python scripts/review_packet.py --since <base-commit>        # 审查某提交以来的改动
  python scripts/review_packet.py --files scripts/a.py b.py    # 审查指定文件
  python scripts/review_packet.py --since HEAD~3 --out docs/review-packet-x.md
  python scripts/review_packet.py --since HEAD~3 --json        # 机器可读

纯标准库，只读，<5s。
"""
import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- 红线区识别（命中即提示需老大签字 / 最高审查强度）----------
RED_FILE_PAT = re.compile(
    r"(stop_loss|stop_profit|take_profit|risk|position|holdings|trade|order|execute|fill|capital)",
    re.I,
)
RED_CONTENT_PAT = re.compile(
    r"(止损|止盈|追高|0\.08|0\.04|120\s*(日|天)|max_drawdown|硬止损)", re.I
)

# ---------- 写侧动作识别（触发 §2.9 回授断言提醒）----------
WRITESIDE_PAT = re.compile(
    r"(message_queue|send_feishu|notification_sender|alert_log|cron_config|"
    r"jsonl|feedback_log|\.json\b.*append|append_finding)", re.I
)

# ---------- 数据写入识别 ----------
DATA_WRITE_PAT = re.compile(r"open\([^)]*data[/\\][^)]*['\"][wa]", re.I)


def _git(*args):
    """只读 git 调用，失败返回空串不抛异常（loud 但降级：标注 UNAVAILABLE）"""
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=30,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception as e:
        return f"__ERR__{e}"


def load_lint_module():
    """复用 code_review_lint.py 的规则函数，避免两套实现漂移"""
    p = os.path.join(ROOT, "scripts", "code_review_lint.py")
    if not os.path.exists(p):
        return None
    try:
        spec = importlib.util.spec_from_file_location("_crl", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        print(f"🔴 [scripts\review_packet.py] CR-01(return): except Exception:", file=sys.stderr)
        return None
TESTS_INDEX = {}


def build_tests_index():
    """一次性读入 tests/ 全文，用于判断'某模块是否有测试覆盖'"""
    td = os.path.join(ROOT, "tests")
    if not os.path.isdir(td):
        return
    for fn in os.listdir(td):
        if not fn.endswith(".py"):
            continue
        fp = os.path.join(td, fn)
        try:
            TESTS_INDEX[fn] = open(fp, encoding="utf-8", errors="ignore").read()
        except Exception:
            print(f"🔴 [scripts\review_packet.py] CR-01: except Exception:", file=sys.stderr)
def has_test(rel_path):
    """
    测试覆盖分两档——区分"真测了"与"看起来测了"：
      直接覆盖(direct)：tests/*.py 内容中出现模块名（import / 字符串引用）→ 真覆盖
      间接覆盖(indirect)：仅测试文件名与模块 token 重合，内容未引用 → 疑似"测了数据产物
                          而非被测函数"，属假绿风险，必须提示审查人人工核
    （2026-10-16 实测：tests/test_holdings_sync.py 92 行只校验 data/holdings.json，
      未 import sync_holdings.py —— 若只做文件名匹配就会误判为"有覆盖"）
    """
    mod = os.path.splitext(os.path.basename(rel_path))[0]
    if not mod or mod.startswith("_"):
        return None, None
    pat = re.compile(r"\b" + re.escape(mod) + r"\b")
    direct = [f for f, src in TESTS_INDEX.items() if pat.search(src)]
    toks = set(t for t in re.split(r"[_\-.]", mod.lower()) if t)
    indirect = []
    for f in TESTS_INDEX:
        if f in direct:
            continue
        fn = f.lower()
        for pre in ("test_", "test"):
            if fn.startswith(pre):
                fn = fn[len(pre):]
        fn = fn[:-3] if fn.endswith(".py") else fn
        ftoks = set(t for t in re.split(r"[_\-.]", fn) if t)
        inter = toks & ftoks
        if len(inter) >= 2 or (len(toks) == 1 and inter):
            indirect.append(f)
    return direct, indirect


def classify(rel):
    """改动类型标签"""
    if rel.startswith("tests/"):
        return "测试"
    if rel.startswith("scripts/"):
        return "脚本"
    if rel.startswith(("docs/", "mainline/docs/")) or rel.endswith(".md"):
        return "文档"
    if rel.endswith((".json", ".jsonl", ".yaml", ".yml")):
        return "配置/数据"
    if rel.endswith(".py"):
        return "代码(根目录)"
    return "其他"


def collect_files(since, files_arg):
    """返回 [(rel, added, deleted)]"""
    if files_arg:
        out = []
        for f in files_arg:
            ap = f if os.path.isabs(f) else os.path.join(ROOT, f)
            rel = os.path.relpath(ap, ROOT).replace("\\", "/")
            out.append((rel, None, None))
        return out
    numstat = _git("diff", "--numstat", f"{since}..HEAD")
    out = []
    for line in (numstat or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            a, d, rel = parts[0], parts[1], parts[2]
            try:
                out.append((rel, int(a) if a.isdigit() else 0, int(d) if d.isdigit() else 0))
            except ValueError:
                out.append((rel, 0, 0))
    return out


def run_lint(files_rel, lint):
    """只跑改动文件的 CR-01~CR-04"""
    if not lint:
        return None, "UNAVAILABLE: code_review_lint.py 缺失"
    findings = []
    for rel in files_rel:
        ap = os.path.join(ROOT, rel)
        if not (os.path.exists(ap) and rel.endswith(".py")):
            continue
        try:
            src = open(ap, encoding="utf-8", errors="ignore").read()
            tree = ast.parse(src)
        except Exception as e:
            findings.append({"rule": "CR-00", "sev": "🔴", "file": rel, "line": 0,
                             "msg": f"解析失败（语法错误？）: {e}"})
            continue
        n_lines = len(src.splitlines())
        try:
            lint.check_cr01(tree, rel, findings)
            lint.check_cr02(tree, rel, findings)
            lint.check_cr03(tree, rel, findings, n_lines)
            lint.check_cr04(src, rel, findings)
        except Exception as e:
            findings.append({"rule": "CR-ERR", "sev": "🟡", "file": rel, "line": 0,
                             "msg": f"规则执行异常: {e}"})
    return findings, None


def audit_file(rel):
    """单文件自动审查项：红线 / 写侧 / 测试 / 回滚点"""
    ap = os.path.join(ROOT, rel)
    res = {"rel": rel, "type": classify(rel), "red": [], "writeside": False,
           "tests": None, "tests_indirect": None, "git_tracked": None, "bak": False}
    if not os.path.exists(ap):
        res["missing"] = True
        return res
    res["git_tracked"] = bool(_git("ls-files", "--error-unmatch", rel))
    base = os.path.basename(rel)
    res["bak"] = any(
        f.startswith(base) and (".bak" in f or ".backup" in f)
        for f in os.listdir(os.path.dirname(ap) or ".")
    ) if os.path.isdir(os.path.dirname(ap) or ".") else False

    if not rel.endswith(".py"):
        return res
    try:
        src = open(ap, encoding="utf-8", errors="ignore").read()
    except Exception:
        return res
    res["tests"], res["tests_indirect"] = has_test(rel)
    for i, line in enumerate(src.splitlines(), 1):
        if RED_CONTENT_PAT.search(line):
            res["red"].append((i, line.strip()[:80]))
    if RED_FILE_PAT.search(rel) or res["red"]:
        res["is_red_zone"] = True
    if WRITESIDE_PAT.search(src) or DATA_WRITE_PAT.search(src):
        res["writeside"] = True
    return res


def render_md(meta, files, audits, findings, lint_err):
    L = []
    L.append(f"# L2 审查输入包 · {meta['title']}")
    L.append("")
    L.append(f"- 生成时间：{meta['ts']}")
    L.append(f"- 基准：{meta['base']}")
    L.append(f"- 改动文件：{len(files)} 个")
    L.append(f"- 生成工具：`scripts/review_packet.py`（只读，不代替审查判断）")
    L.append("")

    # 红旗区汇总
    reds = [a for a in audits if a.get("is_red_zone")]
    ws = [a for a in audits if a.get("writeside")]
    no_test = [a for a in audits
               if a["type"] in ("脚本", "代码(根目录)") and a.get("tests") is not None and not a["tests"]]
    indir = [a for a in audits
             if a["type"] in ("脚本", "代码(根目录)") and not a.get("tests") and a.get("tests_indirect")]
    L.append("## 一、需要审查人重点关注的信号")
    L.append("")
    L.append(f"| 信号 | 命中 | 含义 |")
    L.append("|---|---|---|")
    L.append(f"| 🔴 红线区改动 | {len(reds)} | 止损/止盈/持仓/成交/风控类，需最高审查强度（老大签字） |")
    L.append(f"| ⚠️ 写侧动作 | {len(ws)} | 新增/改动写侧 → 必须答 §2.9 回授断言三问（谁消费/多久/失败谁报） |")
    L.append(f"| 🧪 无测试覆盖的脚本 | {len(no_test)} | 改了生产脚本但没有测试引用它 |")
    L.append(f"| ⚠️ 疑似假覆盖 | {len(indir)} | 有同名测试但**未 import 被测模块**（只校验数据产物？）→ 假绿风险 |")
    L.append("")
    if reds:
        L.append("**红线区文件**：" + "、".join(f"`{a['rel']}`" for a in reds))
        L.append("")
    if ws:
        L.append("**写侧动作文件**：" + "、".join(f"`{a['rel']}`" for a in ws))
        L.append("")
    if no_test:
        L.append("**无测试覆盖**：" + "、".join(f"`{a['rel']}`" for a in no_test))
        L.append("")
    if indir:
        L.append("**疑似假覆盖（需人工核）**：" + "、".join(
            f"`{a['rel']}` ← {', '.join(a['tests_indirect'][:3])}" for a in indir))
        L.append("")

    # 改动清单
    L.append("## 二、改动清单")
    L.append("")
    L.append("| 文件 | 类型 | +行 | -行 | 测试覆盖 | 入版本库 | 回滚点 |")
    L.append("|---|---|---|---|---|---|---|")
    for a in audits:
        f = next((x for x in files if x[0] == a["rel"]), None)
        ad = f[1] if f and f[1] is not None else "—"
        de = f[2] if f and f[2] is not None else "—"
        if a["type"] == "测试":
            t = "—（自身即测试）"
        elif a.get("tests") is None:
            t = "—"
        elif a["tests"]:
            t = f"✅ {len(a['tests'])} 个"
        elif a.get("tests_indirect"):
            t = f"⚠️ 间接 {len(a['tests_indirect'])} 个·未import"
        else:
            t = "❌ 无"
        L.append(f"| `{a['rel']}` | {a['type']} | {ad} | {de} | {t} | "
                 f"{'✅' if a.get('git_tracked') else '❌'} | {'✅' if a.get('bak') else '—'} |")
    L.append("")

    # L1 门禁
    sev_order = {"🔴": 0, "🟡": 1}
    # findings 可能是 tuple (rel, lineno, rule, sev, msg) 或 dict，统一归一化
    def _norm(f):
        if isinstance(f, dict):
            return f
        # tuple: (file, line, rule, sev, msg)
        return {"file": f[0], "line": f[1], "rule": f[2], "sev": f[3], "msg": f[4]}
    normed = [_norm(x) for x in (findings or [])]
    normed.sort(key=lambda x: (sev_order.get(x.get("sev", ""), 9), x.get("rule", "")))
    L.append("## 三、L1 机器门禁（只跑改动文件）")
    L.append("")
    if lint_err:
        L.append(f"> {lint_err}")
    elif not normed:
        L.append("✅ 无 CR-01~CR-04 命中")
    else:
        L.append("| 级别 | 规则 | 位置 | 说明 |")
        L.append("|---|---|---|---|")
        for f in normed:
            loc = f"{f['file']}:{f['line']}" if f.get("line") else f["file"]
            L.append(f"| {f.get('sev','')} | {f.get('rule','')} | `{loc}` | {f.get('msg','')} |")
    L.append("")

    # L2 checklist 预填
    L.append("## 四、L2 审查 checklist（审查人填写）")
    L.append("")
    L.append("| # | 检查项 | 机器预填 | 审查人结论 |")
    L.append("|---|---|---|---|")
    L.append(f"| 1 | 改动是否有 🔴 级缺陷 | L1 命中 {sum(1 for f in normed if f.get('sev')=='🔴')} 项 | ☐ 通过 ☐ 打回 |")
    L.append(f"| 2 | 红线区改动是否有测试 + 老大签字 | 红线区 {len(reds)} 个 | ☐ 通过 ☐ 打回 |")
    L.append(f"| 3 | 写侧动作是否注册回授断言（§2.9） | 写侧 {len(ws)} 个 | ☐ 通过 ☐ 打回 |")
    L.append("| 4 | 是否有'先红后绿'证据（缺陷修复类） | 需人工核 | ☐ 通过 ☐ 打回 |")
    L.append("| 5 | 异常分支是否 loud fail（非静默默认值） | L1 CR-01 已扫 | ☐ 通过 ☐ 打回 |")
    L.append("| 6 | 回滚点是否在位 | .bak/commit | ☐ 通过 ☐ 打回 |")
    L.append("| 7 | 数据写入是否走 atomic_json | L1 CR-02 已扫 | ☐ 通过 ☐ 打回 |")
    L.append("")
    L.append("---")
    L.append("")
    L.append("> 本包只保证**证据完整**，不代表审查通过。判断权在 L2 审查人（老六）。")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="L2 审查输入包生成器（只打包证据，不代替审查）")
    ap.add_argument("--since", help="基准 commit，审查其到 HEAD 的改动")
    ap.add_argument("--files", nargs="*", help="直接指定改动文件")
    ap.add_argument("--out", help="输出 Markdown 路径（默认 stdout）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    ap.add_argument("--title", default="", help="包标题（如单号）")
    args = ap.parse_args()

    if not args.since and not args.files:
        ap.error("需指定 --since <commit> 或 --files <文件...>")

    build_tests_index()
    files = collect_files(args.since, args.files)
    if not files:
        print("⚠️ 未取到任何改动文件（git 可用？base 正确？）", file=sys.stderr)
        sys.exit(1)

    lint = load_lint_module()
    audits = [audit_file(r[0]) for r in files]
    py_rels = [a["rel"] for a in audits if a["rel"].endswith(".py") and not a.get("missing")]
    findings, lint_err = run_lint(py_rels, lint)

    meta = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base": args.since or "(--files 指定)",
        "title": args.title or f"{args.since or '指定文件'} 起",
    }

    if args.json:
        print(json.dumps({"meta": meta, "files": [{"rel": r[0], "add": r[1], "del": r[2]} for r in files],
                          "audits": audits, "findings": findings}, ensure_ascii=False, indent=2))
        return

    md = render_md(meta, files, audits, findings or [], lint_err)
    if args.out:
        op = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
        os.makedirs(os.path.dirname(op), exist_ok=True)
        with open(op, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"✅ 审查包已写入: {op}")
    else:
        print(md)


if __name__ == "__main__":
    main()
