# -*- coding: utf-8 -*-
"""
[守卫 H2/H3/H7] bootstrap 单一入口 + 回滚索引 + 环境预检

═══ 背景 ═══
2026-10-17 治理发现：系统有 **4 份引导入口并列**（AGENTS.md / CONTEXT.md /
mainline/docs/CAPABILITY-REGISTRY.md / mainline/docs/AGENT-EXECUTION-PROTOCOL-2026-09-27.md），
且**没有加载顺序** —— 新 Agent / 新会话全靠猜，谁先读到哪份就被哪份的口径带跑。
本守卫把 `BOOTSTRAP.md` 钉成唯一入口，并用**校验戳**（加载清单的有序 SHA256）保证：
清单被改名 / 删除 / 插入 / 换序 → 立刻红。

═══ 为什么是"有序 SHA256"而不是"逐条断言存在" ═══
逐条断言只能验"文件在不在"，验不出"顺序变了"和"少了一条"。
有序列表取哈希后，任何增删改序都会变值 —— 一条断言覆盖四种破坏。
"""
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP = os.path.join(PROJECT, "BOOTSTRAP.md")
BAK_INDEX = os.path.join(PROJECT, ".agent", "bak-index-20261017.json")
# 2026-10-24 T051 C4 对齐: 索引脚本 2026-10-23 S4 基地化已归档至 archive/scripts-20261023/
# (活跃层 scripts/build_bak_index.py 不再存在; 归档版 PROJECT 自动定位指向 archive/,
#  任何实跑都会触发重建写 archive/.agent/ 禁区 → 仅做静态检查, 禁止执行, 见 BOOTSTRAP.md §四)。
BAK_SCRIPT = os.path.join(PROJECT, "archive", "scripts-20261023", "build_bak_index.py")

# ── 从 BOOTSTRAP.md 的「一、加载顺序」表格中解析有序路径 ──
# 形如： | 1 | `AGENTS.md` | 团队契约 ... | ✅ 全文 |
RE_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`([^`]+)`\s*\|")
# 允许反引号/`**` 包裹（BOOTSTRAP.md 里会写成 **LOAD_ORDER_SHA256: `xxxx`**）
RE_STAMP = re.compile(r"LOAD_ORDER_SHA256:\s*\**\s*`?([0-9a-fA-F]{64})`?")


def _load_order():
    """返回 BOOTSTRAP.md §一 表格里的有序文件路径（已排除 BOOTSTRAP.md 自身）。"""
    if not os.path.exists(BOOTSTRAP):
        return []
    out = []
    with open(BOOTSTRAP, encoding="utf-8") as fh:
        for line in fh:
            m = RE_ROW.match(line.strip())
            if not m:
                continue
            path = m.group(2).strip()
            if path.endswith("BOOTSTRAP.md") or path == "BOOTSTRAP.md":
                continue
            out.append(path)
    return out


def _sha(paths):
    return hashlib.sha256("\n".join(paths).encode("utf-8")).hexdigest()


def test_bootstrap_exists():
    """H2：唯一引导入口必须存在（否则又回到"4 份并列全靠猜"）。"""
    assert os.path.exists(BOOTSTRAP), (
        "缺少 BOOTSTRAP.md —— 新会话将没有固定加载顺序，回到 4 份入口并列的旧病"
    )


def test_load_order_files_all_exist():
    """H2：BOOTSTRAP 清单里每个文件都必须真实存在（幽灵入口比没有入口更误导）。"""
    paths = _load_order()
    assert len(paths) >= 8, "引导清单条目 %d 偏少，解析规则可能失效" % len(paths)
    missing = [p for p in paths if not os.path.exists(os.path.join(PROJECT, p))]
    assert not missing, "BOOTSTRAP.md 引导清单指向不存在的文件:\n  " + "\n  ".join(missing)


def test_load_order_stamp_matches():
    """H2：加载顺序校验戳必须与清单当前内容一致（改名/删除/插入/换序 → 红）。"""
    text = open(BOOTSTRAP, encoding="utf-8").read() if os.path.exists(BOOTSTRAP) else ""
    m = RE_STAMP.search(text)
    assert m, "BOOTSTRAP.md 缺少 LOAD_ORDER_SHA256 校验戳"
    expect = _sha(_load_order())
    assert m.group(1) == expect, (
        "BOOTSTRAP.md 加载顺序已变，但校验戳未刷新。\n"
        "  清单 SHA256 = %s\n"
        "  请把 BOOTSTRAP.md 里的 LOAD_ORDER_SHA256 改为上面这个值（顺序变更必须是有意的）。"
        % expect
    )


def test_bootstrap_states_env_precheck():
    """H7：BOOTSTRAP 必须写清"跑之前的环境预检"，否则 PYTHONPATH/沙箱/venv 三坑会继续踩。"""
    text = open(BOOTSTRAP, encoding="utf-8").read()
    for token in ("unset PYTHONPATH", "numpy", "regression"):
        assert token in text, "BOOTSTRAP.md 环境预检节缺少关键项: %s" % token


def test_bak_index_exists_and_usable():
    """H3：.bak 索引必须存在且结构完整（188 个 .bak 长期无索引，改错找不到回滚点）。"""
    assert os.path.exists(BAK_SCRIPT), "缺少 scripts/build_bak_index.py"
    assert os.path.exists(BAK_INDEX), "缺少 .agent/bak-index-20261017.json（跑 scripts/build_bak_index.py 生成）"
    idx = json.load(open(BAK_INDEX, encoding="utf-8"))
    ents = idx.get("entries")
    assert isinstance(ents, list) and len(ents) >= 50, "索引条目异常: %r" % (len(ents) if ents else None)
    for e in ents:
        assert "bak" in e and "原文件" in e and "备份时间" in e and "改动摘要" in e, (
            "索引条目字段不全（索引必须含 时间戳/原文件/改动摘要）: %r" % e.get("bak")
        )


def test_bak_script_is_readonly_safe():
    """H3：索引脚本必须只读（`.bak` 备份不删是红线，脚本不得有删除动作）。"""
    src = open(BAK_SCRIPT, encoding="utf-8").read()
    for bad in ("os.remove", "os.unlink", "shutil.rmtree", "shutil.move"):
        assert bad not in src, "build_bak_index.py 含破坏性调用 %s —— .bak 不删是红线" % bad


def test_bak_index_find_works():
    """H3 端到端：--find 能真的查到回滚点（机制存在 ≠ 机制生效，必须有活体断言）。

    2026-10-24 T051 C4 对齐：索引脚本 S4 归档后，归档版 (archive/scripts-20261023/)
    的 PROJECT 自动定位指向 archive/，任何实跑（含 --find）都会触发 build() 重建并写
    archive/.agent/ 禁区（2026-10-24 实测撞过一次并清理）。查询语义改由**直接读索引**
    承担（与 --find 的过滤逻辑等价：按 原文件 子串命中）；待活跃等价件补建后恢复实跑。
    """
    idx = json.load(open(BAK_INDEX, encoding="utf-8"))
    ents = idx.get("entries", [])
    hit = [e for e in ents if "risk_rules.py" in (e.get("原文件") or "")]
    assert hit, "索引中 --find risk_rules.py 未命中任何回滚点（索引=%s）" % BAK_INDEX


# ────────────── 先红后绿：证明守卫本身能检出破坏 ──────────────
def test_selftest_detects_tampering():
    """自检：清单被删一条 / 换序 / 戳被改 → 三种破坏都必须被检出，防止守卫空转。"""
    base = ["AGENTS.md", "CONTEXT.md", ".workbuddy/RULES.md"]
    s0 = _sha(base)
    assert s0 != _sha(base[:-1]), "删一条未改变哈希 —— 校验戳失效"
    assert s0 != _sha([base[1], base[0], base[2]]), "换序未改变哈希 —— 校验戳失效"
    assert s0 != _sha(base + ["多一个.md"]), "插入未改变哈希 —— 校验戳失效"
    # 解析规则自检：能正确从表格行里取出路径与序号
    assert RE_ROW.match("| 1 | `AGENTS.md` | 团队契约 | ✅ |").groups() == ("1", "AGENTS.md")
    assert RE_STAMP.search("LOAD_ORDER_SHA256: " + "a" * 64).group(1) == "a" * 64
    # 反引号/`**` 包裹形态同样要能识别（首次落地时就是被这个形态卡红的，2026-10-17）
    assert RE_STAMP.search("**LOAD_ORDER_SHA256: `" + "b" * 64 + "`**").group(1) == "b" * 64


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
