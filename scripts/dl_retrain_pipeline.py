#!/usr/bin/env python
"""T006: DL 预训练自动化重训流水线 (FR-001, FR-002, FR-005, FR-006, 宪法XI)

串联: 队列检查 → 季度预算检查 → 重训 → 132日回测 → 效果对比 → 评审触发

Phase 2 (T009-T011, 2026-10-24):
- run_backtest_comparison()  132日回测前后对照 (FR-005)
- trigger_review() / check_review_timeout()  评审触发 + 72h 超时
- atomic_weight_switch()  原子切换 (归档 + 升级 + metadata + 回滚)

CLI:
    python scripts/dl_retrain_pipeline.py --trigger {cron|ic_flip|ic_decay|manual} [--dry-run]
    python scripts/dl_retrain_pipeline.py --trigger cron --check-timeout   # 仅 72h 超时检查

宪法 VII 合规: 显式异常类型，无裸 except。
宪法 V: 数据不出本机（所有产出写 data/）。
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"

RETRAIN_QUEUE_FILE = DATA_DIR / "retrain_queue.json"
QUARTER_COUNT_FILE = DATA_DIR / "quarter_retrain_count.json"
WEIGHT_STATUS_FILE = DATA_DIR / "weight_status.json"
REPORT_FILE = DATA_DIR / "dl_retrain_report.json"
MESSAGE_QUEUE_FILE = DATA_DIR / "message_queue.json"


def _load_json(path: Path, default):
    """安全读取 JSON，缺失/损坏返回 default"""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [WARN] JSON 读取失败 {path.name}: {exc}")
        return default


def _save_json(path: Path, data) -> None:
    """原子写入 JSON (tmp + os.replace 跨平台原子覆盖)

    P0修复 (2026-10-24 T009): 原实现用 Path.rename 覆盖已存在文件,
    Windows 上 WinError 183 (当文件已存在时无法创建) — 生产每日写
    message_queue/weight metadata 必踩。os.replace = POSIX rename 语义。

    P2 (c16f8feb 补全): 崩溃残留 — 进程在 tmp 写完后 os.replace 前被杀
    (断电/OOM) 会残留 <name>.json.tmp; 清理钩子 = main() 启动时
    _cleanup_stale_json_tmp() 扫 DATA_DIR 下 >24h 的陈旧 tmp。
    """
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _cleanup_stale_json_tmp(max_age_hours: int = 24) -> int:
    """P2 (c16f8feb 补全): 清理 _save_json 崩溃残留的 *.json.tmp

    扫描 DATA_DIR 顶层 + MODELS_DIR (metadata 写入点 L608/L622) 下
    >max_age_hours 的陈旧件 (并行在跑任务的 fresh tmp 不动, 其 os.replace
    成功后 tmp 自然消失)。Returns: 清理件数。
    """
    import time
    now = time.time()
    removed = 0
    for base_dir in (DATA_DIR, MODELS_DIR):
        if not base_dir.is_dir():
            continue
        for tmp in base_dir.glob("*.json.tmp"):
            try:
                if now - tmp.stat().st_mtime > max_age_hours * 3600:
                    tmp.unlink()
                    removed += 1
            except OSError:
                continue
    if removed:
        print(f"  [cleanup] 清除 {removed} 个陈旧 *.json.tmp 残留 (> {max_age_hours}h)")
    return removed


def alert(severity: str, message: str) -> None:
    """写告警到 message_queue.json"""
    queue: list = _load_json(MESSAGE_QUEUE_FILE, [])
    ts = datetime.now(timezone(timedelta(hours=8))).isoformat()
    queue.append({"ts": ts, "severity": severity, "source": "dl_retrain_pipeline", "message": message})
    _save_json(MESSAGE_QUEUE_FILE, queue)


def check_quarter_budget(trigger: str) -> tuple[bool, dict]:
    """检查季度触发预算（FR-006）

    Returns: (allowed: bool, count_data: dict)
    """
    count = _load_json(QUARTER_COUNT_FILE, {})
    current_quarter = _current_quarter()

    # 季度重置
    if count.get("quarter") != current_quarter:
        count = {
            "quarter": current_quarter,
            "manual_count": 0,
            "ic_count": 0,
            "total_count": 0,
            "limit": 1,
        }

    limit = count.get("limit", 1)
    total = count.get("total_count", 0)

    if total >= limit:
        return False, count

    # 预扣（不立即写入，由主流程决定是否真正消耗）
    return True, count


def _current_quarter() -> str:
    """返回当前季度标识 如 2026-Q4"""
    now = datetime.now()
    quarter = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{quarter}"


def check_retrain_queue() -> list[dict]:
    """读取重训队列中的 pending 任务"""
    queue_data = _load_json(RETRAIN_QUEUE_FILE, {"tasks": [], "updated_at": None})
    tasks = queue_data.get("tasks", [])
    return [t for t in tasks if t.get("status") == "pending"]


def check_weight_status() -> dict:
    """读取权重状态"""
    return _load_json(WEIGHT_STATUS_FILE, {"total_weights": 0, "weights": []})


def queue_retrain_task(trigger: str, data_window: str = "") -> None:
    """入队一个重训任务"""
    queue_data = _load_json(RETRAIN_QUEUE_FILE, {"tasks": [], "updated_at": None})
    task_id = f"rt_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    queue_data["tasks"].append({
        "task_id": task_id,
        "trigger_source": trigger,
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "data_window": data_window,
        "status": "pending",
    })
    queue_data["updated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    _save_json(RETRAIN_QUEUE_FILE, queue_data)
    print(f"  入队: {task_id} trigger={trigger}")


def run_retrain_dry_run() -> dict:
    """模拟重训流程（不实际执行 train_dl_model.py）"""
    print("  [DRY-RUN] 模拟重训流程...")
    return {
        "retrain_executed": False,
        "new_weight_path": None,
        "report_generated": False,
    }


# ══════════════════════════════════════════════════════════
#  Phase 2: T009-T011 (132日回测对照 + 评审触发 + 原子切换)
# ══════════════════════════════════════════════════════════
# 口径说明 (R0 只读约束):
#  - 回测引擎 backtest/backtest_rotation.py 只读调用 (import 公开函数), 不改引擎文件。
#  - 132日窗口通过运行时 patch 引擎模块属性 BACKTEST_START/END 实现 (函数退出时还原),
#    引擎文件零修改。
#  - DL 融合口径 = 实验口径 factor*0.8 + dl_score*0.2 (0.20 取自 factors/dl_stock_predictor.py
#    L59 numpy 模块常量, 非实盘 import 路径)。对比时因子部分恒定、差异全部来自 DL 权重。
#    ⚠️ R0 打回 A9 更正 (c16f8feb 补全, 2026-10-24): 本口径 ≠ 实盘口径 —
#    实盘路径 = core/pipeline/integrated_picker.py L81 从 factors.dl_stock_predictor_torch
#    取 DL_WEIGHT=0.10 (torch L50 保守起步); 当前 repo .venv 无 torch → L84 except →
#    _HAS_DL=False → L709/L717/L733 全关 → 当前实盘 DL 贡献 = 0%; 若实盘 venv 装 torch
#    → 实盘 = 0.10 + L733-739 dl_bonus。本对照为受控实验, 报告 JSON dl_fusion.note
#    字段如实溯源, 不再宣称"实盘同参"。
#  - TOP1命中率口径 (spec 澄清): 132日回测 TOP1 持仓序列(=rotation trades) 的胜率
#    (退出口径 pnl>0 占比), 与引擎 summarize().win_rate 同源。

DL_FUSE_FACTOR_WEIGHT = 0.80   # 因子分占比 (实验口径 0.8/0.2, 两项勿单改)
DL_FUSE_DL_WEIGHT = 0.20       # DL分占比 (实验口径: 取自 factors/dl_stock_predictor.py L59 常量,
                               #  非实盘参数 — 实盘 torch-gated: 无torch=0%, 有torch=0.10(torch L50)+L733 bonus)
REVIEW_TIMEOUT_HOURS = 72      # 三方评审超时 (spec Edge Case)
OLD_WEIGHT_CANONICAL = MODELS_DIR / "dl_predictor.pkl"


def enforce_quarter_budget(trigger: str) -> tuple[bool, dict]:
    """Step2 可测化封装: 预算检查 + 超限 P1 告警 (供 main 与测试共用)

    Returns: (allowed, count_data)。超限时发 P1 告警并返回 False, 计数文件不改动。
    """
    allowed, count = check_quarter_budget(trigger)
    if not allowed:
        alert("P1", f"季度重训预算已耗尽 ({count.get('quarter')}: {count.get('total_count')}/"
                    f"{count.get('limit')})，阻断 {trigger} 触发")
    return allowed, count


# ── T009: 132日回测前后对照 ──────────────────────────────

def _load_engine_bundle(trading_days: int = 132) -> dict:
    """引擎数据准备 (镜像 backtest_rotation.main() Step1/1.5, 引擎文件零修改)。

    两次回测 (旧/新权重) 共享同一份数据 + 同一 132 日窗口 = 对照组口径。
    需要 TDX 扩展数据在本机, 生产 cron 环境可运行; 测试中整体 mock 掉。
    """
    import backtest as BT
    import backtest.backtest_rotation as br
    from backtest.backtest_fast_inds import fast_compute_all, build_sorted_index
    from datetime import date as _date

    all_stocks = BT.collect_all_stocks()
    cache = BT.load_name_cache()
    stocks_data: dict = {}
    for code, _mkt in sorted(all_stocks.items()):
        if BT.is_st_stock(cache.get(code, "")):
            continue
        tdx_records = BT.get_tdx_data(code, 3000) or []
        ext_records = BT.get_extended_data(code) or []
        if ext_records:
            ext_dates = {r["date"] for r in ext_records}
            records = [r for r in tdx_records if r["date"] not in ext_dates] + ext_records
            records.sort(key=lambda r: r["date"])
        else:
            records = tdx_records
        records = [r for r in records
                   if (r["date"] if isinstance(r["date"], _date)
                       else _date.fromisoformat(str(r["date"]))) >= _date(2020, 3, 2)]
        if len(records) >= 30:
            stocks_data[code] = records

    sh_records = BT._load_sh_index_records(0)
    dates = [r["date"] if isinstance(r["date"], _date) else _date.fromisoformat(str(r["date"]))
             for r in sh_records]
    if len(dates) < trading_days:
        raise RuntimeError(f"训练数据不足: 指数交易日 {len(dates)} < {trading_days}, 跳过重训 (P1)")
    window_start, window_end = dates[-trading_days], dates[-1]

    # 132日窗口 = 运行时 patch 引擎模块属性
    # 窗口 patch/restore 在本函数 try/finally 内闭环，避免异常路径污染同进程引擎状态
    _orig_start, _orig_end = br.BACKTEST_START, br.BACKTEST_END
    try:
        br.BACKTEST_START, br.BACKTEST_END = window_start, window_end

        # 指标预计算 (与 main() 同序: 只算窗口内扫描日截面)
        _keep = [d for d in dates if window_start <= d <= window_end]
        keep_dates = set(str(_keep[i]) for i in range(0, len(_keep), br.SCAN_STEP))
        inds_cache: dict = {}
        for code, records in sorted(stocks_data.items()):
            result = fast_compute_all(records, keep_dates=keep_dates, code=code)
            if result:
                inds_cache[code] = result
        sorted_codes, all_dates = build_sorted_index(inds_cache)
    finally:
        br.BACKTEST_START, br.BACKTEST_END = _orig_start, _orig_end

    return {
        "br": br, "BT": BT,
        "stocks_data": stocks_data, "cache": cache, "sh_records": sh_records,
        "inds_cache": inds_cache, "all_dates": all_dates, "sorted_codes": sorted_codes,
        "window": (window_start, window_end), "orig_window": (_orig_start, _orig_end),
        "strategy": br.STRATEGY,
    }


def _make_dl_scorer(bundle: dict, engine):
    """DL 融合评分器 (实验口径 0.8/0.2, 非实盘参数 — A9 更正), 作为引擎 pick_candidates 的 score_fn 注入。

    score_fn 签名 = 引擎契约: (code, inds, weekly, cross_rank, market_state) -> (score, _)。
    异常策略 (宪法 VII): 显式 except + 首响大声 + 每500次汇报 (与引擎 L575-585 先例同模式),
    非静默吞掉。因子分支与 DL 分支独立计数 (c16f8feb 补全): 共享计数器会导致
    首响标签错位 (另一分支先失败时本分支"首次"被吞) + 审计字段 dl_score_fail_count 被污染。
    Returns: (score_fn, fail_state) — fail_state 为审计计数 {"fail": DL分支 N, "factor_fail": 因子分支 M}。
    """
    br = bundle["br"]
    from core.pipeline.tdx_core import score_stock as _factor_score
    stocks_data = bundle["stocks_data"]
    state = {"fail": 0, "factor_fail": 0}

    def score_fn(code, inds, weekly, cr, ms):
        try:
            sc, _, _ = _factor_score(inds, weekly, strategy=bundle["strategy"],
                                     cross_rank=cr, market_state=ms)
        except Exception as _exc_factor:
            state["factor_fail"] += 1
            if state["factor_fail"] == 1:
                print(f"⚠️⚠️ 因子评分首次异常 ({code}): {_exc_factor!r} — 归零, 后续同类只计数", flush=True)
            elif state["factor_fail"] % 500 == 0:
                print(f"⚠️ 因子评分异常累计 {state['factor_fail']} 次 — 因子分部分不可信, 请排查!", flush=True)
            sc = 0.0  # 引擎默认分支同行为 (backtest_rotation L580-586 先例: 评分异常归零)
        dl = 0.0
        recs = stocks_data.get(code) or []
        if recs:
            try:
                pred, conf = engine.predict_single_stock(recs[-80:])
                if pred is not None:
                    dl = max(min(float(pred), 0.08), -0.08) * float(conf)
            except Exception as exc:
                state["fail"] += 1
                if state["fail"] == 1:
                    print(f"⚠️⚠️ DL评分首次异常 ({code}): {exc!r} — 后续同类只计数", flush=True)
                elif state["fail"] % 500 == 0:
                    print(f"⚠️ DL评分异常累计 {state['fail']} 次 — 结果不可信, 请排查!", flush=True)
        return sc * DL_FUSE_FACTOR_WEIGHT + dl * DL_FUSE_DL_WEIGHT, {}

    return score_fn, state


def _run_engine_for_weight(weight_path: Path, bundle: dict) -> dict:
    """T009 单权重 132日轮动回测 → 三项指标。

    实盘主候选配置 S3 (引擎 main() L1314: 止损10% + TREND_TP_LADDER['up'] + 持有120d),
    唯一变量 = DL 权重 (score_fn 注入), 因子/撮合/过滤全部同引擎同参。
    """
    from factors.dl_stock_predictor import DLPredictionEngine
    br = bundle["br"]

    weight_path = Path(weight_path)
    engine = DLPredictionEngine(model_path=str(weight_path))
    if not engine.is_model_ready():
        raise RuntimeError(f"DL 权重不可加载: {weight_path} (is_model_ready=False), 回测中止")

    cfg = br.RotationConfig(
        "DL-132d-对照", stop_pct=0.10,
        trailing={"ladder": br.TREND_TP_LADDER["up"]},
        max_hold_days=120, chase_ban_pct=br.CHASE_BAN_PCT, min_score=-100)
    scorer, fail_state = _make_dl_scorer(bundle, engine)
    trades, eq = br.simulate_rotation(
        bundle["stocks_data"], bundle["cache"], bundle["sh_records"], cfg,
        score_fn=scorer, inds_cache=bundle["inds_cache"],
        all_dates=bundle["all_dates"], sorted_codes=bundle["sorted_codes"])
    s = br.summarize(trades, eq, cfg)

    # TOP1命中率 = TOP1持仓序列胜率 (退出口径, 与 summarize().win_rate 同源)
    return {
        "top1_hit_rate": s.get("win_rate", 0.0),
        "annualized_return": s.get("annual_pct", 0.0),
        "max_drawdown": s.get("max_drawdown_pct", 0.0),
        "trades": s.get("trades", 0),
        "dl_score_fail_count": fail_state["fail"],
        "factor_score_fail_count": fail_state["factor_fail"],
    }


def _engine_git_commit() -> str:
    """准则7: 回测数字必须可溯源到引擎 commit"""
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        return f"unknown(rc={r.returncode}:{(r.stderr or '').strip()[:80]})"
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unknown({type(exc).__name__}:{exc})"


def run_backtest_comparison(old_weight: Path, new_weight: Path,
                            report_path: Optional[Path] = None, trading_days: int = 132) -> dict:
    """T009: 旧/新权重 132日回测前后对照 (FR-005)

    判据 (spec 澄清): 新命中率 ≥ 旧命中率 且 (新回撤 − 旧回撤) ≤ 2pp → verdict=pass。
    结果写 data/dl_retrain_report.json (tmp+rename 原子写)。
    """
    old_w, new_w = Path(old_weight), Path(new_weight)
    report_path = Path(report_path) if report_path else REPORT_FILE
    for p, label in ((old_w, "旧权重"), (new_w, "新权重")):
        if not p.exists():
            raise FileNotFoundError(f"{label}文件不存在: {p}")

    print(f"  Step5: 132日回测对照 {old_w.name} vs {new_w.name} ...")
    bundle = _load_engine_bundle(trading_days)
    br = bundle["br"]
    try:
        old_metrics = _run_engine_for_weight(old_w, bundle)
        new_metrics = _run_engine_for_weight(new_w, bundle)
    finally:
        # 还原引擎窗口属性 (只读约束: 不污染引擎模块状态)
        br.BACKTEST_START, br.BACKTEST_END = bundle["orig_window"]

    dd_delta = round(new_metrics["max_drawdown"] - old_metrics["max_drawdown"], 2)
    # [P1/A10] 零成交守卫: trades=0 → insufficient_data, 不触发评审/切换, 发 P1 告警
    if old_metrics["trades"] == 0 or new_metrics["trades"] == 0:
        alert("P1", f"回测零成交守卫触发: old_trades={old_metrics['trades']}, "
              f"new_trades={new_metrics['trades']} — 判定 insufficient_data, 中止")
        verdict = "insufficient_data"
        status = "aborted"
    else:
        verdict = "pass" if (new_metrics["top1_hit_rate"] >= old_metrics["top1_hit_rate"]
                             and dd_delta <= 2.0) else "fail"
        status = "pending_review" if verdict == "pass" else "rejected"

    ts = datetime.now(timezone(timedelta(hours=8))).isoformat()
    report = {
        "created_at": ts,
        "engine_file": "backtest/backtest_rotation.py (只读调用)",
        "engine_commit": _engine_git_commit(),
        "window": {"start": str(bundle["window"][0]), "end": str(bundle["window"][1]),
                   "trading_days": trading_days},
        "old_weight": str(old_w), "new_weight": str(new_w),
        "old_metrics": old_metrics, "new_metrics": new_metrics,
        "criterion": {"top1": "new>=old", "drawdown": f"new-old<=2.0pp (实测 {dd_delta:+.2f}pp)"},
        "dl_fusion": {
            "factor_weight": DL_FUSE_FACTOR_WEIGHT, "dl_weight": DL_FUSE_DL_WEIGHT,
            # 实验口径: DL_WEIGHT=0.20 为对照测试设定，非实盘参数。
            # 实盘路径: integrated_picker L81 从 torch 模块取 DL_WEIGHT=0.10 (factors/dl_stock_predictor_torch.py L50);
            # repo .venv 无 torch → _HAS_DL=False → 当前实盘 DL 贡献 = 0%。
            "note": "实验口径(对照测试), 非实盘参数; 实盘 torch-gated: 无torch=0%, 有torch=0.10+L733bonus"
        },
        # [R1/A11] 前视偏差披露: DL 评分器 recs[-80:] 锚数据截止日, 每扫描日含该日后数据,
        # 绝对指标(win_rate/annual_pct/dd)被污染; 仅相对判据(new>=old/回撤Δ)可作门禁, 绝对值不做引用。
        "dl_lookahead": True,
        "criterion_note": "仅相对判据(new≥old 命中率 & 回撤Δ≤2pp)可作门禁; 绝对指标受前视偏差污染, 不做引用",
        "verdict": verdict,
        "status": "aborted" if verdict == "insufficient_data" else ("pending_review" if verdict == "pass" else "rejected"),
    }
    _save_json(report_path, report)
    print(f"  Step6: verdict={verdict} (命中率 {old_metrics['top1_hit_rate']}→"
          f"{new_metrics['top1_hit_rate']}%, 回撤Δ {dd_delta:+.2f}pp) → {report_path.name}")
    if verdict == "insufficient_data":
        print("  ⚠️  零成交守卫触发: 判定 insufficient_data, 中止切换流程 (P1 告警已发)")
    return report


# ── T010: 评审触发 + 72h 超时 ─────────────────────────────

def _build_review_body(report: dict, report_path: Path) -> str:
    """kanban 评审卡 body: 报告路径 + 指标对比表"""
    om, nm = report.get("old_metrics", {}), report.get("new_metrics", {})
    lines = [
        "## 003-pretraining-automation: DL 重训效果评审 (R0)",
        "",
        f"- 报告: `{report_path}`",
        f"- 引擎: {report.get('engine_file')} @ {report.get('engine_commit')}",
        f"- 窗口: {report.get('window')}",
        f"- 旧权重: `{report.get('old_weight')}` / 新权重: `{report.get('new_weight')}`",
        f"- verdict (自动判据): **{report.get('verdict')}**",
        "",
        "| 指标 | 旧 | 新 | Δ |",
        "|------|----|----|----|",
        f"| TOP1命中率% | {om.get('top1_hit_rate')} | {nm.get('top1_hit_rate')} | "
        f"{round(float(nm.get('top1_hit_rate', 0)) - float(om.get('top1_hit_rate', 0)), 1)} |",
        f"| 年化收益% | {om.get('annualized_return')} | {nm.get('annualized_return')} | "
        f"{round(float(nm.get('annualized_return', 0)) - float(om.get('annualized_return', 0)), 2)} |",
        f"| 最大回撤% | {om.get('max_drawdown')} | {nm.get('max_drawdown')} | "
        f"{round(float(nm.get('max_drawdown', 0)) - float(om.get('max_drawdown', 0)), 2)} |",
        "",
        "判据: 新命中率≥旧 且 回撤Δ≤2pp → 请 atomcode 独立评审 (R0: 权重文件操作+回测引擎调用)。",
        "评审通过 → 执行 `scripts/dl_retrain_pipeline.py` 原子切换 (T011); 不通过 → 旧权重继续服役。",
    ]
    return "\n".join(lines)


def _kanban_create_review_card(body: str, assignee: str = "laowu") -> str:
    """创建 kanban 评审卡 (hook: 测试可 mock; 默认走 hermes CLI, --body-file 防换行丢失)"""
    import re
    import subprocess
    body_file = DATA_DIR / "review_card_body.tmp.md"
    body_file.parent.mkdir(parents=True, exist_ok=True)
    body_file.write_text(body, encoding="utf-8")
    cmd = ["hermes", "kanban", "create",
           "[003·R0] DL重训评审: 132日回测对照通过, 请atomcode独立评审签字",
           "--body-file", str(body_file), "--assignee", assignee, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(PROJECT_ROOT))
    if r.returncode != 0:
        raise RuntimeError(f"kanban 评审卡创建失败 rc={r.returncode}: "
                           f"{(r.stderr or r.stdout or '').strip()[:300]}")
    m = re.search(r'"id"\s*:\s*"(t_[0-9a-f]+)"', r.stdout) or re.search(r"\b(t_[0-9a-f]{8,})\b", r.stdout)
    if not m:
        raise RuntimeError(f"kanban 创建成功但未解析到任务ID: {r.stdout[:200]}")
    return m.group(1)


def _mark_queue_task_rejected() -> None:
    """verdict=fail: 重训队列最近一个 pending 任务标 rejected (旧权重继续服役)"""
    queue = _load_json(RETRAIN_QUEUE_FILE, {"tasks": [], "updated_at": None})
    tasks = queue.get("tasks", [])
    pending = [t for t in tasks if t.get("status") == "pending"]
    if not pending:
        print("  [note] 重训队列无 pending 任务, 跳过 rejected 标记")
        return
    target = pending[-1]
    target["status"] = "rejected"
    queue["updated_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
    _save_json(RETRAIN_QUEUE_FILE, queue)
    print(f"  队列任务 {target.get('task_id')} → rejected")


def trigger_review(verdict: str, report_path: Optional[Path] = None) -> dict:
    """T010: 评审触发 (Step7)

    pass → 创建 kanban 评审卡 (指派 laowu), 报告 status=pending_review。
    fail → 报告 status=rejected + 队列标 rejected + P2 告警 (旧权重继续)。
    insufficient_data (A10 零成交守卫) → 短路: P1 告警已在守卫侧发出,
    不创建评审卡 / 不切换 / 不标队列 / 不覆盖 status=aborted。
    72h 超时检测见 check_review_timeout()。
    """
    report_path = Path(report_path) if report_path else REPORT_FILE
    report = _load_json(report_path, None)
    if not isinstance(report, dict):
        raise FileNotFoundError(f"报告不存在: {report_path} (先执行 run_backtest_comparison)")

    if verdict == "insufficient_data":
        # A10 零成交守卫 (c16f8feb 补全): 对比结果无效, 维持守卫侧已写的 status=aborted,
        # 不落入 fail 分支 (rejected 覆盖 + 队列标 rejected + P2 "未达标" 误导)
        print("  Step7: [SKIP] verdict=insufficient_data (零成交守卫), 不创建评审卡, 不切换, 请排查数据/引擎")
        return {"status": report.get("status", "aborted")}

    if verdict == "pass":
        task_id = _kanban_create_review_card(_build_review_body(report, report_path))
        report["status"] = "pending_review"
        report["review_task_id"] = task_id
        _save_json(report_path, report)
        print(f"  Step7: 评审卡已创建 {task_id} → 指派 laowu")
        return {"status": "pending_review", "review_task_id": task_id}

    report["status"] = "rejected"
    _save_json(report_path, report)
    _mark_queue_task_rejected()
    alert("P2", f"重训效果对比未达标 (verdict=fail): 旧权重 {report.get('old_weight')} 继续服役, "
                 f"新权重 {report.get('new_weight')} 未部署, 保留在临时路径待评审补做")
    return {"status": "rejected"}


def check_review_timeout(report_path: Optional[Path] = None, now: Optional[datetime] = None) -> bool:
    """T010: 72h 评审超时检测 (spec Edge Case)

    report.status=pending_review 且距 created_at > 72h → 旧权重 metadata status 改
    "extended" (自动续期, 不强制切换) + P2 提醒; 报告 status 同步改 extended。
    Returns: 是否发生了超时续期。
    """
    report_path = Path(report_path) if report_path else REPORT_FILE
    report = _load_json(report_path, None)
    if not isinstance(report, dict) or report.get("status") != "pending_review":
        return False
    created_at = report.get("created_at")
    if not created_at:
        raise ValueError(f"报告 {report_path.name} 缺 created_at, 无法计算 72h 超时")
    created = datetime.fromisoformat(created_at)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone(timedelta(hours=8)))
    now = now or datetime.now(timezone(timedelta(hours=8)))
    if (now - created).total_seconds() <= REVIEW_TIMEOUT_HOURS * 3600:
        return False

    old_w = Path(report.get("old_weight", str(OLD_WEIGHT_CANONICAL)))
    meta_path = old_w.with_suffix(old_w.suffix + ".metadata.json")
    meta = _load_json(meta_path, None) or {"file": old_w.name}
    meta["status"] = "extended"
    meta["checked_at"] = now.isoformat()
    _save_json(meta_path, meta)
    report["status"] = "extended"
    _save_json(report_path, report)
    alert("P2", f"三方评审 72h 超时 ({REVIEW_TIMEOUT_HOURS}h): 旧权重 {old_w.name} 自动续期 "
                 f"(status=extended), 新权重保留待评审补做")
    print(f"  72h超时: 旧权重 {old_w.name} → extended")
    return True


# ── T011: 原子切换 ─────────────────────────────────────────

def _atomic_write_json(path: Path, data) -> None:
    _save_json(path, data)


def atomic_weight_switch(new_weight: Path, old_weight: Optional[Path] = None) -> dict:
    """T011: 评审通过后原子切换权重 (tmp+rename 模式)

    1) 旧权重 → dl_predictor_archive_YYYYMMDD.pkl (归档; 同日多次加序号)
    2) 新权重 → 规范名 (旧权重路径, 通常 models/dl_predictor.pkl)
    3) metadata.json (权重旁 .pkl.metadata.json): trained_at=今天, status=valid
    任一步失败 → 回滚 (新权重恢复临时名, 旧权重不动/恢复), 抛 RuntimeError。
    """
    new_w = Path(new_weight)
    old_w = Path(old_weight) if old_weight else OLD_WEIGHT_CANONICAL
    if not new_w.exists():
        raise FileNotFoundError(f"新权重不存在: {new_w}")
    if not old_w.exists():
        raise FileNotFoundError(f"旧权重缺失, 拒绝切换: {old_w}")

    date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    archive = old_w.parent / f"{old_w.stem}_archive_{date_str}.pkl"
    n = 1
    while archive.exists():
        archive = old_w.parent / f"{old_w.stem}_archive_{date_str}_{n:02d}.pkl"
        n += 1

    meta_path = old_w.with_suffix(old_w.suffix + ".metadata.json")
    new_meta_path = new_w.with_suffix(new_w.suffix + ".metadata.json")
    promoted = False
    old_meta_moved = False
    try:
        old_w.rename(archive)
        new_w.rename(old_w)
        promoted = True
        # metadata 血缘: 旧权重 metadata → 跟随归档件 (weight_lifecycle_check 已排除归档扫描);
        # 新权重 metadata → 其字段并入规范 metadata 后删除 (防孤儿文件)
        old_meta_raw = _load_json(meta_path, None)
        if old_meta_raw is not None:
            _save_json(archive.with_suffix(archive.suffix + ".metadata.json"), old_meta_raw)
            meta_path.unlink()
            old_meta_moved = True
        prev_meta = _load_json(new_meta_path, None)
        meta = {
            "trained_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "data_window": (prev_meta or {}).get("data_window"),
            "ic_baseline": (prev_meta or {}).get("ic_baseline"),
            "status": "valid",
            "model_type": "dl_predictor",
            "switched_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "source_weight": new_w.name,
            "archived_as": archive.name,
        }
        _atomic_write_json(meta_path, meta)
        if new_meta_path.exists():
            new_meta_path.unlink()
            print(f"  [note] 新权重自带 metadata 已并入 {meta_path.name}, 临时 metadata 移除")
    except Exception as exc:
        # 回滚: 已升级 → 逐级还原 (含 metadata); 只归档 → 还原旧权重 (新权重仍在临时名)
        try:
            if promoted:
                old_w.rename(new_w)
                archive.rename(old_w)
                if old_meta_moved:
                    arch_meta = archive.with_suffix(archive.suffix + ".metadata.json")
                    if arch_meta.exists() and not meta_path.exists():
                        arch_meta.rename(meta_path)
            elif archive.exists():
                archive.rename(old_w)
        except OSError as rb_exc:
            raise RuntimeError(f"原子切换失败且回滚失败: {exc}; 回滚: {rb_exc}") from exc
        raise RuntimeError(f"原子切换失败已回滚 (旧权重不变): {exc}") from exc

    print(f"  原子切换完成: {new_w.name} → {old_w.name}; 旧权重归档 {archive.name}")
    return {"archived": str(archive), "active": str(old_w), "meta": str(meta_path)}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="DL 预训练自动化重训流水线")
    parser.add_argument("--trigger", required=True,
                        choices=["cron", "ic_flip", "ic_decay", "manual"],
                        help="触发源")
    parser.add_argument("--dry-run", action="store_true", help="模拟执行，不实际重训")
    parser.add_argument("--check-timeout", action="store_true",
                        help="仅执行 72h 评审超时检查后退出 (cron 每日轻量检查用)")
    args = parser.parse_args()

    ts = datetime.now(timezone(timedelta(hours=8))).isoformat()
    print(f"[dl_retrain_pipeline] {ts} trigger={args.trigger}")

    _cleanup_stale_json_tmp()  # P2 (c16f8feb 补全): _save_json 崩溃残留 *.json.tmp 清理

    if args.check_timeout:
        extended = check_review_timeout()
        print(f"  72h超时检查: {'已续期(extended)' if extended else '未超时/无待评审'}")
        return 0

    # Step 1: 检查队列
    pending = check_retrain_queue()
    print(f"  Step1: 队列 pending={len(pending)}")

    # Step 2: 检查季度预算 (T012 可测化: 超限 P1 阻断)
    allowed, count = enforce_quarter_budget(args.trigger)
    print(f"  Step2: 季度预算 total={count.get('total_count', 0)}/{count.get('limit', 1)} → {'OK' if allowed else 'BLOCKED'}")

    if not allowed:
        print("  ⛔ 预算超限，P1 告警已发出")
        return 1

    # Step 3: 检查权重状态
    weight_status = check_weight_status()
    needs_retrain = any(
        w.get("status") in ("needs_retrain", "no_metadata")
        for w in weight_status.get("weights", [])
    )
    ic_trigger = args.trigger in ("ic_flip", "ic_decay")
    should_proceed = needs_retrain or ic_trigger or len(pending) > 0
    print(f"  Step3: 权重需要重训={needs_retrain}, IC触发={ic_trigger}, 队列有任务={len(pending)>0} → {'继续' if should_proceed else '跳过'}")

    if not should_proceed:
        print("  ℹ️ 无需重训，正常退出")
        return 0

    # Step 4: 执行重训（或 dry-run）
    if args.dry_run:
        result = run_retrain_dry_run()
        print(f"  Step4: {result}")
    else:
        print("  Step4: [SKIP] 实际重训需调用 train_dl_model.py")
        result = {"retrain_executed": False, "new_weight_path": None}

    # Step 5-7: Phase 2 (T009-T011) 132日回测对照 → 报告 → 评审触发
    new_weight = result.get("new_weight_path")
    if args.dry_run:
        print("  Step5-7: [DRY-RUN] 跳过回测对照/报告/评审 (未产生新权重)")
    elif new_weight:
        old_weight = OLD_WEIGHT_CANONICAL
        report = run_backtest_comparison(old_weight, Path(new_weight))
        trigger_review(report["verdict"])
    else:
        print("  Step5-7: [SKIP] 无新权重产出 (重训未实际执行), 跳过对照与评审")

    # 消耗预算（仅在实际执行时）
    if not args.dry_run and result.get("retrain_executed"):
        trigger_type = "manual" if args.trigger == "manual" else "ic"
        key = f"{trigger_type}_count"
        count[key] = count.get(key, 0) + 1
        count["total_count"] = count.get("total_count", 0) + 1
        _save_json(QUARTER_COUNT_FILE, count)
        print(f"  预算消耗: {key} +1 → total={count['total_count']}")

    print("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
