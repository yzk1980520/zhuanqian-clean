# -*- coding: utf-8 -*-
"""
[守卫] 回测必须自证"考虑过退市股" —— AGENTS.md:97 铁律的机器化。

═══ 为什么 ═══
2026-10-17 诊断：`backtest_rotation.py` grep「退市|delist」= 0 处，
看上去完全没覆盖退市股，违反铁律。
审计（`scripts/audit_delisted_coverage.py`）后真相是：

    扩展库主板票 3367 只  vs  TDX 当前上市 3210 只
    → 独家 **157 只**（TDX 已删，含退市股）
      其中 参与回测(>=30根且非ST) **15 只**
           ST/*ST 剔除           **66 只**
           空壳(0根)             **76 只** ← 真实幸存者偏差缺口
           （恒等式 15 + 66 + 0 + 76 = 157）

即：退市股**在池子里，但全项目 grep 不到、结果 JSON 里也看不到**。
"无法自证" 与 "真的没做" 在后果上等价 —— 都不可信。

本守卫把这条钉死：审计文件必须存在、必须新鲜、必须证明池子里有退市股。

═══ 数字口径（2026-10-17 老大裁定）═══
初版审计报 with_data_count=25，与回测器实算 15 打架。根因是**口径不同**：
回测器 `BT.is_st_stock` 实际是 `backtest.py:47` 别名到 `is_st_only`
（只排 ST/*ST 前缀，**不排**含"退"的票 —— R9 刻意保留退市股修幸存者偏差）。
审计脚本已对齐到同一真源。本测试**不硬编码 15/66/76**（数据会变），
只断言语义：恒等式成立、ST 过滤确已施加、参与数 > 0。

═══ 注意 ═══
本守卫**只卡"自证"**，不卡"空壳已补齐"（empty_count==0）—— 那是 P1 数据任务
（第三方源对 2021-2024 退市股覆盖极差，很可能拿不全），不能用 P0 标准卡。
"""
import json
import os
import sys

import pytest

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(PROJECT, "data", "delisted_audit.json")
SCRIPT = os.path.join(PROJECT, "scripts", "audit_delisted_coverage.py")

MAX_AGE_DAYS = 14  # 审计超过两周视为过期，需重跑


def _load():
    if not os.path.exists(AUDIT):
        return None
    try:
        with open(AUDIT, encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError) as e:
        print(f"🔴 [test_delisted_coverage.py:52] CR-01 静默吞噬响铃化 (P1-4b t_bae6c7d6): 捕获 (ValueError, OSError) → 兜底, 异常={e}", file=sys.stderr)
        return None


def test_audit_script_exists():
    """审计脚本必须在位 —— 没有它就永远无法自证。"""
    assert os.path.exists(SCRIPT), (
        "缺少退市覆盖审计脚本 %s\n"
        "用法: python scripts/audit_delisted_coverage.py" % SCRIPT
    )


def test_audit_result_exists_and_fresh():
    """审计结果必须存在且新鲜 —— 过期的证据等于没有证据。"""
    import datetime
    d = _load()
    assert d is not None, (
        "缺少退市覆盖审计结果 data/delisted_audit.json —— 请先跑:\n"
        "  python scripts/audit_delisted_coverage.py"
    )
    gen = d.get("generated", "")
    try:
        when = datetime.datetime.fromisoformat(gen)
    except (ValueError, TypeError):
        pytest.fail("审计文件 generated 字段不可解析: %r" % gen)
    age = (datetime.datetime.now() - when).days
    assert age <= MAX_AGE_DAYS, (
        "退市覆盖审计已过期 %d 天（上限 %d 天）：%s\n"
        "请重跑: python scripts/audit_delisted_coverage.py" % (age, MAX_AGE_DAYS, gen)
    )


def test_delisted_stocks_are_in_pool():
    """核心断言：候选池里必须有 TDX 已删的代码 —— 否则证明不了考虑过退市股。"""
    d = _load()
    if d is None:
        pytest.skip("审计结果缺失，由 test_audit_result_exists_and_fresh 报错")
    assert d.get("exclusive_count", 0) > 0, (
        "扩展库中没有任何 TDX 已删代码 —— 回测候选池不含退市股，违反 AGENTS.md:97"
    )
    assert d.get("with_data_count", 0) > 0, (
        "TDX 已删代码全部无可用数据 —— 形式上在池子里，实质未参与回测"
    )


# R9 幸存者偏差地板，变更必须走 CONTRACT-CHANGELOG + 广播
# 初值 91 = 2026-10-17 审计实测 with_data_count(恒等式 91+66+0+0=157)。
# D8/D9 (2026-10-19) 三项过滤为**逐扫描日**口径(退市整理期窗口/价格地板/ADV地板),
# 不整只剔除任何票, 故该数字不因 D8/D9 下降 —— 若未来因口径变更需要下调,
# 必须走 CONTRACT-CHANGELOG + 广播, 禁止静默改数。
MIN_DELISTED_IN_BACKTEST = 91


def _assert_above_floor(wc):
    """R9 地板判定(供真实数据与合成侵蚀场景共用, 保证测的就是守的那条)。"""
    assert wc >= MIN_DELISTED_IN_BACKTEST, (
        "with_data_count=%d 低于 R9 幸存者偏差地板 %d —— 退市股有效参与数被侵蚀"
        "(157→10 这类渐进侵蚀骗得过 >0 断言, 骗不过地板)。若为口径变更导致的合理下降, "
        "必须先走 CONTRACT-CHANGELOG + 广播再改地板, 禁止静默下调"
        % (wc, MIN_DELISTED_IN_BACKTEST)
    )


def test_with_data_floor_not_eroded():
    """A 增强版下限地板(增量, 不动现有 >0 断言): 退市股有效参与数不得低于地板。"""
    d = _load()
    if d is None:
        pytest.skip("审计结果缺失，由 test_audit_result_exists_and_fresh 报错")
    _assert_above_floor(d.get("with_data_count", 0) or 0)


def test_floor_blocks_erosion_synthetic():
    """地板的牙齿(先红后绿): 合成侵蚀值必须触发 AssertionError —— 地板不是摆设。"""
    with pytest.raises(AssertionError):
        _assert_above_floor(10)   # 157→10 的渐进侵蚀场景, 必须被抓住


def test_survivorship_gap_is_tracked():
    """幸存者偏差缺口必须被量化并暴露，不允许"不知道有多少缺口"。"""
    d = _load()
    if d is None:
        pytest.skip("审计结果缺失")
    assert "empty_count" in d, "审计结果缺少 empty_count（空壳数量）字段"
    gap = d["empty_count"]
    # 不卡 gap==0（那是 P1 目标），只卡"被记录下来了"
    print("\n  退市股在池: %d 只 | 有数据参与回测: %d 只 | 空壳缺口: %d 只"
          % (d.get("exclusive_count", 0), d.get("with_data_count", 0), gap))
    assert isinstance(gap, int) and gap >= 0


def test_scanner_selfcheck():
    """自检：审计脚本的过滤逻辑不会被指数/科创板污染（先红后绿已实测）。"""
    src = open(SCRIPT, encoding="utf-8").read()
    # 必须做主板白名单过滤，否则 sh000001(上证指数) 会被算成退市股
    assert "_in_universe" in src, "审计脚本缺少主板白名单过滤 _in_universe"
    assert "ALLOWED_PREFIX" in src, "审计脚本缺少 ALLOWED_PREFIX 白名单"


def test_st_filter_uses_backtester_authority():
    """钉死 ST 过滤的真源：必须用回测器的 is_st_stock(=is_st_only)，不许重造判据。

    反例(初版差点踩): 误用 tdx_data.is_st_stock（含"退"判据，实盘选股口径）
    会得到 st_skipped=143 / with_data=4 —— 比回测器多剔 77 只，方向是错的，
    等于把"修幸存者偏差"这件事反向做了一遍。
    """
    src = open(SCRIPT, encoding="utf-8").read()
    assert "import backtest" in src, "审计脚本必须 import backtest 取权威 ST 判据"
    assert "is_st_only" in src, "审计脚本必须注明真源是 is_st_only"
    d = _load()
    if d is None:
        pytest.skip("审计结果缺失")
    assert d.get("st_filter_applied") is True, "审计未施加 ST 过滤(名称表不可用)"
    assert "is_st_only" in (d.get("st_filter_source") or ""), (
        "ST 过滤来源不是回测器真源: %r" % d.get("st_filter_source"))


def test_counts_form_identity():
    """语义断言（不硬编码具体数字）：四分类之和必须等于 exclusive_count。"""
    d = _load()
    if d is None:
        pytest.skip("审计结果缺失")
    ec = d.get("exclusive_count")
    parts = [d.get("with_data_count"), d.get("st_skipped"),
             d.get("empty_count"), d.get("thin_count")]
    assert None not in parts, "审计结果缺少分类字段: %r" % {
        k: d.get(k) for k in ("with_data_count", "st_skipped", "empty_count", "thin_count")}
    assert ec is not None and ec > 0, "exclusive_count 缺失或为 0"
    assert sum(parts) == ec, (
        "分类计数不闭合: %d + %d + %d + %d = %d ≠ exclusive_count %d"
        % (parts[0], parts[1], parts[2], parts[3], sum(parts), ec))


def test_with_data_is_st_filtered_not_inflated():
    """对齐后的 with_data_count 必须 <= 未过滤的原始值（ST 过滤只会减少，不会增加）。"""
    d = _load()
    if d is None:
        pytest.skip("审计结果缺失")
    aligned = d.get("with_data_count")
    raw = d.get("with_data_before_st_filter")
    if raw is None:
        pytest.skip("审计结果无 with_data_before_st_filter 字段")
    assert aligned is not None and aligned > 0, "with_data_count 应 > 0，实际 %r" % aligned
    assert aligned <= raw, (
        "对齐值(%d) 不应大于未过滤原始值(%d) —— ST 过滤方向反了" % (aligned, raw))


# ══════════════════════════════════════════════════════
#  门禁断言（check_backtest_sanity.py）的 PASS/FAIL 契约
#  先红后绿: 每条 FAIL 分支都先被做成"能检出"，再确认正常数据下 PASS
# ══════════════════════════════════════════════════════
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)
import backtest.check_backtest_sanity as CBS  # noqa: E402


@pytest.fixture
def audit_path(tmp_path, monkeypatch):
    """把门禁的降级读取路径重定向到 tmp，隔离真实 data/delisted_audit.json。"""
    p = tmp_path / "delisted_audit.json"
    monkeypatch.setattr(CBS, "AUDIT_FALLBACK", str(p))
    return p


def _write(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def test_gate_pass_when_audit_present(audit_path):
    """【绿】有审计文件且数字成立 → PASS。"""
    _write(audit_path, {"exclusive_count": 157, "with_data_count": 25,
                        "empty_count": 132, "thin_count": 0})
    dcov, src = CBS.resolve_delisted_coverage({})
    assert dcov is not None
    ok, detail = CBS.check_delisted_coverage(dcov)
    assert ok, detail
    assert "delisted_audit.json" in src, src


def test_gate_fail_when_audit_missing(audit_path):
    """【红】审计文件缺失 → FAIL，且原因必须点名 AGENTS.md:97。"""
    assert not audit_path.exists()
    dcov, _ = CBS.resolve_delisted_coverage({})
    assert dcov is None
    ok, detail = CBS.check_delisted_coverage(dcov)
    assert not ok
    assert "AGENTS.md:97" in detail, detail


def test_gate_fail_when_exclusive_zero(audit_path):
    """【红】exclusive_count=0 = 候选池里根本没有退市股 → FAIL。"""
    _write(audit_path, {"exclusive_count": 0, "with_data_count": 0, "empty_count": 0})
    ok, detail = CBS.check_delisted_coverage(CBS.resolve_delisted_coverage({})[0])
    assert not ok
    assert "exclusive_count=0" in detail, detail


def test_gate_fail_when_with_data_zero(audit_path):
    """【红】形式上在池子里、实质无数据（全空壳）→ 也必须 FAIL。"""
    _write(audit_path, {"exclusive_count": 157, "with_data_count": 0, "empty_count": 157})
    ok, detail = CBS.check_delisted_coverage(CBS.resolve_delisted_coverage({})[0])
    assert not ok
    assert "with_data_count=0" in detail, detail


def test_gate_does_not_fail_on_empty_count(audit_path):
    """钉住设计决定：空壳缺口只暴露、不卡（P1 数据任务，不能用 P0 标准卡死）。"""
    _write(audit_path, {"exclusive_count": 10, "with_data_count": 3, "empty_count": 7})
    ok, detail = CBS.check_delisted_coverage(CBS.resolve_delisted_coverage({})[0])
    assert ok, detail


def test_gate_result_json_takes_priority(audit_path):
    """结果JSON自带 delisted_coverage 时优先用它，不降级（即便审计文件是坏的）。"""
    _write(audit_path, {"exclusive_count": 0, "with_data_count": 0})
    data = {"delisted_coverage": {"exclusive_count": 157, "with_data_count": 25}}
    dcov, src = CBS.resolve_delisted_coverage(data)
    assert src == "rotation_backtest_result.json", src
    assert CBS.check_delisted_coverage(dcov)[0]


def test_gate_rejects_corrupt_json(audit_path):
    """审计文件坏了（不可解析）→ 等同缺失 → FAIL，不许静默放过。"""
    audit_path.write_text("{ this is not json", encoding="utf-8")
    dcov, _ = CBS.resolve_delisted_coverage({})
    assert dcov is None
    assert not CBS.check_delisted_coverage(dcov)[0]


def _run_gate(tmp_path, monkeypatch, capsys, audit_obj=None, inline=None):
    """跑真实 main()，返回 stdout。只用于断言"退市股覆盖自证"这一行。"""
    monkeypatch.setattr(CBS, "AUDIT_FALLBACK", str(tmp_path / "delisted_audit.json"))
    if audit_obj is not None:
        _write(tmp_path / "delisted_audit.json", audit_obj)
    payload = {"window": ["2021-01-04", "2026-09-18"],
               "results": [{"config": "T", "trades": []}]}
    if inline is not None:
        payload["delisted_coverage"] = inline
    rj = tmp_path / "result.json"
    _write(rj, payload)
    monkeypatch.setattr(sys, "argv", ["check_backtest_sanity.py", str(rj)])
    CBS.main()
    return capsys.readouterr().out


def test_gate_end_to_end_green(tmp_path, monkeypatch, capsys):
    """端到端【绿】：无内联字段时降级读审计文件，该行 PASS。"""
    out = _run_gate(tmp_path, monkeypatch, capsys,
                    audit_obj={"exclusive_count": 157, "with_data_count": 25,
                               "empty_count": 132, "thin_count": 0})
    assert "PASS  退市股覆盖自证(AGENTS.md:97)" in out, out


def test_gate_end_to_end_red(tmp_path, monkeypatch, capsys):
    """端到端【红】：审计文件缺失 → 该行 FAIL 并给出中文原因。"""
    out = _run_gate(tmp_path, monkeypatch, capsys)
    assert "FAIL  退市股覆盖自证(AGENTS.md:97)" in out, out
    assert "候选池无法自证含退市股" in out, out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
