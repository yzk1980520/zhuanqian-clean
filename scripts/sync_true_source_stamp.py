# -*- coding: utf-8 -*-
"""
[H4] 契约真源戳（True Source Stamp）登记/刷新器（2026-10-17 W5 治理）

═══ 它解决什么 ═══
B3 要求「改契约必须留痕 + 广播」，但留痕与否**没有机器判据** —— 全靠自觉，
于是 09-30 把止损 8%→10% 之后没人广播，6 处文档继续写 8%，供奉了 17 天。

本脚本把"真源当前版本"钉成一个短戳，让**文档可以声明"我是照着这一版真源写的"**：
- `.agent/true-source-stamp.json` 记录 `core/risk/risk_rules_impl.py` 的 SHA256；
- 各契约文档头部写 `TSS:<前12位>`；
- `tests/test_doc_freshness.py` 比对：真源变了但戳没刷新 → **FAIL**，
  提示"请先登记 CONTRACT-CHANGELOG + 广播，再刷新戳"。

═══ 用法 ═══
    python scripts/sync_true_source_stamp.py            # 登记当前真源版本（写入 json）
    python scripts/sync_true_source_stamp.py --check    # 只检查是否过期（不写）

═══ 铁律 ═══
**刷新戳 = 声明"文档已跟上真源"**，所以刷新前必须先完成：
① `docs/CONTRACT-CHANGELOG-20261017.md` 登记 ② `scripts/broadcast_contract_change.py` 广播
③ 各契约文档的 TSS 戳同步。三步没做完就刷新 = 用机器给自己的懈怠盖章。
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUE_SOURCE = os.path.join(PROJECT, "core", "risk", "risk_rules_impl.py")
STAMP_PATH = os.path.join(PROJECT, ".agent", "true-source-stamp.json")


def sha256_of(path):
    """真源内容哈希 —— 归一化换行符后再算。

    2026-10-19 老六架构审查修复: 原实现按【原始字节】哈希, 而本机 working tree 是
    CRLF(实测 risk_rules.py 含 905 个 \\r\\n)、git 库内是 LF(.gitattributes:7
    `* text=auto eol=lf`) ⇒ 同一份内容在不同 checkout 机器上算出两个不同的戳,
    守卫变成环境相关(可假红也可假绿)。改为先 CRLF→LF 归一化, 使戳只反映内容。
    ⚠️ 本函数必须与 tests/test_doc_freshness.py::sha256_of 保持同一口径。
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        tail = b""
        for chunk in iter(lambda: fh.read(65536), b""):
            buf = tail + chunk
            # 跨 chunk 边界的 \\r\\n 不会被 replace 命中, 故留最后一个字节到下一轮
            if buf.endswith(b"\r"):
                tail, buf = buf[-1:], buf[:-1]
            else:
                tail = b""
            h.update(buf.replace(b"\r\n", b"\n"))
        if tail:
            h.update(tail)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="契约真源戳登记/刷新（H4）")
    ap.add_argument("--check", action="store_true", help="只检查是否过期，不写入")
    args = ap.parse_args()

    cur = sha256_of(TRUE_SOURCE)
    token = cur[:12]
    old = None
    if os.path.exists(STAMP_PATH):
        try:
            old = json.load(open(STAMP_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            old = None

    print("=== 契约真源戳 ===")
    print("真源文件 : %s" % os.path.relpath(TRUE_SOURCE, PROJECT))
    print("当前 SHA : %s" % cur)
    print("文档戳记 : TSS:%s" % token)
    if old:
        print("已登记   : %s (%s)" % (old.get("risk_rules_sha256", "?")[:12], old.get("stamped_at", "?")))
        if old.get("risk_rules_sha256") != cur:
            print("\n⚠️ 真源已变更但戳未刷新 —— tests/test_doc_freshness.py 会 FAIL。")
            print("   刷新前请确认已完成：① CONTRACT-CHANGELOG 登记 ② broadcast_contract_change.py 广播")
            if not args.check:
                print("   本次将继续写入新戳（= 声明文档已跟上）。")
        else:
            print("\n✅ 戳与真源一致，无需刷新。")
            if args.check:
                return 0

    if args.check:
        return 0 if old and old.get("risk_rules_sha256") == cur else 1

    os.makedirs(os.path.dirname(STAMP_PATH), exist_ok=True)
    payload = {
        "meta": {
            "name": "契约真源戳（True Source Stamp）",
            "why": "2026-10-17 W5 治理 H4：让文档可声明『我是照着这一版真源写的』，"
                   "真源变了而戳没刷新 = 文档没跟上，机器直接红",
            "refresh_before_you_stamp": [
                "① docs/CONTRACT-CHANGELOG-20261017.md 登记变更",
                "② python scripts/broadcast_contract_change.py 广播",
                "③ 同步各契约文档头部的 TSS: 戳",
            ],
        },
        "true_source": "core/risk/risk_rules_impl.py",
        "risk_rules_sha256": cur,
        "stamp_token": "TSS:%s" % token,
        "stamped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "previous": (old or {}).get("risk_rules_sha256"),
    }
    with open(STAMP_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print("\n已写入: %s" % os.path.relpath(STAMP_PATH, PROJECT))
    print("请把各契约文档头部的戳改为: TSS:%s" % token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
