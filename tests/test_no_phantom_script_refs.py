# -*- coding: utf-8 -*-
"""
[守卫 H6] 幽灵引用：文档指向不存在的脚本（2026-10-17 W5 治理）

═══ 背景 ═══
治理时发现 `scripts/check_data_freshness.py` **根本不存在**，却被多份文档引用为
"数据新鲜度检查的正确做法"。后来人照着做 → `python scripts/check_data_freshness.py`
→ 文件不存在 → 要么以为自己搞错了路径，要么以为"这个检查本来就跑不了"，
**两种结论都比"文档写错了"更伤**。这就是幽灵引用：文档把人主动带沟里。

同类项 `scripts/atomcode_rotate.py` 也是幽灵（见 PHANTOM_MAP），被 `channel.json`
登记为**老五的调度入口** —— 调度入口指向一个不存在的脚本，等于老五的自动派单从未真正接上。

═══ 判据 ═══
活跃治理文档里出现的 `scripts/xxx.py` 引用，**必须真实存在**；否则 FAIL，
并给出 `PHANTOM_MAP` 里登记的"真源在哪"（如果已查明）。

白名单必须写理由，不允许裸放行。
"""
import os
import re
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 强制层：这些文档是"会发号施令"的治理件，引用错了必须红 ──
ENFORCED_DOCS = [
    "BOOTSTRAP.md",
    "AGENTS.md",
    "CONTEXT.md",
    "README.md",
    ".workbuddy/RULES.md",
    ".workbuddy/PERSONA.md",
    "docs/CONTRACT-CHANGELOG-20261017.md",
    "deliverables/决策台账-20261017.md",
    "deliverables/待老大拍板清单-20261017.md",
    "team/职责.md",
]

RE_SCRIPT = re.compile(r"scripts/[A-Za-z0-9_\-]+\.py")

# ── 幽灵 → 真源映射（已查明的给出去处，未查明的标"待处置"）──
PHANTOM_MAP = {
    "scripts/check_data_freshness.py":
        "真源是**函数**不是脚本：health_monitor/checkers/data.py::check_data_freshness"
        "（tests/test_health_monitor.py:22 有 import 实证）。"
        "另有 hh/scripts/auto_tdx_refresh.py:155 同名函数（另一条链路，勿混）。",
    "scripts/atomcode_rotate.py":
        "**不存在**，但被 channel.json:11 登记为老五的调度入口、team/职责.md 引用。"
        "实际存在的是 scripts/atomcode_bridge.py。→ 待老大拍板：补建 rotate 脚本 / 或改指向 bridge。"
        "（deliverables/待老大拍板清单-20261017.md 议题 11）",
    # ── 2026-10-17 全量核查（议题 12）发现的同类项 ──
    "laowu_receive.py":
        "**生产位不存在**，只在 research_archive/laowu_receive.py（归档区）。"
        "被 channel.json:20 登记为 hermes_to_laowu 通道的 dispatch 执行体。",
    "scripts/check_gateway.py":
        "**不存在**。被 mainline/docs/CAPABILITY-REGISTRY.md、TEAM-COMMS-PROTOCOL.md 和"
        "项目记忆登记为『网关自检工具（2026-09-27 建）』。",
    "scripts/mount_pointer.py":
        "**不存在**。被 CAPABILITY-REGISTRY.md 与项目记忆登记为 CONFIG-MOUNT-SOP 的工具之一"
        "（同组的 scripts/check_protocol_mount.py **存在**）。",
    "team/relay.py":
        "**不存在**。被 TEAM-COMMS-PROTOCOL.md §2.7 与 CAPABILITY-REGISTRY.md 登记为终稿评审的中继入口。",
    "monthly_tune.py":
        "**不存在**。被 TEAM-COMMS-PROTOCOL.md 登记为月度调参入口。",
    "automation_system.py":
        "**生产位不存在**，只在 research_archive/automation_system.py（归档区）。"
        "被 AGENTS.md §6.1 登记为『老五审批闸』载体（选股执行前检查 review_status.json）。"
        "注意：闸的**读法**真源是 review_gate.py（存在），缺的是**执行体**。",
    "scripts/autodetect_blockers.py":
        "**不存在**。被 .agent/RUNBOOK.md 登记为阻塞项自动检测脚本。",
    "scripts/ic_monitor.py":
        "**不存在**。被 SOUL.md §3.4 复盘流程引用（SOUL.md 自 09-30 起未生效，已在白名单中）。",
    # ── 2026-10-23 S4 基地化归档件（活跃层不再存在, 出处已查明, 非"不存在"类幽灵）──
    "scripts/build_bak_index.py":
        "S4 归档至 archive/scripts-20261023/build_bak_index.py (2026-10-23)。归档版 PROJECT 自动定位"
        "指向 archive/, 实跑会写 archive/.agent/ 禁区 → 禁止在归档位执行 (2026-10-24 T051 核验, "
        "BOOTSTRAP.md §四 已对齐)。",
    "scripts/restore_archived_docs.py":
        "S4 归档至 archive/scripts-20261023/restore_archived_docs.py (2026-10-23)。归档版 REPO_ROOT "
        "自动定位指向 archive/ (禁区), 禁止在归档位实跑; 还原操作待活跃等价件补建。",
    "scripts/scan_archived_links.py":
        "S4 归档至 archive/scripts-20261023/scan_archived_links.py (2026-10-23)。归档版 REPO_ROOT "
        "自动定位指向 archive/, 实跑需以活跃等价件补建后执行。",
    "scripts/factor_weight_proposal.py":
        "S4 归档至 archive/scripts-20261023/factor_weight_proposal.py (2026-10-23)。",
    "scripts/purged_kfold.py":
        "S4 归档至 archive/scripts-20261023/purged_kfold.py (2026-10-23)。",
    "scripts/backtest_param_sweep.py":
        "S4 归档至 archive/scripts-20261023/backtest_param_sweep.py (2026-10-23)。",
}

# ── 白名单：(文件, 被引用脚本) → 理由 ──
WHITELIST = {
    ("SOUL.md", "scripts/data_freshness_check.py"):
        "SOUL.md 自 2026-09-30 起状态=待拍板**从未生效**，其 §3 每日流程是历史提案；"
        "2026-10-17 已在文件头标注『非权威，与 AGENTS.md 冲突处以 AGENTS.md 为准』，"
        "脚本清单待该文件整体处置时一并清",
    ("SOUL.md", "scripts/discrimination_check.py"): "同上（SOUL.md 历史提案，未生效）",
    ("SOUL.md", "scripts/generate_pool.py"): "同上（SOUL.md 历史提案，未生效）",
    ("SOUL.md", "scripts/ic_monitor.py"): "同上（SOUL.md 历史提案，未生效）",
    ("SOUL.md", "scripts/performance_review.py"): "同上（SOUL.md 历史提案，未生效）",
    ("SOUL.md", "scripts/pre_market_estimate.py"): "同上（SOUL.md 历史提案，未生效）",
    ("SOUL.md", "scripts/update_warroom.py"): "同上（SOUL.md 历史提案，未生效）",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/atomcode_rotate.py"):
        "本文是在**引用 channel.json 的既有登记**来陈述事实（议题 11 正文已注明该脚本不存在），"
        "属取证引用而非发号施令",
    # 议题 12 的核查表**本身就是在列举这些不存在的路径** —— 取证清单，不是发号施令
    ("deliverables/待老大拍板清单-20261017.md", "scripts/check_gateway.py"):
        "议题 12 核查表的取证行（列的就是'登记了但不存在'的入口）",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/mount_pointer.py"):
        "议题 12 核查表的取证行（列的就是'登记了但不存在'的入口）",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/autodetect_blockers.py"):
        "议题 12 核查表的取证行（列的就是'登记了但不存在'的入口）",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/ic_monitor.py"):
        "议题 12 正文的取证行（说明这批只出现在未生效的 SOUL.md 里）",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/factor_ic_132d_v10_exact.py"):
        "这是**提案中拟新建**的路径（原文『把引擎本体入库（放 `scripts/factor_ic_132d_v10_exact.py`）』），"
        "描述的是『应该建在哪』，不是『现在就有』。拍板落地后本条应移除。",
    ("team/职责.md", "scripts/atomcode_rotate.py"):
        "2026-10-17 已改为**警示行**（原文把它当可用调度入口，现明确标注『该脚本不存在，待老大拍板』）。"
        "此处必须保留原路径才能说清问题，属取证引用",
    # ── 2026-10-24 T051 C4: S4 归档 (2026-10-23) 后, 拍板清单历史台账保留旧引用, 出处已登记 PHANTOM_MAP ──
    ("deliverables/待老大拍板清单-20261017.md", "scripts/scan_archived_links.py"):
        "议题 4 结项的 2026-10-17 W4 复跑命令取证行；脚本 2026-10-23 S4 归档至 "
        "archive/scripts-20261023/（PHANTOM_MAP 已登记），历史台账保留原路径，不回填改动",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/factor_weight_proposal.py"):
        "议题正文的只读体检结果取证引用；脚本 2026-10-23 S4 归档至 "
        "archive/scripts-20261023/（PHANTOM_MAP 已登记），历史台账保留原路径",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/purged_kfold.py"):
        "议题描述行（列举反过拟合 5 脚本）；purged_kfold 2026-10-23 S4 归档至 "
        "archive/scripts-20261023/（PHANTOM_MAP 已登记），历史台账保留原路径",
    ("deliverables/待老大拍板清单-20261017.md", "scripts/backtest_param_sweep.py"):
        "议题描述行（列举反过拟合 5 脚本）；backtest_param_sweep 2026-10-23 S4 归档至 "
        "archive/scripts-20261023/（PHANTOM_MAP 已登记），历史台账保留原路径",
}


def _scan():
    hits = []
    for rel in ENFORCED_DOCS:
        full = os.path.join(PROJECT, rel)
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                for ref in set(RE_SCRIPT.findall(line)):
                    if (rel, ref) in WHITELIST:
                        continue
                    if os.path.exists(os.path.join(PROJECT, ref)):
                        continue
                    hits.append((rel, i, ref, line.strip()[:110]))
    return hits


def _explain(ref):
    return PHANTOM_MAP.get(ref, "（真源未查明，请人工确认该脚本是否应存在）")


def test_no_phantom_script_refs():
    """H6：活跃治理文档不得引用不存在的脚本 —— 幽灵引用会主动把后来人带沟里。"""
    hits = _scan()
    assert not hits, (
        "发现幽灵引用（文档指向不存在的脚本）:\n"
        + "\n".join(
            "  %s:%d  → %s\n      %s\n      真源: %s" % (r, i, ref, line, _explain(ref))
            for r, i, ref, line in hits)
        + "\n\n处理：改成真实路径；若为历史文件必须保留旧引用，"
        "在 tests/test_no_phantom_script_refs.py 的 WHITELIST 写明理由，不允许裸放行。"
    )


def test_phantom_map_is_honest():
    """自检：PHANTOM_MAP 里登记为"不存在"的，现在确实还不存在（若被补建了，本条会红，提醒移除登记）。"""
    for ref in PHANTOM_MAP:
        exists = os.path.exists(os.path.join(PROJECT, ref))
        if "**不存在**" in PHANTOM_MAP[ref]:
            assert not exists, (
                "%s 已被补建，请从 PHANTOM_MAP 移除该条目（否则守卫永远在报一个已修的问题）" % ref
            )


def test_selftest_detects_phantom():
    """自检：扫描器能检出人为构造的幽灵引用，且对真实脚本不误报（先红后绿）。"""
    assert RE_SCRIPT.search("python scripts/check_data_freshness.py").group(0) == \
        "scripts/check_data_freshness.py"
    assert RE_SCRIPT.search("python scripts/build_bak_index.py --find x").group(0) == \
        "scripts/build_bak_index.py"
    # 反向：真实存在的脚本不应被判幽灵
    # 2026-10-24 T051 C4 对齐: build_bak_index 2026-10-23 S4 归档, 活跃层路径已不存在,
    # 反向控制改用归档件 (archive/scripts-20261023/), 活跃层缺失本身即 S4 事实断言。
    assert os.path.exists(os.path.join(PROJECT, "archive", "scripts-20261023", "build_bak_index.py"))
    assert not os.path.exists(os.path.join(PROJECT, "scripts", "build_bak_index.py"))
    assert not os.path.exists(os.path.join(PROJECT, "scripts/check_data_freshness.py"))
    # 白名单键可命中
    assert ("SOUL.md", "scripts/ic_monitor.py") in WHITELIST


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
