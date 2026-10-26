# 策略自动迭代优化闭环 · 骨架+schema（evolution_loop v1 · 交付物 1）

**版本**: v1-draft（待老大审查，未启动真实循环）
**日期**: 2026-10-09
**作者**: 总管（Hermes/agnes）
**状态**: 骨架交付，dry_run 默认，**未上线**。上线需老大批 dry_run 演习（交付物 4）。

> 本协议落地"机器在笼子里自动转、拍板点全部外置"。核心：每笔变更可审计/可回滚/红线零触碰。
> 先建台子（本文档 + `evolution_loop.py` 骨架 + TDD 测试）→ 老大审查 → 再上 Phase 分片任务单 + dry_run 演习。

---

## 〇、笼子校准（关键发现：提示词红线 ≠ 系统真源，骨架绑真源）

红线守护**不硬编码提示词里的具体数值**（提示词可能漂移），而是每轮**动态读系统真源 + 记录基线 + 检测漂移**。
下表是"提示词值 vs 系统真源"的校准结果，骨架一律以**真源列为准**：

| 红线常量 | 提示词值 | 系统真源 | 校准结论 |
|---|---|---|---|
| 硬止损（全仓） | 10% | `risk_rules.STRATEGY_STOP_LOSS_PCT["全仓"]=0.10`（S3 三方会签 2026-09-30）| ✅ 一致 |
| 移动止盈阶梯 | "6-10-20" | `risk_rules.TREND_TP_LADDER["up"]=[(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]`（S3 吃大肉 2026-10-06，总卖出 48%）| ❌ **不一致**（真源五档，非三档 6-10-20）|
| 追高关闭 | 4% | `risk_rules.CHASE_BAN_PCT=4.0` | ✅ 一致 |
| 时间止损 | 120日 | `risk_rules.TIME_STOP_TRADING_DAYS=120` | ✅ 一致 |
| 因子门禁 | IC>0.03 / IR>0.3 / 单调 | `factor_gate_v2.GATE_CONFIG`（ic 0.03 / ir 0.3 / dir_rate 0.55 / monotonicity 0.02）| ✅ 一致（单调用 0.02 真源，非提示词未给）|

**结论**：`RedlineGuard` 读 `risk_rules.py` 常量真源做漂移检测（读到 STOP/CHASE/TIME/TP_LADDER），**检测"被改没被改"**（漂移→冻结），**不校验"值对不对"**（值以真源为准）。提示词"6-10-20"作废，骨架零处硬编码阶梯。

---

## 一、iteration_log 扩展 schema（挂现有 `iteration_log.json`，不新建）

现有 `iteration_log.json` 顶层：`version / created / description / iterations[] / config`。
本闭环**扩展**（追加字段，不破坏既有 `iterations[]` 向后兼容）：

```jsonc
{
  "version": "1.1",                     // 升级版本标记
  "iterations": [ /* 既有启发式迭代账本，不动 */ ],
  "config": { /* 既有 train/valid/gate_thresholds，不动 */ },
  "redline_baseline": {                  // 新增：循环启动时的红线常量真源快照（首 run bootstrap）
    "captured_at": "2026-10-09T...Z",
    "fields": {
      "STRATEGY_STOP_LOSS_PCT_全仓": 0.10,
      "CHASE_BAN_PCT": 4.0,
      "TIME_STOP_TRADING_DAYS": 120,
      "TREND_TP_LADDER_up": [[6,0.15],[10,0.05],[15,0.07],[25,0.09],[999,0.12]],
      "TREND_TP_LADDER_down": [[5,0.03],[10,0.04],[15,0.05],[20,0.06],[30,0.08],[999,0.10]]
    }
  },
  "closed_loop_config": {                // 新增：循环参数（写死项=防过拟合铁律，不可协商）
    "max_proposals_per_round": 3,
    "propose_source_rotation": ["A","B","C","D"],   // 因子/信号/参数/结构 四层轮转
    "smoke_window_days": 60,
    "confirm_window_days": 132,
    "walk_forward_tail_days": 20,        // 铁律:末20日纯OOS,未参与任何fit/选参
    "grid_max_points": 20,              // C层参数网格≤20点
    "cooldown_window_days": 30,         // 铁律:同因子/参数30日内
    "cooldown_ban_days": 60,            // 铁律:被拒2次→60日内不得再提案
    "cooldown_min_rejections": 2,
    "sharpe_anomaly_ratio": 2.0,        // 铁律:合入使夏普>2.0×基线→人工评审(优秀到反常)
    "oos_ic_fail_days": 5,              // 升级点E2:样本外连续5日IC<0→暂停循环
    "oos_ic_decay_reaudit_ratio": 0.5   // 升级点E5:月度过拟合体检,样本外衰减>50%→全量重审当月合入
  },
  "lessons": [ /* 教训库, 见 §二 */ ],
  "escalations": [ /* 升级拍板点队列, 见 §四 */ ]
}
```

**写口纪律**：以上任何新增字段的落盘走 `atomic_json.update_json`（台账写口，防并发覆盖）。
`redline_baseline` 首 run bootstrap 由循环自己写；`closed_loop_config` 的"铁律"字段**只读**（改动=另开单）。

---

## 二、教训库 schema（`lessons[]`，含一手证据字段，SOUL 准则 5 / AGENTS 证据链）

每个**未过门禁被回滚**的提案进教训库，结构化记录失败样本（防 30 日冷却 + 月度重审的数据源）：

```jsonc
{
  "lesson_id": "L_20261009_0001",
  "timestamp": "2026-10-09T...Z",
  "round_id": "R_20261009_03",
  "proposal_source": "C",                 // A因子/B信号/C参数/D结构
  "target": "factor_id 或 param_name",    // 冷却判定的 key
  "proposal": "变更说明（一句话）",
  "gate_results": {
    "G1_stat":   {"pass": false, "ic": 0.02, "ir": 0.25, "rankic_monotonic": false},
    "G2_robust": {"pass": true,  "sharpe_decay_pct": 18.0},
    "G3_equiv":  {"pass": true,  "sanity_exit_code": 0}
  },
  "failed_gate": "G1_stat",
  "failure_reason": "样本外 IC=0.02<0.03 且 RankIC 非单调",
  "evidence": {                            // 一手证据字段（不得打勾放行, 写不出=未验证）
    "decision_id": "...",
    "engine_commit": "...",              // SOUL准则7: 结论必须声明来自哪个 commit 的引擎
    "data_window": "2021-01-04~2026-09-18(132d,末20d纯OOS)",
    "includes_delisted": true,
    "before_metrics": {"sharpe": 1.0, "win_rate": 0.319},
    "after_metrics":  {"sharpe": 0.9, "win_rate": 0.30},
    "pessimistic_loss": "G1 fail 不合并, 本提案 0 损失(已回滚)",
    "symmetry_argument": "IC<阈值不合并, 对称于'过门禁才合入'",
    "invalidation_trigger": "若该因子 240日稳健 ICIR 转正则重提"
  },
  "rejection_count": 1,                   // 同 target 累计被拒次数
  "last_rejection": "2026-10-09",
  "cooldown_until": "2026-11-08",         // 命中冷却规则时=last_rejection+60d, 否则 null
  "status": "rejected"
}
```

**冷却判定（纯逻辑，`cooldown_active`）**：同 target 最近 2 次被拒间隔 ≤30d 且 today < last_rejection+60d → 冷却中。

---

## 三、门禁三关定义（CONFIRM 后 GATE，过三关才允许合入）

| 关 | 判据 | 真源 |
|---|---|---|
| **G1 统计关** | 样本外 IC>0.03 且 IR>0.3 且 RankIC 单调（单调差≥0.02）| `factor_gate_v2.GATE_CONFIG` |
| **G2 稳健关** | 参数扰动 ±20% 后夏普衰减 <30%（防过拟合硬指标）| 回测引擎扰动重算 |
| **G3 等价关** | `check_backtest_sanity.py` 退出码=0（PASS）| 现有 sanity gate |

任一关 fail → 该提案 ROLLBACK + 入教训库。
分 regime 分段（牛/熊/震荡）：CONFIRM 全量 132d 时须各段不劣于基线（regime 分段结果入 evidence）。

**walk-forward 铁律**：132d 确认窗内嵌 20d walk-forward，**末 20d 从未参与任何 fit/选参**（纯 OOS）。CONFIRM 断言 `last_20d_pure_oos: true`。

---

## 四、升级拍板点（机器不自决，挂起 + 飞书请示老大）

| 点 | 触发 | 动作 |
|---|---|---|
| **E1 红线变更** | `RedlineGuard` 检测 risk_rules 常量漂移 | 立即停循环 + urgent 飞书 + 回滚 + 生成《参数变更申请》挂起 |
| **E2 OOS 恶化** | 样本外连续 5 日 IC<0 或回撤破 L1（单日-3%/累计-10%）| 暂停迭代循环本身 + 请示 |
| **E3 因子库变动** | active 因子数变动（转正/降级/移除）| 请示（新增转正/降级/移除需老五+老大）|
| **E4 熔断联挂** | `circuit_breaker.circuit_level` ≥ L1（L1黄/L2红停/L3紧急降阶）| L1升级等待, L2/L3 循环自暂停 + urgent 飞书 |
| **E5 月度过拟合** | 合入变更的样本外衰减 >50% | 全量重审当月合入 + 请示 |

**实现约束**：循环对以上 5 点**只产出"escalated 挂起"决策**，**绝无自决放行权**。挂起写入 `escalations[]` + 飞书（`system-broadcast` 多群）+ 等待。
E4 与 `circuit_breaker` 联挂：`circuit_interlock(level_str)` 纯映射 L0→正常 / L1→escalate / L2L3→pause+escalate。

---

## 五、交付物 2：`evolution_loop.py` 骨架接口（seams，TDD 待验证）

纯逻辑函数（注入 I/O，可测）+ 薄 I/O 包装：

```python
redline_check(read_fn, baseline)      # {'frozen','changed_fields','reason'}  漂移检测
cooldown_active(rejections, today, ...) -> bool   # 30d/60d 冷却纯逻辑
sharpe_anomaly(baseline, current, ratio=2.0) -> bool  # 优秀到反常
circuit_interlock(level_str) -> {'pause','escalate','action'}  # 熔断映射
class EvolutionLoop:
    def __init__(self, dry_run=True, *, read_redline_fn, redline_baseline,
                 gate_fn, write_spy=None, ...)   # 全部依赖注入
    def run_round(self, proposals, today, circuit_level="L0",
                  baseline_sharpe, current_sharpe) -> dict
    # 返回 {'round_id','paused','pause_reason','escalated':[...],
    #       'results':[{'proposal_id','status','failed_gate','lesson_recorded'}],
    #       'sharpe_anomaly':bool}
    # status ∈ {merged_dryrun, rolled_back, skipped_cooldown, skipped_paused}
```

**硬红线 2（不自动买卖）**：`dry_run=True` 时 `run_round` 零实际写口（不触 holdings/trade_log/review_status），仅 dry_run 决策 + 日志。`write_spy` 注入记录（测试断言未被调用）。
**硬红线 3（门禁未全绿=永远 dry_run）**：`review_gate.evaluate` 非放行 → 循环保持 dry_run，不写 `review_status.json`。

**stubs（待审查后接真）**：`run_backtest_fn` / `gate_fn` 在骨架里是**注入的可调用**（真实回测引擎/门禁调用留接缝），不硬接——避免骨架一跑就触发真回测（红线2）。

### 终审裁定后新增的 2 个 seam（Kimi 终审 2026-10-09，TDD 已验证）
| seam | 签名 | 裁定来源 | TDD |
|---|---|---|---|
| **OOS 接缝隔离** | `oos_purity_check(fit_dates, oos_dates, tuned_on_dates=None)` | 裁定1 硬约束：walk-forward OOS 段必须在**接缝层断言**保证未参与 fit/选参（不靠自觉）。engine 出结论前必调，违反①OOS∩fit ②OOS∩tuned ③OOS 非时序末尾任一 → `pure=False` | `test_evolution_loop_seams.py` OOS×5 |
| **红线只写指针校验** | `redline_pointer_compliant(text)` + `check_redline_pointer.py` | §三裁定：提示词/文档红线只写指针(risk_rules.XXX)不写具体数值。任何红线数值行未带真源指针=判漂移。校验口径单一真源=本纯函数(不分裂)，机器入口 `check_redline_pointer.py`(退码0/1) | `test_evolution_loop_seams.py` 指针×5 |

**接真回测接缝（P1/P2）强制**：`run_backtest_fn` 出结论前**必须**先过 `oos_purity_check` 断言 OOS 段纯净（否则 seam 层拒判，不靠工程自觉）。

---

## 六、验收断言（用断言不用打勾，SOUL 准则 5）

| 验收项 | 断言（一手证据）| 状态 |
|---|---|---|
| 红线漂移检测 | `test_redline_*`：改常量→`frozen=True`+`changed_fields`含该字段 | 见 `tests/test_evolution_loop.py` |
| 冷却铁律 | `test_cooldown_*`：30d 内 2 拒→`cooldown_active=True`；60d 过期→False | 同上 |
| 夏普反常 | `test_sharpe_anomaly_*`：>2.0× 基线→True | 同上 |
| 熔断自停 | `test_circuit_*` + `test_run_round_circuit_L2_*`：L2→`paused=True`+E4 | 同上 |
| 红线冻结回滚 | `test_run_round_redline_*`：漂移→全提案 `rolled_back`+E1，零 merge | 同上 |
| 门禁 fail 入教训库 | `test_run_round_gate_fail_*`：G1 fail→`rolled_back`+`lesson_recorded=True` | 同上 |
| dry_run 零写口 | `test_run_round_gate_pass_*`：三关绿→`merged_dryrun` 且 `write_spy` 未调用 | 同上 |
| 夏普反常触发人工评审 | `test_run_round_sharpe_*`：合并同时 `escalated` 含 E5 | 同上 |

**未验证项（如实标注，非打勾）**：
- `run_backtest_fn`/`gate_fn` 真实接缝（接真回测引擎 + `check_backtest_sanity` 实跑）——骨架留注入点，真接是交付物 3 任务单，本轮不接（避免触发真回测）。
- 升级点 E2（样本外连续 5 日 IC<0 的**在线**监控）——骨架提供 `sharpe_anomaly` 离线判据 + E5 月度重审，**在线日度 IC 监控**接 `daily_monitor` cron，本轮未接（留维护窗口）。
- 飞书升级通道（`system-broadcast` 实发）——骨架只产 `escalations[]` 数据，实发是执行层动作，本轮 dry_run 不发。

---

## 七、红线清单（骨架前置检查，违反=停循环+urgent飞书+回滚）

1. `risk_rules.py` 常量只读（漂移检测 §〇），改动→《参数变更申请》挂起 E1
2. 不自动买卖：dry_run 循环不触 holdings/trade_log/review_status 写口
3. 门禁未全绿=永远 dry_run，迭代不改 review_status.json
4. 回测引擎变更后 `check_backtest_sanity.py` 必 PASS（G3）
5. 测试期望值只来自决策记录/文档现值/手算 worked example（本 schema 的 §六 断言值均手算）
6. 每轮落 `.bak_<日期>_<轮次>` + git 原子 commit + 失败一键回滚
