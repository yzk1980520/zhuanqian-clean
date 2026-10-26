#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""carrier_check.py — 计划任务载体存在性断言 (P-B1 自愈引擎件, 只读版 2026-10-23·老四)
检查项 (read-only, 不自动修复):
  P0: Zhuanqian_* 任务 State != Ready (Disabled/缺失 = 自愈链路断供, 接 meta-watchdog)
  P1: 任务引用的 .bat 不存在 / 未 commit (git 工作区 lost-in-archive 风险, P1#5 同根因)
  P1: .bat 引用的 .py 脚本不存在 (脚本失传 = 载体空转)
  P1: 写侧新鲜度 (配置驱动): stats/log 停更超阈值 = 数据链断写 (P-B3 前置件)
输出: JSON {pass, p0, p1, tasks[]}; exit 0=pass / 1=fail。
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 写侧新鲜度配置: 任务名 -> (新鲜度文件相对路径, 允许小时数, 时间字段)
FRESHNESS_RULES = {
    "Zhuanqian_HistoryRefresh": ("scripts/refresh_extended_data_stats.json", 30, "run_at"),
    "Zhuanqian_HoldingsSync": ("data/holdings_sync.log", 30, None),  # None = mtime
}

# 产物探针 (症状层): 任务跑了但管道断裂 (RC!=0) 时写侧新鲜度抓不到, 用滚动产物 mtime 抓。
# 10/24 件: board rank 件隔 1 日根因 = daily_auto.bat %PY% 无引号展开 RC=9009, 任务 RC=0 假绿。
ARTIFACT_PROBES = {
    "Zhuanqian_DailyAuto": {
        "glob": "logs/rank_*.json",   # s3_auto_pipeline 写 logs/rank_YYYY-MM-DD.json
        "max_age_h": 50,              # 工作日: 上日 20:00 产物 >50h = 管道断 (当日 20:00 未出新件)
        "trading_days_only": True,    # 周末 (非交易日) 豁免: 周五件至周一 20:00 前不算断
    },
}

PY_REF = re.compile(r'"([^"]*\.py)"\s*([>]+)\s*"?([^"\s]+\.log)"?')


def git_tracked(rel, tracked):
    return rel.replace("\\", "/") in tracked


def freshness_ok(path: Path, rule_hours: int, ts_field):
    if not path.exists():
        return False
    if ts_field:
        try:
            txt = json.loads(path.read_text(encoding="utf-8"))
            ts = txt.get(ts_field, "")
            t = time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
        except Exception:
            return False
    else:
        t = path.stat().st_mtime
    return (time.time() - t) <= rule_hours * 3600


def query_tasks():
    """PowerShell 导出 Zhuanqian_* 任务 (UTF-8 JSON, 避免 GBK 解析问题)。"""
    ps = (
        "Get-ScheduledTask | Where-Object {$_.TaskName -like 'Zhuanqian*'} | "
        "ForEach-Object { "
        "$t = $_; "
        "$info = $t | Get-ScheduledTaskInfo; "
        "$act = @($t.Actions | Select-Object -First 1); "
        "$exv = if ($act.Count -gt 0) { $act[0].Execute } else { '' }; "
        "$av = if ($act.Count -gt 0) { $act[0].Arguments } else { '' }; "
        "[pscustomobject]@{ TaskName=$t.TaskName; State=($t.State).ToString(); "
        "LastRunTime=($info.LastRunTime).ToString(); Execute=$exv; Arguments=$av } }"
        " | ConvertTo-Json -Depth 3"
    )
    p = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if p.returncode != 0:
        return None, (p.stderr or "").strip()[:300]
    data = json.loads(p.stdout) if p.stdout.strip() else []
    return (data if isinstance(data, list) else [data]), None


REF_SCAN = re.compile(r'"([^"]+\.(?:vbs|bat|py))"')

# 根因层: bat 内 `set "VAR=<含空格路径>"` 后 %VAR% 无引号展开 → cmd 空格拆断 → RC=9009 (10/24 件)
_SET_DEF = re.compile(r'^\s*@?set\s+"([A-Z_][A-Z0-9_]*)=(.*?)"\s*$', re.M)
_EXPAND = re.compile(r'(?<!["%])(?<!\w)%([A-Z_][A-Z0-9_]*)%(?![=])')


def bat_unquoted_expand_p1s(bat_path):
    """扫描 bat: 值含空格的变量, 在命令行位置无引号展开 = 必然拆断 → P1 清单。"""
    text = Path(bat_path).read_text(encoding="utf-8", errors="replace")
    risky = {v: val for v, val in _SET_DEF.findall(text) if " " in val}
    if not risky:
        return []
    p1s = []
    for ln, line in enumerate(text.splitlines(), 1):
        head = line.strip()
        if not head or head.startswith(("@echo", "echo ", "rem ", "@rem")) or head.startswith("@"):
            # echo 行内的变量展开不拆断命令 (仅输出), 跳过; 只查命令行位置 (行首可执行段)
            continue
        for m in _EXPAND.finditer(line):
            var = m.group(1)
            if var in risky:
                p1s.append(f"L{ln} {head[:70]} (={var} 值含空格, % 展开无引号 → cmd 拆断, 需加引号 \"%{var}%\")")
    return p1s


def main():
    p0, p1, tasks = [], [], []
    tracked = set(subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
    ).stdout.splitlines())
    data, err = query_tasks()
    if err:
        print(json.dumps({"pass": False, "p0": ["P0: 任务查询失败: " + err],
                          "p1": [], "tasks": []}, ensure_ascii=False, indent=1))
        return 1
    tracked_norm = {c.replace("\\", "/") for c in tracked}
    for t in data:
        name, state = t.get("TaskName", ""), (t.get("State") or "")
        ex, args = (t.get("Execute") or ""), (t.get("Arguments") or "")
        issues = []
        if state not in ("Ready", ""):
            p0.append(f"P0: 任务 {name} State={state} (自愈链路断供, 需 /ENABLE 或重注册)")
        # action 完整性: schtasks /TR 含空格路径未加引号 → 字段被拆断 (D:\open | code\...), 任务静默失效
        if ex and "." not in os.path.basename(ex):
            p0.append(f"P0: 任务 {name} action 拆分损坏: Execute='{ex}' (含空格路径未加引号, 需 Register-ScheduledTask 重注册)")
        # 提取全部被引用的脚本载体 (.vbs 启动器 / .bat / .py): 载体失传 = 静默断链 (P1#5 同根因)
        refs = REF_SCAN.findall(ex + " " + args)
        seen = set()
        for ref in refs:
            norm = ref.replace("/", "\\").lstrip('"')
            rel = norm.replace("D:\\open code\\zhuanqian\\", "").replace("\\", "/")
            key = ref.lower()
            if key in seen or not ref or "open code\\zhuanqian" not in norm.lower():
                continue
            seen.add(key)
            if not os.path.exists(ROOT / rel):
                p1.append(f"P1: 任务 {name} 引用 {ref} 不存在 (载体空转)")
                continue
            if rel not in tracked_norm:
                p1.append(f"P1: 任务 {name} 引用未 commit: {rel} (归档轮丢失风险)")
            if ref.lower().endswith(".bat"):
                py = PY_REF.search(Path(ROOT / rel).read_text(encoding="utf-8", errors="replace"))
                if py:
                    pyref = py.group(1).replace("\\", "/")
                    pyrel = pyref.replace("D:/open code/zhuanqian/", "")
                    if not os.path.exists(ROOT / pyrel):
                        p1.append(f"P1: 任务 {name} 的 .bat 引用 .py 不存在: {pyref} (脚本失传)")
                # 根因层: bat 内无引号变量展开静态断言 (10/24 daily_auto RC=9009 同型件)
                for hit in bat_unquoted_expand_p1s(ROOT / rel):
                    p1.append(f"P1: 任务 {name} 的 .bat {rel} 无引号展开隐患: {hit}")
        rule = FRESHNESS_RULES.get(name)
        if rule:
            fpath, hours, tsf = rule
            if not freshness_ok(ROOT / fpath, hours, tsf):
                p1.append(f"P1: 任务 {name} 写侧新鲜度异常: {fpath} 停更>{hours}h (数据链断写)")
        # 产物探针 (症状层, 10/24 board rank 隔 1 日件): 任务假绿 (RC=0) 但管道断裂时抓滚动产物断更
        probe = ARTIFACT_PROBES.get(name)
        if probe:
            if probe.get("trading_days_only") and time.localtime().tm_wday in (5, 6):
                pass  # 周末豁免: 非交易日不产 rank 件
            else:
                import glob as _glob
                cands = _glob.glob(str(ROOT / probe["glob"]))
                if not cands:
                    p1.append(f"P1: 任务 {name} 产物探针: {probe['glob']} 全缺失 (管道从未产出)")
                else:
                    newest = max(os.path.getmtime(c) for c in cands)
                    age_h = (time.time() - newest) / 3600
                    if age_h > probe["max_age_h"]:
                        p1.append(f"P1: 任务 {name} 产物探针: 最新 {probe['glob']} 龄 {age_h:.1f}h "
                                  f">{probe['max_age_h']}h (选股管道断产, 任务 RC 假绿, 查 cron 日志 RC!=0)")
        tasks.append({"name": name, "state": state, "issues": issues or None})
    result = {"pass": not p0 and not p1, "p0": p0, "p1": p1, "tasks": tasks,
              "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"\n[P-B1 carriers] 任务 {len(tasks)} 个 | P0={len(p0)} P1={len(p1)}",
          file=sys.stderr)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
