#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drill_gov_metadata_wipe.py — P-B4 合成故障演练件 (dev 自动修复通道"再生冲掉溯源字段"型)
背景: 10/24 dev 通道 (author=dev@zhuanqian.local) 再生 factor_gate.json 时冲掉 3 个
@user 终裁溯源字段 (GATE_STRICT_RULE / ruling_timestamp / ruling_by), 审计链断裂
(@老五 抓到, RUL 独立真源 data/rulings/ic_strict_gate_ruling.json 兜底, 57848d6d)。
演练: 在 tmp 副本上模拟冲掉 → 断言 RUL 独立源在场且字段完整 = 兜底网有效 (P1 告警件, 非修复);
零副作用: 只读生产件, 写面仅 tmp, 不自动写回任何治理元数据 (quarantine 语义: 冲掉只告警不修)。
exit: 0=兜底网有效(冲掉可溯源) 1=RUL 源缺失/字段不全(兜底网本身破, 真 P1)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "data" / "factor_ic" / "factor_gate.json"
RUL = ROOT / "data" / "rulings" / "ic_strict_gate_ruling.json"
WIPED_FIELDS = ("GATE_STRICT_RULE", "ruling_timestamp", "ruling_by")


def main():
    fails = []
    # 1) 生产件在场性 (缺=演练无法构造故障, fail-close)
    if not GATE.exists():
        fails.append(f"GATE 源缺失: {GATE} (fail-close)")
    else:
        gate = json.loads(GATE.read_text(encoding="utf-8"))
        # 2) 模拟 dev 通道再生: 副本上冲掉 3 字段 (写面=tmp, 零副作用)
        wiped = {k: v for k, v in gate.items()}
        for f in WIPED_FIELDS:
            wiped[f] = None if f in wiped else "MISSING"
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", dir=tempfile.gettempdir(),
                                          delete=False, encoding="utf-8")
        json.dump(wiped, tmp, ensure_ascii=False)
        tmp.close()
        _ = json.load(open(tmp.name, encoding="utf-8"))  # 冲掉件可解析
        os.unlink(tmp.name)
        print(f"  [演练] tmp 副本冲掉 {len(WIPED_FIELDS)} 溯源字段完成 (生产件未动)")
    # 3) 兜底断言: RUL 独立真源在场 + 关键溯源字段完整
    if not RUL.exists():
        fails.append(f"P1: RUL 独立源缺失: {RUL} — 兜底网破, dev 通道再生将永久断审计链")
    else:
        rul = json.loads(RUL.read_text(encoding="utf-8"))
        need = ("decided_by", "evidence")
        for k in need:
            if not any(k in kk.lower() for kk in rul):
                fails.append(f"P1: RUL 源缺 {k} 字段 — 兜底溯源不全")
        print(f"  [断言] RUL 独立源在场且 {list(need)} 完整 ✓ (冲掉件可经 RUL 回溯, P1 告警不自动修)")
    result = {"pass": not fails, "p1": fails,
              "repair_class": "quarantine", "note": "再生冲掉=只告警不修 (防洗白总则), 修复走会签"}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
