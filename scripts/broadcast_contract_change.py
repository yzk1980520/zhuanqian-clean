#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
契约变更广播器 — 让「谁改了契约，所有人都要知道」从一个约定变成一个动作。

═══ 为什么需要这个脚本 ═══
2026-10-17 诊断发现：09-30 三方会签把止损 8%→10%，但 17 天后仍有 6 处文档写 8%，
其中一份还挂着「P0 / 禁止修改」标签。**没有任何机制通知到各 agent**，谁改的谁知道。
本脚本把广播固化成一条命令，改契约必须跑它，否则留痕缺失。

═══ 它做五件事 ═══
  1. CHANGELOG 追加变更条目（谁/何时/从什么改到什么/依据/是否回测复核）
  2. 当日记忆追加（防止新会话读到旧口径）
  3. 生成飞书推送文本（打印出来，人工或用 hermes 发到团队群）
  4. 可选：在看板建任务卡，派给需要同步数据/代码的人
  5. **自动刷新契约真源戳**（`scripts/sync_true_source_stamp.py`）—— 2026-10-17 老大拍板：
     「不要留成『改契约的人记得手跑一步』。凡是要求人记住的步骤，三次之内必漏一次，
     而且漏了是**静默的**（戳不刷新不会报错，只会让 bootstrap 校验慢慢失真）。」
     **刷新失败 = 广播失败**（exit 1 + 打印原因），绝不静默跳过；新戳值打进
     CHANGELOG / 契约台账 / 记忆 / 飞书文本，做到可追溯。

═══ 用法 ═══
  python scripts/broadcast_contract_change.py \
      --item   "硬止损" \
      --from   "0.08 (8%)" \
      --to     "0.10 (10%)" \
      --source "risk_rules.py:51 STRATEGY_STOP_LOSS_PCT" \
      --basis  "2026-09-30 三方会签" \
      --impact "在持仓位 sh603727 止损价需从 18.72 同步为 18.31" \
      --author workbuddy \
      --backtest pending

  --backtest : done | pending | skip   （pending 会在输出里标红提醒必须补）
  --kanban   zongguan                  （可选，给谁建同步任务卡）
  --dry-run                            （只打印不落盘）

注意：本脚本**不写实盘数据**（holdings/trade_log 属总管独占），只做留痕与通知。
"""
import argparse
import datetime
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG = os.path.join(PROJECT, "CHANGELOG.md")
MEMORY_DIR = os.path.join(PROJECT, ".workbuddy", "memory")
HERMES = r"D:/Hermes agent/Hermes Agent CN Desktop/.hermes/bin/hermes.exe"

# 真源戳（H4）—— 广播时自动刷新，不靠人肉记得跑
STAMP_SCRIPT = os.path.join(PROJECT, "scripts", "sync_true_source_stamp.py")
STAMP_JSON = os.path.join(PROJECT, ".agent", "true-source-stamp.json")
CONTRACT_CHANGELOG = os.path.join(PROJECT, "docs", "CONTRACT-CHANGELOG-20261017.md")

BANNER = "=" * 62


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def refresh_true_source_stamp():
    """
    自动刷新契约真源戳（老大 2026-10-17 拍板：不许留成"人肉记得跑一步"）。

    返回 (ok, token, detail)。**失败必须响亮报错** —— 静默跳过正是本轮治理要消灭的病：
    戳不刷新不会报错，只会让 bootstrap 校验与文档新鲜度守卫慢慢失真。
    """
    if not os.path.exists(STAMP_SCRIPT):
        return False, "", "真源戳脚本不存在：%s" % os.path.relpath(STAMP_SCRIPT, PROJECT)
    try:
        r = subprocess.run(
            [sys.executable, os.path.relpath(STAMP_SCRIPT, PROJECT)],
            cwd=PROJECT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    except Exception as e:  # noqa: BLE001 —— 任何异常都要变成响亮的失败，不是静默跳过
        return False, "", "调用 sync_true_source_stamp.py 异常：%r" % e

    if r.returncode != 0:
        return False, "", ("sync_true_source_stamp.py 退出码 %d\nstdout: %s\nstderr: %s"
                           % (r.returncode, (r.stdout or "")[-400:], (r.stderr or "")[-400:]))

    token = ""
    try:
        import json
        with open(STAMP_JSON, encoding="utf-8") as fh:
            token = json.load(fh).get("stamp_token", "")
    except Exception as e:  # noqa: BLE001
        return False, "", "真源戳已刷新但读回失败（%r）—— 戳状态不明，按失败处理" % e
    if not token.startswith("TSS:"):
        return False, "", "真源戳格式异常：%r" % token
    return True, token, (r.stdout or "").strip()


def _today():
    return datetime.date.today().isoformat()


def _changelog_entry(a, stamp):
    flag = {"done": "✅ 已回测复核", "pending": "⚠️ **待回测复核**",
            "skip": "➖ 无需回测"}[a.backtest]
    return (
        "\n## [%s] 契约变更：%s —— %s → %s\n"
        "- **真源**：`%s`\n"
        "- **依据**：%s\n"
        "- **影响面**：%s\n"
        "- **132 日全量回测**：%s\n"
        "- **广播人**：%s\n"
        "- **契约真源戳**：`%s`（`risk_rules.py` SHA256，由广播自动刷新；"
        "各契约文档头部须同步此戳，否则 `tests/test_doc_freshness.py` 会红）\n"
        % (_now(), a.item, a.frm, a.to, a.source, a.basis, a.impact, flag, a.author, stamp)
    )


def _memory_entry(a, stamp):
    return (
        "\n## %s 契约变更广播 · %s —— %s → %s\n"
        "- 真源：%s ｜ 依据：%s\n"
        "- 影响：%s\n"
        "- 132日回测：%s ｜ 广播人：%s\n"
        "- 契约真源戳：`%s`\n"
        % (_now(), a.item, a.frm, a.to, a.source, a.basis, a.impact, a.backtest, a.author, stamp)
    )


def _feishu_text(a, stamp):
    flag = {"done": "已回测复核", "pending": "**待回测复核（请安排 132 日全量）**",
            "skip": "无需回测"}[a.backtest]
    return (
        "【契约变更广播 · %s】\n"
        "%s：%s → %s\n"
        "真源：%s\n"
        "依据：%s\n"
        "影响：%s\n"
        "回测：%s\n"
        "契约真源戳：%s\n"
        "—— 请各 agent 同步各自文档/记忆，并把文档头部的 TSS 戳改为上面这个值，勿再沿用旧值。\n"
        % (_now(), a.item, a.frm, a.to, a.source, a.basis, a.impact, flag, stamp)
    )


def main():
    p = argparse.ArgumentParser(description="契约变更广播器：改契约必须留痕并通知全员")
    p.add_argument("--item", required=True, help="变更项，如 硬止损")
    p.add_argument("--from", dest="frm", required=True, help="原值")
    p.add_argument("--to", dest="to", required=True, help="新值")
    p.add_argument("--source", required=True, help="代码真源位置")
    p.add_argument("--basis", default="老大拍板", help="变更依据")
    p.add_argument("--impact", default="（未填写）", help="影响面/需同步的人")
    p.add_argument("--author", default="workbuddy", help="广播人")
    p.add_argument("--backtest", choices=["done", "pending", "skip"], default="pending")
    p.add_argument("--kanban", default=None, help="可选：给谁建同步任务卡")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    print(BANNER)
    print("契约变更广播  %s" % _now())
    print(BANNER)

    # ── 0) 自动刷新契约真源戳（老大 2026-10-17 拍板：不许靠人肉记得跑）──
    if a.dry_run:
        stamp = "（dry-run，未刷新真源戳）"
    else:
        ok, token, detail = refresh_true_source_stamp()
        if not ok:
            print("\n" + BANNER)
            print("❌ 广播**未完成**：契约真源戳自动刷新失败。")
            print(BANNER)
            print(detail)
            print("\n这是**故意的硬失败**——静默跳过会让 bootstrap 校验与文档新鲜度守卫")
            print("慢慢失真（戳不刷新不会报错，只会悄悄错）。请先修好上面的问题再广播，")
            print("或临时手动跑：python scripts/sync_true_source_stamp.py")
            return 1
        stamp = token
        print("✅ 真源戳已自动刷新：%s" % stamp)
        for ln in detail.splitlines():
            if "文档戳记" in ln or "已写入" in ln:
                print("   " + ln.strip())

    print(_changelog_entry(a, stamp))

    if a.backtest == "pending":
        print("⚠️ 回测状态 = pending：契约数值变更**必须**补 132 日全量回测，")
        print("   复核通过后方可确认合入生产。")

    if a.dry_run:
        print("\n[dry-run] 未落盘。")
        print("\n--- 飞书推送文本 ---\n" + _feishu_text(a, stamp))
        return 0

    # 1) CHANGELOG
    with open(CHANGELOG, "a", encoding="utf-8") as fh:
        fh.write(_changelog_entry(a, stamp))
    print("✅ 已追加 CHANGELOG.md")

    # 1b) 契约台账（B3 要求的留痕处；缺失只警告不硬失败，避免台账改名/归档后卡死广播）
    if os.path.exists(CONTRACT_CHANGELOG):
        with open(CONTRACT_CHANGELOG, "a", encoding="utf-8") as fh:
            fh.write("\n> %s · 契约变更广播：%s %s → %s ｜ 真源戳 `%s` ｜ 广播人 %s ｜ 回测 %s\n"
                     % (_now(), a.item, a.frm, a.to, stamp, a.author, a.backtest))
        print("✅ 已追加 %s" % os.path.relpath(CONTRACT_CHANGELOG, PROJECT))
    else:
        print("⚠️ 未找到契约台账 %s —— 变更未登记进台账，B3 留痕不完整"
              % os.path.relpath(CONTRACT_CHANGELOG, PROJECT))

    # 2) 当日记忆
    os.makedirs(MEMORY_DIR, exist_ok=True)
    mem = os.path.join(MEMORY_DIR, "%s.md" % _today())
    with open(mem, "a", encoding="utf-8") as fh:
        fh.write(_memory_entry(a, stamp))
    print("✅ 已追加 %s" % os.path.relpath(mem, PROJECT))

    # 3) 飞书文本
    print("\n--- 飞书推送文本（请发到团队群）---\n" + _feishu_text(a, stamp))

    # 4) 可选看板
    if a.kanban:
        if not os.path.exists(HERMES):
            print("⚠️ 未找到 hermes.exe，跳过建卡：%s" % HERMES)
            return 0
        title = "【契约变更·同步】%s：%s → %s" % (a.item, a.frm, a.to)
        body = _feishu_text(a)
        cmd = [HERMES, "kanban", "create", title, "--body", body,
               "--assignee", a.kanban, "--created-by", a.author, "--priority", "0"]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        print("✅ 看板建卡: %s" % (r.stdout or r.stderr).strip()[:200])

    return 0


if __name__ == "__main__":
    sys.exit(main())
