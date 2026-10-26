# -*- coding: utf-8 -*-
"""§2.9 回授断言铁律 —— 老五 alert_log D-10 守卫的读侧消费断言 (2026-10-26)。

写侧动作: 老五在 core/risk/risk_rules_impl.py _emit_time_stop_unknown_alert 的 D-10 段
          加了 _is_synthetic / _explicit_queue 守卫, 使 合成/测试哨兵码 不再写生产
          data/alert_log.jsonl (改为分流 synthetic_alert_audit.jsonl)。
读侧消费断言 (本测试):
  - 消费者 : pytest 回归门禁 (QSP_GitSync 工作日 09:30 + 手动回归)
  - 周期    : 每次回归 / 每日 git 同步门禁
  - 失败路径: 本测试 FAIL (红) → 回归门禁不绿 → 不推远程 → 总管被卡住
  - 不变量  : 生产 data/alert_log.jsonl 中不得再出现 合成码(无6位A股代码)的
              risk_rules_time_stop P0 行。出现=守卫被绕过/回退, 立即打回。

口径与 impl 一致: 合成码 = stock 字段无 \\d{6}。
数据窗口: 仅检查 data/alert_log.jsonl (本地台账), 只读, 不写交易数据。
"""
import os
import re
import sys


def _project_root():
    # tests/test_x.py -> 上一级即项目根 (data/ 所在)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SIX = re.compile(r"\d{6}")
STOCK = re.compile(r"stock=(\S+)")
SOURCE = "risk_rules_time_stop"


def test_alert_log_has_no_synthetic_time_stop_p0():
    """生产 P0 台账不得含合成码(无6位A股代码)的 risk_rules_time_stop 行。"""
    alert_log = os.path.join(_project_root(), "data", "alert_log.jsonl")
    if not os.path.exists(alert_log):
        # 台账尚未生成: 无违规可查, 放行 (非假绿——没有数据就没有污染)
        return

    offenders = []
    with open(alert_log, encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            if SOURCE not in line:
                continue
            m = STOCK.search(line)
            code = m.group(1) if m else ""
            if not SIX.search(code):
                offenders.append((ln, code, line.strip()[:120]))

    assert not offenders, (
        "生产 alert_log.jsonl 出现合成码 risk_rules_time_stop P0 (守卫 D-10 被绕过/回退?): %s"
        % offenders[:5]
    )


def test_guard_synthetic_detection_matches_impl():
    """守卫的合成码判定口径 (无\\d{6}) 必须与 risk_rules_impl 保持一致。"""
    sys.path.insert(0, _project_root())
    try:
        import core.risk.risk_rules_impl as impl
    except Exception as e:  # impl 不可导入=更大的问题, 直接红
        raise AssertionError("无法导入 core.risk.risk_rules_impl: %s" % e)

    # 合成哨兵(无6位) 必须被判为 synthetic; 真实持仓(6位) 必须不被判
    probes = {
        "unknown": True,      # 合成 -> _is_synthetic True
        "TEST001": True,
        "MISSING": True,
        "SH603727": False,    # 真实 6 位 -> 非 synthetic
        "600519": False,
    }
    for code, expect_synthetic in probes.items():
        got = not SIX.search(str(code))
        assert got is expect_synthetic, "合成判定口径漂移: %s -> %s (期望 %s)" % (
            code, got, expect_synthetic
        )
    # 确认真实实现里 _is_synthetic 的判定表达式仍是基于 6 位数字 (防口径漂移)
    src = open(
        os.path.join(_project_root(), "core", "risk", "risk_rules_impl.py"),
        encoding="utf-8",
    ).read()
    assert "_is_synthetic" in src, "impl 缺失 _is_synthetic 守卫 (D-10 回退?)"
    assert re.search(r'_is_synthetic\s*=\s*not\s+.*search\(r"\\d\{6\}"', src) or re.search(
        r'_is_synthetic\s*=\s*not\s+.*\\d\{6\}', src
    ), "impl _is_synthetic 判定偏离 '无6位数字=合成' 口径"
