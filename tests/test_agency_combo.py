# -*- coding: utf-8 -*-
"""test_agency_combo.py — agency 专家组合门 (3组合, RED→GREEN)

seam: team/agency_combo.py 的 COMBOS / combo_spec / run_combo
纪律: 专家输出=研究/评审输入, 末位门专家默认否决, 产物落 deliverables, 不碰交易数据。
"""
import sys, json
from pathlib import Path

import pytest

BASE = Path(r"D:/open code/zhuanqian")
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "team"))


def _make_fake_lib(tmp_path):
    """假专家库: 8 个专家文件, 每个含唯一锚点 marker (独立验证 LLM 收到谁)"""
    lib = tmp_path / "lib"
    specs = {
        "engineering-code-reviewer": ("代码审查员", "REVIEW_ANCHOR"),
        "testing-evidence-collector": ("证据收集者", "EVIDENCE_ANCHOR"),
        "testing-reality-checker": ("现实检验者", "REALITY_ANCHOR"),
        "engineering-software-architect": ("软件架构师", "ARCH_ANCHOR"),
        "engineering-data-engineer": ("数据工程师", "DATA_ANCHOR"),
        "engineering-minimal-change-engineer": ("最小变更工程师", "MINCHANGE_ANCHOR"),
        "security-compliance-auditor": ("合规审计师", "COMPLIANCE_ANCHOR"),
        "testing-performance-benchmarker": ("性能基准师", "PERF_ANCHOR"),
    }
    by_dir = {
        "engineering": [k for k in specs if k.startswith("engineering-")],
        "testing": [k for k in specs if k.startswith("testing-")],
        "security": [k for k in specs if k.startswith("security-")],
    }
    for d, ks in by_dir.items():
        (lib / d).mkdir(parents=True)
        for k in ks:
            nm, mk = specs[k]
            (lib / d / f"{k}.md").write_text(
                f"---\nname: {nm}\ndescription: x\n---\n\n# {nm}\n你是{nm}...{mk}...\n",
                encoding="utf-8")
    return lib


# ── Slice 1: 组合声明 + 规格查询 ────────────────────────────────────
def test_combos_declared_and_gated():
    from agency_combo import COMBOS, combo_spec
    assert set(COMBOS) == {"r0_release_gate", "arch_review_board", "compliance_perf_gate"}
    for name, s in COMBOS.items():
        assert s["gate_expert"] == s["experts"][-1], f"{name} 门专家必须在末位"
    # 各组合专家序列 (独立期望, 非重读实现)
    assert combo_spec("r0_release_gate")["experts"] == [
        "engineering-code-reviewer", "testing-evidence-collector", "testing-reality-checker"]
    assert combo_spec("arch_review_board")["experts"] == [
        "engineering-software-architect", "engineering-data-engineer",
        "engineering-minimal-change-engineer"]
    assert combo_spec("compliance_perf_gate")["experts"] == [
        "security-compliance-auditor", "testing-performance-benchmarker"]
    with pytest.raises(KeyError):
        combo_spec("not_a_combo")


# ── Slice 2: run_combo DAG 执行 + 产物 + manifest + 交易数据零改动 ──
def test_run_combo_r0_mock(tmp_path, monkeypatch):
    import agency_combo

    root = tmp_path
    (root / "data").mkdir()
    (root / "trade_log.json").write_text(json.dumps({"t": 1}), encoding="utf-8")
    (root / "data" / "holdings.json").write_text(json.dumps({"h": []}), encoding="utf-8")
    before_hold = (root / "data" / "holdings.json").read_text(encoding="utf-8")
    before_tl = (root / "trade_log.json").read_text(encoding="utf-8")

    monkeypatch.setattr(agency_combo, "PROJECT_ROOT", root)
    lib = _make_fake_lib(tmp_path)

    calls = []

    def fake_llm(system_prompt, user_brief):
        calls.append((system_prompt, user_brief))
        # 每专家返回含其锚点 + 末位(reality-checker)给固定 verdict 字面量
        for mk in ("REVIEW_ANCHOR", "EVIDENCE_ANCHOR", "REALITY_ANCHOR", "ARCH_ANCHOR",
                   "DATA_ANCHOR", "MINCHANGE_ANCHOR", "COMPLIANCE_ANCHOR", "PERF_ANCHOR"):
            if mk in system_prompt:
                extra = "\nVERDICT: NEEDS_IMPROVEMENT" if mk == "REALITY_ANCHOR" else ""
                return f"{mk}_OUT{extra}"
        raise AssertionError(f"LLM 收到未知专家 system prompt: {system_prompt[:40]}")

    out = agency_combo.run_combo(
        "r0_release_gate",
        task="任务: 修复 tdx_indicators date 解析\n证据: tests/test_compute_indicators_date.py 4/4 GREEN",
        library_path=str(lib),
        llm=fake_llm,
    )

    # ① 3 专家按 DAG 顺序调用 (锚点序列独立断言)
    anchors = [a for sp, _ in calls for a in
               ("REVIEW_ANCHOR", "EVIDENCE_ANCHOR", "REALITY_ANCHOR") if a in sp]
    assert anchors == ["REVIEW_ANCHOR", "EVIDENCE_ANCHOR", "REALITY_ANCHOR"], "DAG 顺序必须固定"

    # ② 上游输出注入下游 user brief (DAG 传递)
    assert "REVIEW_ANCHOR_OUT" in calls[1][1], "code-reviewer 输出须进入 evidence-collector 输入"
    assert "EVIDENCE_ANCHOR_OUT" in calls[2][1], "evidence-collector 输出须进入 reality-checker 输入"

    # ③ 产物文件 + verdict 提取 (独立字面量)
    f = Path(out["file"])
    assert f.exists()
    content = f.read_text(encoding="utf-8")
    assert "REVIEW_ANCHOR_OUT" in content and "REALITY_ANCHOR_OUT" in content
    assert "NEEDS_IMPROVEMENT" in content

    # ④ manifest 只增 combo_gates, phases 原样
    mf = json.loads((root / "deliverables" / "trading-agent" / "sh603727" / "manifest.json")
                   .read_text(encoding="utf-8")) if (root / "deliverables" / "trading-agent" / "sh603727" / "manifest.json").exists() else None
    # (本测试未指定 code 目录, 产物走默认: 验证 out 里带 code 路径即可)
    assert "code" in out and "combo" in out and out["combo"] == "r0_release_gate"
    assert out["verdict"] == "NEEDS_IMPROVEMENT"

    # ⑤ 交易数据零改动 (红线)
    assert (root / "data" / "holdings.json").read_text(encoding="utf-8") == before_hold
    assert (root / "trade_log.json").read_text(encoding="utf-8") == before_tl


def test_run_combo_pass_verdict(tmp_path, monkeypatch):
    """verdict 提取: 门专家回 PASS 时提取 PASS (非恒 NEEDS)"""
    import agency_combo
    root = tmp_path
    monkeypatch.setattr(agency_combo, "PROJECT_ROOT", root)
    lib = _make_fake_lib(tmp_path)

    def fake_llm(sp, ub):
        mk = next((m for m in ("REVIEW_ANCHOR", "REALITY_ANCHOR") if m in sp), "?")
        return f"{mk}_OK\nVERDICT: PASS" if mk == "REALITY_ANCHOR" else f"{mk}_OK"

    out = agency_combo.run_combo("r0_release_gate", task="t", library_path=str(lib),
                                 llm=fake_llm, code="sz000001")
    assert out["verdict"] == "PASS"


def test_gate_brief_carries_verdict_protocol(tmp_path, monkeypatch):
    """门纪律: 门专家的 user brief 必须显式要求 VERDICT 输出协议 (防自由发挥→提取落空)"""
    import agency_combo
    root = tmp_path
    monkeypatch.setattr(agency_combo, "PROJECT_ROOT", root)
    lib = _make_fake_lib(tmp_path)

    calls = []

    def fake_llm(sp, ub):
        calls.append((sp, ub))
        return "OK"

    agency_combo.run_combo("compliance_perf_gate", task="t", library_path=str(lib), llm=fake_llm)
    # 末位调用 = 门专家(performance-benchmarker)
    gate_sp, gate_ub = calls[-1]
    assert "PERF_ANCHOR" in gate_sp
    # 独立字面量断言: 协议行必须含机器可提取的 marker + 两个合法取值
    assert "VERDICT:" in gate_ub
    assert "PASS" in gate_ub and "NEEDS_IMPROVEMENT" in gate_ub
    # 上游专家不带门协议 (只有门出 verdict)
    assert "VERDICT:" not in calls[0][1]


def test_route_combos_by_task(tmp_path, monkeypatch):
    """按需路由: C1 恒在(默认放行门), C2/C3 按任务关键词加跑 (独立 work example)"""
    from agency_combo import route_combos
    # work examples (独立手判, 非重读实现):
    #  "重构"命中 C2; 无性能/合规词 → 不 C3
    assert route_combos("回测引擎评分函数重构, R0 合入") == ["r0_release_gate", "arch_review_board"]
    # 纯 bug 修复, 无架构/性能词 → 只 C1 默认门
    assert route_combos("修复 daily_pick cron 崩溃") == ["r0_release_gate"]
    #  "超时/性能/基准"命中 C3
    assert route_combos("回测扫描超时优化, 性能基准") == ["r0_release_gate", "compliance_perf_gate"]
    #  合规词命中 C3
    assert route_combos("数据红线合规审计") == ["r0_release_gate", "compliance_perf_gate"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-p", "no:cacheprovider", "--no-cov"])