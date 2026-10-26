# -*- coding: utf-8 -*-
"""R4b TDD: scripts/convexity_protector.py save_result 改原子写 (#4 根因)

#4 坏文件根因 = save_result 用裸 open(output_path, 'w') 直写最终路径, json.dump 中途被杀
→ 留下 111 字节截断的坏文件。重生成只修了症状, 根因 (裸写) 还在, 下次同样会坏。

R4b (K48): save_result 改原子写 (tmp + os.replace 同目录), 写中断不得留下坏文件。
  S1: json.dump 中途被杀 (模拟) → 目标路径不得存在 (原子写: 半成品只在 tmp, 不 replace 则目标不动)
  S2: 正常写 → 目标路径产出合法 JSON + 无 .tmp 残留
"""
import json
import os
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import convexity_protector as cp  # noqa: E402


def test_r4b_s1_interrupt_leaves_no_corrupt_target(tmp_path, monkeypatch):
    """S1: 写中断 (json.dump 抛异常模拟进程被杀) → 目标路径不得留下半成品文件。

    裸 open('w') 直写: 文件立即创建(空), dump 抛 → 目标=空/半成品 → 红。
    原子写 (tmp+replace): 只写 tmp, 不 replace → 目标不存在 → 绿。
    """
    prot = cp.ConvexityProtector()
    target = tmp_path / "convexity_out.json"

    def fake_dump(obj, f, *a, **kw):
        raise InterruptedError("模拟写中断 (进程被杀)")

    monkeypatch.setattr(cp.json, "dump", fake_dump)

    with pytest.raises(InterruptedError):
        prot.save_result({"oos_is_ratio": 0.3242, "cv": 4.4974,
                          "overfit_flag": np.bool_(True), "protection_passed": False},
                         str(target))

    assert not target.exists(), (
        f"写中断却留下目标文件 {target} (裸 open 非原子, 根因未修); "
        f"原子写应只写 tmp, 中断时目标不动"
    )


def test_r4b_s2_atomic_success_produces_valid_json(tmp_path):
    """S2: 正常写 → 目标路径产出可 parse 的合法 JSON (含 numpy 值已转原生) + 无 .tmp 残留"""
    prot = cp.ConvexityProtector()
    target = tmp_path / "convexity_out.json"
    res = prot.save_result(
        {"oos_is_ratio": 0.3242, "cv": 4.4974, "overfit_flag": np.bool_(True),
         "protection_passed": np.False_},
        str(target))

    assert os.path.exists(target), f"正常写后目标文件应存在: {target}"
    with open(target, encoding="utf-8") as f:
        data = json.load(f)  # 若为半成品/裸写中断, 这里会 JSONDecodeError
    assert data["overfit_flag"] is True, "numpy.bool_ 应转原生 bool"
    assert data["protection_passed"] is False, "numpy.False_ 应转原生 bool"
    # 原子写不应残留 tmp 文件 (同目录 .tmp* 清理)
    leftovers = [x for x in os.listdir(tmp_path) if x.startswith(".tmp") or "tmp_review" in x]
    assert not leftovers, f"原子写残留 tmp 文件未清理: {leftovers}"
