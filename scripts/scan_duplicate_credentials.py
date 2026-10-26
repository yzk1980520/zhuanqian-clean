# -*- coding: utf-8 -*-
"""scan_duplicate_credentials.py — 凭证台账与去重门禁 (Hermes治理方案v1 T4, 2026-10-15 总管)

老六方案 T4:
  1. 建 config/credentials_ledger.json: 只记 app_id/profile/群/用途/轮换日期, 不记 secret
  2. 8套 app_secret 从 profiles/*/config.yaml 迁入 hermes-home/.env (T4 剩余项, 待老大 PAT 前置后做)
  3. 本脚本: 静态扫描全 profiles 的 app_id 重复(网关运行时单实例锁已有, 补静态门禁)

扫描源:
  - D:\\Hermes agent\\Hermes Agent CN Desktop\\data\\hermes-home\\profiles\\*\\config.yaml
  - 同目录 config.yaml (default)
  - 仓库 config/feishu_config.json / feishu_fallback_app.json

判级:
  - 跨 profile 重复 app_id        → REJECT (P1, 网关单实例锁根因, G1)
  - repo fallback 与 desktop default 共享 app_id → INTENTIONAL (T2 P0 绕过通道按设计用 default 应用, 记录不拒)
  - 输出台账 = 唯一真源; 09:00 监督核验"台账与配置一致"即重跑本脚本比对

退出码: 0=台账已生成(允许 intentional 共享), 2=发现 REJECT 级重复
"""
import json
import os
import re
import glob
import datetime as _dt
import sys

HERMES_HOME = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_PATH = os.path.join(REPO, "config", "credentials_ledger.json")
REPO_FEISHU_JSONS = [
    (os.path.join(REPO, "config", "feishu_config.json"), "repo custom-bot webhook (health_monitor 兜底, 19007 已死待老大重建)"),
    (os.path.join(REPO, "config", "feishu_fallback_app.json"), "repo default-app bot API (T2 P0 绕过队列直发通道, 与 desktop default 共享 app_id 属设计内)"),
]


def extract_app_ids(path):
    """正则提取 cli_* app_id(不读 secret)。返回 [(context, app_id)]。"""
    txt = open(path, encoding="utf-8", errors="replace").read()
    ids = []
    lines = txt.splitlines()
    ctx = "?"
    for i, line in enumerate(lines):
        m2 = re.match(r"^(\s*)([A-Za-z0-9_]+)\s*:\s*$", line)
        m1 = re.match(r"^\s*app_id\s*:\s*(cli_[0-9a-f]+)", line)
        if m1:
            indent = len(line) - len(line.lstrip())
            ctx = "root" if indent <= 2 else "section"
            ids.append((ctx, m1.group(1)))
    return ids


def main():
    sources = []
    for p in sorted(set(glob.glob(os.path.join(HERMES_HOME, "profiles", "*", "config.yaml")))):
        sources.append((p, "profile:" + os.path.basename(os.path.dirname(p))))
    sources.append((os.path.join(HERMES_HOME, "config.yaml"), "default(hermes-home)"))
    for p, purpose in REPO_FEISHU_JSONS:
        if os.path.exists(p):
            sources.append((p, "repo"))

    entries = []
    for path, profile in sources:
        if not os.path.exists(path):
            continue
        if path.endswith(".json"):
            obj = json.load(open(path, encoding="utf-8"))
            if isinstance(obj, dict) and obj.get("app_id"):
                entries.append({
                    "app_id": obj.get("app_id"),
                    "profile": profile,
                    "config_file": path,
                    "context": "json",
                    "secret_stored_in_file": bool(obj.get("app_secret")),
                    "purpose": profile,
                    "group": "待对账(T5)",
                    "rotation_date": "未知(P0凭据泄露 10-09 裁定待轮换)",
                })
            continue
        txt = open(path, encoding="utf-8", errors="replace").read()
        has_secret = ("app_secret" in txt) or ("appSecret" in txt)
        for ctx, aid in extract_app_ids(path):
            entries.append({
                "app_id": aid,
                "profile": profile,
                "config_file": path,
                "context": ctx,
                "secret_stored_in_file": has_secret,
                "purpose": purpose,
                "group": "待对账(T5)",
                "rotation_date": "未知(P0凭据泄露 10-09 裁定待轮换)",
            })

    ledger = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "generator": "scripts/scan_duplicate_credentials.py (T4 2026-10-15)",
        "note": "只记 app_id 不记 secret; secret 迁移 hermes-home/.env 为 T4 剩余项",
        "entries": entries,
    }

    # 重复判定
    dup, intentional = {}, []
    by_id = {}
    for e in entries:
        by_id.setdefault(e["app_id"], []).append(e)
    for aid, lst in by_id.items():
        if len(lst) < 2:
            continue
        profiles = {x["profile"] for x in lst}
        repo_involved = any(x["profile"] == "repo" for x in lst)
        desktop_profiles = {x["profile"] for x in lst if x["profile"] != "repo"}
        if repo_involved and len(desktop_profiles) <= 1:
            intentional.append({"app_id": aid, "profiles": sorted(profiles),
                                "reason": "repo T2 P0 绕过通道与 desktop default 共享应用, 设计内, 记录不拒"})
        else:
            dup[aid] = sorted(profiles)

    ledger["duplicates_rejected"] = dup
    ledger["intentional_sharing"] = intentional

    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    print("台账已写 %s: %d 条, 跨profile重复=%d, 设计内共享=%d" % (
        LEDGER_PATH, len(entries), len(dup), len(intentional)))
    for aid, ps in dup.items():
        print("🚨 REJECT 跨profile重复: %s in %s" % (aid, ", ".join(ps)))
    for it in intentional:
        print("ℹ️ INTENTIONAL: %s in %s" % (it["app_id"], ", ".join(it["profiles"])))
    return 2 if dup else 0


if __name__ == "__main__":
    sys.exit(main())
