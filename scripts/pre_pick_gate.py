#!/usr/bin/env python3
# DEPRECATED → use scripts/check_all.py contract
# -*- coding: utf-8 -*-
"""
pre_pick_gate.py — 选股前必检清单门禁（P0 阻断）
=================================================================
总管落地（老四方案 2026-10-14 拍板项②）：把 老四 precheck_cli.py 必检清单
收敛为选股前置阻断门。
语义（总管裁定，与 daily_pick 步骤3b 一致）：
  - 阻断集 BLOCKING_CIDS = {F1, D1, G1, G2}（数据新鲜度/评审闸/合理性闸/必要文件）
    任一 P0 FAIL → 禁止本轮选股。
  - G3（三重解冻）只控制"落仓"，不阻断选股候选池（dry_run 态选股照跑、交易不落仓）。
  - R1/R2 为 P1/P2，仅记录不阻断。
  - fail-safe：清单自身异常 → 判定 BLOCK，不静默放行。
副作用（只写自己的契约文件，不碰交易数据）：
  - BLOCK  → 写 data/pre_pick_blocker.json + 追加 P0 到 data/alert_log.jsonl
              （老四 P0 中继 cron 消费 → 飞书）
  - 非BLOCK → 清除旧 data/pre_pick_blocker.json
用法：
  python scripts/pre_pick_gate.py          # exit 0=放行 / 1=阻断
  import pre_pick_gate; pre_pick_gate.main()   # 进程内调用
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BLOCKER = DATA / "pre_pick_blocker.json"
ALERT_LOG = DATA / "alert_log.jsonl"

# 阻断选股候选池的 P0 项（G3 只管落仓，见模块 docstring）
BLOCKING_CIDS = ("F1", "D1", "G1", "G2")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def evaluate() -> dict:
    """运行老四必检清单并给出本门裁决。

    返回 {ts, verdict, blocked, blocking, g3_dry_run, message, items, summary}
    """
    sys.path.insert(0, str(ROOT))
    items, verdict = [], ""
    try:
        from scripts import precheck_cli  # 老四出品，2026-10-20 P2-1b 归位 scripts/（原仓根）
        res = precheck_cli.run_checklist()
        items = res.get("items", [])
        verdict = res.get("verdict", "")
    except Exception as e:
        # fail-safe：清单自身异常 → 合成 P0 FAIL 项，判 BLOCK（不静默放行）
        items = [{
            "cid": "GATE", "name": "必检清单执行异常", "severity": "P0",
            "status": "FAIL", "message": f"precheck_cli 执行异常: {e}",
            "evidence": f"{type(e).__name__}: {e}", "details": {},
        }]
        verdict = "BLOCK"
        print(f"  ⚠️ 必检清单执行异常 → fail-safe 阻断: {type(e).__name__}: {e}")

    blocking = [it["cid"] for it in items
                if it.get("cid") in BLOCKING_CIDS
                and it.get("severity") == "P0"
                and it.get("status") == "FAIL"]
    g3 = next((it for it in items if it.get("cid") == "G3"), None)
    g3_dry_run = bool(g3 and g3.get("status") != "PASS")
    blocked = len(blocking) > 0

    fail_msgs = [f"{it.get('cid')}: {it.get('message','')}" for it in items
                 if it.get("cid") in blocking]
    message = ("P0阻断项 " + "/".join(blocking) + "：" + " | ".join(fail_msgs)) if blocked \
        else "必检清单放行" + ("（G3未全绿→交易dry_run，候选池照出）" if g3_dry_run else "")
    fail_cnt = sum(1 for it in items if it.get("status") == "FAIL")
    warn_cnt = sum(1 for it in items if it.get("status") == "WARN")
    summary = {"total": len(items), "fail": fail_cnt, "warn": warn_cnt,
               "blocking": len(blocking)}
    return {
        "ts": _now(), "verdict": verdict, "blocked": blocked,
        "blocking": blocking, "g3_dry_run": g3_dry_run,
        "message": message, "items": items, "summary": summary,
    }


def record(outcome: dict) -> None:
    """BLOCK → 写 blocker + 追加 P0 到 alert_log；非BLOCK → 清 blocker。"""
    DATA.mkdir(parents=True, exist_ok=True)
    if outcome["blocked"]:
        _atomic_write_json(BLOCKER, {
            "ts": outcome["ts"], "blocking": outcome["blocking"],
            "verdict": outcome["verdict"], "g3_dry_run": outcome["g3_dry_run"],
            "message": outcome["message"],
            "by": "pre_pick_gate", "schema": "v1",
        })
        line = {
            "ts": outcome["ts"], "level": "P0",
            "task_id": "pre_pick_gate", "check": "pre_pick",
            "issue": outcome["message"],
            "evidence": f"blocking={outcome['blocking']} verdict={outcome['verdict']} "
                        f"g3_dry_run={outcome['g3_dry_run']}",
            "state": "new", "source": "pre_pick_gate",
        }
        with open(ALERT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    elif BLOCKER.exists():
        try:
            BLOCKER.unlink()
        except Exception:
            print(f"🔴 [scripts\pre_pick_gate.py] CR-01: except OSError:", file=sys.stderr)
def main() -> int:
    out = evaluate()
    record(out)
    s_fail = sum(1 for it in out["items"] if it.get("status") == "FAIL")
    s_warn = sum(1 for it in out["items"] if it.get("status") == "WARN")
    print(f"[pre_pick_gate] ts={out['ts']} verdict={out['verdict']} "
          f"(FAIL={s_fail} WARN={s_warn}) blocked={out['blocked']} "
          f"g3_dry_run={out['g3_dry_run']}")
    if out["blocked"]:
        print(f"  🛑 {out['message']}")
        print(f"  已写 {BLOCKER.name} + P0 已入 alert_log（老四中继发飞书）")
    else:
        print(f"  ✅ {out['message']}")
    return 1 if out["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
