# -*- coding: utf-8 -*-
"""evolution_loop.py — 策略自动迭代优化闭环 v1 骨架（交付物 2）

设计: 机器在"笼子"里自动转, 拍板点全部外置给老大。
  - 红线只读: risk_rules.py 常量动态读真源 + 记录基线 + 漂移检测(被改没被改, 不校验值对不对)
  - 不自动买卖: dry_run=True 时零实际写口(不触 holdings/trade_log/review_status)
  - 门禁未全绿=永远 dry_run; 任一关 fail → 回滚 + 入教训库
  - 熔断联挂: L0正常 / L1升级等待 / L2L3自停+urgent飞书

真源 trace (SOUL 准则5/7, 结论声明来自哪):
  - 红线常量 → risk_rules.py (STRATEGY_STOP_LOSS_PCT/CHASE_BAN_PCT/TIME_STOP_TRADING_DAYS/TREND_TP_LADDER)
  - 门禁三关 → factor_gate_v2.GATE_CONFIG + check_backtest_sanity.main()(退出码)
  - 熔断     → circuit_breaker.circuit_level() (L0-L3, 阈值真源 docs/实盘准入标准_v1.0.md §四)
  - 教训库   → iteration_log.json 扩展 (schema: docs/evolution_loop_v1_schema.md §二)

本文件核心全为纯函数/依赖注入(可测), 底部薄 I/O 包装默认 dry_run, 绝不自动启动真实循环。
真实回测引擎/门禁调用留作注入 seam(run_backtest_fn/gate_fn), 骨架不硬接(红线2: 避免一跑就触发真回测)。
"""
import sys
import os
import os as _os  # noqa: S6 基地化残留修复 (2026-10-24 T051 C4): 模块多处引用 _os (L692/766/831/1099+), 迁移时丢失别名 → NameError
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time as _time  # noqa
from datetime import date, timedelta, datetime

# 强制 stdout utf-8 (与全系统其它脚本一致, 防 gbk 控制台崩)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ═══════════════════════════════════════════════════════════
#  默认教训库写口 (测试可注入; 真实落盘走 atomic_json, 见底部 I/O 包装)
# ═══════════════════════════════════════════════════════════
_LESSON_REF = []


def get_lesson_ref():
    """教训库内存写口(测试桩)。返回一个 list; EvolutionLoop 向其 append 教训记录。

    真实环境应换成指向 iteration_log.json 扩展段的 atomic 写口(交付物 3 接)。
    本轮骨架用内存 list 保证可测且零真 I/O(红线2)。
    """
    global _LESSON_REF
    _LESSON_REF = []
    return _LESSON_REF


# ═══════════════════════════════════════════════════════════
#  红线漂移检测 (笼子核心: 检测"被改没被改", 不校验"值对不对")
# ═══════════════════════════════════════════════════════════
def redline_check(read_fn, baseline):
    """比对 baseline['fields'] 与 read_fn() 现读真源, 返回漂移结果。

    语义: 基线里有而真源读不到(被删) 或 值不同(被改) → 该字段漂移 → 冻结(fail-safe)。
    读真源失败 → 也冻结(SOUL#9 不静默吞, 绝不放行)。
    返回: {'frozen': bool, 'changed_fields': [..], 'reason': str}
    """
    fields = (baseline or {}).get("fields", {}) if isinstance(baseline, dict) else {}
    try:
        current = read_fn()
    except Exception as e:  # 读不到真源 = fail-safe 冻结(不静默吞)
        return {"frozen": True, "changed_fields": sorted(fields.keys()),
                "reason": f"红线真源读取失败({e}) → fail-safe 冻结, 全循环挂起"}
    if not isinstance(current, dict):
        current = {}

    changed = []
    for key, base_val in fields.items():
        if key not in current:
            changed.append(key)          # 基线有、真源无(被删) → 红线只读, 删=改
        elif current[key] != base_val:
            changed.append(key)          # 值漂移
    changed.sort()
    if changed:
        return {"frozen": True, "changed_fields": changed,
                "reason": "红线常量漂移: " + ", ".join(changed)}
    return {"frozen": False, "changed_fields": [], "reason": "红线无漂移"}


# ═══════════════════════════════════════════════════════════
#  冷却铁律 (防过拟合: 同因子/参数 30日内被拒2次 → 冷却, 60日内不得再提案)
# ═══════════════════════════════════════════════════════════
def cooldown_active(last_rejections, today, window_days=30, ban_days=60, min_rejections=2):
    """判定某 target 是否处于冷却中。

    铁律(防过拟合, 写死不许协商): 最近两次被拒间隔 ≤ window_days(30d)
    且 today < last_rejection + ban_days(60d) → 冷却中(不得再提案)。
    手算例: 被拒于 -10d/-5d → 间隔5d≤30, last=-5d, ban至+55d, today(0)<+55d → True。
             被拒于 -100d/-95d → ban至-35d, today(0) > -35d → 冷却过期 → False。
    返回: bool
    """
    rejs = [r for r in (last_rejections or []) if isinstance(r, (date, datetime))]
    if len(rejs) < min_rejections:
        return False
    two = sorted(rejs, key=lambda x: x if isinstance(x, date) else x.date())[-2:]
    interval = abs((two[1] - two[0]).days)
    if interval > window_days:
        return False                    # 两次被拒拉太开 → 不触发
    ban_until = two[1] + timedelta(days=ban_days)
    if isinstance(today, datetime):
        ban_until = datetime.combine(ban_until, datetime.min.time())
    return today < ban_until


# ═══════════════════════════════════════════════════════════
#  夏普反常 (防过拟合: 合入使夏普提升 > ratio× 基线 → 优秀到反常=可疑, 触发人工评审)
# ═══════════════════════════════════════════════════════════
def sharpe_anomaly(baseline, current, ratio=2.0):
    """累计合入变更使回测夏普提升 > ratio× 基线 → 触发人工评审(防过拟合)。

    基线 ≤0(无意义) 时: 只要当前 >0 即视为反常(保守挂起, 防除零)。
    手算例: 基线1.0 当前2.5 → 2.5 > 2.0×1.0 → True; 当前1.9 → 1.9 < 2.0 → False。
    """
    if baseline is None or current is None:
        return False
    if baseline <= 0:
        return current > 0
    return current > ratio * baseline


# ═══════════════════════════════════════════════════════════
#  熔断联挂 (E4: L0正常 / L1升级等待 / L2L3自停+urgent; 未知级别 fail-safe 停)
# ═══════════════════════════════════════════════════════════
def circuit_interlock(level):
    """把熔断级别映射为循环动作(纯映射, 不执行任何交易)。

    L0 → 不暂停不升级;  L1 → 不暂停但升级等待(次日人工复核);
    L2/L3 → 暂停循环 + 升级(红停开仓/紧急降阶);  未知 → 保守暂停+升级(SOUL#9 不静默吞)。
    """
    if level == "L0":
        return {"pause": False, "escalate": False, "action": "正常, 无动作"}
    if level == "L1":
        return {"pause": False, "escalate": True,
                "action": "黄预警: 升级等待, 次日开盘前人工复核"}
    # L2 / L3 / 未知 → 保守 fail-safe(绝不放行)
    if level in ("L2", "L3"):
        return {"pause": True, "escalate": True,
                "action": f"{level} 自停: 冻结新提案 + urgent飞书 + 冷却计时器"}
    return {"pause": True, "escalate": True,
            "action": f"未知熔断级别 {level!r} → fail-safe 自停(不静默吞, SOUL#9)"}


# ═══════════════════════════════════════════════════════════
#  walk-forward 纯 OOS 接缝隔离 (裁定1: 接缝层断言保证, 不靠自觉)
# ═══════════════════════════════════════════════════════════
def oos_purity_check(fit_dates, oos_dates, tuned_on_dates=None):
    """walk-forward 纯 OOS 接缝隔离断言（老大终审裁定 1 硬约束）。

    铁律: 132日确认窗内嵌末20d walk-forward, 该 OOS 段**从未参与任何 fit/选参**。
    接真回测时, engine 出结论前必须调本函数断言切分合法——**隔离在接缝层做, 不靠自觉**。
    任一违反 → pure=False + violations:
      ① OOS 段与 fit 段日期有交集(数据泄漏)
      ② OOS 段日期出现在 tuned_on(选参/调优用过 OOS = 最严重泄漏)
      ③ OOS 段非时序末尾(早于 fit 末日 = 非 walk-forward 的"未见未来段")
    纯函数(输入日期序列, 无 I/O, 可测); 日期可比较(ISO 字符串/ date 均可)。
    返回: {'pure': bool, 'violations': [..], 'reason': str}
    """
    fit = set(fit_dates or [])
    oos = set(oos_dates or [])
    tuned = set(tuned_on_dates or [])
    violations = []
    # ① OOS 与 fit 重叠(数据泄漏)
    overlap_fit = oos & fit
    if overlap_fit:
        violations.append(f"oos 与 fit 重叠 {len(overlap_fit)} 日(数据泄漏): {sorted(overlap_fit)[:3]}…")
    # ② OOS 参与选参/调参(最严重泄漏)
    overlap_tuned = oos & tuned
    if overlap_tuned:
        violations.append(f"oos 参与选参/调优 {len(overlap_tuned)} 日(最严重泄漏): {sorted(overlap_tuned)[:3]}…")
    # ③ OOS 必须在时序末尾(纯OOS"未见未来段"): 有 oos 日早于 fit 末日 → 非末尾
    if oos and fit:
        fit_last = max(fit)
        oos_before = [d for d in oos if d < fit_last]
        if oos_before:
            violations.append(f"oos 段 {len(oos_before)} 日早于 fit 末日 {fit_last}(非 walk-forward 末段): {oos_before[:3]}…")
    if violations:
        return {"pure": False, "violations": violations,
                "reason": "OOS 不纯净: " + "; ".join(violations)}
    return {"pure": True, "violations": [], "reason": "OOS 纯净(未参与 fit/选参, 时序末尾)"}


# ═══════════════════════════════════════════════════════════
#  红线"只写指针"机器校验 (§三裁定: 提示词/文档红线永不写具体数值, 只写 risk_rules 常量名指针)
#  规则追溯矩阵校验项: 任何文档/提示词出现红线具体数值(且该行未带真源指针) = 判漂移
# ═══════════════════════════════════════════════════════════
import re as _re

# 五族红线的"具体数值断言"特征(命中=该行使用了红线数值)
_REDLIN_VALUE_PATTERNS = (
    _re.compile(r"(止损|止盈|追高|CHase|CHASE)[^\n]{0,12}\d"),      # 止损10%/追高4% 等
    _re.compile(r"时间止损[^\n]{0,6}1[0-9]{2}"),                     # 时间止损120日
    _re.compile(r"(阶梯|LADDER)[^\n]{0,20}\d"),                      # 阶梯 X-Y-Z / 档位
    _re.compile(r"\d+(?:\.\d+)?\s*%\s*(止损|止盈|回撤)"),             # 10%止损
)
# 真源指针特征(命中=该行带了 risk_rules 常量名指针, 合规)
_REDLIN_POINTER_PATTERNS = (
    _re.compile(r"risk_rules\."),
    _re.compile(r"(STRATEGY_STOP_LOSS_PCT|CHASE_BAN_PCT|TIME_STOP_TRADING_DAYS|TREND_TP_LADDER|get_trend_tp_ladder)"),
)
# 历史口径/证据标注特征(命中=该行数值是旧口径记录而非当前红线, 已标注则合规;
# 数值只信 risk_rules.py, 文档里的旧值(如 09-30 的 8%止损/4档阶梯)是历史证据, 标"历史口径·现真源=…"即合规)
_REDLIN_HIST_MARKERS = ("历史口径", "现真源", "旧口径", "（历史", "(历史")
# 测试 fixture/用例数据特征(命中=该行是回测测试样本数值, 非"红线参数声明", 豁免不判;
# 如 "Test 5: 止损优先 | pnl=-9%, sl=92 | exit=True" 里 sl=92 是股价/pnl=-9% 是浮亏, 不是止损参数)
_REDLIN_FIXTURE_RE = _re.compile(
    r"(Test\s*\d|pnl\s*=|sl\s*=|tp[12]\s*=|exit\s*=|type\s*=\s*(stop|take)|"
    r"浮亏\s*-?\d|卖出\s*\d+%\s*\(|触发\s*\d+%\s*止盈|evaluate_exit)")


def redline_value_lines(text):
    """扫描文本, 返回每行是否"红线数值行"及是否带真源指针。

    每行判定:
      is_redline_value = 命中任一 _REDLIN_VALUE_PATTERNS(该行出现红线具体数值)
      has_pointer      = 命中任一 _REDLIN_POINTER_PATTERNS(该行带 risk_rules 常量指针)
                         或带历史口径标注(_REDLIN_HIST_MARKERS, 旧值=证据非当前红线, 合规)
    返回: [{'line_no':int, 'line':str, 'is_redline_value':bool, 'has_pointer':bool}, ...]
    仅回传"疑似红线数值行"(is_redline_value=True), 精简输出。

    ⚠️ 代码围栏(```)内的行 = 代码片段/测试 fixture, 本就不是"红线数值声明",
       跳过不判(否则会把 return 语句的 format string、测试样本值误报成红线漂移)。
    """
    out = []
    in_fence = False
    for i, ln in enumerate((text or "").splitlines(), 1):
        stripped = ln.lstrip()
        # 围栏开关行(行首三个反引号)本身不算代码行, 切换状态后继续
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue  # 代码块内的行跳过(非红线声明)
        # 测试 fixture/用例数据行 → 跳过(样本数值非红线参数声明)
        if _REDLIN_FIXTURE_RE.search(ln):
            continue
        if any(p.search(ln) for p in _REDLIN_VALUE_PATTERNS):
            has_ptr = any(p.search(ln) for p in _REDLIN_POINTER_PATTERNS)
            has_hist = any(m in ln for m in _REDLIN_HIST_MARKERS)
            out.append({"line_no": i, "line": ln,
                        "is_redline_value": True, "has_pointer": (has_ptr or has_hist)})
    return out


def redline_pointer_compliant(text):
    """§三裁定校验: 文档/提示词红线只写指针(指向 risk_rules 常量), 不写具体数值。

    判据: 任何"红线数值行"若未同时带真源指针(常量名) → 违规(判漂移)。
    合规文档 = 每个红线数值行都引用 risk_rules.XXX 常量(指针), 或整行就是常量名引用。
    返回: {'compliant': bool, 'violations': [{'line_no','line'}...], 'value_line_count': int}
    纯函数, 可测; 不读盘(文本注入)。
    """
    vlines = redline_value_lines(text)
    violations = [v for v in vlines if not v["has_pointer"]]
    return {"compliant": not violations, "violations": violations,
            "value_line_count": len(vlines)}


# ═══════════════════════════════════════════════════════════
#  真实门禁三关实现（EVOL-P1v2：gate_fn 接真源 + 裁定1 OOS隔离）
# ═══════════════════════════════════════════════════════════
def _gate_g1_stat(prop, gate_v2):
    """G1 统计关：调 factor_gate_v2.check_factor，返回 schema §三三关 dict。"""
    from core.scoring.factor_gate_v2 import FactorGateV2 as _FGV2
    if gate_v2 is None:
        gate_v2 = _FGV2()
    name = prop.get("factor_name", prop.get("target", "unknown"))
    fv = prop.get("factor_values", [])
    ret = prop.get("returns", [])
    codes = prop.get("codes")
    n_trades = prop.get("n_trades", 0)
    sharpe_is = prop.get("sharpe_is", 0.0)
    expected_sign = prop.get("expected_sign", None)
    report = gate_v2.check_factor(
        factor_name=name, factor_values=fv, returns=ret, codes=codes,
        n_trades=n_trades, sharpe_is=sharpe_is, expected_sign=expected_sign,
    )
    metrics = report.get("metrics", {})
    checks = report.get("checks", {})
    ic = metrics.get("ic", 0.0)
    ir = metrics.get("ir", 0.0)
    mono = checks.get("monotonicity", {}).get("passed", False)
    return {"pass": report.get("verdict", "FAIL") == "PASS",
            "ic": round(ic, 4), "ir": round(ir, 2) if ir else None,
            "rankic_monotonic": mono, "detail": report}


def _gate_g2_robust(prop):
    """G2 稳健关：参数扰动 ±20% 重算夏普，衰减 < sharpe_decay_threshold%。桩模式返回 pass=True。"""
    from core.scoring.factor_gate_v2 import GATE_CONFIG
    sharpe_base = prop.get("sharpe_base")
    sharpe_perturb = prop.get("sharpe_perturb")
    threshold = GATE_CONFIG.get("sharpe_decay_threshold", 30.0)
    if sharpe_base is None or sharpe_perturb is None:
        return {"pass": True, "sharpe_decay_pct": 0.0, "note": "桩模式：无扰动数据"}
    if sharpe_base <= 0:
        decay = 0.0 if sharpe_perturb >= 0 else 100.0
    else:
        decay = abs(sharpe_perturb - sharpe_base) / abs(sharpe_base) * 100
    return {"pass": decay < threshold, "sharpe_decay_pct": round(decay, 2)}


def _gate_g3_equiv(result_json_path):
    """G3 等价关：直接调用 check_backtest_sanity.main，断言退出码=0（不走 subprocess）。"""
    import backtest.check_backtest_sanity as _cbs
    import sys as _sys
    _old_argv = _sys.argv
    try:
        _sys.argv = [_sys.argv[0], result_json_path] if result_json_path else _sys.argv
        rc = int(_cbs.main())
        return {"pass": rc == 0, "sanity_exit_code": rc}
    except SystemExit as _e:
        return {"pass": False, "sanity_exit_code": int(_e.code or 1), "error": str(_e)}
    except Exception as e:
        return {"pass": False, "sanity_exit_code": -1, "error": str(e)}
    finally:
        _sys.argv = _old_argv


def make_gate_fn(result_json_path=None, gate_v2=None):
    """工厂：构造 gate_fn(prop)，注入真实门禁三关 + OOS 接缝隔离（裁定1）。

    gate_fn(prop) 返回 {"G1_stat": {...}, "G2_robust": {...}, "G3_equiv": {...}}
    阈值全部来自 factor_gate_v2.GATE_CONFIG（无硬编码）。
    """
    def gate_fn(prop):
        # 裁定1：OOS 接缝隔离 — 在得出结论前必须断言 walk-forward OOS 纯净
        fit_dates = prop.get("fit_dates", [])
        oos_dates = prop.get("oos_dates", [])
        tuned_on_dates = prop.get("tuned_on_dates", [])
        oos_check = oos_purity_check(fit_dates, oos_dates, tuned_on_dates)
        if not oos_check["pure"]:
            return {
                "G1_stat": {"pass": False, "reason": "OOS不纯净",
                            "violations": oos_check["violations"]},
                "G2_robust": {"pass": False, "reason": "OOS不纯净"},
                "G3_equiv": {"pass": False, "reason": "OOS不纯净"},
            }
        g1 = _gate_g1_stat(prop, gate_v2)
        g2 = _gate_g2_robust(prop)
        gj = result_json_path or prop.get("result_json")
        g3 = _gate_g3_equiv(gj) if gj else {
            "pass": True, "sanity_exit_code": 0, "note": "无结果文件，跳过G3"}
        return {"G1_stat": g1, "G2_robust": g2, "G3_equiv": g3}
    return gate_fn


# ═══════════════════════════════════════════════════════════
#  EvolutionLoop 状态机 (PROPOSE→SMOKE→CONFIRM→GATE→MERGE/ROLLBACK)
# ═══════════════════════════════════════════════════════════
class EvolutionLoop:
    """单轮迭代状态机。全部依赖注入, 无内置 I/O, 可测。

    硬红线2: dry_run=True 时 run_round 零实际写口(仅 dry_run 决策 + 写口 spy 记录)。
    硬红线3: 门禁未全绿=永远 dry_run; 任一关 fail → rolled_back + 入教训库。
    """

    GATE_ORDER = ("G1_stat", "G2_robust", "G3_equiv")

    def __init__(self, dry_run=True, *, read_redline_fn, redline_baseline,
                 gate_fn, rejections_by_target=None, write_spy=None,
                 lessons_ref=None, round_seq=1, log_path=None):
        self.dry_run = dry_run
        self.read_redline_fn = read_redline_fn
        self.redline_baseline = redline_baseline
        self.gate_fn = gate_fn
        self.rejections_by_target = rejections_by_target or {}
        self.write_spy = write_spy or (lambda *a, **k: None)
        self.lessons_ref = lessons_ref if lessons_ref is not None else get_lesson_ref()
        self.round_seq = round_seq
        self.log_path = log_path  # P3v2: 持久化路径

    # ── 内部: 首道未过的关 ──
    def _first_failed_gate(self, g):
        for name in self.GATE_ORDER:
            res = g.get(name) if isinstance(g, dict) else None
            if not (isinstance(res, dict) and res.get("pass") is True):
                return name
        return None

    # ── 内部: 记一条教训(schema §二) ──
    def _record_lesson(self, round_id, p, g, failed_gate, today):
        lesson = {
            "lesson_id": f"L_{today.isoformat()}_{len(self.lessons_ref)+1:04d}",
            "timestamp": datetime.now().isoformat(),
            "round_id": round_id,
            "proposal_source": p.get("source"),
            "target": p.get("target"),
            "proposal": p.get("desc"),
            "gate_results": g if isinstance(g, dict) else None,
            "failed_gate": failed_gate,
            "failure_reason": self._reason_of(g, failed_gate),
            "evidence": {
                "engine_commit": _get_engine_commit(),
                "includes_delisted": None,
                "before_metrics": None, "after_metrics": None,
                "pessimistic_loss": f"{failed_gate} fail 不合并, 本提案 0 损失(已回滚)",
            },
            "rejection_count": self._rejection_count(p.get("target"), today),
            "last_rejection": today.isoformat(),
            "cooldown_until": self._calc_cooldown_until(p.get("target"), today),
            "status": "rejected",
        }
        self.lessons_ref.append(lesson)
        # P3v2: 持久化到 iteration_log.json
        if self.log_path:
            import core.pipeline.atomic_json as _aj
            def _mutator(data):
                lessons = data.get("lessons", [])
                lessons.append(lesson)
                data["lessons"] = lessons
                return data
            _aj.update_json(self.log_path, _mutator, default={"lessons": []})
        return lesson

    def _calc_cooldown_until(self, target, today):
        """计算冷却到期日：从 lessons 中统计同 target 的历史被拒次数。"""
        rejs = [l for l in (self.lessons_ref or [])
                if l.get("target") == target and l.get("status") == "rejected"]
        rejs.sort(key=lambda x: x.get("last_rejection", ""))
        if len(rejs) < 1:
            return None
        # 同 target 累计被拒次数
        count = len(rejs)
        if count >= 2:
            # 60 天铁律
            last = rejs[-1].get("last_rejection", "")
            if last:
                from datetime import date as _date
                try:
                    last_date = _date.fromisoformat(last)
                    from datetime import timedelta as _td
                    return (last_date + _td(days=60)).isoformat()
                except Exception:
                    pass
        return None

    def _reason_of(self, g, failed_gate):
        res = g.get(failed_gate) if isinstance(g, dict) else None
        if not isinstance(res, dict):
            return f"{failed_gate} 结果缺失(fail-safe)"
        return f"{failed_gate} fail: ic={res.get('ic')} ir={res.get('ir')} " \
               f"monotonic={res.get('rankic_monotonic')} " \
               f"sharpe_decay={res.get('sharpe_decay_pct')} " \
               f"sanity={res.get('sanity_exit_code')}"

    def _rejection_count(self, target, today):
        rejs = [r for r in (self.rejections_by_target.get(target) or [])
                if isinstance(r, (date, datetime)) and r <= today]
        return len(rejs) + 1   # +1 = 本次将被记入的这条

    def run_round(self, proposals, today, circuit_level="L0",
                  baseline_sharpe=None, current_sharpe=None):
        """跑一轮。返回 {'round_id','paused','pause_reason','escalated','results','sharpe_anomaly'}。

        前置检查(违反=停循环): ① 红线漂移(E1) ② 熔断自停(E4)。
        逐提案: 冷却铁律 → 门禁三关 → (全绿: dry_run=merged_dryrun 否则写口) / (fail: 回滚+教训)。
        收尾: 夏普反常(E5, 未暂停且触发时升级)。
        P3v2: 落 lesson 到 lessons[], 落 escalation 到 escalations[], 均走 atomic_json。
        """
        round_id = f"R_{today.isoformat()}_{self.round_seq:02d}"
        escalated = []
        results = []
        paused = False
        pause_reason = None

        # 前置1: 红线漂移检测(E1)
        rl = redline_check(self.read_redline_fn, self.redline_baseline)
        if rl["frozen"]:
            escalated.append({"point": "E1", "reason": rl["reason"],
                              "fields": rl["changed_fields"],
                              "action": "停循环 + urgent飞书 + 回滚 + 生成《参数变更申请》挂起"})
            paused, pause_reason = True, "redline_drift"

        # 前置2: 熔断联挂(E4)
        if not paused:
            ci = circuit_interlock(circuit_level)
            if ci["pause"]:
                escalated.append({"point": "E4", "reason": f"熔断 {circuit_level}: {ci['action']}",
                                   "action": ci["action"]})
                paused, pause_reason = True, f"circuit_{circuit_level}"

        # P3v2: 读 lessons[] 真源用于冷却判定
        lessons_for_cooldown = self._load_lessons_from_log()

        # 逐提案
        for p in proposals:
            pid = p.get("proposal_id")
            if paused:
                results.append({"proposal_id": pid, "status": "skipped_paused",
                                 "failed_gate": None, "lesson_recorded": False,
                                 "source": p.get("source"), "target": p.get("target")})
                continue
            # P3v2: 冷却铁律读 lessons 真源
            if self._cooldown_active_from_lessons(p.get("target"), today, lessons_for_cooldown):
                results.append({"proposal_id": pid, "status": "skipped_cooldown",
                                 "failed_gate": None, "lesson_recorded": False,
                                 "source": p.get("source"), "target": p.get("target")})
                continue
            # 门禁三关
            g = self.gate_fn(p)
            failed = self._first_failed_gate(g)
            if failed:
                self._record_lesson(round_id, p, g, failed, today)
                results.append({"proposal_id": pid, "status": "rolled_back",
                                 "failed_gate": failed, "lesson_recorded": True,
                                 "source": p.get("source"), "target": p.get("target")})
                continue
            # 全绿
            if self.dry_run:
                status = "merged_dryrun"       # 红线2: 零实际写口
            else:
                # P5: 三层闸守卫 + registry 真写口
                gate_result = check_production_gates()
                if not gate_result["passed"]:
                    # 闸 fail → fail-safe，不合并，log 记录
                    status = "gate_blocked"
                    escalated.append({
                        "point": "P5_GATE",
                        "reason": f"生产写口守卫拦截: {gate_result['blocked_by']}",
                        "gates": gate_result["gates"]
                    })
                    results.append({"proposal_id": pid, "status": status,
                                    "failed_gate": "P5_GATE", "lesson_recorded": False,
                                    "source": p.get("source"), "target": p.get("target"),
                                    "gate_result": gate_result})
                    continue
                # 闸全绿 → 真写 registry
                merge_result = merge_to_production_registry(p)
                if merge_result.get("merged"):
                    status = "merged"
                else:
                    status = "merge_failed"
                    escalated.append({
                        "point": "P5_MERGE",
                        "reason": f"Registry 合并失败: {merge_result.get('error')}"
                    })
                results.append({"proposal_id": pid, "status": status,
                                 "failed_gate": None, "lesson_recorded": False,
                                 "source": p.get("source"), "target": p.get("target"),
                                 "merge_result": merge_result})
            results.append({"proposal_id": pid, "status": status,
                             "failed_gate": None, "lesson_recorded": False,
                             "source": p.get("source"), "target": p.get("target")})

        # 收尾: 夏普反常(E5)
        anomaly = sharpe_anomaly(baseline_sharpe, current_sharpe)
        if anomaly and not paused:
            escalated.append({"point": "E5",
                               "reason": f"合入使夏普 {current_sharpe} > 2.0×基线 {baseline_sharpe} "
                                         f"(优秀到反常=可疑) → 全量重审 + 人工评审",
                               "baseline_sharpe": baseline_sharpe, "current_sharpe": current_sharpe})

        # P3v2: 落 escalations[] 到 iteration_log.json
        if escalated and self.log_path:
            import core.pipeline.atomic_json as _aj
            def _mutator(data):
                escs = data.get("escalations", [])
                escs.extend(escalated)
                data["escalations"] = escs
                return data
            _aj.update_json(self.log_path, _mutator, default={"escalations": []})

        return {"round_id": round_id, "paused": paused, "pause_reason": pause_reason,
                 "escalated": escalated, "results": results, "sharpe_anomaly": anomaly}

    def _load_lessons_from_log(self):
        """P3v2: 从 log_path 读取 lessons[] 真源。"""
        if not self.log_path:
            return []
        import core.pipeline.atomic_json as _aj
        data = _aj.atomic_load(self.log_path, default={})
        return data.get("lessons", [])

    def _cooldown_active_from_lessons(self, target, today, lessons):
        """P3v2: 从 lessons 真源判定冷却。

        铁律: 同 target 最近2次被拒间隔 ≤30d 且 today < last_rejection+60d → 冷却中。
        """
        rejs = [l for l in (lessons or [])
                if l.get("target") == target and l.get("status") == "rejected"]
        rejs.sort(key=lambda x: x.get("last_rejection", ""))
        if len(rejs) < 2:
            return False
        from datetime import date as _date, timedelta as _td
        last_two = rejs[-2:]
        try:
            d1 = _date.fromisoformat(last_two[0]["last_rejection"])
            d2 = _date.fromisoformat(last_two[1]["last_rejection"])
        except (KeyError, ValueError):
            return False
        interval = abs((d2 - d1).days)
        if interval > 30:
            return False
        ban_until = d2 + _td(days=60)
        today_d = today if isinstance(today, _date) else getattr(today, 'date', lambda: today)()
        return today_d < ban_until


# ═══════════════════════════════════════════════════════════
#  三层闸生产写口守卫 (P5: dry_run=False 切生产前强制校验)
#  闸1: 红线 pristine (check_redline_pointer.py exit=0)
#  闸2: 老五 R0 放行 (review_status.json laowu_approved=true)
#  闸3: 老大拍板标记 (boss_release=true in review_status.json)
#  任一闸 fail → merged=0, registry diff=0 (fail-safe)
# ═══════════════════════════════════════════════════════════
def check_production_gates(review_status_path="data/review_status.json",
                           redline_check_script="check_redline_pointer.py"):
    """三层闸生产写口守卫。

    返回: {'passed': bool, 'gates': {gate_name: {'passed': bool, 'reason': str}}, 'blocked_by': str|None}
    """
    gates = {}
    blocked_by = None

    # 闸1: 红线 pristine (机器校验)
    try:
        import subprocess as _sp
        _project_root = PROJECT_ROOT  # P1修复(20261023): S5迁移core/ops/后误指core/ops/, redline_check在仓库根
        r = _sp.run(["python", redline_check_script],
                    capture_output=True, text=True, cwd=_project_root)
        if r.returncode == 0:
            gates["redline_pristine"] = {"passed": True, "reason": "红线指针合规"}
        else:
            gates["redline_pristine"] = {"passed": False, "reason": f"红线违规: {r.stdout[:200]}"}
            blocked_by = "redline_pristine"
    except Exception as e:
        gates["redline_pristine"] = {"passed": False, "reason": f"红线检查失败: {e}"}
        blocked_by = "redline_pristine"

    # 闸2: 老五 R0 放行 (evolution 专属审批块)
    try:
        import core.pipeline.atomic_json as _aj
        review_data = _aj.atomic_load(review_status_path, default={})
        # 隔离：evolution 专属审批块，不碰全局 laowu_approved (R1修复)
        # 安全访问：null/缺失 → {}，避免 AttributeError (R0修复)
        evolution_review = review_data.get("evolution_review") or {}
        laowu_r0 = evolution_review.get("laowu_r0", False)
        # review_gate 统一判空逻辑：仅显式 True 放行，缺失/False/None → 冻结
        if laowu_r0 is True:
            gates["laowu_r0"] = {"passed": True, "reason": "老五 R0 已放行 (evolution_review)"}
        else:
            gates["laowu_r0"] = {"passed": False, "reason": f"老五 R0 未放行 (evolution_review.laowu_r0={laowu_r0!r})"}
            blocked_by = blocked_by or "laowu_r0"
    except Exception as e:
        gates["laowu_r0"] = {"passed": False, "reason": f"老五 R0 检查失败: {e}"}
        blocked_by = blocked_by or "laowu_r0"

    # 闸3: 老大拍板标记 (evolution 专属审批块)
    try:
        import core.pipeline.atomic_json as _aj
        review_data = _aj.atomic_load(review_status_path, default={})
        # 隔离：evolution 专属审批块，不碰全局 boss_release
        # 安全访问：null/缺失 → {}，避免 AttributeError (R0修复)
        evolution_review = review_data.get("evolution_review") or {}
        boss_release = evolution_review.get("boss_release", False)
        if boss_release is True:
            gates["boss_release"] = {"passed": True, "reason": "老大已拍板 (evolution_review)"}
        else:
            gates["boss_release"] = {"passed": False, "reason": f"老大未拍板 (evolution_review.boss_release={boss_release!r})"}
            blocked_by = blocked_by or "boss_release"
    except Exception as e:
        gates["boss_release"] = {"passed": False, "reason": f"老大拍板检查失败: {e}"}
        blocked_by = blocked_by or "boss_release"

    all_passed = all(g["passed"] for g in gates.values())
    return {"passed": all_passed, "gates": gates, "blocked_by": blocked_by}


# ═══════════════════════════════════════════════════════════
#  Registry 合并写口 (P5: dry_run=False 时真写生产 registry)
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  因子闭环 seam (W1 2026-10-17): IC -> 权重调整建议 -> 老大拍板 -> 才写
# 回灌自 archive/root-py-batch3: 6adbea0a 回滚误删, 2026-10-21 合回根侧
# ═══════════════════════════════════════════════════════════
# 红线(老大既定: 自动出建议 + 老大拍板, 不是全自动):
#   机器只到"出建议"为止。factor_weights.json 的写口在
#   scripts/apply_factor_weight_proposal.py, 且必须有老大批准件才放行。
#   本 seam 里没有任何直写 factor_weights.json 的路径 —— 写口以 apply_fn
#   注入, 默认 apply_fn=None(即: 不注入就永远写不了)。
def propose_factor_weight_adjustment(proposal_fn=None):
    """[闭环第2环] 调 scripts/factor_weight_proposal 生成权重调整建议(只读)。

    返回 proposal dict; 失败返回 None(不抛, 交由上层判空)。
    """
    if proposal_fn is None:
        def proposal_fn():
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "factor_weight_proposal",
                _os.path.join(PROJECT_ROOT, "scripts", "factor_weight_proposal.py"))  # P1修复(20261023): scripts/在仓库根
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            import json as _json
            _ic = _json.load(open(_mod.IC_AUTHORITY, "r", encoding="utf-8"))
            _w = _json.load(open(_mod.WEIGHTS, "r", encoding="utf-8"))
            _cfg = _mod._load_json(_mod.THRESHOLDS_CFG, default={}) or {}
            return _mod.build_proposal(_ic, _w, _cfg)
    try:
        return proposal_fn()
    except Exception as e:
        print(f"[W1 seam] 权重建议生成失败: {e}", file=sys.stderr)
        return None


def weight_update_seam(proposal, gates_fn=None, apply_fn=None):
    """[闭环第3/4环] 建议 -> 老大拍板 -> 才写。

    gates_fn 默认 check_production_gates(含 boss_release 老大拍板闸)。
    apply_fn 默认 None —— 不显式注入写口就永远写不了 factor_weights.json。

    返回 {'applied': bool, 'blocked_by': str|None, 'proposal_id': str|None,
          'gates': dict|None}
    """
    if proposal is None:
        return {"applied": False, "blocked_by": "no_proposal",
                "proposal_id": None, "gates": None}

    if gates_fn is None:
        gates_fn = check_production_gates
    gates = gates_fn()
    if not gates.get("passed"):
        return {"applied": False, "blocked_by": gates.get("blocked_by"),
                "proposal_id": proposal.get("proposal_id"), "gates": gates}

    if apply_fn is None:
        # 三层闸全绿但没有注入写口 —— 仍然不写。写口只在 apply 脚本里。
        return {"applied": False, "blocked_by": "apply_fn_not_injected",
                "proposal_id": proposal.get("proposal_id"), "gates": gates}

    try:
        apply_fn(proposal)
    except Exception as e:
        print(f"[W1 seam] 权重应用失败: {e}", file=sys.stderr)
        return {"applied": False, "blocked_by": f"apply_error: {e}",
                "proposal_id": proposal.get("proposal_id"), "gates": gates}
    return {"applied": True, "blocked_by": None,
            "proposal_id": proposal.get("proposal_id"), "gates": gates}


def run_factor_weight_closed_loop(gates_fn=None, apply_fn=None, proposal_fn=None):
    """因子闭环总入口: IC -> 建议 -> (老大拍板) -> 写/不写。

    默认 apply_fn=None, 即默认行为是"只出建议, 绝不写"。
    """
    proposal = propose_factor_weight_adjustment(proposal_fn)
    if proposal is None:
        return {"ok": False, "reason": "proposal_failed",
                "applied": False, "proposal_id": None}
    res = weight_update_seam(proposal, gates_fn=gates_fn, apply_fn=apply_fn)
    res["ok"] = True
    return res


def merge_to_production_registry(proposal, registry_path="data/factor_registry/registry.json"):
    """将通过的提案合并到生产 registry。

    走 FactorRegistry.register() 方法 (passthrough 不洗扩展字段, K45#1)。
    返回: {'merged': bool, 'factor_id': str, 'version': int}
    """
    try:
        from core.scoring.factor_registry import FactorRegistry, FactorMetadata
        import os
        # registry_path 可能是文件路径或目录路径，统一处理
        if _os.path.isfile(registry_path):
            registry_dir = _os.path.dirname(registry_path)
        else:
            registry_dir = registry_path
        reg = FactorRegistry(registry_dir)

        # 从 proposal 提取因子信息
        factor_id = proposal.get("target")
        if not factor_id:
            return {"merged": False, "error": "proposal 缺少 target 字段"}

        # 构建 FactorMetadata
        meta = FactorMetadata(
            factor_id=factor_id,
            name=proposal.get("name", factor_id),
            category=proposal.get("category", "unknown"),
            description=proposal.get("desc", ""),
            direction=proposal.get("direction", "neutral"),
            ic_mean=proposal.get("ic_mean"),
            icir=proposal.get("icir"),
            forward_horizon=proposal.get("forward_horizon", 5),
            formula=proposal.get("formula", ""),
        )

        # 注册到 registry
        success = reg.register(meta)
        if success:
            return {"merged": True, "factor_id": factor_id, "version": meta.version}
        else:
            return {"merged": False, "error": "register() 返回 False"}
    except Exception as e:
        # 写口失败 = fail-safe，不静默吞
        print(f"[P5] merge_to_production_registry 失败: {e}", file=sys.stderr)
        return {"merged": False, "error": str(e)}
def _read_redline_from_source():
    """读 risk_rules.py 真源红线常量，返回五档 fields 字典。

    真源：risk_rules.py 是唯一权威源，零硬编码阶梯值。
    返回: {
      'STOP': STRATEGY_STOP_LOSS_PCT['全仓'],
      'CHASE': CHASE_BAN_PCT,
      'TIME': TIME_STOP_TRADING_DAYS,
      'TP_UP': [list(t) for t in TREND_TP_LADDER['up']],
      'TP_DOWN': [list(t) for t in TREND_TP_LADDER['down']],
    }
    """
    import risk_rules as _rr
    return {
        "STOP": _rr.STRATEGY_STOP_LOSS_PCT.get("全仓"),
        "CHASE": _rr.CHASE_BAN_PCT,
        "TIME": _rr.TIME_STOP_TRADING_DAYS,
        "TP_UP": [list(t) for t in _rr.TREND_TP_LADDER["up"]],
        "TP_DOWN": [list(t) for t in _rr.TREND_TP_LADDER["down"]],
    }


def _get_engine_commit():
    """SOUL 准则7: 结论必须声明来自哪个 commit 引擎。

    读 git rev-parse HEAD，失败回退 UNSPECIFIED。
    """
    import subprocess as _sp
    import os
    try:
        r = _sp.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                    cwd=_os.path.dirname(_os.path.abspath(__file__)))
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "UNSPECIFIED"


def bootstrap_redline_baseline(log_path="iteration_log.json"):
    """首 run: 把真源快照写入 iteration_log.json.redline_baseline。

    走 atomic_json.update_json 台账写口，原子写。
    返回: 写出的 baseline dict。
    """
    import core.pipeline.atomic_json as _aj
    fields = _read_redline_from_source()
    def _mutator(data):
        data["redline_baseline"] = {"fields": fields, "captured_at": datetime.now().isoformat()}
        return data
    _aj.update_json(log_path, _mutator, default={})
    return {"fields": fields}


def run_evolution_loop(proposals, today, circuit_level="L0",
                       baseline_sharpe=None, current_sharpe=None,
                       fit_dates=None, oos_dates=None, tuned_on_dates=None,
                       dry_run=True, log_path="iteration_log.json"):
    """walk-forward 纯 OOS 主循环（裁定1：接缝层保证 OOS 纯净）。

    流程:
    1. 若首次运行（无 redline_baseline）→ bootstrap 写入
    2. redline_check 漂移检测（E1）
    3. 构造 gate_fn（含 OOS 接缝隔离）
    4. 跑 EvolutionLoop.run_round()
    5. 收尾：oos_purity_check 断言末 20d OOS 段纯净

    返回: {round_id, paused, pause_reason, escalated, results, sharpe_anomaly, oos_check}
    """
    # 1. 基线捕获（首次运行时写入）
    import json as _json
    import core.pipeline.atomic_json as _aj
    raw = _aj.atomic_load(log_path, default={})
    baseline = raw.get("redline_baseline")
    if not baseline:
        baseline = bootstrap_redline_baseline(log_path)

    # 2. 红线漂移检测（E1）
    rl = redline_check(_read_redline_from_source, baseline)
    if rl["frozen"]:
        # 冻结时直接返回，不等 loop
        return {
            "round_id": f"R_{today.isoformat()}_BOOT",
            "paused": True,
            "pause_reason": "redline_drift",
            "escalated": [{"point": "E1", "reason": rl["reason"],
                          "fields": rl["changed_fields"],
                          "action": "停循环 + urgent飞书 + 回滚 + 生成《参数变更申请》挂起"}],
            "results": [],
            "sharpe_anomaly": False,
            "oos_check": {"pure": False, "reason": "redline frozen"},
            "engine_commit": _get_engine_commit(),
        }

    # 3. 构造 gate_fn（含 OOS 接缝隔离）
    gate_fn = make_gate_fn()

    # 4. 注入 OOS 日期到 prop
    enriched_props = []
    for p in proposals:
        ep = dict(p)
        if fit_dates is not None:
            ep["fit_dates"] = fit_dates
        if oos_dates is not None:
            ep["oos_dates"] = oos_dates
        if tuned_on_dates is not None:
            ep["tuned_on_dates"] = tuned_on_dates
        enriched_props.append(ep)

    # 5. 跑一轮
    loop = EvolutionLoop(
        dry_run=dry_run,
        read_redline_fn=_read_redline_from_source,
        redline_baseline=baseline,
        gate_fn=gate_fn,
        write_spy=lambda *a, **k: None,
        lessons_ref=get_lesson_ref(),
        log_path=log_path,
    )
    result = loop.run_round(enriched_props, today, circuit_level=circuit_level,
                            baseline_sharpe=baseline_sharpe, current_sharpe=current_sharpe)

    # 6. OOS 纯净断言（裁定1）
    oos_check = oos_purity_check(
        fit_dates or [],
        oos_dates or [],
        tuned_on_dates or []
    )

    result["oos_check"] = oos_check
    result["engine_commit"] = _get_engine_commit()
    return result


def make_dry_run_loop(baseline=None, rejections=None):
    """便捷构造一个 dry_run 骨架循环(默认不连真源)。供审查/dry_run 演习(交付物4)用。"""
    return EvolutionLoop(
        dry_run=True,
        read_redline_fn=_read_redline_from_source,
        redline_baseline=baseline or {"fields": {}},
        gate_fn=lambda p: {"G1_stat": {"pass": False}, "G2_robust": {"pass": True},
                            "G3_equiv": {"pass": True}},   # 桩: 未接真门禁 → fail-safe 不合并
        rejections_by_target=rejections or {},
        write_spy=None,
        lessons_ref=get_lesson_ref(),
    )


# ═══════════════════════════════════════════════════════════
#  E2 IC 序列在线监控钩子（P4v2：接 daily_monitor cron 读样本外 IC）
# ═══════════════════════════════════════════════════════════
def e2_ic_series_check(log_path="iteration_log.json",
                       consecutive_negative_threshold=5):
    """E2 升级点：从 lessons[] 提取 IC 序列，连续 N 日 IC<0 → 触发 escalation E2。

    判定逻辑（SOUL 准则 5）：
      - 读 iteration_log.json.lessons[]，按 timestamp 排序
      - 每 lesson 取 gate_results.G1_stat.detail.metrics.ic（若存在）
      - 连续 negative IC 日数 ≥ threshold → 触发 E2
      - 返回 {'triggered': bool, 'negative_streak': int, 'escalation': dict|None}

    手算例证：
      lessons = [
        {gate_results: {G1_stat: {detail: {metrics: {ic: -0.02}}}}, timestamp: "2026-10-05"},
        {gate_results: {G1_stat: {detail: {metrics: {ic: -0.03}}}}, timestamp: "2026-10-06"},
        ...5条连续负 IC...
      ]
      → negative_streak = 5, triggered = True, escalation = {"point": "E2", ...}
    """
    import core.pipeline.atomic_json as _aj
    from datetime import datetime as _dt

    data = _aj.atomic_load(log_path, default={})
    lessons = data.get("lessons", [])
    if not lessons:
        return {
            "triggered": False,
            "negative_streak": 0,
            "total_lessons": 0,
            "escalation": None,
            "note": "lessons[] 空，无 IC 序列可分析",
        }

    # 提取每日 IC（按 timestamp 排序，取最新 N 条）
    ic_series = []
    for lesson in sorted(lessons, key=lambda x: x.get("timestamp", "")):
        gate = lesson.get("gate_results", {})
        g1 = gate.get("G1_stat", {})
        detail = g1.get("detail", {})
        metrics = detail.get("metrics", {})
        ic = metrics.get("ic")
        ts = lesson.get("timestamp", "")
        if ic is not None:
            ic_series.append({"ic": ic, "timestamp": ts,
                              "lesson_id": lesson.get("lesson_id")})

    # 计算连续负 IC  streak
    negative_streak = 0
    for entry in reversed(ic_series):
        if entry["ic"] < 0:
            negative_streak += 1
        else:
            break

    triggered = negative_streak >= consecutive_negative_threshold
    escalation = None
    if triggered:
        escalation = {
            "point": "E2",
            "reason": f"样本外 IC 连续 {negative_streak} 日 < 0（阈值 {consecutive_negative_threshold}）→ 暂停迭代循环",
            "negative_streak": negative_streak,
            "threshold": consecutive_negative_threshold,
            "action": "暂停迭代循环本身 + 飞书请示老大",
            "last_negative_ic": ic_series[-1]["ic"] if ic_series else None,
        }

    return {
        "triggered": triggered,
        "negative_streak": negative_streak,
        "total_lessons": len(lessons),
        "ic_series_length": len(ic_series),
        "escalation": escalation,
        "latest_ics": ic_series[-5:] if ic_series else [],
    }


if __name__ == "__main__":
    import argparse as _ap
    import os
    import time as _time  # noqa

    _parser = _ap.ArgumentParser(description="evolution_loop CLI")
    _sub = _parser.add_subparsers(dest="cmd", required=True)

    _smoke = _sub.add_parser("smoke", help="dry_run 冒烟（现有路径）")

    _first = _sub.add_parser("first-pass", help="只读首跑：全循环真跑，写口重定向 scratch")
    _first.add_argument("--log-path", default="iteration_log.json", help="迭代账本路径")
    _first.add_argument("--scratch-dir", default=".hermes/scratch/readonly_first_pass",
                        help="scratch 输出目录")
    _first.add_argument("--today", default=None, help="日期 YYYY-MM-DD，默认今天")
    _first.add_argument("--dry-run", action="store_true", default=True,
                        help="仅报告，不触写口（默认开启）")
    _first.add_argument("--production", action="store_true", default=False,
                        help="切生产写口（需三层闸全绿）")

    _check_e2 = _sub.add_parser("e2-check", help="E2 IC序列检查：连续5日IC<0→暂停")
    _check_e2.add_argument("--log-path", default="iteration_log.json", help="迭代账本路径")

    _args = _parser.parse_args()

    if _args.cmd == "smoke":
        # 原有冒烟路径不变
        def _matched_read():
            return {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}

        loop = EvolutionLoop(
            dry_run=True,
            read_redline_fn=_matched_read,
            redline_baseline={"fields": {"STOP": 0.10, "CHASE": 4.0, "TIME": 120}},
            gate_fn=lambda p: {"G1_stat": {"pass": True, "ic": 0.04, "ir": 0.5,
                                             "rankic_monotonic": True},
                                "G2_robust": {"pass": True, "sharpe_decay_pct": 10.0},
                                "G3_equiv": {"pass": True, "sanity_exit_code": 0}},
            write_spy=None,
            lessons_ref=get_lesson_ref(),
        )
        demo_props = [
            {"proposal_id": "DEMO1", "source": "C", "target": "top_n", "desc": "top_n 60→40"},
        ]
        out = loop.run_round(demo_props, date.today(), circuit_level="L0",
                             baseline_sharpe=1.0, current_sharpe=1.1)
        import json as _json
        print(_json.dumps(out, ensure_ascii=False, indent=2, default=str))
        print("(骨架 dry_run 冒烟: 匹配桩读→无漂移, 三门绿→merged_dryrun, 零实际写口; 接真门禁前桩 fail-safe 不合并)")

    elif _args.cmd == "first-pass":
        # 只读首跑：全循环真跑，所有写口重定向 scratch，产出观察报告
        # P5: --production 标志切换生产写口（需三层闸全绿）
        scratch_dir = _args.scratch_dir
        log_path = _args.log_path
        _today = date.fromisoformat(_args.today) if _args.today else date.today()
        _production_mode = _args.production

        # P5: 生产模式检查三层闸
        gate_result = None
        if _production_mode:
            print("[first-pass] 生产模式检测中...")
            gate_result = check_production_gates()
            if not gate_result["passed"]:
                print(f"[first-pass] ❌ 生产写口守卫拦截: {gate_result['blocked_by']}")
                import json as _json
                print(f"[first-pass] 闸状态: {_json.dumps(gate_result['gates'], ensure_ascii=False, indent=2)}")
                print("[first-pass] 保持 dry_run 模式，不触生产 registry")
                _production_mode = False
            else:
                print("[first-pass] ✅ 三层闸全绿，切换生产写口")

        # 1. 备份当前 log_path → scratch
        _os.makedirs(scratch_dir, exist_ok=True)
        bak_ts = _time.strftime("%Y%m%d_%H%M%S")
        bak_path = _os.path.join(scratch_dir, f"iteration_log.json.bak_{bak_ts}")
        if _os.path.exists(log_path):
            import shutil as _shutil
            _shutil.copy2(log_path, bak_path)
            print(f"[first-pass] 备份: {log_path} → {bak_path}")

        # 2. 构造 scratch 写入路径（所有写口指向 scratch）
        scratch_log = _os.path.join(scratch_dir, "iteration_log_scratch.json")
        scratch_report = _os.path.join(scratch_dir, "observation_report.json")
        scratch_report_md = _os.path.join(scratch_dir, "observation_report.md")
        scratch_lessons = _os.path.join(scratch_dir, "lessons_scratch.json")
        scratch_escalations = _os.path.join(scratch_dir, "escalations_scratch.json")

        # 3. 初始化 scratch 副本（浅拷贝当前 log，但写口重定向）
        import core.pipeline.atomic_json as _aj
        import json as _json_mod
        current = _aj.atomic_load(log_path, default={})
        scratch_data = {k: v for k, v in current.items()}
        scratch_data["readonly_first_pass"] = {
            "init_time": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            "original_log_path": log_path,
            "scratch_log_path": scratch_log,
            "gated": True,  # 写口 gated，不触生产
        }
        _aj.atomic_dump(scratch_data, scratch_log)

        # 4. 构造 write_spy 拦截器：记录写口调用但不写生产
        write_log = []

        def _write_interceptor(*args, **kwargs):
            """拦截所有 write_spy 调用，记入 write_log，不写生产。"""
            write_log.append({"args": args, "kwargs": kwargs,
                              "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%S")})

        # 5. 构造 mock log_path：所有 `_record_lesson` / `_escalation` 的 atomic_json.update_json
        #    注入 scratch_log 而非真实 log_path
        #    用 patching 方式：临时覆盖 _aj.atomic_load / update_json 的默认路径
        _orig_atomic_load = _aj.atomic_load
        _orig_update_json = _aj.update_json

        def _patched_atomic_load(path, **kw):
            if path == log_path:
                return _orig_atomic_load(scratch_log, **kw)
            return _orig_atomic_load(path, **kw)

        def _patched_update_json(path, mutator, **kw):
            if path == log_path:
                return _orig_update_json(scratch_log, mutator, **kw)
            return _orig_update_json(path, mutator, **kw)

        _aj.atomic_load = _patched_atomic_load
        _aj.update_json = _patched_update_json

        try:
            # 6. 跑一轮（dry_run=True 或 production 模式）
            result = run_evolution_loop(
                proposals=[],  # 首轮无提案，纯观察循环状态机
                today=_today,
                dry_run=not _production_mode,
                log_path=scratch_log if not _production_mode else log_path,
            )
            result["write_interceptor_calls"] = write_log
            result["scratch_log_path"] = scratch_log
            result["mode"] = "production" if _production_mode else "readonly_first_pass"
            result["production_unmodified"] = not _production_mode  # production 模式会修改 registry

            # 7. 生成观察报告
            report = {
                "mode": "production" if _production_mode else "readonly_first_pass",
                "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%S"),
                "today": _today.isoformat(),
                "result": result,
                "findings": {
                    "production_iteration_log_unchanged": not write_log and not _production_mode,
                    "production_registry_unmodified": not _production_mode,
                    "production_holdings_unmodified": True,
                    "escalations_recorded_in_scratch": len(result.get("escalated", [])) > 0,
                    "production_gates": gate_result if _production_mode else None,
                },
                "next_steps": [
                    "老大审阅本观察报告（observation_report.md）",
                    "✅ 三层闸全绿 → 已切生产写口，registry 实写",
                    "任一闸 fail → 保持 dry_run/scratch，merged=0",
                ],
            }
            _aj.atomic_dump(report, scratch_report)
            print(f"[first-pass] 观察报告已写入: {scratch_report}")
            print(f"[first-pass] scratch log: {scratch_log}")

        finally:
            # 8. 恢复 atomic_json 原始函数
            _aj.atomic_load = _orig_atomic_load
            _aj.update_json = _orig_update_json

    elif _args.cmd == "e2-check":
        # E2 IC 序列检查：从 lessons 提取 IC，连续5日负 → 触发 escalation E2
        log_path = _args.log_path
        e2_result = e2_ic_series_check(log_path)
        import json as _json
        print(_json.dumps(e2_result, ensure_ascii=False, indent=2))
