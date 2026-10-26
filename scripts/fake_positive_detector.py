#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fake_positive_detector.py — 假绿周期检测器

功能：
  扫描 position_decision.json（决策+score快照）× trade_log.json（权威全量台账）
  → 识别"score高但后续实亏" → 追加写 data/fake_positive_log.jsonl

输出格式（每行JSON）：
  {
    "ts": "<detector run timestamp>",
    "stock_code": "<stock>",
    "stock_name": "<name>",
    "score_at_decision": <float>,       # 决策时score（by_score或action.score）
    "decision_ts": "<position_decision timestamp>",
    "pnl_actual": <float>,               # 实际盈亏金额
    "pnl_pct": <float>,                  # 实际盈亏比例
    "ratio": <float>,                    # pnl_pct / score_at_decision 归一化比值
    "evidence": "<解释性指标>"
  }

回授断言（老六 §三）：
  - 写入侧：本脚本
  - 消费侧：weekly_ic cron 事件（cron_dispatcher.py --event weekly_ic）
    在周报生成前读取 fake_positive_log.jsonl，汇总假绿条目数进周报
  - 消费不到处理：weekly_ic 报告中标注"fake_positive_log.jsonl 无新条目"或"文件不存在"
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime

# 强制 utf-8 stdout
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    print(f"🔴 [scripts\fake_positive_detector.py] CR-01: except Exception:", file=sys.stderr)
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from core.pipeline.atomic_json import atomic_dump, atomic_load

# ── 配置 ──────────────────────────────────────────────────────────────────────
POSITION_DECISION_PATH = ROOT / "data" / "position_decision.json"
TRADE_LOG_PATH = ROOT / "data" / "trade_log.json"
OUTPUT_LOG_PATH = ROOT / "data" / "fake_positive_log.jsonl"

# 运行心跳 (2026-10-19 老六加): 本脚本只在 findings>0 时才写 OUTPUT_LOG_PATH，
# 因此「产物 mtime」无法证明它跑过 —— findings=0 时文件根本不更新甚至不存在。
# 闭环健康度 A5 需要一个无论结果如何都留痕的痕迹，故每次运行追加一行心跳。
# 判据: A5 查本文件新鲜度(周更 soft 10d / hard 21d)，不查 OUTPUT_LOG_PATH。
RUN_HEARTBEAT_PATH = ROOT / "data" / "audit" / "fake_positive_runs.jsonl"

_OUTPUT_PATH_OVERRIDE = None  # 测试注入用
_data_integrity = True  # 模块级数据完整性标志


def _ensure_output_exists() -> None:
    """无 findings 时也要让产物文件存在。

    下游 weekly_report_generator 读不到文件时会标注「文件不存在」，
    把「本次 0 条假绿」误报成「检测环节故障」。创建空文件让语义回到正确：
    文件存在 + 0 行 = 检测跑过且无发现；文件不存在 = 从未跑过。
    """
    p = Path(_OUTPUT_PATH_OVERRIDE) if _OUTPUT_PATH_OVERRIDE else OUTPUT_LOG_PATH
    try:
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
    except Exception as e:
        print(f"  [warn] 产物占位文件创建失败: {e}", file=sys.stderr)


def _append_run_heartbeat(ts: str, findings: int, trades_loaded: int,
                          data_integrity: bool, ok: bool) -> None:
    """每次运行都留痕。写失败绝不抛异常 —— 心跳是观测手段，不能反过来拖垮检测。"""
    rec = {
        "ts": ts,
        "findings": findings,
        "trades_loaded": trades_loaded,
        "data_integrity": bool(data_integrity),
        "ok": bool(ok),
    }
    try:
        RUN_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(RUN_HEARTBEAT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"  [warn] 运行心跳写入失败 (不影响检测结论): {e}", file=sys.stderr)


def _output_path():
    """返回输出路径（支持测试覆盖）"""
    return Path(_OUTPUT_PATH_OVERRIDE) if _OUTPUT_PATH_OVERRIDE else OUTPUT_LOG_PATH

# 假绿判定阈值（可调）
SCORE_THRESHOLD = 0.5        # by_score >= 此值视为"高分决策"
PNL_PCT_THRESHOLD = -5.0     # pnl_pct < 此值视为"实亏"
# ratio = |pnl_pct| / score_at_decision，>1.0 表示亏损幅度超过评分预期
RATIO_WARNING = 1.0

# ── 工具函数 ───────────────────────────────────────────────────────────────────

def load_decision():
    """加载 position_decision.json，返回 dict；不存在则返回 None"""
    if not POSITION_DECISION_PATH.exists():
        return None
    return atomic_load(str(POSITION_DECISION_PATH), default=None)


def load_trades():
    """加载 trade_log.json（权威台账），返回 list[dict]；文件不存在返回 []
    格式：{"trades": [...]} 或纯 list[...]
    字段规范化：将原始字段(code/name/date/time/profit_loss/profit_pct)
    映射为 detector 内部统一口径(stock_code/stock_name/exec_time/pnl/pnl_pct/strategy)。
    异常时设置 _data_integrity=False 标志。
    """
    global _data_integrity
    if not TRADE_LOG_PATH.exists():
        return []
    try:
        data = atomic_load(str(TRADE_LOG_PATH), default=None)
        if data is None:
            return []
        if isinstance(data, dict):
            raw = data.get("trades", [])
        elif isinstance(data, list):
            raw = data
        else:
            return []
        trades = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            # 规范化字段（兼容两种口径）
            exec_ts_str = t.get("exec_time") or (
                f"{t.get('date', '')} {t.get('time', '')}".strip()
            )
            if not exec_ts_str:
                continue
            trades.append({
                "stock_code": t.get("stock_code") or t.get("code", ""),
                "stock_name": t.get("stock_name") or t.get("name", ""),
                "exec_time": exec_ts_str,
                "pnl_pct": t.get("pnl_pct", t.get("profit_pct", 0.0)),
                "pnl": t.get("pnl", t.get("profit_loss", 0.0)),
                "strategy": t.get("strategy", t.get("reason", "")),
                **t,  # 保留原始字段供下游使用
            })
        return trades
    except Exception:
        _data_integrity = False
        return []


def parse_ts(ts_str):
    """解析 ISO 类时间戳字符串，失败返回 None"""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts_str, fmt)
        except ValueError:
            print(f"⚠️ [scripts\fake_positive_detector.py] 兼容处理: except ValueError:", file=sys.stderr)
    return None


def detect_fake_positives(decision, trades):
    """
    核心检测逻辑：
    1. 取 decision.timestamp 作为 cutoff
    2. 过滤 exec_time >= cutoff 的 trades
    3. 对每条 trade，检查 by_score >= SCORE_THRESHOLD 且 pnl_pct < PNL_PCT_THRESHOLD
    4. 也支持 decision.actions 中 per-stock score 的格式（未来扩展）
    返回 list[dict] 每条发现
    """
    findings = []
    if decision is None:
        return findings

    dec_ts_str = decision.get("timestamp", "")
    dec_ts = parse_ts(dec_ts_str)
    if dec_ts is None:
        return findings

    # 获取决策时的评分（portfolio level）
    target_pos = decision.get("target_position", {})
    by_score = target_pos.get("by_score", 0.0)
    strategy = decision.get("strategy", {})
    primary_strategy = strategy.get("primary", "unknown")

    # 检查 actions 中是否有 per-stock score（未来扩展）
    actions = decision.get("actions", [])
    has_per_stock_scores = bool(actions)

    for trade in trades:
        exec_ts_str = trade.get("exec_time", "")
        exec_ts = parse_ts(exec_ts_str)
        if exec_ts is None:
            continue
        # 只考虑决策之后的交易
        if exec_ts < dec_ts:
            continue

        stock_code = trade.get("stock_code", "")
        stock_name = trade.get("stock_name", "")
        pnl_pct = float(trade.get("pnl_pct") or 0.0)
        pnl_actual = float(trade.get("pnl") or 0.0)
        trade_strategy = trade.get("strategy", "")

        # 确定 score_at_decision
        # 优先用 by_score（portfolio level），fallback 用 1.0（默认高分假设）
        score_at_decision = by_score if by_score > 0 else 1.0

        # 假绿判定：高分决策 + 实亏
        is_fake_positive = (
            score_at_decision >= SCORE_THRESHOLD
            and pnl_pct < PNL_PCT_THRESHOLD
        )

        if not is_fake_positive:
            continue

        # 计算 ratio
        ratio = abs(pnl_pct) / score_at_decision if score_at_decision > 0 else 0.0

        # 生成证据指标
        evidence_parts = []
        if ratio >= RATIO_WARNING:
            evidence_parts.append(f"ratio={ratio:.2f}(>={RATIO_WARNING})")
        evidence_parts.append(f"by_score={score_at_decision}")
        evidence_parts.append(f"pnl_pct={pnl_pct}%")
        evidence_parts.append(f"strategy={trade_strategy}")
        evidence = "; ".join(evidence_parts)

        findings.append({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "score_at_decision": score_at_decision,
            "decision_ts": dec_ts_str,
            "pnl_actual": pnl_actual,
            "pnl_pct": pnl_pct,
            "ratio": round(ratio, 4),
            "evidence": evidence,
        })

    return findings


def append_finding(finding, output_path=None):
    """追加写一行 JSONL（原子写，按 (stock_code, decision_ts) 去重）
    output_path: 测试注入用，None 则用默认 OUTPUT_LOG_PATH
    已存在相同 (stock_code, decision_ts) 则跳过，不重复写入。
    """
    target = Path(output_path) if output_path else _output_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # 去重：读出现有记录，检查 (stock_code, decision_ts) 是否已存在
    key = (finding.get("stock_code"), finding.get("decision_ts"))
    if key[0] and key[1]:
        existing = []
        if target.exists():
            with open(target, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing.append(json.loads(line))
                    except json.JSONDecodeError:
                        print(f"🔴 [scripts\fake_positive_detector.py] CR-01: except json.JSONDecodeError:", file=sys.stderr)
            if any(
                e.get("stock_code") == key[0] and e.get("decision_ts") == key[1]
                for e in existing
            ):
                return  # 已存在，跳过

    line = json.dumps(finding, ensure_ascii=False, default=str) + "\n"
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)


def run(detector_ts=None, output_path=None):
    """
    主入口：加载数据 → 检测 → 写日志 → 打印摘要
    output_path: 测试注入用，None 则用默认 OUTPUT_LOG_PATH
    返回 (finding_count, findings_list, data_integrity)
    """
    global _OUTPUT_PATH_OVERRIDE, _data_integrity
    prev_override = _OUTPUT_PATH_OVERRIDE
    if output_path is not None:
        _OUTPUT_PATH_OVERRIDE = str(output_path)

    data_integrity = True  # 默认数据完整
    try:
        decision = load_decision()
        trades = load_trades()
        # 检查 load_trades 是否设置了异常标志
        if not _data_integrity:
            data_integrity = False
            _data_integrity = True  # 重置标志供下次使用
        findings = detect_fake_positives(decision, trades)

        # 写入新发现
        for finding in findings:
            append_finding(finding)
        _ensure_output_exists()

        # 打印摘要
        dec_info = ""
        if decision:
            dec_info = (
                f"decision_ts={decision.get('timestamp')} "
                f"by_score={decision.get('target_position',{}).get('by_score')} "
                f"strategy={decision.get('strategy',{}).get('primary')}"
            )
        else:
            dec_info = "position_decision.json 不存在"

        print(f"[fake_positive_detector] {detector_ts or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  {dec_info}")
        print(f"  trades_loaded={len(trades)}, findings={len(findings)}, data_integrity={data_integrity}")

        if not data_integrity:
            # 数据异常态：红标警告
            print(f"  ⚠️  [假绿检查异常: 数据源加载时发生错误] 检测结果不可信，请检查 trade_log.json", file=sys.stderr)
        elif findings:
            print(f"  ⚠️  检测到 {len(findings)} 条假绿样本：")
            for finding in findings:
                print(f"    - {finding['stock_code']} {finding['stock_name']} "
                      f"score={finding['score_at_decision']} "
                      f"pnl={finding['pnl_pct']}% "
                      f"ratio={finding['ratio']}")
        else:
            print(f"  ✅ 未检测到假绿样本")

        _append_run_heartbeat(
            detector_ts or datetime.now().isoformat(timespec="seconds"),
            len(findings), len(trades), data_integrity, True,
        )
        return len(findings), findings, data_integrity
    except Exception as e:
        # 数据加载异常：置 data_integrity=False，红标输出
        data_integrity = False
        print(f"[fake_positive_detector] {detector_ts or datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  ⚠️  [假绿检查异常: {e}] 数据源不可信，data_integrity=false")
        print(f"  data_integrity=false", file=sys.stderr)
        _append_run_heartbeat(
            detector_ts or datetime.now().isoformat(timespec="seconds"),
            0, 0, False, False,
        )
        # 返回空结果但标记异常
        return 0, [], data_integrity
    finally:
        _OUTPUT_PATH_OVERRIDE = prev_override


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="假绿周期检测器")
    parser.add_argument("--now", help="覆盖检测时间戳 (ISO)", default=None)
    args = parser.parse_args()
    count, _, data_integrity = run(detector_ts=args.now)
    sys.exit(0 if count == 0 else 1)
