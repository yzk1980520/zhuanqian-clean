# scripts/ gitignore 白名单缺口清单 · 2026-10-19

> 实施方：fix-live-filter（寇豆码） · 缘起：team-lead 复核 L3 报告 §五.3 时要求补齐，
> 用于老大做「白名单加几条」的选择题。全部结论实数实测（`git ls-files` + 全仓引用扫描）。

---

## 一、总量实测

| 项 | 数 |
|---|---|
| `scripts/` 下程序文件（.py/.bat/.cmd/.sh） | 539 |
| 已被 git 跟踪（白名单内） | 147 |
| **被 `scripts/*` 排除且不在白名单** | **396**（另有 3 个 Windows 计划任务 `.task.xml` 同样被排除） |

`.gitignore:12` 的 `scripts/*` 一刀切排除，白名单只放行了 147 个（多为 AOCI/dispatch/gate 等
 feeder 脚本）。被排除的 396 个里，**一部分是历史臃肿脚本**（code-reviewer-fat 的三档清理清单
已覆盖，任务 #9 已完成），但**另一部分是实盘链路/计划任务/门禁的直连文件——它们不在任何
commit 里，换机即丢**。本清单只列后者。

---

## 二、A 级：实盘/调度/门禁直连（建议立即加白名单）

| # | 文件 | 角色 | 被谁引用（实测） |
|---|---|---|---|
| 1 | `scripts/auto_live_pipeline.py` | **实盘唯一选股路径**（`run_stock_selection`） | `daily_pick.py`（tracked，模块 import）；cron `daily_pick` 事件 → `python dojo_bridge.py daily_pick` → daily_pick.py（cron_config.json:49） |
| 2 | `scripts/pre_pick_gate.py` | 选股前 P0 阻断门（09:25 早鸟预警） | `cron_config.json:8`（pre_pick 事件命令链明示） |
| 3 | `scripts/factor_ic_132d_refresh.py` | 因子 IC 权威源周更（132d 口径） | `cron_config.json:180-181`（周更调度命令）；入口 `scripts/Zhuanqian_FactorIC132d.bat`（**同样被排除**） |
| 4 | `scripts/Zhuanqian_FactorIC132d.bat` + `scripts/Zhuanqian_FactorIC132d.task.xml` | Windows 计划任务「因子 IC 周更」注册三件套之二三 | 计划任务本体；cron_config.json:180 描述其注册方式 |
| 5 | `scripts/auto_pipeline.py` | 132 日全量调仓回测执行入口（AGENTS.md:96 铁律载体） | `cron_config.json:154-155`（`python scripts/auto_pipeline.py --wait`）；入口 bat 同样被排除 |
| 6 | `scripts/Zhuanqian_Rotation132d.bat` + `.task.xml` | 计划任务「132d 全量回调」三件套 | cron_config.json:154 链路（第 0 步审计 + 回测 + 新鲜度闸门 + 验收） |
| 7 | `scripts/audit_delisted_coverage.py` | 退市覆盖审计（门禁第 6 条降级证据源） | cron_config.json:154（rotation bat 第 0 步）；`tests/test_delisted_coverage.py` |
| 8 | `scripts/check_backtest_result_fresh.py` | 回测结果新鲜度闸门（防门禁拿旧结果假绿） | cron_config.json:154（rotation bat 回测与验收之间） |
| 9 | `scripts/walk_forward_backtest.py` / `walk_forward_gate.py` / `walk_forward_report.py` | W8 walk-forward 衰减阻断三件套 | `cron_config.json` + `config/walk_forward_gate.json` + `deliverables/W8-walkforward衰减阻断-20261017.md`；入口 bat+task.xml 同样被排除 |
| 10 | `scripts/Zhuanqian_WalkForward.bat` + `.task.xml` | 计划任务「walk-forward」三件套 | 同上 |
| 11 | `scripts/system_audit_checker.py` | B3 门禁消费方（系统审计） | `tests/test_b3_gate_consumers.py`（9 处）、`tests/test_b3_bare_except_fix.py` |
| 12 | `scripts/s3_auto_pipeline.py` | B3 门禁消费方 + 自带 `run_stock_selection`（另一条选股入口！） | `tests/test_b3_gate_consumers.py`（7 处） |
| 13 | `scripts/fix_history_data.py` | 历史数据修复（history_daily 修复链） | `k72_acceptance_test.py`（tracked，9 处） |

**A 级合计 16 个文件（含 3 组 bat+task.xml 三件套）。其中 #1 就是本次 L3 主修文件——
它此刻只以工作区文件 + 本次 `.bak_20261019_laoliu` 形式存在。**

---

## 三、B 级：测试/治理层直连（建议加白名单或明确判决）

| 文件 | 角色 | 被谁引用 |
|---|---|---|
| `scripts/direct_ic_calc.py` / `quick_ic_sample.py` | IC 计算 | `tests/test_factor_ic.py`（各 6 处） |
| `scripts/ic_capital_compound.py` | 复利计算 | `tests/test_5_transitions.py`（6 处） |
| `scripts/file_change_validator.py` | 文件变更校验 | `tests/test_file_change_validator.py`（14 处） |
| `scripts/ai_analysis.py` | AI 分析层 | `dashboards/dashboard_v2.py`（tracked，8 处） |
| `scripts/sync_true_source_stamp.py` | true-source-stamp 同步（契约治理） | `AGENTS.md` + `docs/CONTRACT-CHANGELOG-20261017.md` |
| `scripts/broadcast_contract_change.py` | 契约人格广播（治理） | `AGENTS.md` + `BOOTSTRAP.md` + `channel.json` + `CONTEXT.md` |
| `scripts/gate_check.py` | 门禁检查 | 仅文档引用（W1/W5/W8 三份交付物）——建议先确认是否仍存活再定 |

---

## 四、C 级：仅文档引用的历史/臙肿脚本（不建议进白名单，走清理）

`trade_executor.py`、`update_trade_log.py`、`daily_reconcile.py`、`position_manager.py`、
`live_trading_loop.py`、`cron_daily_select.py`、`daily_auto_select.py`、`pick_best_stock.py`、
`intelligent_selection_pipeline.py`、`auto_trade_pipeline.py`、`rebuild_factor_ic.py` 等
（实测仅被 output/diagnostic、mainline/docs 历史报告引用，无 cron/生产代码引用）——
属 code-reviewer-fat 三档清理清单（任务 #9）覆盖范围，**不占白名单名额，建议直接清理**。

---

## 五、D9 报告「6025f3ed 已 commit」认知更正（实数核实）

1. commit `6025f3ed`（2026-10-09）**存在**且是 HEAD 祖先——我 L3 报告初稿称「本仓不存在」，
   **那句是错的，以此为准更正**。
2. 但该 commit **刻意没有包含** `scripts/auto_live_pipeline.py`：commit message 原文
   「gitignored(盘上): scripts/auto_live_pipeline.py (SOUL#9收窄源真, 已scratch备份)」，
   当时把盘上文件和 `scratch/pre_commit_backup_20261009/` 当作唯一副本。
3. **该 scratch 备份目录现已不存在**（实测 `scratch/` 整个被清掉）⇒ 该文件自 10-09 起
   至今没有任何 commit 级副本，历史备份链也断了，只剩工作区文件。
4. D9 报告「`:254 import / :319 调用` 已 commit」的表述应更正为：**接线代码在盘上、
   从未入库**；且该次接的只有主板白名单半边（commit message 明言「主板前缀白名单」），
   ST/退市半边（传 name）直到本次 L3 才补上——这与闭环审查「实盘侧只完成一半」的结论互证。

---

## 六、给老大的选择题（建议）

**方案 1（推荐，最小改动）**：`.gitignore` 白名单补 A 级 16 个文件（逐条 `!scripts/xxx`
带注释，与现有白名单风格一致），B 级 7 个单独议；C 级走清理不补。
**方案 2**：把 `scripts/*` 改为 `scripts/*.tmp` 之类精确排除、全量入库 396 个——会把大量
死代码一起入库，不推荐。
**方案 3**：维持现状，但把 A 级文件手工同步到一个 tracked 的 `scripts_prod/` 镜像目录——
制造双源，不推荐。

无论选哪个，`scripts/auto_live_pipeline.py` 是实盘唯一选股路径（daily_pick.py 已 import 它），
**换机/重clone 后 cron daily_pick 会直接 ImportError**，这一条建议优先。
