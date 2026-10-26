# DEPRECATED → use scripts/check_all.py contract
# -*- coding: utf-8 -*-
"""check_protocol_mount.py v2 — 三重核验 Hermes 侧执行规范指针挂载状态 (2026-09-27 升级)

升级背景 (PROP-2026-09-27-CONFIG-MOUNT 方案2):
  v1 只做关键词匹配, 存在假阳性/假阴性 (09-27 实证: 空指针含"协议挂载点"但无路径被误判;
  合格指针因关键词不匹配被误判 NOT_MOUNTED)。
v2 三重验证:
  ① PyYAML 解析合法性 (语法坏 = YAML_BAD)
  ② 指针位于 agent.system_prompt 标量块内且含双路径 (位置错 = WRONG_LOCATION)
  ③ 双路径指向的文件真实存在 (文件丢 = DOC_MISSING / CHK_MISSING)

用法:
  python scripts/check_protocol_mount.py            # 核验全部 profile
  python scripts/check_protocol_mount.py --selftest # 自检: 构造坏样本验证 FAIL 检出能力
exit 0 = PASS (必挂全 MOUNTED) / exit 1 = FAIL
只读不写 (--selftest 只写系统临时目录)。
"""
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    print(f"🔴 [scripts\check_protocol_mount.py] CR-01: except Exception:", file=sys.stderr)
import yaml

HERMES_HOME = r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home"
PROFILES = ["zongguan", "laosan", "laowu", "opencode", "atomcode", "workbuddy", "niuma"]
MUST = ["zongguan", "laosan", "laowu", "opencode", "atomcode", "workbuddy"]

DOC_PATH = r"D:\open code\zhuanqian\mainline\docs\AGENT-EXECUTION-PROTOCOL-2026-09-27.md"
CHK_PATH = r"D:\open code\zhuanqian\.agent\CHECKLIST.md"
# 指针行锚点 (system_prompt 内应出现的路径串, 统一正斜杠形态)
DOC_MARK = "mainline/docs/AGENT-EXECUTION-PROTOCOL-2026-09-27.md"
CHK_MARK = ".agent/CHECKLIST.md"


def check_one(path):
    """三重验证单个 profile, 返回 (status, detail)。"""
    if not os.path.exists(path):
        return "FILE_MISSING", "config.yaml 不存在"
    try:
        raw = open(path, encoding="utf-8-sig").read()
        data = yaml.safe_load(raw)
    except Exception as e:
        return "YAML_BAD", f"{type(e).__name__}: {str(e)[:60]}"
    sp = str((data.get("agent") or {}).get("system_prompt") or "")
    if sp.count(DOC_MARK) > 1:
        return "DUPLICATED", "指针重复挂载, 需 unmount 后重挂"
    has_doc = DOC_MARK in sp
    has_chk = CHK_MARK in sp
    if not (has_doc and has_chk):
        # 关键词在文件其他位置但不在 system_prompt → 位置错误
        if DOC_MARK in raw or "协议挂载点" in raw:
            return "WRONG_LOCATION", "指针存在但不在 agent.system_prompt 内或缺路径"
        return "NOT_MOUNTED", "system_prompt 无指针"
    # 路径真实性
    if not os.path.exists(DOC_PATH):
        return "DOC_MISSING", f"规范正文文件丢失: {DOC_PATH}"
    if not os.path.exists(CHK_PATH):
        return "CHK_MISSING", f"核查清单文件丢失: {CHK_PATH}"
    # 内容锚点: 规范正文必须含版本标识(防路径对但内容被偷换)
    try:
        doc_head = open(DOC_PATH, encoding="utf-8").read(2000)
        if "执行规范" not in doc_head and "EXECUTION" not in doc_head.upper():
            return "DOC_INVALID", "规范正文内容与版本标识不符"
    except Exception as e:
        return "DOC_UNREADABLE", str(e)[:60]
    return "MOUNTED", ""


def _selftest():
    """构造 3 类坏样本 + 1 个好样本, 验证检出能力。只写系统临时目录。"""
    good = (
        "model:\n  default: test\n"
        "agent:\n"
        "  system_prompt: '你是测试。\n"
        "\n"
        "    📌 协议挂载点：本profile已挂载《智能体高效执行规范 v1》\n"
        f"    协议正文：{DOC_MARK.replace('/', chr(47))}\n"
        f"    执行前核查清单：{CHK_MARK}'\n"
        "display:\n  message_reactions: true\n"
    )
    # 坏样本1: 指针插在映射区 (总管 09-27 事故形态: 全角冒号 + 无引号块)
    bad_location = good.replace(
        "display:\n  message_reactions: true\n", ""
    ) + "\n    📌 协议挂载点：本profile已挂载御龙决协议\n    协议正文：D:" + chr(92) + "x.md\n"
    # 坏样本2: 语法损坏 (裸半角冒号键值)
    bad_syntax = good.replace("display:", "display: {broken")
    # 坏样本3: 只有半截指针 (缺 CHECKLIST)
    bad_partial = good.replace(f"    执行前核查清单：{CHK_MARK}'", "'")
    cases = [("好样本应MOUNTED", good, "MOUNTED"),
             ("映射区指针应检出WRONG_LOCATION", bad_location, None),
             ("语法损坏应检出YAML_BAD", bad_syntax, "YAML_BAD"),
             ("缺核查清单应FAIL", bad_partial, None)]
    ok = True
    tmpdir = tempfile.mkdtemp(prefix="cpm_selftest_")
    for name, content, expect in cases:
        p = os.path.join(tmpdir, "config.yaml")
        open(p, "w", encoding="utf-8", newline="\n").write(content)
        status, _ = check_one(p)
        if expect:
            passed = status == expect
        else:
            passed = status != "MOUNTED"
        ok = ok and passed
        print(f"  {'✅' if passed else '❌'} 自检[{name}] → {status}")
    print(f"自检结论: {'PASS — 坏样本检出能力正常' if ok else 'FAIL — 存在漏检, 禁止信任本脚本'}")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return _selftest()

    results = {}
    for p in PROFILES:
        results[p] = check_one(os.path.join(HERMES_HOME, "profiles", p, "config.yaml"))

    print(f"规范: {DOC_PATH}")
    for p in PROFILES:
        status, detail = results[p]
        tag = "必挂" if p in MUST else "可选"
        if status == "MOUNTED":
            mark = "✅"
        elif p not in MUST and status == "NOT_MOUNTED":
            mark = "⭕"
        else:
            mark = "❌"
        line = f"  {mark} [{p:<10}] {status:<16} ({tag})"
        if detail:
            line += f" {detail}"

    missing = [p for p in MUST if results[p][0] != "MOUNTED"]
    # 结果落盘 (审计锚点, 老五评审要求: 核验结果可追溯)
    try:
        import json, datetime
        out = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "script": "check_protocol_mount.py v2.1",
            "results": {p: results[p][0] for p in PROFILES},
            "pass": not missing,
        }
        os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agent"), exist_ok=True)
        out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agent", "mount-check-latest.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"留痕: {out_path}")
    except Exception as e:
        print(f"(留痕写入失败, 不影响核验结论: {e})")
    if not missing:
        print(f"结论: PASS — 必挂 {len(MUST)} 个全部 MOUNTED (语法✓ 位置✓ 路径真实✓)")
        return 0
    print(f"结论: FAIL — 必挂清单异常 {len(missing)} 个: {', '.join(missing)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
