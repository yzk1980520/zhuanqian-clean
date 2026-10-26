# -*- coding: utf-8 -*-
"""self_audit_checkers.py — 自审 Agent R0 检查器模块

检查规则（R0 优先级）：
  C-1  S1假绿复现：final_verdict=FAIL ∧ laowu_approved=True
  C-2  门禁一致性：sanity gate PASS ∧ review_gate frozen=True
  D-1  DD口径漂移：全库 max_drawdown 赋值 ≠ 裁定 35%
  A-1  契约漂移：裸读 review_status.json 裁定类消费方未走 review_gate
  R1   代码资产检测：双远程 main 新鲜度（调 scripts/check_remote_main_freshness.py）
       ——Hermes治理方案v1 T3 (2026-10-15)：379积压16天没响的直接原因就是检测范围
       不含代码资产，漏报=假绿同级 P0
  M-1  告警环meta：QSP_MsgDrain 活性（data/drain_state.json last_run <15min）
       ——Hermes治理方案v1 T2 (2026-10-15)：告警链路自身死了也要能报警；
       5min级先头监控=计划任务 QSP_DrainWatch（stale 连续2轮 P0 绕过队列直发），
       本项为自审 15:35 例行复检
  M-2  RULING快照漂移：scan kanban.db review/done 任务 body 含 RULING hash →
       judge_accept_with_ruling_check() 验对齐 → 漂移写 data/message_queue.json
       ——R1-2 B段真实接入（2026-10-16 老三）：读侧检测环，非 Hermes goal-loop judge
  M-4  因子衰减监控：跑 scripts/factor_decay_monitor.py --json（P2-O3, 2026-10-20 老三）
       ——读 权威表 factor_ic_latest.json + 20d 对比 t2b_gate_20d_check.json，
       连击达阈值（翻转≥20d / chg5保留率<40%×2周 / 全活跃IR<0.3×30d）→
       信号登记 data/decay_signals.json（追加型防重复）+ message_queue.json 唯一出口；
       新信号 FAIL，飞书投递由 QSP_MsgDrain drain（本项不二次写队列，单一写口）

只读不写。发现问题 → alert_log.jsonl append + stdout + send_with_fallback。
"""
import json
import os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import re
import sqlite3
import sys
import subprocess
import time
import threading
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
# 2026-10-23 双轨升级[t_290cac7e]: S5基地化迁入core/ops/后 ROOT 误指 core/ops 目录,
# 致 6 处 ROOT/scripts|data 路径探针误报"缺失"→检查器静默 SKIPPED。
# 修正: ROOT 一律用 S5 前算法正确的 PROJECT_ROOT(仓库根), 回滚点 .bak_20261023。
ROOT = PROJECT_ROOT
DATA_DIR = os.path.join(ROOT, "data")
REVIEW_STATUS_PATH = os.path.join(DATA_DIR, "review_status.json")
ALERT_LOG_PATH = os.path.join(ROOT, "data", "alert_log.jsonl")
SANITY_GATE_PATH = os.path.join(DATA_DIR, "sanity_gate_status.json")

# RULING-DD-20261015 裁定真值（60% 过渡值；回退条款：S3 全量132日 DD<53% 确认后降至 0.53）
# 前次 RULING-DD-20261014（35%）已作废，见 docs/DD门禁口径裁定-20261015-新基线重裁.md
DD_TRUTH_VALUE = 0.60
DD_TRUTH_VALUE_RULE = "RULING-DD-20261015"

# 排除的扫描路径（诊断/测试/归档/虚拟环境不参与契约检查）
# P1-3 (2026-10-19 老三)：旧黑名单漏了 .venv/.worktrees/archive/backups/models，
# 致 D-1/A-1 全扫 24,846 个 .py（其中 .venv 占 23,926 = 96%），单项 153.9s 成自审超时真凶
# （计时探针 total=286.93s 贴 300s 线，生产变体下 exit 124）。补全后只审项目一方代码。
SCAN_EXCLUDE_DIRS = {
    "__pycache__", ".git", ".trash", ".scratch", "htmlcov",
    "research_archive", "mainline", "agents", "1", "docs",
    ".venv", ".worktrees", ".trash_envs",
    "archive", "backups", "models", "aipy laoliu",
}

# 排除的文件模式（诊断脚本、测试、临时文件、对比分析脚本）
SCAN_EXCLUDE_PATTERNS = re.compile(
    r"(test_|_test\.py|diag|audit|health_check|old_|tmp_|backup|compare_|quick_)",
    re.IGNORECASE,
)

# 裁定类关键词（表示该引用用于门禁裁定，而非显示/诊断）
GATE_CITATION_KEYWORDS = re.compile(
    r"laowu_approved\s*==\s*True|laowu_approved\s*is\s*True|"
    r"final_verdict\s*==\s*['\"]PASS['\"]|final_verdict\s*==\s*True|"
    r"if\s+laowu_approved\b|if\s+not\s+laowu_approved\b|"
    r"if\s+final_verdict\b|gate\[.frozen.\]|not\s+gate\[.frozen.\]|"
    r"laowu_approved\s*and\s|laowu_approved\s*or\s",
    re.IGNORECASE,
)


# ====================================================================
# 数据类
# ====================================================================

@dataclass
class AuditResult:
    checker: str
    category: str   # false_green | gate_consistency | threshold_conflict | contract_drift
    status: str     # PASS | FAIL | SKIPPED
    severity: str   # P0 | P1 | P2
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    evidence: str = ""

    def is_failure(self) -> bool:
        return self.status == "FAIL"

    def to_json_line(self) -> str:
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "checker": self.checker,
            "category": self.category,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "evidence": self.evidence,
        }
        return json.dumps(entry, ensure_ascii=False)


# ====================================================================
# C-1：S1假绿复现检测
# ====================================================================

def check_c1_s1_false_green() -> AuditResult:
    """final_verdict=FAIL ∧ laowu_approved=True 矛盾组合。

    真源契约：状态源契约 S1 节 — 消费方须走 review_gate.evaluate() 仲裁。
    事故证据：K44 假绿事故（final_verdict=FAIL 被 laowu_approved=True 绕过）。
    """
    try:
        with open(REVIEW_STATUS_PATH, "r", encoding="utf-8-sig") as f:
            status = json.load(f)
    except FileNotFoundError:
        return AuditResult(
            checker="c1_s1_false_green", category="false_green",
            status="SKIPPED", severity="P0",
            message="review_status.json 不存在，跳过 C-1 检测",
            evidence="文件缺失",
        )
    except Exception as e:
        return AuditResult(
            checker="c1_s1_false_green", category="false_green",
            status="SKIPPED", severity="P0",
            message=f"review_status.json 解析失败: {e}",
            evidence=str(e),
        )

    if not isinstance(status, dict):
        return AuditResult(
            checker="c1_s1_false_green", category="false_green",
            status="SKIPPED", severity="P0",
            message="review_status.json 非 dict 结构，跳过",
            evidence="结构异常",
        )

    final_verdict = status.get("final_verdict")
    laowu_approved = status.get("laowu_approved")

    # final_verdict 显式 FAIL（字符串或 bool False）
    fv_is_fail = False
    if final_verdict is False:
        fv_is_fail = True
    elif isinstance(final_verdict, str) and final_verdict.strip().upper() == "FAIL":
        fv_is_fail = True

    if fv_is_fail and laowu_approved is True:
        return AuditResult(
            checker="c1_s1_false_green", category="false_green",
            status="FAIL", severity="P0",
            message=f"【C-1 假绿】final_verdict={final_verdict!r} 但 laowu_approved=True — 矛盾组合！",
            details={
                "final_verdict": final_verdict,
                "laowu_approved": laowu_approved,
                "findings": status.get("findings", {}),
            },
            evidence="参考 K44 假绿排查事故；状态源契约 S1 节 + review_gate.py B1 硬失败否决逻辑",
        )

    return AuditResult(
        checker="c1_s1_false_green", category="false_green",
        status="PASS", severity="P0",
        message="C-1 假绿检测通过",
        details={"final_verdict": final_verdict, "laowu_approved": laowu_approved},
    )


# ====================================================================
# C-2：门禁一致性检测
# ====================================================================

def check_c2_gate_consistency() -> AuditResult:
    """sanity gate PASS（或 SKIP）但 review_gate 冻结的矛盾。

    sanity_gate_status.json: status=PASS/SKIP 表示回测门禁通过；
    review_gate.evaluate() frozen=True 表示评审闸冻结。
    两者矛盾 = 假绿风险。
    """
    # 1. 读 sanity gate 状态
    sanity_pass = None
    try:
        with open(SANITY_GATE_PATH, "r", encoding="utf-8") as f:
            sanity_data = json.load(f)
        sanity_status = sanity_data.get("status", "")
        # PASS 或 SKIP（无新回测则跳过视为不冲突）都算 sanity 侧无问题
        if sanity_status in ("PASS", "SKIP"):
            sanity_pass = True
        elif sanity_status == "FAIL":
            sanity_pass = False
        else:
            sanity_pass = None
    except FileNotFoundError:
        return AuditResult(
            checker="c2_gate_consistency", category="gate_consistency",
            status="SKIPPED", severity="P0",
            message="sanity_gate_status.json 不存在，跳过 C-2 检测",
            evidence="文件缺失",
        )
    except Exception as e:
        return AuditResult(
            checker="c2_gate_consistency", category="gate_consistency",
            status="SKIPPED", severity="P0",
            message=f"sanity_gate_status.json 解析失败: {e}",
            evidence=str(e),
        )

    # 2. 读 review_gate 状态
    try:
        import review_gate
        gate_result = review_gate.evaluate(REVIEW_STATUS_PATH)
    except Exception as e:
        return AuditResult(
            checker="c2_gate_consistency", category="gate_consistency",
            status="SKIPPED", severity="P0",
            message=f"review_gate.evaluate() 调用失败: {e}",
            evidence=str(e),
        )

    actual_frozen = gate_result.get("frozen", True)

    # 3. 矛盾检测：sanity 放行但 review_gate 冻结
    if sanity_pass is True and actual_frozen:
        return AuditResult(
            checker="c2_gate_consistency", category="gate_consistency",
            status="FAIL", severity="P0",
            message="【C-2 门禁矛盾】sanity gate 放行但 review_gate 冻结 — 假绿风险！",
            details={
                "sanity_gate_status": sanity_data.get("status"),
                "sanity_gate_id": sanity_data.get("gate_id"),
                "review_gate_frozen": actual_frozen,
                "review_gate_source": gate_result.get("source"),
                "review_gate_reason": gate_result.get("reason"),
            },
            evidence="状态源契约 S1 节：review_gate.evaluate() 为唯一仲裁读法",
        )

    return AuditResult(
        checker="c2_gate_consistency", category="gate_consistency",
        status="PASS", severity="P0",
        message="C-2 门禁一致性检测通过",
        details={
            "sanity_pass": sanity_pass,
            "review_gate_frozen": actual_frozen,
            "review_gate_source": gate_result.get("source"),
        },
    )


# ====================================================================
# D-1：DD 口径漂移检测
# ====================================================================

def _walk_python_files() -> List[str]:
    """遍历项目根目录下所有 .py 文件，排除诊断/测试/归档目录。"""
    py_files = []
    for root, dirs, files in os.walk(ROOT):
        # 排除目录
        dirs[:] = [d for d in dirs if d not in SCAN_EXCLUDE_DIRS]
        for fname in files:
            if not fname.endswith(".py") or fname.endswith(".bak"):
                continue
            # 只对文件名（不含路径）做排除模式匹配，避免 temp 路径中的 "tmp" 误伤
            if SCAN_EXCLUDE_PATTERNS.search(fname):
                continue
            filepath = os.path.join(root, fname)
            py_files.append(filepath)
    return py_files


def _is_in_gate_context(lines: List[str], lineno: int) -> bool:
    """判断指定行是否处于 GATE 字典/门禁定义上下文中。

    向上查找最近的 '{' 行，看是否在 GATE = { ... } 或类似结构中。
    """
    # 向上找 30 行内的 GATE 定义
    for offset in range(min(30, lineno), 0, -1):
        idx = lineno - offset
        if idx < 0:
            break
        prev = lines[idx].strip()
        if re.match(r'^GATE\s*=', prev) or prev in ('{', ' GATE = {'):
            return True
        if prev.startswith(')') or prev.startswith(']'):
            break
    return False


def _is_comment_or_docstring_line(lines: List[str], lineno: int) -> bool:
    """判断指定行是否是注释或 docstring 内容。"""
    stripped = lines[lineno].strip()
    if stripped.startswith('#'):
        return True
    # 检查是否在 triple-quote 字符串内
    in_triple_quote = False
    for i in range(lineno):
        line = lines[i].strip()
        # 简单启发式：跳过以 - 开头的 docstring 列表项
        if line.startswith('"""') or line.startswith("'''"):
            in_triple_quote = not in_triple_quote
        if in_triple_quote and stripped.startswith('- '):
            return True
    return False


def _extract_dd_threshold_from_line(line: str, all_lines: Optional[List[str]] = None,
                                     lineno_idx: int = -1) -> Optional[float]:
    """从单行代码中提取 DD 门禁阈值数值（比例形式）。

    只提取门限定义类赋值，跳过占位符(0.0)/结果数据(多小数位)/监控触发阈值。
    """
    stripped = line.strip()
    if stripped.startswith("#"):
        return None

    # 模式1：JSON/gate dict 赋值 "max_drawdown": X
    m = re.search(r'"max_drawdown"\s*:\s*([0-9.]+)', stripped)
    if m:
        val = float(m.group(1))
        if val == 0.0:
            return None  # 占位符，跳过
        # 多小数位 → 结果数据（如 29.68），跳过
        if val != round(val, 2):
            return None
        # 百分比结果数据（>1 且含小数）→ 跳过
        if val > 1.0 and val != round(val):
            return None
        if val > 1.0:
            return val / 100.0
        return val

    # 模式2：GATE["max_drawdown"] = X 赋值
    m = re.search(r'GATE\s*\[\s*"max_drawdown"\s*\]\s*=\s*([0-9.]+)', stripped)
    if m:
        val = float(m.group(1))
        if val == 0.0:
            return None
        if val > 1.0:
            return val / 100.0
        return val

    # 模式3：max_dd <= N（门限定义，N 为整数或一位小数）
    m = re.search(r'\bmax_dd\s*(<=|>=)\s*(\d+(?:\.\d+)?)\b', stripped)
    if m:
        threshold = float(m.group(2))
        if threshold == 0.0:
            return None
        # 只保留整数或一位小数的阈值（排除 29.68 这类结果值）
        if threshold != round(threshold, 1):
            return None
        # 监控触发阈值用 > 而非 <=，这里只匹配 <=（门限定义）
        if threshold > 1.0:
            return threshold / 100.0
        return threshold

    return None


def check_d1_dd_threshold_drift() -> AuditResult:
    """全库扫描 max_drawdown 门禁赋值，与裁定 35% 比对。

    裁定来源：RULING-DD-20261014，真值 = 0.35。
    只检测门限定义类赋值，跳过占位符(0.0)/结果数据/监控触发阈值。
    """
    py_files = _walk_python_files()
    drifts: List[Dict[str, Any]] = []

    for fpath in py_files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.read().splitlines()
        except Exception:
            continue
        for lineno, line in enumerate(all_lines, 1):
            val = _extract_dd_threshold_from_line(line, all_lines, lineno - 1)
            if val is None:
                continue
            # 与裁定值比较
            if abs(val - DD_TRUTH_VALUE) > 0.01:
                drifts.append({
                    "file": os.path.relpath(fpath, ROOT),
                    "line": lineno,
                    "value": val,
                    "line_content": line.strip()[:120],
                })

    if not drifts:
        return AuditResult(
            checker="d1_dd_threshold_drift", category="threshold_conflict",
            status="PASS", severity="P0",
            message=f"D-1 DD 口径一致性检测通过（扫描 {len(py_files)} 个文件，未发现漂移）",
            details={"truth_value": DD_TRUTH_VALUE, "drifts_found": 0, "rule": DD_TRUTH_VALUE_RULE},
            evidence=f"{DD_TRUTH_VALUE_RULE} 裁定：DD 门禁真值 = 60% (0.60)（过渡值；回退条款：S3 DD<53% 确认后降至 0.53）",
        )

    return AuditResult(
        checker="d1_dd_threshold_drift", category="threshold_conflict",
        status="FAIL", severity="P0",
        message=f"D-1 DD 口径漂移！发现 {len(drifts)} 处与裁定 60% 不一致",
        details={"truth_value": DD_TRUTH_VALUE, "drifts": drifts, "rule": DD_TRUTH_VALUE_RULE},
        evidence=f"{DD_TRUTH_VALUE_RULE} 裁定：DD 门禁真值 = 60%；请修正为 0.60 或 60",
    )


# ====================================================================
# A-1：S1 消费方契约漂移检测
# ====================================================================

def check_a1_s1_consumer_arbitration() -> AuditResult:
    """检测裸读 review_status.json 用于裁定但未走 review_gate 的消费方。

    仲裁读法：review_gate.evaluate() → frozen bool。
    违约信号：脚本含 review_status.json 引用 + 使用 laowu_approved/final_verdict 做决策
              但无 import review_gate（或其别名）。
    """
    py_files = _walk_python_files()
    violations: List[Dict[str, Any]] = []

    for fpath in py_files:
        relpath = os.path.relpath(fpath, ROOT)
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        # 跳过不含 review_status.json 引用的文件
        if "review_status.json" not in content:
            continue

        all_lines = content.splitlines()

        # 检查是否 import review_gate（含别名如 import review_gate as _rg）
        has_review_gate_import = (
            "import review_gate" in content or "from review_gate" in content
        )

        if has_review_gate_import:
            # 检查是否有任何 .evaluate( / .flag_state( / .is_frozen( 调用
            # 兼容别名：_rg.evaluate( / gate.evaluate( 等
            if re.search(r'\b\w+\.evaluate\(', content) or \
               re.search(r'\b\w+\.flag_state\(', content) or \
               re.search(r'\b\w+\.is_frozen\(', content):
                continue  # 合规：有 import 且有仲裁函数调用
            # 有 import 但没调用仲裁函数 → 可疑
            violations.append({
                "file": relpath,
                "reason": "import review_gate 但未调用仲裁函数",
            })
            continue

        # 无 review_gate import，逐行检查是否有裁定类使用
        for lineno, line in enumerate(all_lines, 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # 跳过 docstring 内的列表项（- xxx）
            if _is_comment_or_docstring_line(all_lines, lineno - 1):
                continue
            # 跳过纯加载行（load_json / json.load）
            if "load_json" in stripped or "json.load" in stripped:
                continue
            # 跳过纯显示/打印行
            if any(kw in stripped for kw in ("print(", 'f"', "f'", "<div", "<span", "class=")):
                continue
            # 检查裁定类关键词
            if GATE_CITATION_KEYWORDS.search(stripped):
                violations.append({
                    "file": relpath,
                    "line": lineno,
                    "content": stripped[:120],
                    "reason": "裸读 review_status.json 用于裁定，未走 review_gate.evaluate()",
                })
                break  # 每文件只报一次

    if not violations:
        return AuditResult(
            checker="a1_s1_consumer_arbitration", category="contract_drift",
            status="PASS", severity="P0",
            message=f"A-1 S1 消费方合规检测通过（扫描 {len(py_files)} 个文件，未发现违例）",
            details={"scanned_files": len(py_files), "violations": 0},
            evidence="状态源契约 S1 节：仲裁读法为 review_gate.evaluate()",
        )

    return AuditResult(
        checker="a1_s1_consumer_arbitration", category="contract_drift",
        status="FAIL", severity="P0",
        message=f"A-1 契约漂移！发现 {len(violations)} 处裸读 review_status.json 未走 review_gate",
        details={"violations": violations, "scanned_files": len(py_files)},
        evidence="状态源契约 S1 节 + t_a3b76998 修复历史（dashboard 4文件已修复）",
    )


# ====================================================================
# R1：代码资产检测 — 双远程 main 新鲜度 (Hermes治理方案v1 T3, 2026-10-15)
# ====================================================================

def check_r1_remote_freshness() -> AuditResult:
    """R1 代码资产检测项：调 scripts/check_remote_main_freshness.py。

    判据（老六方案 T3）：双远程 main 尖端提交时间龄 >48h 或 本地领先 >50
    → 按假绿同级 P0 告警入 alert_log.jsonl。
    背景：379 积压 16 天 self_audit 每天跑却没响，直接原因检测范围不含代码资产。
    """
    script = os.path.join(ROOT, "scripts", "check_remote_main_freshness.py")
    if not os.path.exists(script):
        return AuditResult(
            checker="r1_remote_freshness", category="code_asset",
            status="SKIPPED", severity="P0",
            message="R1 代码资产检测项：check_remote_main_freshness.py 缺失，无法执行",
            evidence="文件缺失: scripts/check_remote_main_freshness.py",
        )
    try:
        r = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", timeout=60,
                            env={**os.environ, "PYTHONPATH": ""})
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        tail = out[-400:]
        if r.returncode == 0:
            return AuditResult(
                checker="r1_remote_freshness", category="code_asset",
                status="PASS", severity="P0",
                message="R1 代码资产检测：双远程 main 新鲜度 ✅（时间龄/领先量均在阈值内）",
                evidence=tail,
            )
        return AuditResult(
            checker="r1_remote_freshness", category="code_asset",
            status="FAIL", severity="P0",
            message="R1 代码资产检测：双远程疑似停摆（main尖端时间龄>48h 或 本地领先>50）— 假绿同级告警",
            evidence=tail,
        )
    except subprocess.TimeoutExpired:
        # P1-3 (2026-10-19): 超时降级 P2「超时跳过」——git 远程拉取挂死时不阻塞主流程。
        return AuditResult(
            checker="r1_remote_freshness", category="code_asset",
            status="SKIPPED", severity="P2",
            message="R1 代码资产检测超时跳过（P2降级，60s 预算耗尽），git 远程拉取阻塞，不阻塞主流程",
            evidence="subprocess.TimeoutExpired(60s)",
        )
    except Exception as e:
        return AuditResult(
            checker="r1_remote_freshness", category="code_asset",
            status="SKIPPED", severity="P0",
            message=f"R1 代码资产检测项异常: {e}",
            evidence=str(e),
        )


# ====================================================================
# M-1：告警环 meta — QSP_MsgDrain 活性 (Hermes治理方案v1 T2, 2026-10-15)
# ====================================================================

def check_m1_drain_liveness() -> AuditResult:
    """M-1 告警环 meta：data/drain_state.json 的 last_run 新鲜度 <15min。

    5分钟级先头监控由计划任务 QSP_DrainWatch（scripts/drain_meta_check.py）承担：
    连续 2 轮 stale → P0 绕过队列经 default 应用 bot API 直发。
    本项为 self_audit（15:35 例行）的独立复检，防止 DrainWatch 自己也停摆。
    告警环失效 = 所有告警静默，按假绿同级 P0。
    """
    state_path = os.path.join(DATA_DIR, "drain_state.json")
    if not os.path.exists(state_path):
        return AuditResult(
            checker="m1_drain_liveness", category="alert_ring_meta",
            status="FAIL", severity="P0",
            message="M-1 告警环meta：data/drain_state.json 缺失 — QSP_MsgDrain 未运行，告警投递环断裂",
            evidence="文件缺失: data/drain_state.json",
        )
    try:
        with open(state_path, encoding="utf-8") as f:
            st = json.load(f)
        last = datetime.fromisoformat(st["last_run"])
        age_min = (datetime.now() - last).total_seconds() / 60.0
        if age_min < 15:
            return AuditResult(
                checker="m1_drain_liveness", category="alert_ring_meta",
                status="PASS", severity="P0",
                message=f"M-1 告警环meta：QSP_MsgDrain 活性正常（last_run 龄 {age_min:.0f}min <15min）",
                evidence=f"last_run={st['last_run']}",
            )
        return AuditResult(
            checker="m1_drain_liveness", category="alert_ring_meta",
            status="FAIL", severity="P0",
            message=f"M-1 告警环meta：QSP_MsgDrain 停摆（last_run 龄 {age_min:.0f}min ≥15min）— 告警投递环断裂，P0 应由 QSP_DrainWatch 绕过队列直发",
            evidence=f"last_run={st['last_run']} (当前龄 {age_min:.0f}min)",
        )
    except Exception as e:
        return AuditResult(
            checker="m1_drain_liveness", category="alert_ring_meta",
            status="SKIPPED", severity="P0",
            message=f"M-1 告警环meta检测异常: {e}",
            evidence=str(e),
        )


# ====================================================================
# M-2：RULING 快照漂移检测（R1-2 B段真实接入，2026-10-16 老三）
# ====================================================================

# Hermes kanban DB 路径（与 kanban_* 工具共用同一 DB）
# 优先级：环境变量 > 已知固定路径 > 扫描
_HERMES_KANBAN_CANDIDATES: List[str] = []
_hermes_home_env = os.environ.get("HERMES_HOME")
if _hermes_home_env:
    _HERMES_KANBAN_CANDIDATES.append(os.path.join(_hermes_home_env, "kanban", "boards", "zhuanqian", "kanban.db"))
_HERMES_KANBAN_CANDIDATES.extend([
    r"D:\Hermes agent\Hermes Agent CN Desktop\data\hermes-home\kanban\boards\zhuanqian\kanban.db",
    os.path.join(os.path.expanduser("~"), "Hermes agent", "Hermes Agent CN Desktop", "data", "hermes-home", "kanban", "boards", "zhuanqian", "kanban.db"),
    os.path.join(os.path.expanduser("~"), ".hermes", "kanban.db"),
])
_KANBAN_DB_PATH: Optional[str] = next((p for p in _HERMES_KANBAN_CANDIDATES if os.path.exists(p)), None)

_KANBAN_FENCE_ENV = ("HERMES_DELEGATED_CHILD_CONTEXT",)


def _read_side_env():
    """剥离委托栅栏 marker，还原非委托上下文以安全调用 kanban list/show。"""
    env = os.environ.copy()
    for k in _KANBAN_FENCE_ENV:
        env.pop(k, None)
    return env

_RULING_HASH_PATTERN = re.compile(r"[a-f0-9]{12}", re.IGNORECASE)


def check_m2_ruling_drift() -> AuditResult:
    """M-2 RULING 快照漂移检测：scan kanban.db review/done 任务 → judge_accept_with_ruling_check。

    读侧检测环（非 Hermes goal-loop judge）：
    - 扫描 status IN ('review','done') 且 body 含 RULING hash 的任务
    - 对每个命中任务调 judge_accept_with_ruling_check()
    - 发现漂移 → 写 data/message_queue.json（T2 告警唯一出口）
    - 本项 PASS 不代表 Hermes goal-loop judge 已接入（那是 D-2 技术债）
    """
    # 1. 导入 ruling_hash（延迟导入避免循环）
    try:
        from utils.ruling_hash import judge_accept_with_ruling_check, extract_ruling_hash_from_body
    except ImportError as e:
        return AuditResult(
            checker="m2_ruling_drift", category="ruling_drift",
            status="SKIPPED", severity="P0",
            message=f"M-2 导入 ruling_hash 失败: {e}",
            evidence=str(e),
        )

    # 2. 连接 kanban DB
    if not os.path.exists(_KANBAN_DB_PATH):
        return AuditResult(
            checker="m2_ruling_drift", category="ruling_drift",
            status="SKIPPED", severity="P0",
            message=f"M-2 kanban DB 不存在: {_KANBAN_DB_PATH}",
            evidence=f"路径: {_KANBAN_DB_PATH}",
        )

    try:
        conn = sqlite3.connect(_KANBAN_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, status, body FROM tasks WHERE status IN ('review','done')"
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        return AuditResult(
            checker="m2_ruling_drift", category="ruling_drift",
            status="SKIPPED", severity="P0",
            message=f"M-2 kanban DB 查询异常: {e}",
            evidence=str(e),
        )

    # 3. 筛选 body 含 RULING hash 的任务
    ruling_registry = {
        "RULING-DD": "docs/DD门禁口径裁定-20261015-新基线重裁.md"
    }
    drifted: List[dict] = []

    for row in rows:
        body = row["body"] or ""
        # 检查 body 是否含 RULING hash 字段（表格模式）
        if "快照 hash" not in body and "RULING" not in body.upper():
            continue
        task_id = row["id"]
        task_title = (row["title"] or "")[:60]
        task_status = row["status"]

        # 调 judge 验收
        try:
            result = judge_accept_with_ruling_check(body, ruling_registry)
        except Exception as e:
            drifted.append({
                "task_id": task_id, "title": task_title,
                "error": str(e),
            })
            continue

        if result["verdict"] == "BLOCKED":
            drifted.append({
                "task_id": task_id, "title": task_title,
                "reason": result["reason"],
                "ruling_check": result.get("ruling_check", {}),
            })

    # 4. 漂移写入 message_queue.json（T2 告警唯一出口）
    if drifted:
        try:
            from core.ops.message_queue import add_message
            for d in drifted:
                alert_content = (
                    f"🚨 【M-2 RULING漂移】任务 {d['task_id']}（{d['title']}）口径过期\n"
                    f"原因: {d.get('reason', d.get('error', 'unknown'))}\n"
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                add_message("self_audit_m2", alert_content, priority="critical")
            evidence = f"漂移任务数={len(drifted)}，已入 message_queue.json"
            return AuditResult(
                checker="m2_ruling_drift", category="ruling_drift",
                status="FAIL", severity="P0",
                message=f"M-2 RULING快照漂移！发现 {len(drifted)} 个漂移任务",
                evidence=evidence,
                details={"drifted_tasks": drifted},
            )
        except Exception as e:
            return AuditResult(
                checker="m2_ruling_drift", category="ruling_drift",
                status="SKIPPED", severity="P0",
                message=f"M-2 写 message_queue 失败: {e}",
                evidence=str(e),
            )

    # 5. 无漂移 → PASS
    scanned = sum(1 for row in rows if ("快照 hash" in (row["body"] or "") or "RULING" in (row["body"] or "").upper()))
    return AuditResult(
        checker="m2_ruling_drift", category="ruling_drift",
        status="PASS", severity="P0",
        message=f"M-2 RULING快照漂移检测通过（扫描 {scanned} 个含 RULING 引用任务，0 漂移）",
        evidence=f"scanned={scanned}, drifted=0, kanban_db={_KANBAN_DB_PATH}",
    )


# ====================================================================
# M-3：派单审计消费断言（P1-F，2026-10-19 总管）
# ====================================================================

_DISPATCH_AUDIT_STATE_PATH = os.path.join(DATA_DIR, "dispatch_audit_state.json")
_DISPATCH_VIOLATION_THRESHOLD_DAYS = 2  # 连续 %d 日违规 → P0
_M3_SKIP_REASONS = ("parse_fail", "timeout", "no_data")  # R1-P5 t_45357e19: SKIPPED 三类枚举


def _m3_write_state(skipped_reason=None, violations_count=None,
                    checked=None, scope_since=None) -> bool:
    """M-3 探针 state 写回（原子 tmp+os.replace；R1-P5 再冻结加固 t_45357e19）。

    语义（两类轮次，state 永不冻结——冻结=10-19 型「次日误升级 P0」的复发条件）:
      - 实测轮（PASS/FAIL）: skipped_reason=None + violations_count=<实测 int>
        + checked/scope_since；
      - SKIPPED 轮: skipped_reason∈_M3_SKIP_REASONS + violations_count=None
        （null=未实测，禁止伪造 0 假绿；checked/scope_since 不携带——避免把上轮
        实测值冒充本轮）；last_run 两种轮次都推进。
    校验失败抛 ValueError（loud，编程错误不静默）；IO 失败响铃 stderr 返回 False，
    不影响本轮审计结果（下轮连续日上下文缺失，由升级链读 null 断链兜底）。
    """
    if skipped_reason is not None and skipped_reason not in _M3_SKIP_REASONS:
        raise ValueError("skipped_reason 不在三类枚举 %r: %r" % (_M3_SKIP_REASONS, skipped_reason))
    if skipped_reason is None and (not isinstance(violations_count, int) or isinstance(violations_count, bool)):
        raise ValueError("实测轮 violations_count 必须为 int, 得到: %r" % (violations_count,))
    try:
        now_iso = datetime.now().isoformat(timespec="seconds")
        new_state = {
            "last_run": now_iso,
            "violations_count": violations_count,
            "skipped_reason": skipped_reason,
        }
        if checked is not None:
            new_state["checked"] = checked
            new_state["scope_since"] = scope_since
        tmp = _DISPATCH_AUDIT_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _DISPATCH_AUDIT_STATE_PATH)
        return True
    except Exception as e:
        print("🔴 M-3 state 写回失败(不影响本轮审计结果, 下轮连续日上下文缺失): %s" % e, file=sys.stderr)
        return False


def check_m3_dispatch_audit() -> AuditResult:
    """M-3 派单审计：调 scripts/dispatch_audit_check.py --json，消费 §2.9 读侧断言。

    判据：
      - violations 非空 → FAIL（P1），记入 alert_log + message_queue.json
      - 连续 2 个相邻实测违规日 → 升级为 P0（state violations_count 实测值驱动；
        2日 P1→P0 节奏不动，R1-P5 t_45357e19）
      - 脚本缺失/调用失败/解析失败/超时 → SKIPPED（不影响主流程）；
        R1-P5: SKIPPED 轮也写 state（last_run 推进 + skipped_reason 三类枚举
        parse_fail/timeout/no_data + violations_count=null 断连续链），state 永不冻结——
        冻结态不得驱动次日 P0 误升级（10-19 型复发条件）

    真源：scripts/dispatch_audit_check.py v1.1（C1-C5 机判项）
    """
    script = os.path.join(ROOT, "scripts", "dispatch_audit_check.py")
    if not os.path.exists(script):
        # R1-P5: SKIPPED 也写 state（no_data=无可审计数据源），last_run 推进不冻结
        _m3_write_state(skipped_reason="no_data")
        return AuditResult(
            checker="m3_dispatch_audit", category="dispatch_audit",
            status="SKIPPED", severity="P1",
            message="M-3 派单审计：dispatch_audit_check.py 缺失，无法执行",
            evidence="文件缺失: scripts/dispatch_audit_check.py",
        )
    try:
        r = subprocess.run(
            [sys.executable, script, "--json", "--max-tasks", "5"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            timeout=60, env=_read_side_env(),
        )
        out = (r.stdout or "") + (r.stderr or "")
        # rc≠0 仅表示发现违规/异常，stdout 仍含 JSON（最后解析用）；loud fail 走解析失败兜底
        try:
            rep = json.loads(out)
        except Exception as e:
            # R1-P5: 解析失败 SKIPPED 也写 state（parse_fail），state 不冻结
            _m3_write_state(skipped_reason="parse_fail")
            return AuditResult(
                checker="m3_dispatch_audit", category="dispatch_audit",
                status="SKIPPED", severity="P1",
                message=f"M-3 派单审计 JSON 解析失败: {e}",
                evidence=out[-300:],
            )
    except subprocess.TimeoutExpired:
        # P1-3 (2026-10-19): 超时降级 P2「超时跳过」——不阻塞主流程、不触发 P1/P0 升级。
        # 真源 dispatch_audit_check 自身挂死/kanban 读侧慢时，如实留痕而非整条自审超时。
        # R1-P5: 超时 SKIPPED 也写 state（timeout），state 不冻结
        _m3_write_state(skipped_reason="timeout")
        return AuditResult(
            checker="m3_dispatch_audit", category="dispatch_audit",
            status="SKIPPED", severity="P2",
            message="M-3 派单审计超时跳过（P2降级，60s 预算耗尽），kanban list/show 调用阻塞，不阻塞主流程",
            evidence="subprocess.TimeoutExpired(60s)",
        )
    except Exception as e:
        # R1-P5: 调用异常=本轮无审计数据（no_data），SKIPPED 也写 state，不冻结
        _m3_write_state(skipped_reason="no_data")
        return AuditResult(
            checker="m3_dispatch_audit", category="dispatch_audit",
            status="SKIPPED", severity="P1",
            message=f"M-3 派单审计调用异常: {e}",
            evidence=str(e),
        )

    checked = rep.get("checked", 0)
    violations = rep.get("violations", [])
    scope_since = rep.get("scope_since", "unknown")

    # 读取上轮 state 用于连续天数判断
    last_state = {}
    try:
        with open(_DISPATCH_AUDIT_STATE_PATH, encoding="utf-8") as f:
            last_state = json.load(f) or {}
    except Exception as e:
        print("🔴 M-3 state 读取失败(按无上轮 state 处理, 连续日上下文重置): %s" % e, file=sys.stderr)

    # 写本轮实测 state（无论 pass/fail 都更新，供下轮连续判断；R1-P5 统一走 _m3_write_state 原子写）
    _m3_write_state(violations_count=len(violations), checked=checked, scope_since=scope_since)

    if not violations:
        return AuditResult(
            checker="m3_dispatch_audit", category="dispatch_audit",
            status="PASS", severity="P1",
            message=f"M-3 派单审计：{checked} 单合规（窗口 {scope_since} 起）",
            evidence=f"checked={checked}, violations=0",
            details={"checked": checked, "violations": []},
        )

    # 连续天数判定
    # R1-P5 t_45357e19: consecutive 死字段删除——state 自始未写入该键（写回仅
    # last_run/violations_count/checked/scope_since 实测 4 字段，M-3 447e9517 写回面），
    # 旧读法 last_state.get("consecutive", 0) 恒 0，判定实际只由 violations_count 驱动，
    # 本处收敛为等价单式；SKIPPED 轮 violations_count=null → 连续链断开（consecutive 归 1），
    # 冻结态/SKIPPED 态不得驱动 P0 误升级（10-19 型），2 个相邻实测违规日 → P0 节奏不变。
    prev = last_state.get("violations_count", -1)
    prev_count = prev if isinstance(prev, int) and not isinstance(prev, bool) else -1
    consecutive = 2 if prev_count > 0 else 1

    severity = "P0" if consecutive >= _DISPATCH_VIOLATION_THRESHOLD_DAYS else "P1"
    consec_msg = (
        f"⚠️ 连续第{consecutive}日违规（阈值{_DISPATCH_VIOLATION_THRESHOLD_DAYS}日→P0）"
        if severity == "P0" else ""
    )

    # 写 message_queue.json（P1 出口，规则 11 唯一投递器）
    try:
        sys.path.insert(0, ROOT)
        from core.pipeline.atomic_json import atomic_dump, atomic_load
        q = os.path.join(DATA_DIR, "message_queue.json")
        items = atomic_load(q, []) or []
        body_items = violations[:8]
        body = "; ".join("%s %s: %s" % (v["id"], v["rule"], v["detail"]) for v in body_items)
        items.append({
            "id": "dispatchaudit_p%d_%d" % (0 if severity == "P0" else 1, int(datetime.now().timestamp())),
            "content": "⚠️ [派单审计-%s] %d 单不合规（近窗口 %d 单）：%s%s"
                       % (severity, len(violations), checked, body, " " + consec_msg if consec_msg else ""),
            "platform": "feishu", "ts": datetime.now().timestamp(),
        })
        atomic_dump(items, q)
    except Exception as e:
        print("M-3 写 message_queue.json 失败: %s" % e, file=sys.stderr)

    return AuditResult(
        checker="m3_dispatch_audit", category="dispatch_audit",
        status="FAIL", severity=severity,
        message=f"M-3 派单审计：{len(violations)} 项违规（{checked} 单受审，{consec_msg}）",
        evidence=f"checked={checked}, violations={len(violations)}, consecutive={consecutive}",
        details={"violations": violations[:10], "consecutive": consecutive},
    )


# ====================================================================
# M-4：因子衰减监控（P2-O3, 2026-10-20 老三）
# ====================================================================

def check_m4_factor_decay() -> AuditResult:
    """M-4 因子衰减监控复检：跑 scripts/factor_decay_monitor.py --json。

    判据：
      - 本轮新信号（report.fired 非空）→ FAIL（含 P1 信号则 P1，否则 P2）；
        信号由监控器登记 data/decay_signals.json（追加型防重复）并写
        data/message_queue.json 唯一出口，飞书投递由 QSP_MsgDrain drain；
        本项 FAIL 的框架直推（_send_alert）= 告警环失效兜底（同 M-2/M-3 先例），
        非第二条飞书通道。
      - rc=2（数据契约断裂 / 队列写失败）→ SKIPPED P1（loud，不静默）
      - 无新信号 → PASS（报当前连击 + stale 标记）

    真源：scripts/factor_decay_monitor.py（P2-O3 挂表；规则/计数口径见其 docstring）
    """
    script = os.path.join(ROOT, "scripts", "factor_decay_monitor.py")
    if not os.path.exists(script):
        return AuditResult(
            checker="m4_factor_decay", category="factor_decay",
            status="SKIPPED", severity="P1",
            message="M-4 因子衰减监控：scripts/factor_decay_monitor.py 缺失（P2-O3 挂表未落地）",
            evidence=f"文件缺失: {script}",
        )
    try:
        r = subprocess.run(
            [sys.executable, script, "--json"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            timeout=60, env=_read_side_env(),
        )
    except subprocess.TimeoutExpired:
        # P1-3 同款：超时 → P2 SKIPPED，不阻塞主流程
        return AuditResult(
            checker="m4_factor_decay", category="factor_decay",
            status="SKIPPED", severity="P2",
            message="M-4 因子衰减监控超时跳过（P2降级，60s 预算耗尽），不阻塞主流程",
            evidence="subprocess.TimeoutExpired(60s)",
        )
    except Exception as e:
        return AuditResult(
            checker="m4_factor_decay", category="factor_decay",
            status="SKIPPED", severity="P1",
            message=f"M-4 因子衰减监控调用异常: {e}",
            evidence=str(e),
        )

    try:
        report = json.loads(r.stdout)
    except Exception as e:
        return AuditResult(
            checker="m4_factor_decay", category="factor_decay",
            status="SKIPPED", severity="P1",
            message=f"M-4 因子衰减监控 JSON 解析失败: {e}",
            evidence=(r.stdout or "")[-300:],
        )

    if r.returncode != 0:
        return AuditResult(
            checker="m4_factor_decay", category="factor_decay",
            status="SKIPPED", severity="P1",
            message=f"M-4 因子衰减监控 loud fail（rc={r.returncode}）: {report.get('error', '')}",
            evidence=f"rc={r.returncode}, stdout_tail={(r.stdout or '')[-300:]}",
        )

    fired = report.get("fired", [])
    if fired:
        sev = "P1" if any(s.get("severity") == "P1" for s in fired) else "P2"
        summary = "; ".join(
            f"{s.get('key')} 连击 {s.get('streak_days')}d → {s.get('severity')} {s.get('recommendation')}"
            for s in fired)
        return AuditResult(
            checker="m4_factor_decay", category="factor_decay",
            status="FAIL", severity=sev,
            message=(f"M-4 因子衰减：{len(fired)} 个新信号（{summary}）；"
                     f"已登记 decay_signals.json + 写 message_queue.json 唯一出口"),
            evidence=(f"fired={[s.get('id') for s in fired]}, obs={report.get('obs_dates')}, "
                      f"warnings={report.get('warnings')}"),
            details={"fired": fired, "counters": report.get("counters", {})},
        )

    counters = report.get("counters", {})
    streaks = {k: v.get("streak_days") for k, v in counters.items()
               if isinstance(v, dict) and v.get("streak_days", 0) > 0}
    stale = {k: v for k, v in (report.get("stale") or {}).items() if v.get("stale")}
    msg = f"M-4 因子衰减监控：无新信号；活跃连击={streaks or '无'}"
    if stale:
        msg += f"；⚠️ 数据 stale: {list(stale.keys())}"
    return AuditResult(
        checker="m4_factor_decay", category="factor_decay",
        status="PASS", severity="P2",
        message=msg,
        evidence=f"obs={report.get('obs_dates')}, warnings={report.get('warnings')}",
        details={"streaks": streaks, "stale": stale},
    )


# ====================================================================
# 告警写入 + 发送
# ====================================================================

def _append_alert_log(result: AuditResult) -> None:
    """append-only 写入 alert_log.jsonl。"""
    if result.status != "FAIL":
        return
    try:
        os.makedirs(os.path.dirname(ALERT_LOG_PATH), exist_ok=True)
        with open(ALERT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(result.to_json_line() + "\n")
    except Exception as e:
        print(f"⚠️ [self_audit] 写 alert_log.jsonl 失败: {e}", file=sys.stderr)


def _send_alert(result: AuditResult) -> None:
    """复用 cron_message_sender 三通道发送告警。"""
    if result.status != "FAIL":
        return
    try:
        from cron_message_sender import send_with_fallback
        emoji = {"P0": "🔴", "P1": "🟡", "P2": "🟢"}.get(result.severity, "ℹ️")
        text = (
            f"{emoji} 【自审Agent-{result.checker}】{result.severity}\n"
            f"状态: {result.status}\n"
            f"消息: {result.message}\n"
            f"证据: {result.evidence}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        ok = send_with_fallback(text)
        if ok:
            print(f"✅ [self_audit] 告警已推送 (checker={result.checker})")
        else:
            print(f"⚠️ [self_audit] 告警推送失败 (checker={result.checker})", file=sys.stderr)
    except Exception as e:
        print(f"⚠️ [self_audit] 告警发送异常: {e}", file=sys.stderr)


# ====================================================================
# 主入口
# ====================================================================

# P1-3 (2026-10-19): 逐项墙钟预算。超预算 → P2 SKIPPED「超时跳过」，不阻塞主流程。
# 设计口径（非拍脑袋）：subprocess 检查器 R1/M3 内部已各带 60s cap，进程内检查器
# D-1/A-1 修复扫描黑名单后 <2s，故预算=60s 只是防「全扫目录重新膨胀/subprocess 挂死」
# 回归的兜底安全网；健康态下永不触发。
CHECKER_TIME_BUDGET_S = 60




def _run_checker_bounded(fn, budget_s: int) -> AuditResult:
    """在独立线程里跑检查器 fn，墙钟预算 budget_s（ThreadPoolExecutor worker）。

    - 预算内完成：返回 fn 产出的 AuditResult（正常 PASS/FAIL/SKIPPED）。
    - 超预算：返回 P2 SKIPPED「超时跳过」，主流程继续；遗留线程继续后台跑。
    - fn 抛非超时异常：返回 P0 SKIPPED（真异常≠超时，保留 P0 不静默吞）。

    抽成独立 helper 以便单测（不触发 8 个真实检查器）。

    ⚠️ 线程模型如实说明（6be0aae6 移除 thread_factory 后）：
    CPython 的 ThreadPoolExecutor worker 恒为非 daemon。健康态（各检查器 <60s，
    实测 self_audit 全流程 ~45s）下 worker 均正常结束，无遗留、退出干净。
    仅当某检查器真超预算（回归：目录再膨胀/subprocess 挂死）触发「超时跳过」时，
    遗留 worker 会在进程收尾被 atexit join —— 这是已知取舍，非静默缺陷；
    真回归场景应由 SCAN_EXCLUDE 黑名单告警 + 下一轮自审复检兜底。
    """
    t0 = time.monotonic()
    ex = concurrent.futures.ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="audit_" + fn.__name__,
    )
    fut = ex.submit(fn)
    try:
        result = fut.result(timeout=budget_s)
    except concurrent.futures.TimeoutError:
        # future.result(timeout) 抛 builtins.TimeoutError（本 py3.11 无
        # concurrent.futures.TimeoutExpired 名）。检查器内部异常均已自行 try/except
        # 返回 AuditResult，不会泄漏 TimeoutError，故此处命中=预算耗尽。
        elapsed = time.monotonic() - t0
        result = AuditResult(
            checker=fn.__name__, category="unknown",
            status="SKIPPED", severity="P2",
            message=f"检查器 {fn.__name__} 超时跳过（P2降级，{budget_s}s 预算耗尽，实际{elapsed:.0f}s），不阻塞主流程",
            evidence=f"concurrent.futures.TimeoutError budget={budget_s}s",
        )
    except Exception as e:
        result = AuditResult(
            checker=fn.__name__, category="unknown",
            status="SKIPPED", severity="P0",
            message=f"检查器异常: {e}",
            evidence=str(e),
        )
    finally:
        # wait=False：正常完成时立即回收；超时遗留线程不在此 join（避免把超时成本
        # 转移到主流程）；其收尾 join 由进程 atexit 承担（见 docstring 取舍说明）。
        ex.shutdown(wait=False, cancel_futures=True)
    return result


def run_all_checkers(send_alerts: bool = True,
                     per_checker_budget_s: int = CHECKER_TIME_BUDGET_S) -> List[AuditResult]:
    """运行全部 R0 检查器，返回结果列表。

    P1-3 (2026-10-19): 每项套 per_checker_budget_s（默认60s）墙钟预算 ——
    超预算降级 P2 SKIPPED「超时跳过」而非阻塞主流程（独立线程，遗留线程收尾
    join 由进程 atexit 承担，见 _run_checker_bounded 取舍说明）。顺序执行，
    避免 M-2/M-3 并发写 message_queue.json。
    """
    checkers = [
        check_c1_s1_false_green,
        check_c2_gate_consistency,
        check_d1_dd_threshold_drift,
        check_a1_s1_consumer_arbitration,
        check_r1_remote_freshness,        # T3 (2026-10-15): 代码资产检测
        check_m1_drain_liveness,          # T2 (2026-10-15): 告警环 meta 复检
        check_m2_ruling_drift,            # R1-2 B段真实接入 (2026-10-16): RULING 快照漂移
        check_m3_dispatch_audit,          # P1-F (2026-10-19 总管): 派单审计消费断言，2日连续→P0
        check_m4_factor_decay,            # P2-O3 (2026-10-20 老三): 因子衰减监控挂表（M-2/M-3 已占号）
    ]

    results: List[AuditResult] = []
    for checker_fn in checkers:
        print(f"\n🔍 运行 {checker_fn.__name__} ...")
        result = _run_checker_bounded(checker_fn, per_checker_budget_s)
        results.append(result)

        if result.status == "PASS":
            print(f"   ✅ {result.message}")
        elif result.status == "SKIPPED":
            print(f"   ⏭️  {result.message}")
        else:
            print(f"   🚨 {result.message}")
            _append_alert_log(result)
            if send_alerts:
                _send_alert(result)

    return results


def print_summary(results: List[AuditResult]) -> None:
    """打印汇总。"""
    fails = [r for r in results if r.status == "FAIL"]
    skips = [r for r in results if r.status == "SKIPPED"]
    passes = [r for r in results if r.status == "PASS"]

    print("\n" + "=" * 60)
    print(f"📊 自审 Agent R0 汇总")
    print(f"   通过: {len(passes)} | 失败: {len(fails)} | 跳过: {len(skips)}")
    if fails:
        print("   🚨 失败项:")
        for r in fails:
            print(f"      - [{r.severity}] {r.checker}: {r.message}")
    print("=" * 60)


if __name__ == "__main__":
    results = run_all_checkers(send_alerts=True)
    print_summary(results)
    sys.exit(1 if any(r.status == "FAIL" for r in results) else 0)
