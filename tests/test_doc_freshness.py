# -*- coding: utf-8 -*-
"""
[守卫 H4] 文档新鲜度机器校验（2026-10-17 W5 治理）

═══ 背景 ═══
治理前的状态：**完全没有**文档新鲜度校验。文档写完就放着，改了代码没人知道文档已过期，
于是 09-30 三方会签把止损 8%→10% 之后，6 处文档继续写 8% 达 17 天。

低成本做法：复用 `.agent/regression/__init__.py` **D 组**（"门禁数据文件存在性与新鲜度"）
的思路，把它扩展到 `.md`：
    D 组管"数据文件在不在、新不新鲜" → 本组管"治理文档在不在、跟没跟上真源、陈没陈旧"。

═══ 三条判据 ═══
1. **存在性** —— 治理文档必须存在（缺了 = 机制洞）。
2. **真源联动（本组的核心）** —— `risk_rules.py` 是契约唯一真源。文档头部带
   `TSS:<真源 SHA256 前12位>` 戳，声明"我是照着这一版真源写的"。
   真源变了而戳没刷新 → **FAIL**，提醒"先登记 CONTRACT-CHANGELOG + 广播，再刷新戳"。
   这比"按 mtime 猜新鲜度"确定：git checkout / 文件拷贝都不会误判。
3. **陈旧度** —— 决策台账/待拍板清单超过 `STALE_FAIL_DAYS` 天未更新 → FAIL（当前远未到期）。

═══ 为什么不是纯 mtime 比较 ═══
mtime 会被 git checkout、文件拷贝、备份还原意外刷新，产生"看起来新其实没跟上"的假绿。
TSS 戳比对的是**内容哈希**，只认内容。
"""
import hashlib
import json
import os
import re
import sys
import time

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUE_SOURCE = os.path.join(PROJECT, "core", "risk", "risk_rules_impl.py")
STAMP_PATH = os.path.join(PROJECT, ".agent", "true-source-stamp.json")

# ── 治理文档：缺一个就是机制洞 ──
GOVERNANCE_DOCS = [
    "BOOTSTRAP.md",
    "AGENTS.md",
    "docs/CONTRACT-CHANGELOG-20261017.md",
    "deliverables/决策台账-20261017.md",
    "deliverables/待老大拍板清单-20261017.md",
    ".workbuddy/RULES.md",
    ".workbuddy/PERSONA.md",
]

# ── 必须带真源戳的契约文档（真源一变，它们必须跟着复核）──
STAMPED_DOCS = [
    "AGENTS.md",
    ".workbuddy/RULES.md",
    "docs/CONTRACT-CHANGELOG-20261017.md",
]

# ── 陈旧度阈值 ──
STALE_FAIL_DAYS = 90          # 决策/拍板类文档超过此天数未更新 → FAIL
RE_TSS = re.compile(r"TSS:([0-9a-f]{12})")


def sha256_of(path):
    """真源内容哈希 —— 归一化换行符后再算(与 scripts/sync_true_source_stamp.py 同口径)。

    2026-10-19: 原按原始字节哈希, 本机 CRLF / git 库内 LF ⇒ 同一内容两个戳,
    守卫环境相关(可假红也可假绿)。改为 CRLF→LF 归一化, 使戳只反映内容。
    ⚠️ 修改此处必须同步 scripts/sync_true_source_stamp.py::sha256_of。
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        tail = b""
        for chunk in iter(lambda: fh.read(65536), b""):
            buf = tail + chunk
            if buf.endswith(b"\r"):
                tail, buf = buf[-1:], buf[:-1]
            else:
                tail = b""
            h.update(buf.replace(b"\r\n", b"\n"))
        if tail:
            h.update(tail)
    return h.hexdigest()


def _age_days(path):
    return (time.time() - os.path.getmtime(path)) / 86400.0


def test_governance_docs_exist():
    """H4-1：治理文档必须在位（缺一份 = 机制洞，与新会话入口无关但同样致命）。"""
    missing = [p for p in GOVERNANCE_DOCS if not os.path.exists(os.path.join(PROJECT, p))]
    assert not missing, "治理文档缺失:\n  " + "\n  ".join(missing)


def test_true_source_stamp_registered():
    """H4-2：真源当前版本必须已登记。真源变了却没登记 = 改了契约没走留痕/广播流程。"""
    assert os.path.exists(STAMP_PATH), (
        "缺少 .agent/true-source-stamp.json —— 跑 `python scripts/sync_true_source_stamp.py` 登记"
    )
    stamp = json.load(open(STAMP_PATH, encoding="utf-8"))
    cur = sha256_of(TRUE_SOURCE)
    assert stamp.get("risk_rules_sha256") == cur, (
        "真源 core/risk/risk_rules_impl.py 已变更，但 .agent/true-source-stamp.json 未刷新 →\n"
        "  当前真源 SHA: %s\n  已登记    SHA: %s\n"
        "处理顺序（**别跳步**）：\n"
        "  ① 在 docs/CONTRACT-CHANGELOG-20261017.md 登记本次变更\n"
        "  ② 跑 python scripts/broadcast_contract_change.py 广播\n"
        "  ③ 同步各契约文档头部的 TSS 戳\n"
        "  ④ 跑 python scripts/sync_true_source_stamp.py 刷新戳"
        % (cur, stamp.get("risk_rules_sha256"))
    )


def test_contract_docs_carry_current_stamp():
    """H4-2b：契约文档的 TSS 戳必须等于真源当前版本（声明"我照这一版真源写过/复核过"）。"""
    stamp = json.load(open(STAMP_PATH, encoding="utf-8"))
    expect = stamp["risk_rules_sha256"][:12]
    bad = []
    for rel in STAMPED_DOCS:
        full = os.path.join(PROJECT, rel)
        if not os.path.exists(full):
            bad.append((rel, "文件不存在"))
            continue
        m = RE_TSS.search(open(full, encoding="utf-8").read())
        if not m:
            bad.append((rel, "缺少 TSS 戳"))
        elif m.group(1) != expect:
            bad.append((rel, "戳 %s ≠ 真源 %s" % (m.group(1), expect)))
    assert not bad, (
        "契约文档未跟上真源（真源版本 %s）:\n  " % expect
        + "\n  ".join("%s — %s" % b for b in bad)
        + "\n\n处理：复核文档内容后把戳改为 TSS:%s，或跑 scripts/sync_true_source_stamp.py 看新戳。" % expect
    )


def test_decision_ledger_not_stale():
    """H4-3：决策台账 / 待拍板清单不得长期无人维护（超 STALE_FAIL_DAYS 天 → FAIL）。"""
    stale = []
    for rel in ("deliverables/决策台账-20261017.md", "deliverables/待老大拍板清单-20261017.md"):
        full = os.path.join(PROJECT, rel)
        if not os.path.exists(full):
            continue
        age = _age_days(full)
        if age > STALE_FAIL_DAYS:
            stale.append((rel, "%.0f 天未更新" % age))
    assert not stale, "决策类文档已陈旧（阈值 %d 天）:\n  " % STALE_FAIL_DAYS + "\n  ".join(
        "%s — %s" % s for s in stale)


def test_broadcast_auto_refreshes_true_source_stamp():
    """H4：广播脚本必须**自动**刷新真源戳（老大 2026-10-17 拍板：不许靠人肉记得跑一步）。

    静默跳过是这里最危险的失败模式 —— 戳不刷新不会报错，只会让 bootstrap 校验
    与文档新鲜度守卫**慢慢失真**。所以要求：失败 = exit 1 + 响亮打印。
    """
    bc = os.path.join(PROJECT, "scripts", "broadcast_contract_change.py")
    assert os.path.exists(bc), "缺少 scripts/broadcast_contract_change.py"
    src = open(bc, encoding="utf-8").read()
    assert "sync_true_source_stamp.py" in src, (
        "广播脚本未引用 sync_true_source_stamp.py —— 真源戳又变成'人肉记得跑'了")
    assert "refresh_true_source_stamp()" in src, "广播脚本未调用刷新函数"
    # 失败必须硬退出，且在写 CHANGELOG/记忆之前（顺序：先刷新，后落盘）
    assert "return 1" in src, "刷新失败必须 exit 1（响亮报错），不允许静默跳过"
    i_fail = src.index("if not ok:")
    i_changelog = src.index("# 1) CHANGELOG")
    assert i_fail < i_changelog, "刷新失败分支必须在写 CHANGELOG 之前（否则会留下'半条广播'）"
    # 新戳必须进广播内容（可追溯）
    assert "契约真源戳" in src, "广播内容未携带真源戳，不可追溯"


# ────────────── 先红后绿：证明守卫本身能检出 ──────────────
def test_selftest_detects_stale_and_drift():
    """自检：① 过期文档能被判定为陈旧 ② 戳不匹配能被识别 ③ 正确戳不误报。"""
    # ① 陈旧度判据：用 100 天前的时间戳验证阈值逻辑
    assert (time.time() - (time.time() - 100 * 86400)) / 86400.0 > STALE_FAIL_DAYS
    assert (time.time() - (time.time() - 1 * 86400)) / 86400.0 <= STALE_FAIL_DAYS
    # ② 戳解析：能取到、能比对
    assert RE_TSS.search("**TSS:f39cdae2961c** ← 真源戳").group(1) == "f39cdae2961c"
    assert RE_TSS.search("TSS:000000000000").group(1) != "f39cdae2961c"
    # ③ 不含戳的文本不应被误判为"有戳"
    assert RE_TSS.search("本文件没有戳") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
