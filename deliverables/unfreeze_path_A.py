#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""总管备用执行脚本：解冻路径A（A2 冻结，review_status.json）。
默认 dry-run（只打印 + 验证，不写盘）。--execute 才真正落盘。

设计依据：deliverables/总管仲裁-出票解冻与移交-20261020.md §1.3
  - 正确姿势 = 恢复 final_verdict="PASS"（非删键；删键会落到 B1 findings 硬失败仍冻结）
  - 删 _freeze_20261018
  - 新写 freeze_unlock_record（unlocked_by 注明依据+批准人）
  - 原子写（atomic_json.update_json），写后重跑 review_gate.evaluate 断言 frozen=False

资金动作：恢复出票（建仓前置）→ 须老大签批后才 --execute。
用法：
  .venv/Scripts/python.exe deliverables/unfreeze_path_A.py            # dry-run
  .venv/Scripts/python.exe deliverables/unfreeze_path_A.py --execute  # 老大签后落盘
"""
import json, os, sys, shutil, copy

PROJECT = r"D:\open code\zhuanqian"
RS = os.path.join(PROJECT, "data", "review_status.json")
BAK = os.path.join(PROJECT, "data", "review_status.json.bak_20261020_解冻前")
sys.path.insert(0, PROJECT)
sys.path.insert(0, os.path.join(PROJECT, "scripts"))
from scripts import review_gate  # noqa

def main():
    execute = "--execute" in sys.argv
    d = json.load(open(RS, encoding="utf-8-sig"))

    # --- candidate state ---
    cand = copy.deepcopy(d)
    cand["final_verdict"] = "PASS"          # restore pre-10-18 value
    cand.pop("_freeze_20261018", None)
    cand["freeze_unlock_record"] = {
        "frozen_at": "2026-10-18",
        "frozen_by": "老六(WorkBuddy) 执行 / 老大 2026-10-18 拍板",
        "unlocked_at": "2026-10-20 (总管执笔, 待/已老大签批)",
        "unlocked_by": "总管裁决 + 老大签批",
        "basis": "冻结起因(P0 amount 损坏 62.67%)已消除: 全仓 0.1314%(32632/24840498) / 选股池 0.00200%(268/13407530), 残留均 ST停牌空值/指数/基金非选股对象; 总管全量复算=老六复核一致。恢复 pre-10-18 出票放行, 零契约变更。"
    }

    # --- dry-run verification (always) ---
    tmp = os.path.join(PROJECT, ".scratch", "rsv_unfreeze_candidate.json")
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    json.dump(cand, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    pre = review_gate.evaluate(RS)
    post = review_gate.evaluate(tmp)
    print("[pre ] gate:", json.dumps(pre, ensure_ascii=False))
    print("[post] gate:", json.dumps(post, ensure_ascii=False))
    assert post["frozen"] is False, "dry-run 验证失败: 候选态仍 frozen=True，脚本拒绝继续"
    assert pre["frozen"] is True, "预检查失败: 现文件本应 frozen=True"

    if not execute:
        print("\n== DRY-RUN 通过，未写盘。需 --execute（且已获老大签批）才落盘 ==")
        print("回滚点:", BAK)
        return 0

    # --- execute (only after 老大 sign-off) ---
    if not os.path.exists(BAK):
        shutil.copy2(RS, BAK)
        print("backup ->", BAK)
    else:
        print("backup 已存在:", BAK, "(不覆盖)")
    from scripts.atomic_json import update_json
    update_json(RS, lambda s: cand, default={})
    live = review_gate.evaluate(RS)
    print("[live] gate after write:", json.dumps(live, ensure_ascii=False))
    assert live["frozen"] is False, "写后断言失败: 落盘后仍 frozen=True"
    print("✅ 解冻完成: final_verdict=PASS, _freeze_20261018 已删, freeze_unlock_record 已写")
    print("回滚: cp " + BAK + " data/review_status.json")
    return 0

if __name__ == "__main__":
    sys.exit(main())
