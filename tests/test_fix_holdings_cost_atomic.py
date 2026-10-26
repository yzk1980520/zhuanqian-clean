# -*- coding: utf-8 -*-
"""R4c #1 TDD: scripts/fix_holdings_cost.py 写实盘 holdings.json 改原子写 (K51 §三 批准, 落码后生效)

#4 同性质根因: L44 裸 open('data/holdings.json','w') 直写实盘事实源, 写中断=持仓数据损坏(比 #4 研究 artifact 更危险)。
改法(落码时执行): 抽 save_holdings() 函数 + 顶层加 __main__ 守护 + 走 atomic_json.update_json(唯一写口, FileLock+fsync)。

TDD 陷阱(本轮落码前报 K51): 当前脚本**顶层无 __main__ 守护**, import 即执行全量(含 L44 裸写盘)。
  故 S1/S2(行为 seam) 落码前 import 会真写 data/holdings.json = 副作用。本轮仅 S3 静态断言可零副作用跑出红态;
  S1/S2 留占位(importorskip 保护), **落码(抽函数+加__main__)后才安全启用**——落码前 pytest 须 -k "s3" 只跑静态项。

seam:
  S3(静态, 本轮可跑): 源码应走 atomic_json 且不再裸 open('data/holdings.json','w') → 当前裸写=红
  S1(行为, 落码后): save_holdings 写中断 → 目标文件内容=写前原值(未破坏)
  S2(行为, 落码后): save_holdings 正常写 → 目标可 json.load + 无 tmp 残留
"""
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "scripts", "fix_holdings_cost.py")


def _src_text():
    with open(SRC, encoding="utf-8") as f:
        return f.read()


def test_s3_static_must_use_atomic_json_not_bare_open():
    """S3(落码前可零副作用跑出): 写口必须走 atomic_json, 不得裸 open('w') 直写 data/holdings.json。

    当前脚本 L44 裸 open('w') + 无 atomic_json → 本断言失败(红)。落码(抽 save_holdings 走 update_json)后 → 绿。
    """
    src = _src_text()
    uses_atomic = ("atomic_json" in src) or ("update_json" in src)
    bare_write = ("'data/holdings.json', 'w'" in src) or ('"data/holdings.json", "w"' in src)
    assert uses_atomic, "脚本未走 atomic_json (仍裸写 data/holdings.json, 根因未修)"
    assert not bare_write, "脚本仍裸 open('w') 直写 data/holdings.json, 需改 atomic_json"


def test_s1_interrupt_leaves_no_corrupt_target(tmp_path):
    """S1(落码后启用): save_holdings 写中断 → 目标=写前原值(未破坏)。

    落码前: 无 save_holdings / 无 __main__ 守护, import 会写盘 → importorskip 保护, 不触发副作用。
    落码时补全: mock atomic_json.update_json 抛中断(不 replace 目标) + 断言目标保持写前原值。
    """
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import fix_holdings_cost as fhc  # 落码后 import 安全(已加 __main__ 守护); 落码前会写盘
    if not hasattr(fhc, "save_holdings"):
        pytest.importorskip("save_holdings 未抽出 (R4c#1 未落码)")
    target = tmp_path / "holdings.json"
    original = {"holdings": [], "available_cash": 100.0}
    target.write_text(json.dumps(original), encoding="utf-8")

    import core.pipeline.atomic_json as atomic_json  # 2026-10-24 T051 C4: S4 裸 import 缺陷修复
    orig_update = atomic_json.update_json

    def _interrupted(path, mutator, default=None):
        # 模拟写中断(进程被杀): 不 replace 目标, 直接抛错, 目标应保持原值
        raise InterruptedError("模拟写中断")

    atomic_json.update_json = _interrupted
    try:
        try:
            fhc.save_holdings({"holdings": [], "available_cash": 0.0}, str(target))
        except InterruptedError:
            print(f"🔴 [tests\test_fix_holdings_cost_atomic.py] CR-01: except InterruptedError:", file=sys.stderr)
    finally:
        atomic_json.update_json = orig_update
    # 核心断言: 写中断后目标内容=写前原值(未破坏), 而非被截断/半成品
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["available_cash"] == 100.0, f"写中断后目标被破坏: {after}"


def test_s2_normal_write_produces_valid_json(tmp_path):
    """S2(落码后启用): save_holdings 正常写 → 目标可 parse + 无 tmp 残留。落码前无函数 → 跳过。"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import fix_holdings_cost as fhc
    if not hasattr(fhc, "save_holdings"):
        pytest.importorskip("save_holdings 未抽出 (R4c#1 未落码)")
    target = tmp_path / "holdings.json"
    fhc.save_holdings({"holdings": [], "available_cash": 22103.56}, str(target))
    assert json.loads(target.read_text(encoding="utf-8"))["available_cash"] == 22103.56
    assert not [x for x in os.listdir(tmp_path) if ".tmp" in x], "残留 tmp"


def test_s4_full_replace_no_stale_field(tmp_path):
    """S4(K54 §二补2 回查补断言, #1 非重开): save_holdings 是**全量替换**语义, 非 key-level merge。

    原 L44 裸 open('w') = 全量覆盖; 改后走 update_json(mutator=lambda _fresh: data) → atomic_dump(data)
    全量写 data(完整新对象)。故盘上原有的多余字段**不应残留**。
    若误改成 merge 语义, 旧字段会残留 = R4b 类行为漂移, 本断言捕获。
    """
    import sys
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import fix_holdings_cost as fhc
    if not hasattr(fhc, "save_holdings"):
        pytest.importorskip("save_holdings 未抽出 (R4c#1 未落码)")
    target = tmp_path / "holdings.json"
    # 盘上原文件含一个多余字段 STALE_FIELD(模拟旧版残留)
    target.write_text(json.dumps({"holdings": [], "available_cash": 1.0, "STALE_FIELD": "old"}),
                      encoding="utf-8")
    # 新写不含 STALE_FIELD 的完整对象
    fhc.save_holdings({"holdings": [], "available_cash": 999.0}, str(target))
    after = json.loads(target.read_text(encoding="utf-8"))
    assert "STALE_FIELD" not in after, f"全量替换失效: 旧字段 STALE_FIELD 残留 → 行为漂移(merge 语义)"
    assert after["available_cash"] == 999.0
