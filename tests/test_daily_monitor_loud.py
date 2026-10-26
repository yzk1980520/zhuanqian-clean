# -*- coding: utf-8 -*-
"""R1 TDD: scripts/factor_ic_daily_monitor.py 主流程 — 修假绿 + per-item 隔离 + 保留 gate 契约

K45 口径 A1 / K46 放行 R1 主体(exit(2) 单列)。4 seam(monkeypatch registry 写, 不真写 data/):
  S1: main 不再调用 reg.sync_to_config()(根版无此方法→AttributeError 假绿根因)
  S2: main 不再调用 sync_weights_to_config(全库无 def=NameError 死引用); --sync 转 loud 提示
  S3: per-item 隔离 — 单因子 update_ic 抛异常时, 该因子列名 loud, 其余因子仍落 registry, 整体不崩
  S4: gate 契约不变 — gate passed→exit0 / not passed→exit1
"""
import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)
import factor_ic_daily_monitor as mon  # noqa: E402


class FakeReg:
    """假 FactorRegistry: 记录调用 + 可注入失败; 提供 sync_to_config 以便检测 main 是否误调它"""

    instances = []

    def __init__(self):
        self.calls = []
        self.fail_on = set(type(self).fail_on)
        FakeReg.instances.append(self)

    def update_ic(self, name, ic):
        if name in self.fail_on:
            raise ValueError(f"{name} registry 写失败(模拟)")
        self.calls.append(("update_ic", name, ic))

    def sync_to_config(self):
        self.calls.append(("sync_to_config",))


def _run_main(monkeypatch, argv, results, gate, fail_on=None):
    """统一驱动 mon.main: 隔离因子计算/落盘/registry, 返回 (exit_code, FakeReg 实例)"""
    FakeReg.instances.clear()

    class _Mod:
        FactorRegistry = FakeReg

    monkeypatch.setitem(sys.modules, "factor_registry", _Mod())
    monkeypatch.setattr(mon, "run_ic_monitor", lambda quick: results)
    monkeypatch.setattr(mon, "check_door_gate", lambda r: gate)
    monkeypatch.setattr(mon, "save_results", lambda r, g: None)
    FakeReg.fail_on = set(fail_on or ())
    monkeypatch.setattr(sys, "argv", ["factor_ic_daily_monitor"] + argv)

    with pytest.raises(SystemExit) as exc:
        mon.main()
    reg = FakeReg.instances[-1] if FakeReg.instances else None
    return exc.value.code, reg


GATE_PASS = {"valid": 5, "total_factors": 5, "observe": 0, "dead": 0, "passed": True, "issues": []}
GATE_FAIL = {"valid": 1, "total_factors": 5, "observe": 1, "dead": 3, "passed": False, "issues": ["有效因子不足"]}


def test_s1_no_sync_to_config(monkeypatch):
    """S1: main 不得调用 reg.sync_to_config (假绿根因)"""
    results = {"a": {"ic": 0.1}, "c": {"ic": 0.3}}
    code, reg = _run_main(monkeypatch, [], results, GATE_PASS)
    assert reg is not None, "main 应构造 registry(保留 update_ic 写口)"
    called = [c for c in reg.calls if c[0] == "sync_to_config"]
    assert not called, f"main 仍在调 sync_to_config (假绿): {called}"


def test_s2_no_sync_weights_to_config(monkeypatch):
    """S2: --sync 不得触发 NameError(死引用), 应 loud 提示走实盘任务单后正常 exit"""
    results = {"a": {"ic": 0.1}}
    # 现码: sync_weights_to_config 无 def → NameError 泄漏 (非 SystemExit) → 红
    code, reg = _run_main(monkeypatch, ["--sync"], results, GATE_PASS)
    assert code in (0, 1), f"--sync 路径未走 SystemExit(可能 NameError/其它崩溃): code={code}"


def test_s3_per_item_isolation(monkeypatch):
    """S3: b 写失败时 a/c 仍落 registry + 整体不崩 + 失败因子被记录"""
    results = {"a": {"ic": 0.1}, "b": {"ic": 0.2}, "c": {"ic": 0.3}}
    code, reg = _run_main(monkeypatch, [], results, GATE_PASS, fail_on={"b"})
    assert code == 0, f"单因子失败不该破坏 gate 契约(exit 0), 实得 {code}"
    ok = sorted(c[1] for c in reg.calls if c[0] == "update_ic")
    assert ok == ["a", "c"], (
        f"per-item 隔离失败: b 写失败不应阻断 a/c 落 registry, 实际更新={ok} "
        f"(现码单 try 包全 for → 一个抛就跳出)"
    )


def test_s4_gate_contract_preserved(monkeypatch):
    """S4: gate passed→exit0 / not passed→exit1 (契约不变)"""
    code_pass, _ = _run_main(monkeypatch, [], {"a": {"ic": 0.1}}, GATE_PASS)
    code_fail, _ = _run_main(monkeypatch, [], {"a": {"ic": 0.1}}, GATE_FAIL)
    assert code_pass == 0, f"gate passed 应 exit0, 实得 {code_pass}"
    assert code_fail == 1, f"gate not passed 应 exit1, 实得 {code_fail}"
