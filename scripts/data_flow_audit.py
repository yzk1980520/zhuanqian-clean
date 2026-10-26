#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据流完整性审计 — 每日扫描 data/ 目录，标记孤儿生产者/消费者 (US5)

扫描 data/**/*.json（排除 data/system/ 自身输出），建立文件→生产者/消费者的映射。
产出 DataFlowReport JSON 写入 data/system/data_flow_report.json。

FR-005: 每日运行，产出孤儿生产者/消费者报告。
SC-005: 孤儿检测准确率 >= 95%。
宪法 VII: 无裸 except:，显式异常类型。
"""
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT / "data"
SYSTEM_DIR = DATA_DIR / "system"
REPORT_PATH = SYSTEM_DIR / "data_flow_report.json"
MSG_QUEUE = PROJECT / "data" / "message_queue.json"

# 排除的目录（审计自身的输出）
EXCLUDE_DIRS = {"system", "__pycache__"}
# 排除的文件模式
EXCLUDE_PATTERNS = {".gitkeep", ".gitignore"}

# T054 裁定（degradation_path）: 扩展扫描范围（core/backtest/team）实测孤儿率 99.45%（28880/29040），
# 未达 <5% 目标——根因是 history_daily/kline_daily/factors 三个批量缓存目录 28k 个
# 按日期/按股生成的文件，其 basename 在源码中不以字面量出现（f-string/glob 模式引用），
# 字面匹配无法闭合，扩展扫描范围对比例无影响。按契约 T054 默认扫描范围**保持原值不合并**，
# 扩展范围经配置（config.json data_flow_scan_dirs / 环境变量 DATA_FLOW_SCAN_DIRS）按需启用。
# tests/ 排除（开发期引用不算生产数据流消费者，与既有注释一致）。
DEFAULT_SCAN_DIRS = ["scripts", "dashboards"]

# SC-005 判据改口径（t_2680636c 裁定 A+C，执行卡 t_a3429d08）：
# 批量缓存目录 + 日期戳文件排除出「契约数据资产」分母，归 batch_cache / ephemeral 桶；
# 批量缓存生命周期归数据管道（auto_tdx_refresh job + 数据质量审计），不归代码引用审计。
# 排除清单配置面：config.json data_flow_excluded_dirs / data_flow_excluded_patterns 键
# > 环境变量 DATA_FLOW_EXCLUDED_DIRS / DATA_FLOW_EXCLUDED_PATTERNS（逗号分隔）> 默认值（随代码入库）。
# 分桶仅影响报告统计口径，不改 find_producers_consumers 匹配语义（matcher R0 锁死，SC-005 准确率≥95% 保留）。
DEFAULT_EXCLUDED_DIRS = ["history_daily", "factors", "akshare"]
DEFAULT_EXCLUDED_PATTERNS = ["20\\d{6}", "_bak_", ".bak_", "testbak", "stale"]

# data/system/ 已注册文件契约（specs/002-system-overview/data-model.md File Contracts 表）。
# 审计不扫 data/system/ 自身输出（EXCLUDE_DIRS），故这 4 条契约以常量声明，
# 判据分母第一项 = 其中实际存在的文件数。
SYSTEM_CONTRACT_FILES = [
    "data/system/health_snapshot.json",
    "data/system/dependency_graph.json",
    "data/system/data_flow_report.json",
    "data/system/role_permissions.json",
]

# 171 项稳定孤儿三态台账（a 登记入契约资产集 / b GC 归档 / c 豁免带过期日）。
# 台账本身是审计输入（脚本按字面量引用其路径 → 审计中归 intact，不入残差分子）。
LEDGER_PATH = DATA_DIR / "audit" / "sc005_orphan_ledger.json"


def resolve_scan_dirs(project: Path) -> list:
    """T054 配置化：消费者扫描目录 script_dirs 的取值。

    优先级：config.json 的 data_flow_scan_dirs 键 > 环境变量 DATA_FLOW_SCAN_DIRS（逗号分隔）> 默认值。
    向后兼容：未配置时返回原始默认值（T054 裁定：扩展范围不并入默认，经上述配置面 opt-in）。
    """
    cfg_path = project / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = None
        if isinstance(cfg, dict):
            dirs = cfg.get("data_flow_scan_dirs")
            if isinstance(dirs, list) and dirs and all(isinstance(d, str) and d.strip() for d in dirs):
                return [d.strip().strip("/") for d in dirs]
    raw = os.environ.get("DATA_FLOW_SCAN_DIRS", "").strip()
    if raw:
        dirs = [d.strip().strip("/") for d in raw.split(",") if d.strip()]
        if dirs:
            return dirs
    return list(DEFAULT_SCAN_DIRS)


def _resolve_excluded_list(key: str, env_key: str, default: list, project: Path) -> list:
    """排除清单统一 resolve：config.json 的 key 键 > 环境变量 env_key（逗号分隔）> 默认值。

    与 resolve_scan_dirs 同一优先级模式（T054 附加-2 已落地的配置面惯例）。
    仅接受非空 list[str]，非法值逐级回退；空 list = 显式清空。
    """
    cfg_path = project / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = None
        if isinstance(cfg, dict):
            val = cfg.get(key)
            if isinstance(val, list) and all(isinstance(x, str) for x in val):
                return [x.strip().strip("/") for x in val if x.strip()]
    raw = os.environ.get(env_key, "").strip()
    if raw:
        items = [x.strip() for x in raw.split(",") if x.strip()]
        if items:
            return items
    return list(default)


def resolve_excluded_dirs(project: Path) -> list:
    """批量缓存目录排除清单（data_flow_excluded_dirs，目录级命中即归 batch_cache 桶）。"""
    return _resolve_excluded_list("data_flow_excluded_dirs", "DATA_FLOW_EXCLUDED_DIRS",
                                  DEFAULT_EXCLUDED_DIRS, project)


def resolve_excluded_patterns(project: Path) -> list:
    """日期戳/临时文件排除模式（data_flow_excluded_patterns，正则匹配 basename，命中归 ephemeral 桶）。"""
    return _resolve_excluded_list("data_flow_excluded_patterns", "DATA_FLOW_EXCLUDED_PATTERNS",
                                  DEFAULT_EXCLUDED_PATTERNS, project)


def classify_bucket(rel_path: str, excluded_dirs: list, patterns: list) -> str:
    """SC-005 分桶（仅统计口径，不影响匹配语义）：

    batch_cache  — 路径中间目录命中 excluded_dirs（目录级/glob 引用的批量缓存，生命周期归数据管道）；
    ephemeral    — 文件名命中 excluded_patterns（日期戳/_bak_/testbak/stale 等临时件）；
    contract_assets — 其余稳定资产（判据分母所在桶）。
    """
    parts = rel_path.split("/")
    if parts[0] == "data":
        mids = parts[1:-1]
    else:
        mids = parts[:-1]
    for part in mids:
        if part in excluded_dirs:
            return "batch_cache"
    basename = parts[-1]
    for pat in patterns:
        try:
            if re.search(pat, basename):
                return "ephemeral"
        except re.error:
            print(f"[WARN] data_flow_excluded_patterns 非法正则，跳过该模式: {pat}", file=sys.stderr)
    return "contract_assets"


def load_ledger(path: Path | None = None) -> dict:
    """读 171 项稳定孤儿三态台账（缺失/损坏 → 空台账，判据字段置 null，不中断审计）。"""
    ledger_file = path or LEDGER_PATH
    try:
        raw = ledger_file.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        ledger = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[WARN] 台账损坏（JSON 解析失败），按无台账处理: {ledger_file}", file=sys.stderr)
        return {}
    return ledger if isinstance(ledger, dict) else {}


def compute_judgment(nodes: list, bucket_of: dict, ledger: dict, project: Path) -> dict:
    """SC-005 契约数据资产判据（A+C 组合，t_2680636c 裁定）：

    分母 D = data/system/ 已注册文件契约（实际存在数）
             + 稳定资产 intact 数
             + 台账 (a) 登记数 + 台账 (c) 豁免数（有效期内与过期均计入资产集）
    分子 N = 台账 (b) GC 待执行且文件仍物理存在 + (c) 豁免（有效与过期）+ 未分类孤儿
    判据通过 = N/D < 5%。GC 执行后（后续卡派单）(b) 项物理出树，N 收敛至 (c) 项。
    无台账时 judgment=null（口径未生效，仅桶统计可用）。
    """
    if not ledger:
        return {"judgment_version": None, "denominator": None, "numerator": None,
                "orphan_rate": None, "pass": None, "post_gc_expected": None}

    import datetime as _dt
    today = _dt.date.today().isoformat()
    disposition = {}
    for item in ledger.get("items", []):
        if isinstance(item, dict) and item.get("file"):
            disposition[str(item["file"]).replace("\\", "/")] = item

    intact = 0
    orphans_stable = []
    for n in nodes:
        if n["status"] == "orphan_consumer":
            continue
        if bucket_of.get(n["file_path"], "batch_cache") != "contract_assets":
            continue
        if n["status"] == "intact":
            intact += 1
        else:
            orphans_stable.append(n["file_path"].replace("\\", "/"))  # 归一 POSIX，与台账键对齐

    registered_a = [f for f, it in disposition.items() if it.get("disposition") == "a"]
    exempt_c = [f for f, it in disposition.items() if it.get("disposition") == "c"]
    gc_b = [f for f, it in disposition.items() if it.get("disposition") == "b"]
    gc_b_present = [f for f in gc_b if f in orphans_stable]  # 文件仍在树中（GC 未执行）
    unclassified = [f for f in orphans_stable if f not in disposition]

    sys_contracts_present = sum(1 for sf in SYSTEM_CONTRACT_FILES if (project / sf).exists())
    denominator = sys_contracts_present + intact + len(registered_a) + len(exempt_c)
    numerator = len(gc_b_present) + len(exempt_c) + len(unclassified)
    rate = (numerator / denominator) if denominator else None
    pass_now = (rate < 0.05) if rate is not None else None

    # GC 执行后 (b) 项物理出树：N 收敛至豁免项
    post_num = len(exempt_c)
    post_rate = (post_num / denominator) if denominator else None
    post_pass = (post_rate < 0.05) if post_rate is not None else None

    return {
        "judgment_version": ledger.get("judgment_version"),
        "data_state_commit": ledger.get("data_state_commit"),
        "denominator": denominator,
        "numerator": numerator,
        "orphan_rate": round(rate, 4) if rate is not None else None,
        "pass": pass_now,
        "breakdown": {
            "system_contracts_present": sys_contracts_present,
            "stable_intact": intact,
            "ledger_registered_a": len(registered_a),
            "ledger_exempt_c": len(exempt_c),
            "ledger_gc_pending_b_present": len(gc_b_present),
            "unclassified": len(unclassified),
        },
        "post_gc_expected": {
            "numerator": post_num,
            "orphan_rate": round(post_rate, 4) if post_rate is not None else None,
            "pass": post_pass,
        },
        "gc_b_deadline": next((it.get("expiry") for f, it in disposition.items()
                                if it.get("disposition") == "b" and it.get("expiry")), None),
        "exempt_c_deadline": next((it.get("expiry") for f, it in disposition.items()
                                   if it.get("disposition") == "c" and it.get("expiry")), None),
        "today": today,
    }


def find_json_files(data_dir: Path) -> list:
    """找到 data/ 下所有 JSON 文件（排除 system/ 输出）。"""
    files = []
    if not data_dir.exists():
        return files
    for json_file in sorted(data_dir.rglob("*.json")):
        rel = json_file.relative_to(data_dir)
        parts = rel.parts
        # 排除 system/ 下的输出
        if "system" in parts:
            continue
        if json_file.name in EXCLUDE_PATTERNS:
            continue
        files.append(json_file)
    return files


def find_producers_consumers(json_files: list, project: Path, data_dir: Path | None = None) -> dict:
    """扫描生产代码目录（resolve_scan_dirs 配置化，默认 scripts/dashboards，可经 config.json/环境变量扩展）中引用每个 JSON 文件的路径。

    排除 tests/（开发期引用不算生产数据流消费者）。
    若 data_dir 提供，同时扫描 data_dir 内的 .py 文件（测试场景：临时目录自带消费者脚本）。
    """
    # file_path -> {"producers": [...], "consumers": [...]}
    mapping = defaultdict(lambda: {"producers": [], "consumers": []})

    # 生产代码目录（附加-2: config.json data_flow_scan_dirs / 环境变量 DATA_FLOW_SCAN_DIRS 可配置；
    # T054 裁定: 默认保持原值 scripts/dashboards，扩展范围 opt-in，详见 DEFAULT_SCAN_DIRS 注释）
    script_dirs = resolve_scan_dirs(project)
    script_files = []
    for d in script_dirs:
        dir_path = project / d
        if dir_path.exists():
            for py_file in dir_path.rglob("*.py"):
                script_files.append(py_file)

    # 测试场景：data_dir 内自带的 Python 文件（临时目录里的 consumer.py 等）
    if data_dir is not None and data_dir.exists():
        for py_file in sorted(data_dir.rglob("*.py")):
            script_files.append(py_file)

    # 预加载各脚本源一次（O(脚本数) 次 IO；原实现 O(JSON×脚本) 次重复 read_text，
    # 19k JSON × 10k 脚本在 Windows 上超 120s）
    loaded_sources: dict = {}
    for script in script_files:
        key = str(script)
        try:
            loaded_sources[key] = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            loaded_sources[key] = None

    # 无损预筛选（反转索引）：若 basename 以子串形式出现在某脚本源中，则 basename
    # 的所有 token 必然也出现在该源中。用 token→脚本 反转索引，把每文件 O(全量脚本)
    # 降为 O(token命中脚本)。只能"剔除不可能命中"的脚本，匹配结果与全量扫描等价。
    # 边界：超短 basename（无 token）回退全量检查，保持等价。
    _tok_re = re.compile(r"[a-z0-9]{4,}")

    def _tokens_of(s: str) -> set:
        return set(_tok_re.findall(s.lower()))

    # 每个脚本的源 token 集合（一次计算）
    script_tokens = {}
    for s in script_files:
        src = loaded_sources.get(str(s))
        if src is not None:
            script_tokens[str(s)] = _tokens_of(src)

    # token -> 脚本 Path 反转索引
    token_index: dict = {}
    for s in script_files:
        for tok in script_tokens.get(str(s), set()):
            token_index.setdefault(tok, set()).add(s)

    for json_file in json_files:
        # 使用 str 比较而非 relative_to，避免跨驱动符问题
        rel_path = str(json_file)
        # 尝试相对路径，失败则用绝对路径
        try:
            rel_path = str(json_file.relative_to(project))
        except ValueError:
            rel_path = str(json_file)
        basename = json_file.name
        # 候选脚本：basename token 命中的脚本之并集（basename 匹配只需 basename token；
        # 完整路径匹配是 basename 的超集情形，同样被覆盖）
        b_tokens = _tokens_of(basename)
        if b_tokens:
            cands = set()
            for tok in b_tokens:
                cands |= token_index.get(tok, set())
        else:
            cands = set(script_files)  # 无 token（超短名）→ 全量检查
        for script in cands:
            source = loaded_sources.get(str(script))
            if source is None:
                continue
            # 匹配完整路径引用
            if rel_path in source:
                try:
                    script_rel = str(script.relative_to(project))
                except ValueError:
                    script_rel = str(script)
                mapping[rel_path]["consumers"].append(script_rel)
            # 匹配文件名引用（更宽松）
            elif basename in source and json_file.suffix in source:
                try:
                    script_rel = str(script.relative_to(project))
                except ValueError:
                    script_rel = str(script)
                mapping[rel_path]["consumers"].append(script_rel)

    return dict(mapping)


def run_audit(data_dir: Path | None = None, ledger_path: Path | None = None) -> dict:
    """运行数据流审计。

    ledger_path: 三态台账路径（缺省读 LEDGER_PATH；测试可注入独立台账位置）。
    """
    if data_dir is None:
        data_dir = DATA_DIR

    scanned_at = datetime.now(timezone.utc).isoformat()
    json_files = find_json_files(data_dir)
    mapping = find_producers_consumers(json_files, PROJECT, data_dir=data_dir)

    orphan_producers = []
    orphan_consumers = []
    nodes = []

    for json_file in json_files:
        # 安全获取相对路径（跨驱动符时 fallback 到绝对路径）
        try:
            rel_path = str(json_file.relative_to(PROJECT))
        except ValueError:
            rel_path = str(json_file)
        info = mapping.get(rel_path, {"producers": [], "consumers": []})

        # 生产者：仅归因到真实存在的脚本（不得引用缺失文件）
        producers = []
        if json_file.exists():
            mtime = datetime.fromtimestamp(json_file.stat().st_mtime, tz=timezone.utc)
            # 从文件名推断生产者，目标脚本必须实际存在才归因
            parent = json_file.parent.name
            candidate = None
            if parent == "factor_ic":
                candidate = PROJECT / "scripts" / "factor_ic_132d_refresh.py"
            elif parent == "history_daily":
                candidate = PROJECT / "scripts" / "auto_live_pipeline.py"
            if candidate is not None and candidate.exists():
                producers = [str(candidate.relative_to(PROJECT))]

        consumers = info.get("consumers", [])

        # 判断状态：
        # - 文件存在 + 无消费者 → orphan_producer
        # - 文件存在 + 有消费者 → intact
        # （orphan_consumer 仅用于缺失文件，在下方单独扫描）
        if not consumers:
            status = "orphan_producer"
            orphan_producers.append(rel_path)
        else:
            status = "intact"

        nodes.append({
            "file_path": rel_path,
            "producer_script": producers[0] if producers else None,
            "consumer_scripts": consumers,
            "created_at": mtime.isoformat() if json_file.exists() else None,
            "last_accessed_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
        })

    # 确定整体状态
    if orphan_producers or orphan_consumers:
        overall_status = "degraded"
    else:
        overall_status = "intact"

    # 扫描 data_dir 内 Python 文件中引用的缺失 JSON 文件（orphan_consumer 场景）
    # 仅扫描 data_dir 自身，避免误报项目内所有脚本中的 .json 字符串
    import re
    missing_files = set()
    if data_dir is not None and data_dir.exists():
        for script in data_dir.rglob("*.py"):
            try:
                src = script.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # 提取绝对路径的 .json 引用（形如 /path/to/file.json）
            for match in re.finditer(r'(?:["\x27])(/[\w/\\.-]+\.json)(?:["\x27])', src):
                ref = match.group(1).replace("\\", "/")
                ref_path = Path(ref)
                if not ref_path.exists():
                    missing_files.add(ref)
            # 提取相对于 data_dir 的 .json 引用
            for match in re.finditer(r'(?:["\x27])(\w+\.json)(?:["\x27])', src):
                ref = match.group(1)
                if not (data_dir / ref).exists() and not (PROJECT / ref).exists():
                    missing_files.add(ref)

    for missing in sorted(missing_files):
        orphan_consumers.append(missing)
        nodes.append({
            "file_path": missing,
            "producer_script": None,
            "consumer_scripts": [],
            "created_at": None,
            "last_accessed_at": datetime.now(timezone.utc).isoformat(),
            "status": "orphan_consumer",
        })

    # SC-005 判据改口径（A+C）：分桶统计 + 契约资产判据（读台账；无台账则判据字段为 null）
    excluded_dirs = resolve_excluded_dirs(PROJECT)
    excluded_patterns = resolve_excluded_patterns(PROJECT)
    ledger = load_ledger(ledger_path)

    bucket_of: dict = {}
    buckets_report: dict = {
        "batch_cache": {"files": 0, "orphans": 0, "orphan_rate": 0.0},
        "ephemeral": {"files": 0, "orphans": 0, "orphan_rate": 0.0},
        "contract_assets": {"files": 0, "orphans": 0, "orphan_rate": 0.0},
    }
    for n in nodes:
        if n["status"] == "orphan_consumer":
            continue  # 缺失文件引用无桶归属
        b = classify_bucket(n["file_path"].replace("\\", "/"), excluded_dirs, excluded_patterns)
        bucket_of[n["file_path"]] = b
        buckets_report[b]["files"] += 1
        if n["status"] == "orphan_producer":
            buckets_report[b]["orphans"] += 1
    for b in buckets_report.values():
        if isinstance(b, dict):
            b["orphan_rate"] = round(b["orphans"] / b["files"], 4) if b["files"] else 0.0

    judgment = compute_judgment(nodes, bucket_of, ledger, PROJECT)
    buckets_report["excluded_dirs"] = excluded_dirs
    buckets_report["excluded_patterns"] = excluded_patterns
    buckets_report["ledger_path"] = str(LEDGER_PATH.relative_to(PROJECT)) if LEDGER_PATH.exists() else None
    buckets_report["judgment"] = judgment

    report = {
        "scanned_at": scanned_at,
        "status": overall_status,
        "orphan_producers": orphan_producers,
        "orphan_consumers": orphan_consumers,
        "nodes": nodes,
        "buckets": buckets_report,
    }
    return report


def write_report(report: dict) -> None:
    """写入审计报告。"""
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from core.pipeline.atomic_json import atomic_dump
        atomic_dump(report, str(REPORT_PATH), ensure_ascii=False, indent=2)
    except ImportError:
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# t_cd7dab36 读侧契约（§2.9/§4.1-12）：读侧=cron_message_sender._render_content（L334-339，
# 只认 content/msg/title+body），条目必须带非空 content 字符串字段（"[level] message" 格式），
# 否则恒 unrenderable → 死信。2026-10-26 晨 3 条 data_flow_audit P2 unrenderable 死信
# （data/drain_dead_letter.jsonl 01:44/01:49/02:44）根因 = 旧条目只有 message 字段。
# 字段形态与队列生产方字段普查（2026-10-26 只读）一致：core/ops/position_alerts.py L49
# 直接构造 "content" 字段入队；core/ops/self_audit_checkers.py L720-727 经
# core/ops/message_queue.py::add_message（L30 "content" 字段，唯一写侧出口）；
# 无生产方使用裸 message 字段 → 与 drain 契约无冲突，不触发重派。
# payload 规则：只留 top-20 孤儿样本 + 总数字段 orphan_count，禁止整表（19k 项 ≈1.2MB/条）入队。
ORPHAN_SAMPLE_LIMIT = 20


def _orphan_payload(items: list, kind: str) -> dict:
    """队列告警孤儿 payload：top-20 样本 + 总数 orphan_count（禁整表入队）。

    kind ∈ {"orphan_producer", "orphan_consumer"}，区分 P2 生产者告警 / P0 消费者告警。
    """
    return {
        "orphan_count": len(items),
        "orphan_kind": kind,
        "orphan_samples": list(items[:ORPHAN_SAMPLE_LIMIT]),
    }


def should_alert_orphan_producers(judgment: dict | None) -> bool:
    """P2 孤儿生产者告警触发判定（t_cd7dab36，跟进 SC-005 判据 t_2680636c 口径）：

    - 判据版本缺失（judgment_version is None，判据未生效）→ True（保守告警）；
    - pass=True（判据通过）→ False（静默：只写报告不写队列）；
    - pass=False / pass=None（不过或无法判定，如分母=0）→ True。
    原则：判据未显式通过前，孤儿生产者仍视为需人工关注的异常。
    """
    if not isinstance(judgment, dict) or judgment.get("judgment_version") is None:
        return True
    return judgment.get("pass") is not True


def write_alert(level: str, message: str, details: dict | None = None) -> None:
    """写入告警到 message_queue.json（共享队列，读-改-写追加语义，不得 atomic_dump 覆盖）。

    读侧契约：条目 content 字段 = "[level] message"（非空字符串），
    cron_message_sender._render_content 统一渲染，杜绝 unrenderable 死信。
    """
    alert = {
        "level": level,
        "type": "data_flow_audit",
        "content": f"[{level}] {message}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **(details or {}),
    }
    try:
        from core.pipeline.atomic_json import update_json
        def _append(existing):
            if existing is None:
                existing = []
            if not isinstance(existing, list):
                existing = [existing]
            existing.append(alert)
            return existing
        update_json(str(MSG_QUEUE), _append, default=[])
    except ImportError as exc:
        print(f"[WARN] atomic_json unavailable, using non-atomic append: {exc}", file=sys.stderr)
        if MSG_QUEUE.exists():
            try:
                existing = json.loads(MSG_QUEUE.read_text(encoding="utf-8"))
                if isinstance(existing, list):
                    existing.append(alert)
                else:
                    existing = [existing, alert]
                MSG_QUEUE.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            except json.JSONDecodeError as exc2:
                print(f"[WARN] message_queue.json corrupt, resetting to [alert]: {exc2}", file=sys.stderr)
                MSG_QUEUE.write_text(json.dumps([alert], ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            MSG_QUEUE.write_text(json.dumps([alert], ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] Failed to write data_flow_audit alert: {exc}", file=sys.stderr)


def main() -> int:
    """入口：运行审计并写入报告。"""
    start = __import__("time").time()
    try:
        report = run_audit()
        write_report(report)
        elapsed = int((__import__("time").time() - start) * 1000)

        print(f"Data flow audit complete: {REPORT_PATH}")
        print(f"  status={report['status']}, orphans_producer={len(report['orphan_producers'])}, "
              f"orphans_consumer={len(report['orphan_consumers'])}, "
              f"nodes={len(report['nodes'])}")
        j = report["buckets"]["judgment"]
        if j.get("judgment_version"):
            print(f"  SC-005 契约资产判据[{j['judgment_version']}]: "
                  f"orphan={j['numerator']} / total={j['denominator']} = "
                  f"{j['orphan_rate'] * 100:.2f}% (pass={j['pass']})")
            pg = j.get("post_gc_expected") or {}
            print(f"  GC 执行后预期: orphan={pg.get('numerator')} / total={j['denominator']} = "
                  f"{(pg.get('orphan_rate') or 0) * 100:.2f}% (pass={pg.get('pass')})")
        else:
            ca = report["buckets"]["contract_assets"]
            print(f"  契约资产桶: orphan={ca['orphans']} / total={ca['files']} = "
                  f"{ca['orphan_rate'] * 100:.2f}% (台账缺失，判据未生效)")
        print(f"  completed in {elapsed}ms")

        # P0 告警：发现孤儿消费者（读取不存在文件）— 真实数据流缺陷，与 SC-005 判据无关直接告警；
        # payload 按读侧契约紧凑化（top-20 样本 + orphan_count，见 _orphan_payload）
        if report["orphan_consumers"]:
            write_alert(
                "P0",
                f"数据流审计发现 {len(report['orphan_consumers'])} 个孤儿消费者",
                _orphan_payload(report["orphan_consumers"], "orphan_consumer"),
            )

        # P2 告警：发现孤儿生产者（t_cd7dab36 口径修复：仅判据未显式通过时告警，
        # pass=True 静默 — 只写报告不写队列；判据版本缺失/无法判定 → 保守告警）
        if report["orphan_producers"] and should_alert_orphan_producers(j):
            write_alert(
                "P2",
                f"数据流审计发现 {len(report['orphan_producers'])} 个孤儿生产者",
                _orphan_payload(report["orphan_producers"], "orphan_producer"),
            )

        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        write_alert("P0", f"数据流审计失败: {exc}", {})
        return 1


if __name__ == "__main__":
    sys.exit(main())
