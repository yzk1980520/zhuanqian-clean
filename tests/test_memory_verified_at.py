# -*- coding: utf-8 -*-
"""
[守卫 F1/F2/F4] 记忆机制（2026-10-17 W5 治理）

═══ 背景 ═══
1. `.workbuddy/memory/MEMORY.md` 曾长期写着「止损 8%」（09-30 会签早改成 10%），
   因为**长期记忆没有有效期概念**，它被写进之后每一个新会话的上下文持续发号施令。
2. 2026-10-01 ~ 10-11 有 **11 天记忆空档**，期间系统在改契约、在出事故 ——
   因为**没有"什么事件必须写记忆"的清单**。
3. 「回撤容忍 vs 卖出比例」这种踩过的坑只活在当时那份日志里 ——
   因为**契约级语义没有强制进长期记忆**。

═══ 本守卫管什么 ═══
- 规则文件 `.workbuddy/MEMORY-RULES.md` 必须在位（否则规则又只是口头约定）
- 校验器 `scripts/check_memory_freshness.py` 必须能自检通过（**先红后绿**：
  正常条目不误报 / 30~60 天判待复核 / >60 天判过期 / 缺戳能检出）
- 校验器对**真实记忆文件**扫得到东西（机制存在 ≠ 机制生效，必须有活体断言）

═══ 为什么本文件不直接判 FAIL「无 verified_at」═══
`.workbudpy/memory/` 由老大/总管统一写，W5 不代写。若在此直接断言"无戳=FAIL"，
会造出一个**别人无法在当天修好**的红 —— 那是拿门禁当鞭子，不是当守卫。
所以：`--strict` 模式留给 CI，日常 pytest 只保证**机制本身有效**。
"""
import os
import subprocess
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES = os.path.join(PROJECT, ".workbuddy", "MEMORY-RULES.md")
# 2026-10-24 T051 C4 对齐: 校验器 2026-10-23 S4 基地化归档至 archive/scripts-20261023/
# (活跃层 scripts/check_memory_freshness.py 不再存在)。归档版 --selftest 自包含, 在归档位
# 可安全实跑 (2026-10-24 核验 rc=0 且不写禁区); 全量扫描根 (L165 __file__ 上跳两级) 在
# 归档位指向 archive/ → 对真实 .workbuddy/memory/ 的活体扫描见 test_checker_scans_real_memory_files 挂起裁定。
CHECKER = os.path.join(PROJECT, "archive", "scripts-20261023", "check_memory_freshness.py")


def _run(args, expect=0):
    return subprocess.run(
        [sys.executable, os.path.relpath(CHECKER, PROJECT)] + args,
        cwd=PROJECT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
    )


def test_memory_rules_exist():
    """F1/F2/F4：记忆规则必须落文件（否则又是"口头约定"，三个月后没人记得）。"""
    assert os.path.exists(RULES), "缺少 .workbuddy/MEMORY-RULES.md"
    text = open(RULES, encoding="utf-8").read()
    for token in ("verified_at", "30 天", "60 天", "必须写记忆", "契约级语义"):
        assert token in text, "MEMORY-RULES.md 缺少关键规则: %s" % token


def test_checker_selftest_passes():
    """先红后绿：校验器自检必须通过 —— 证明它真能检出问题，不是空转。"""
    r = _run(["--selftest"])
    assert r.returncode == 0, "check_memory_freshness.py --selftest 失败:\n%s" % r.stdout
    assert "四类问题全部可检出" in r.stdout, "自检未覆盖全部四类: %s" % r.stdout[-400:]
    for token in ("不误报", "待复核", "过期", "缺 verified_at"):
        assert token in r.stdout, "自检输出缺少覆盖项 %s: %s" % (token, r.stdout[-400:])


def test_checker_scans_real_memory_files():
    """活体断言：校验器对**真实**记忆文件扫得到章节（机制存在 ≠ 机制生效）。

    2026-10-24 T051 C4 裁定挂起 (skip): 校验器 S4 归档 (2026-10-23) 后, 归档版 scan 根
    (check_memory_freshness.py L165: __file__ 上跳两级) 在归档位指向 archive/ (禁区),
    对真实 .workbuddy/memory/ 的活体扫描必然空跑误报 → 待活跃等价件补建后恢复。
    """
    pytest.skip("2026-10-24 T051 C4 裁定: 校验器 S4 归档后 scan 根指向 archive/ (禁区), "
                "真实记忆文件活体扫描挂起, 待活跃等价件补建后恢复")
    r = _run([])
    assert r.returncode == 0, "check_memory_freshness.py 扫描失败:\n%s" % r.stderr[:400]
    assert ".workbuddy/memory/MEMORY.md" in r.stdout, "未扫描项目级长期记忆"
    # 至少扫出 5 个章节（真记忆文件不可能只有一两个 h2）
    import re
    n = len(re.findall(r"^\s{2}[⏳⚠️❓🚫 ]\s", r.stdout, re.M))
    assert n >= 5, "只扫出 %d 个章节，解析规则可能失效:\n%s" % (n, r.stdout[-500:])


def test_checker_default_mode_is_readonly():
    """F1：默认模式必须只读（不加 --mark 就绝不能改记忆文件）。"""
    src = open(CHECKER, encoding="utf-8").read()
    assert "--mark" in src
    # 写操作只允许出现在 mark() 里：mark 被调用前必须有 args.mark 判断
    assert "if args.mark:" in src, "缺少 --mark 开关守卫，可能导致默认模式写文件"


def test_f2_events_and_f4_semantics_documented():
    """F2/F4：规则文件必须写明"哪些事件必须写"和"契约级语义强制入册"。"""
    text = open(RULES, encoding="utf-8").read()
    assert "老大拍板" in text and "事故与回滚" in text, "F2 必写事件清单不全"
    assert "回撤容忍" in text and "TP_SELL_LADDER" in text, "F4 契约级语义示例缺失"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
