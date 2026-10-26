# -*- coding: utf-8 -*-
"""
[守卫] 活跃文档中的契约口径必须与代码真源一致。

═══ 为什么需要这条守卫 ═══
2026-10-17 诊断（deliverables/诊断-多Agent协作闭环-20261017.md）发现：
契约的代码真源只有 risk_rules.py 一处，但描述它的文档有 12 处，且没有任何机制
强制它们一致。结果 09-30 三方会签把止损 8%→10% 之后，仍有 6 处文档继续写 8%，
其中 `.agent/P0-EXEC-ORDER` 还挂着「P0 / 禁止修改」标签 —— 错误值戴着最高权威标签，
被供奉了 17 天，持续误导后续 agent。

这是「文档驱动」而非「契约驱动」的必然结果。本守卫把这条裂缝钉死：
活跃文档里再出现已废弃的契约口径，测试直接红。

═══ 设计原则 ═══
1. **真源动态读取** —— 期望值从 risk_rules.py 实时导入，不在本文件里再抄一份数字
   （再抄一份 = 又造一个真源，正是本次要根治的病）。
2. **只扫"会发号施令"的活跃层** —— 历史回测报告（cron/output、data/audit）里
   「契约版-止损8%-分级止盈」是**历史实验变体名**，改它就是篡改历史，不扫。
3. **白名单必须写理由** —— 历史台账确需保留旧值的，必须在 WHITELIST 写明理由，
   不允许裸放行。

═══ 扫描范围 ═══
活跃层：根目录 *.md、.workbuddy/（含 memory）、.agent/*.md、.hermes/memory/*.md、
        mainline/docs/ 的 4 份活跃件、deliverables/*.md
排除：.worktrees .trash .trash_envs .venv .scratch research_archive archive backups
      docs/ mainline/docs/（除活跃件） cron/output data/audit data/archive_* *.bak*
"""
import os
import re
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

# ── 真源：动态读取，禁止在本文件硬编码期望数字 ──
import risk_rules as rr  # noqa: E402

STOP_LOSS_TRUE = rr.STRATEGY_STOP_LOSS_PCT.get("全仓", 0.10)
CHASE_BAN_TRUE = rr.CHASE_BAN_PCT
TIME_STOP_TRUE = rr.TIME_STOP_TRADING_DAYS

# ── 扫描范围 ──
ACTIVE_DIRS = [".", ".workbuddy", ".agent", ".hermes/memory", "deliverables"]
ACTIVE_MAINLINE_DOCS = [
    "mainline/docs/TEAM-ROSTER.md",
    "mainline/docs/TEAM-COMMS-PROTOCOL.md",
    "mainline/docs/CAPABILITY-REGISTRY.md",
    "mainline/docs/AGENT-EXECUTION-PROTOCOL-2026-09-27.md",
]

EXCLUDE_DIR_TOKENS = (
    ".worktrees", ".trash", ".trash_envs", ".venv", ".scratch", ".git",
    "research_archive", "archive", "backups", "node_modules", "__pycache__",
    "cron", "audit", "archive_2026",
)
EXCLUDE_FILE_TOKENS = (".bak",)


def _is_excluded(relpath):
    low = relpath.replace("\\", "/").lower()
    if any(tok in low for tok in EXCLUDE_FILE_TOKENS):
        return True
    parts = low.split("/")
    return any(p in EXCLUDE_DIR_TOKENS for p in parts[:-1])


def _iter_active_docs():
    seen = set()
    for rel in ACTIVE_DIRS:
        base = os.path.join(PROJECT, rel)
        if not os.path.isdir(base):
            continue
        if rel == ".":
            # 根目录**只扫一层**: 根目录 *.md 是活跃门面;
            # docs/(520) 与 mainline/docs/(1568) 是历史报告坟场, 里面有大量
            # "契约版-止损8%-分级止盈" 这类**历史实验变体名**, 改它=篡改历史, 不扫。
            for name in sorted(os.listdir(base)):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(base, name)
                r = os.path.relpath(full, PROJECT)
                if _is_excluded(r) or r in seen:
                    continue
                seen.add(r)
                yield r, full
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_TOKENS]
            for name in sorted(filenames):
                if not name.endswith(".md"):
                    continue
                full = os.path.join(dirpath, name)
                r = os.path.relpath(full, PROJECT)
                if _is_excluded(r) or r in seen:
                    continue
                seen.add(r)
                yield r, full
    for rel in ACTIVE_MAINLINE_DOCS:
        full = os.path.join(PROJECT, rel)
        if os.path.exists(full) and rel not in seen:
            seen.add(rel)
            yield rel, full


# ── "引用上下文"判据 ──
# 行内含这些标记 = 在**引用/更正/取证**旧值做说明, 不是在发号施令 → 放行。
# 这条比逐条白名单更本质: 白名单管"这几个文件", 引用判据管"这几种说法", 能泛化。
RE_CITATION = re.compile(
    r"废弃|已废|作废|停用|旧值|旧口径|旧记|原记|原写|原为|~~|"
    r"更正|推翻|回改|冲突|取证|不得再用|不得再按|已经不|"
    r"已修|O-2|诊断|复盘|会签前|会签回改|手滑|事故|"
    r"vs\s*10|\d\s*%\s*vs\s*\d|最后一个活着"
)

# ── 日期日志豁免 ──
# .workbuddy/memory/YYYY-MM-DD.md 与 .hermes/memory/ 下的日期日志是**历史流水账**,
# 记录的是"当时发生了什么", 天然会提到已被后续推翻的值。改它就是篡改历史。
# 但长期记忆 MEMORY.md(非日期名)不豁免 —— 它会被写进每个新会话上下文, 必须严格。
RE_DATED_LOG = re.compile(r"(?:^|/)\d{4}-\d{2}-\d{2}\.md$")


def _is_dated_log(relpath):
    return bool(RE_DATED_LOG.search(relpath.replace("\\", "/")))


# ── 已废弃口径的匹配模式 ──
# 止损：各种写法的 8%（09-30 会签前的旧口径）
RE_STOP_LOSS_8 = re.compile(
    r"止损\s*[:：=]?\s*(?:为)?\s*\*{0,2}8\s*%|"          # 止损 8% / 止损:8% / 止损=8%
    r"止损\s*8%|"                                          # 止损8%
    r"8\s*%?\s*止损|"                                      # 8%止损
    r"STOP_LOSS(?:_BASE|_PCT)?\s*[:=]\s*0?\.?08\b|"        # STOP_LOSS_BASE = 0.08
    r"base\s+0\.08|"                                       # base 0.08
    r"strategy,\s*0\.08"                                   # .get(strategy, 0.08)
)
# 止盈：已废弃的 LEGACY 四档 6/8/10/12
RE_LEGACY_TP = re.compile(
    r"6\s*[-/]\s*8\s*[-/]\s*10\s*[-/]\s*12|"               # 6/8/10/12 或 6-8-10-12
    r"\[\s*0\.06\s*,\s*0\.08\s*,\s*0\.10\s*,\s*0\.12\s*\]" # [0.06, 0.08, 0.10, 0.12]
)

# ── 白名单：历史台账确需保留旧值，必须写明理由 ──
# 键 = (相对路径, 该行内必须出现的特征串)；值 = 理由
WHITELIST = {
    (".agent/OPTIMIZATION-PLAN-20261005.md", "已于 2026-09-30 三方会签回改为 10%"):
        "历史台账：记录 10-05 当时确曾改为 8%，已在同行加注「09-30 会签回改为 10%，不得再按 8% 执行」",
    (".agent/P0-EXEC-ORDER-20260930.md", "2026-10-17 老六更正"):
        "历史执行令：更正块内必须引用原错值以便后人核对，正文已改为 10%",
    (".workbuddy/memory/2026-10-17.md", "O-2 止损 8% vs 10%"):
        "事故复盘日志：记录的就是这次口径冲突本身",
    (".workbuddy/memory/2026-10-17.md", "P0-EXEC-ORDER-20260930.md:37"):
        "诊断日志：引用被修复文件的原始错误内容",
    ("deliverables/诊断-多Agent协作闭环-20261017.md", "仍写 8%"):
        "诊断报告：正文就是取证材料，必须引用原值",
    ("deliverables/诊断-多Agent协作闭环-20261017.md", "P0-EXEC-ORDER-20260930.md:37"):
        "诊断报告：取证引用",
    ("deliverables/诊断-多Agent协作闭环-20261017.md", "risk_rules.py:352"):
        "诊断报告：取证引用",
    # ↓ 2026-10-19 老六架构审查补登：这 3 份的「止损8%」出现在【回测变体对照表】与
    #   【漂移取证正文】里。前者是历史实验的变体名（「契约版-止损8%-旧阶梯」是当时
    #   跑过的一个对照组，改名即篡改实验记录）；后者是指控
    #   scripts/single_stock_rotation.py:20 STOP_LOSS_PCT=0.08 漂移的取证原文。
    #   两者删掉都会毁证据，故按铁律「白名单必须写理由」显式放行。
    ("deliverables/W6-ST空壳补数与基线重跑-20261017.md", "契约版-止损8%"):
        "回测变体对照表：该行是历史实验的对照组命名（当时确以 8% 跑过），改名=篡改实验记录",
    ("deliverables/W6-ST空壳补数与基线重跑-20261017.md", "S2备选-回撤敏感-止损8%"):
        "回测变体对照表：同上，历史对照组命名",
    ("deliverables/单票轮动方案重构-20261018.md", "STOP_LOSS_PCT = 0.08"):
        "漂移取证：指控 single_stock_rotation.py 第三份副本仍写 0.08 的证据原文，必须引用原值",
    ("deliverables/臃肿板块盘点与清理清单-20261018.md", "STOP_LOSS_PCT = 0.08"):
        "漂移取证：同上，且该文件同时记录了 GRADED_TP_LADDER 已被真源宣告废弃",
    ("deliverables/臃肿板块盘点与清理清单-20261018.md", "止损漂移**"):
        "漂移取证：同上，正文即取证材料",
    # ↓ 2026-10-19 补登（qa-verifier 验收打回 BUG-01）：这两份是本次架构审查自己
    #   产出的交付物，其中的「止损8%」分别是【盲区统计行】与【09-30 事故指控原文】，
    #   属取证/统计性质，删字会毁证据。守卫现在真的在门禁里跑了（此前从不执行），
    #   所以它们一落盘就被抓到 —— 这是守卫生效的证据，不是文档写错。
    ("deliverables/待老大拍板清单-20261019-架构审查.md", "裸数值命中：止损8%"):
        "盲区统计行：报告守卫扫描盲区时引用「止损8% 命中 388 行」的实测统计，属取证数据不可改",
    ("deliverables/架构闭环审查-20261019.md", "09-30「止损 8%→10%"):
        "事故指控原文：说明本次断裂是 09-30 止损 8%→10% 漂移事故的同构复发，必须引用原值才能说清",
    ("deliverables/交接-总管-20261019-架构审查后续.md", "含「止损8%」字样被守卫抓到"):
        "BUG-01取证行：说明守卫在commit后1~2分钟落盘时抓到「止损8%」——这是守卫生效的证据，不是文档写错；且该行同时记录了修复commit 4f15bab5的哈希，删字会毁审计线索",
}


# ── 文件级白名单 ── 整份文件都是取证材料, 逐行豁免
FILE_LEVEL_WHITELIST = {
    "deliverables/诊断-多Agent协作闭环-20261017.md":
        "诊断报告全文即取证材料, 必须引用原错值才能说清问题",
}


def _whitelisted(relpath, line):
    if relpath.replace("\\", "/") in FILE_LEVEL_WHITELIST:
        return True
    for (path, marker), _reason in WHITELIST.items():
        if relpath.replace("\\", "/") == path and marker in line:
            return True
    return False


def _scan():
    hits = []
    for relpath, full in _iter_active_docs():
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as e:
            print(f"🔴 [test_contract_docs_consistency.py:213] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 OSError → 兜底, 异常={e}", file=sys.stderr)
            continue
        for i, line in enumerate(lines, 1):
            if _whitelisted(relpath, line):
                continue
            if _is_dated_log(relpath):
                continue  # 历史流水账, 见 RE_DATED_LOG 说明
            if RE_CITATION.search(line):
                continue  # 引用/更正/取证旧值, 非发号施令
            if RE_STOP_LOSS_8.search(line):
                hits.append((relpath, i, "止损8%(09-30会签前旧口径)", line.strip()[:120]))
            elif RE_LEGACY_TP.search(line):
                hits.append((relpath, i, "止盈LEGACY四档6/8/10/12(已废弃)", line.strip()[:120]))
    return hits


def test_no_stale_contract_values_in_active_docs():
    """活跃文档里不得再出现已废弃的契约口径 —— 旧文档发号施令是本次诊断的头号病灶。"""
    hits = _scan()
    assert not hits, (
        "活跃文档中出现已废弃契约口径(真源 risk_rules.py: 止损 %.0f%% / S3五档):\n" % (STOP_LOSS_TRUE * 100)
        + "\n".join("  %s:%d  [%s]\n      %s" % h for h in hits)
        + "\n\n处理: 改成真源值; 若为历史台账必须保留旧值, "
        "在 tests/test_contract_docs_consistency.py 的 WHITELIST 写明理由, 不允许裸放行。"
    )


def test_true_source_is_ten_percent():
    """锚: 真源确实是 10%。若哪天会签改成别的值, 这条会先红, 提醒同步所有文档。"""
    assert abs(STOP_LOSS_TRUE - 0.10) < 1e-9, (
        "真源止损已变为 %.4f, 不再是会签的 10%% —— "
        "若这是有意变更, 请同步更新全部活跃文档并复核本守卫的废弃口径清单" % STOP_LOSS_TRUE
    )


def test_zero_point_zero_eight_gone_from_code():
    """锚: 代码里不得再有 0.08 作为止损兜底(2026-10-17 已修 risk_rules.py:352)。"""
    src = open(os.path.join(PROJECT, "risk_rules.py"), encoding="utf-8").read()
    bad = [
        ln for ln in src.splitlines()
        if re.search(r"STRATEGY_STOP_LOSS_PCT\.get\([^)]*,\s*0\.08", ln)
    ]
    assert not bad, "risk_rules.py 仍有 0.08 静默兜底: %s" % bad


def test_scanner_finds_stale_value_selfcheck():
    """自检: 扫描器能检出人为构造的旧口径, 防止守卫本身失效(先红后绿)。"""
    assert RE_STOP_LOSS_8.search("止损 8% / 移动止盈阶梯 6/8/10/12%")
    assert RE_STOP_LOSS_8.search("base_stop_loss_pct = STRATEGY_STOP_LOSS_PCT.get(strategy, 0.08)")
    assert RE_LEGACY_TP.search("TREND_TP_LADDER = [0.06, 0.08, 0.10, 0.12]")
    # 正确写法不应误报
    assert not RE_STOP_LOSS_8.search("止损 10%（全策略统一）")
    assert not RE_LEGACY_TP.search("[(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]")


def test_scan_scope_is_sane():
    """自检: 扫描范围既不为空, 也不该把历史报告层卷进来。"""
    docs = list(_iter_active_docs())
    assert len(docs) >= 20, "活跃文档扫描数 %d 偏少, 排除规则可能误杀" % len(docs)
    rels = [r for r, _ in docs]
    assert not any(r.startswith("cron/") for r in rels), "历史产出层 cron/ 不应被扫入"
    assert not any("/audit" in r for r in rels), "历史审计层 data/audit 不应被扫入"
    assert not any(".bak" in r for r in rels), "备份文件不应被扫入"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
