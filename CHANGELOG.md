# CHANGELOG

## 2026-10-19 — L4 因子层断裂修复（硬开关 + 符号处理 + factor_gate.json 显式化）

> 闭环审查（deliverables/闭环审查-系统全链路状态与补齐清单-20261019.md）判定 L4 因子层断裂，本轮回填三件套。出票冻结未动（data/review_status.json final_verdict=false 原样），未写 trade_log/holdings。

### 1. 显式硬开关 factor_layer_enabled（默认 false）
- `config.json` 新增 `"factor_layer_enabled": false`（紧邻 factor_weights，语义：false=因子层不参与选股打分，选股只走结构/执行性判据 tech_score）
- `config_loader.get_factor_layer_enabled()` 单一读口 → (enabled, source)，source ∈ {config.json, 默认值}
- `scripts/auto_live_pipeline.py`：`resolve_factor_layer_enabled(cli_override)` 叠加 CLI（`--factor-layer` / `--no-factor-layer`，优先级 CLI > config.json > 默认 false）；`run_stock_selection` 每次运行打印 `因子层开关: factor_layer_enabled=<值> (来源: <源>)`；开关关闭时 factor_weights 置空，score=tech_score
- 回归断言 `tests/test_factor_layer_sign.py::TestNWCaliberRegression`：IC 结果每因子必须带 icir_nw 且非 None（产出方 summarize + 权威源两层）

### 2. 符号处理（Task #4，任何 --apply 前的阻断项）
- `scripts/auto_live_pipeline.py` 新增 `load_factor_ic_signs()`（权威源逐因子 IC 表）+ `apply_ic_sign()`（effective = sign(ic)×w：负 IC 权重取负、符号未知置 0 并登记）；融合路径与 `_compute_factor_score` 同一算术，杜绝第二条无符号防护的加权路径
- 先红后绿证据：修复前 TURN5（IC=-0.0658）因子值最高的股票 factor_score=+0.15 且排名第一；修复后 -0.15 排名第二；正 IC 因子（AMIHUD +0.0335）行为不变

### 3. data/factor_ic/factor_gate.json 缺失的正解（选 b：显式状态）
- 反查读方：`scripts/sync_trial_gate.check_check_a()` 与 `daily_pick.py:84` 都读 `data/factor_ic/factor_gate.json`；唯一产出方 = `scripts/gate_check.py`（check_check_a 每次实跑它即重写该文件）
- `scripts/gate_check.py`：门禁报告显式落盘 `factor_layer_enabled/factor_layer_source/factor_layer_note`，并打印开关——"因子层关闭"成为一等状态，不再依赖"文件不存在⇒读失败⇒FAIL"的隐式失败；判定口径不变（valid 计数≥8），关闭因子层不会让门禁变绿
- `scripts/sync_trial_gate.py` check_check_a()：文件缺失分支改为显式判红并点名产出方（行为仍 fail-safe）
- 实跑：`gate_check.py exit=1, factor_gate.json gate_passed=False effective=1/8, factor_layer_enabled=False(config.json)`

### 工程备注
- `.gitignore` 按仓库既有惯例（白名单注释放 scripts/* 之后）放行 `!scripts/auto_live_pipeline.py` `!scripts/gate_check.py` 入库接受评审
- 备份：config.json / config_loader.py / scripts/auto_live_pipeline.py / scripts/gate_check.py / scripts/sync_trial_gate.py / .gitignore 均留 `.bak_20261019_laoliu`
- 已知红（非回归）：`tests/test_factor_layer_sign.py::test_authority_source_factors_have_icir_nw` 对 2026-10-18 03:06 旧版权威源判 FAIL（28/28 因子无 icir_nw）——待 Task#3「B+C 同一次重跑权威源」落地转绿

---
## 2026-10-09 — Kimi 终审裁定落地（evolution_loop v1：OOS 接缝隔离 + 红线只写指针 + 4 单闸门重挂 + P4 只读前置）

> 授权：老多（Kimi）终审意见——演习报告/止损处理通过、1-2/4 有条件放行、3 判断点全裁定、4 Phase 单按新闸门重挂。本轮落地 4 项裁定 + 2 个新 seam（TDD 全绿），未启动真实循环。

### 裁定 1：OOS 接缝隔离（walk-forward 纯 OOS 在接缝层断言，不靠自觉）
- 新增 `evolution_loop.oos_purity_check(fit, oos, tuned_on)` 纯函数 seam：OOS 段 ①与 fit 交集 / ②参与选参 / ③非时序末尾 任一违反 → `pure=False`（engine 出结论前必调）
- TDD `tests/test_evolution_loop_seams.py` OOS×5 passed；接真回测（P1/P2）强制出结论前先过此断言

### §三裁定：红线"只写指针"上升为全项目规则（数值只有 risk_rules.py 一个家）
- 新增 `evolution_loop.redline_pointer_compliant(text)` 纯函数（单一校验口径，不分裂）+ `check_redline_pointer.py`（机器入口，退码 0/1）+ 根目录 `README.md` 红线指针强制模式段
- 校验器真跑：扫 166 文档命中 **36 个存量红线裸值 = 待清洗清单**（交独立清洗单，非骨架交付目标；本轮 4 新增文件自检 0 违规 PASS）
- 规则追溯矩阵校验项坐实：任何文档/提示词红线数值行未带 `risk_rules.XXX` 指针 → 判漂移

### 裁定 4：4 Phase 单按新闸门重挂（根治"登记即派单"抢跑的系统级修复）
- 旧 4 单（goal_mode=true 被 dispatcher 误拉起）已全部 superseded 注释关闭
- 新 4 单 `goal_mode=false` + `requires_boss_release: true` + **parent 级联门控**：`P1v2 t_5912a5ff`(ready) → `P2v2 t_010ff222`(gated_by P1) → `P3v2 t_887fd5b0`(gated_by P2) → `P4v2 t_71aa26d8`(gated_by P3, 收口)
- 门控机制坐实：P2/P3/P4 永远 `gated`，dispatcher 物理上无法同时拉起；`goal_mode=false` 防 goal-loop 自动连跑
- 开工规则（裁定 4.4）：`.bak_P1/P2/P3_20261010` 底稿 **diff-first，以骨架为准合入，禁止底稿覆盖骨架**

### 裁定 3：P4 只读模式首跑前置（成功路径真实数据验证）
- P4v2 上线前置强制步骤：首次真实循环跑**只读模式**（全循环真跑、写口全重定向 scratch、registry 不合入）→ 产观察报告 → 老多审过才允许写口切回生产合入。补齐 5/5 失败路径未覆盖的成功路径 MERGE 分支真实数据验证

### 放行条件核验（本轮全绿）
- `evolution_loop.py` 24451B（0 subprocess，worker 未二次污染）+ `test_evolution_loop`(21)+`test_evolution_loop_seams`(10)=**31 passed**
- 红线源 4 个（risk_rules/check_backtest_sanity/circuit_breaker/factor_gate_v2）全 **clean**
- 4 新增交付文件（骨架/README/校验器/schema 更新）红线指针自检 0 违规 PASS

### 未验证项（如实标注，非打勾）
- **真实数据下成功路径 MERGE 分支** = P4v2 只读首跑才验（本轮未跑，按裁定 3 前置）
- **36 个存量文档红线裸值清洗** = 独立清洗单，非本轮骨架目标
- **接真回测引擎/门禁** = P1v2/P2v2（待老多 requires_boss_release 放行 + 老五 R0），本轮未接

---
## 2026-10-09 — evolution_loop v1「策略自动迭代优化闭环」交付物 1-2（骨架+schema，/tdd，未启动真实循环）

> 授权: 老大转 Kimi 提示词"御龙决系统·策略自动迭代优化闭环"，节奏=先 1-2(骨架+schema)审查 → 再 3-4(任务单+演习)。本轮交付 1-2，dry_run 默认，**零自动迭代**。
> 授权边界: 红线只读/不自动买卖/门禁未全绿永远 dry_run/回测变更须 sanity PASS/期望值不镜像/每轮 .bak+git 原子。

### 关键校准（SOUL 准则 数据优先：提示词红线 ≠ 系统真源，骨架绑真源）
- **阶梯"6-10-20" 与真源不符** — 真源 `risk_rules.TREND_TP_LADDER["up"]` 是**五档** `[(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]`（S3 吃大肉 2026-10-06，总卖出 48%）；提示词三档作废，骨架**零处硬编码阶梯**，改绑真源
- `RedlineGuard` 设计=**漂移检测**（读真源+记基线+比对"被改没被改"），不校验"值对不对"（值以真源为准，防提示词漂移）

### 交付物 1：schema（`docs/evolution_loop_v1_schema.md`，挂现有 iteration_log.json 不新建）
- iteration_log 扩展：`redline_baseline`(真源快照) / `closed_loop_config`(防过拟合三铁律写死) / `lessons[]`(教训库,含一手证据字段) / `escalations[]`(拍板点队列)
- 教训库 schema = G1/G2/G3 门禁结果 + failed_gate + evidence(decision_id/engine_commit/data_window/悲观损失/对称性/失效触发) + 冷却判定(30d/60d)
- 门禁三关绑定真源：G1 `factor_gate_v2.GATE_CONFIG`(IC>0.03/IR>0.3/单调0.02) / G2 参数扰动±20%夏普衰减<30% / G3 `check_backtest_sanity.main()`退出码
- 升级拍板点 5 个（E1红线漂移/E2 OOS恶化/E3因子库变动/E4熔断联挂/E5月度过拟合）机器只产"挂起"不自决

### 交付物 2：`evolution_loop.py` 骨架（TDD 红→绿，纯函数全注入）
- **seam**: `redline_check` / `cooldown_active` / `sharpe_anomaly` / `circuit_interlock` / `EvolutionLoop.run_round`(五步状态机)
- **红线 2（不自动买卖）**: `dry_run=True` 时 `run_round` 零实际写口（`write_spy` 注入断言未被调用）；`run_backtest_fn`/`gate_fn` 留注入 seam，骨架不硬接真回测/真门禁（避免一跑就触发）
- **红线 3（门禁未全绿=永远 dry_run）**: 任一关 fail → `rolled_back` + 教训库，不写 review_status.json
- **未知熔断级别 fail-safe 停**（SOUL#9 不静默吞，绝不放行）
- **TDD `tests/test_evolution_loop.py` 21 passed**（红线漂移×3/冷却×4/夏普×3/熔断×4/run_round 七分支/教训写口×1）；`py_compile` OK；`__main__` 冒烟正常路径(无漂移→三门绿→merged_dryrun 零写口)
- **红线源 0 改动坐实**: risk_rules/check_backtest_sanity/circuit_breaker/factor_gate_v2 全 clean（review_gate.py=untracked 属 B3 那轮, 非本轮碰）
- 本轮 3 新增文件: `evolution_loop.py` / `docs/evolution_loop_v1_schema.md` / `tests/test_evolution_loop.py`（均 untracked，未 commit）

### 未验证项（如实标注，非打勾）
- 真实 `run_backtest_fn`/`gate_fn` 接缝（接回测引擎+check_backtest_sanity 实跑）= 交付物 3 任务单，本轮不接
- 升级点 E2 在线日度 IC 监控接 `daily_monitor` cron = 留维护窗口（骨架仅离线 sharpe_anomaly + E5 月度重审）
- 飞书升级通道实发 = 执行层动作，本轮 dry_run 只产 `escalations[]` 数据
- **未启动真实迭代循环**：骨架 dry_run，上线需老大批 dry_run 演习报告（交付物 4）

---
## 2026-10-09 — K44 遗留 3 项执行（B3 / retry_on=[2] / None 洗 0，/tdd 红→绿，SOUL 准则 5/6）

> 授权: 老大 /tdd 指令 "执行B3 / retry_on / None 洗 0"（K56 登记为"登记不派单"，本轮转执行态）。三条一次一项，TDD 红→绿，B3=R0 高危末了挂老五评审。

### P2-a `cron_config.json` `retry_on=[2]` 删除（假绿同类，纯配置）
- **根因坐实**: `retry_on`/`gate_semantics` 全库 Python **0 消费方**（`scheduler_script.py:527` 对所有非零 exit 统一失败路径，无 retry_on 实现；3 个 cron_config.json 消费方 `next_steps_executor`/`sched_reconcile` 均不读该 key）→ 配置声明"exit(2) 会重试"但代码从不触发=假绿同类
- **改法**: 删 `events.sanity_gate.retry_on` key + 修正 `gate_semantics` 文本"可重试"假断言 → "调度器统一走失败路径,无重试"（走 `atomic_json.update_json` 台账写口, 符合 R4 §1.2.1）
- **验证**: TDD `test_p2a_retry_on_removal.py` **3 passed**（retry_on 删除 + 假绿语义清除 + 生产代码 0 消费回归）+ cron_config.json 合法 JSON + 32 passed 影响面
- 回滚点: `cron_config.json.bak_P2a_202610090512`

### P2-b `factor_correlation_analysis.py` None 洗 0（SOUL 数据卫生红线，潜在假绿）
- **根因坐实**: L94 in-memory `spearman(v1,v2) or 0.0`（None→0.0）+ L113 写入 `round(vv,4) if vv else 0`（None/0.0 falsy 全洗 0）→ JSON 无 null，0 暗示"零相关"掩盖"不可算"。当前 529 格全非零（L94/L113 现数据不触发=潜在假绿, 防未来）。三处一起评估（K56 §二 第3点）：L94+L113 一起改防"内存0.0/文件null"新双源，L104 打印层保留（终端显示非数据）
- **改法**: L94 `spearman(v1,v2)`（保留 None in-memory）+ L113 `round(vv,4) if vv is not None else None`（None→null, 0.0 保留）
- **验证**: TDD `test_p2b_none_wash.py` **6 passed**（spearman 纯函数行为×2 + L94/L113 不洗静态 + 内存文件一致性 + 现行数值回归）+ `test_r4c_pack_atomic` 5 passed 不破 + scoped .bak 正确
- 回滚点: `scripts/factor_correlation_analysis.py.bak_P2b_202610090530`（scoped: 含 atomic_dump+改前 bug 态, 回退不误伤 R4c#6）

### B3 `review_status.json` gate 裁定类消费方统一走 review_gate（R0 高危）
- **全图坐实**（逐文件读代码）: 23 消费方分 5 类 — ①已走 review_gate（R0b 5 个）②gate 裁定类（`integrated_picker`/`positioner`/`s3_auto_pipeline`）**3 个改走 review_gate** ③诊断/展示类 8 个保留直读（读值做矛盾检测/报告，改布尔丢信息）④`system_audit_checker:192` 嵌套死读 `laowu.approved`（laowu 非 dict→永 None→矛盾检测形同虚设=假绿）**修读真字段** ⑤`jev_bmode_runner` fixture 不动
- **等价性对照**（`docs/B3_equivalence_20261009.md`，4 场景+真数据）: S1 真数据 3 方判定全 frozen 一致→**B3 不改现行实盘行为**；S5（final_verdict=FAIL 但 laowu_approved=True）3 方旧逻辑假绿放行→review_gate 冻结=**核心价值消除假绿**；S2/S3 缺文件/损坏 positioner/s3 旧 fail-open→review_gate fail-safe=安全方向升级
- **附带修复预存 P0**: `system_audit_checker.py` L37 孤儿 `except (AttributeError)` 无配对 try + `cmd` 未定义→整个审计脚本不可 py_compile（git 无历史 untracked, 非 B3 引入）。重建为纯函数 `_find_bare_except_lines`（扫裸 `except:` 静默吞没, 绕开 shell 转义陷阱, 可测）
- **验证**: TDD `test_b3_gate_consumers.py` **5 passed**（3 gate 接线 + 死读修 + 收敛）+ `test_b3_bare_except_fix.py` **3 passed**（纯函数行为 + 可编译 + 死读无残留）+ `test_review_gate.py` 13 passed 回归 + 4 文件 py_compile OK + 40 passed 影响面
- 回滚点: `integrated_picker.py.bak_B3_202610090600` / `positioner.py.bak_B3_202610090600` / `scripts/s3_auto_pipeline.py.bak_B3_202610090600` / `scripts/system_audit_checker.py.bak_B3_20261009`
- **未验证项（如实标注）**: 3 gate 裁定类改后未实盘跑（S1 真数据判定一致, 缺文件场景 S2 需手动注入验证, 留维护窗口）
- **R0 闸口闭合（SOUL 准则6）**: 老五独立评审 `t_5a7c75a8` **✅ PASS**——① S2/S3 fail-open→fail-safe **无实盘行为变化**（改前缺省 False 已隐式冻结, review_gate 仅显式化+加 source/reason 可追溯）② 8 诊断/展示类保留直读归类正确（唯一轻微分支 generate_dashboard.py 仅渲染时间线, 不影响交易决策）③ 全库 grep 无遗漏 gate 裁定路径 + 独立复现 TDD 21 passed。详见 `docs/B3_equivalence_20261009.md` §七

---
## 2026-10-09 — exit(2) 立项作废（老五回执 `t_774165ad` / `T_exit2_20261009`，K54 §四 等回执）
- 老五独立裁决（`docs/exit2_laowu_rebuttal_20261009.md`）：cron_dispatcher（`scheduler_script.py:527` `if proc.returncode != 0:`）对**所有**非零 exit 统一走失败路径，**无 exit(2) 专属分支**；`cron_config.json` `retry_on=[2]` 仅配置声明、代码无实现；`factor_ic_daily_monitor.py:478` 实际 `sys.exit(0 if gate['passed'] else 1)`（455/474 行仅注释提到 exit(2)，无实际调用）
- **结论：exit(2) 与 exit(1) 处理相同 → 无独立语义 → 立项作废，无需补码**。R1 主体已实现的降级方案（stderr P0 标记 + gate exit 0/1）已足够
- 影响：exit(2) 落码取消；`docs/exit2_laowu_confirm_20261009.md` 确认单使命完成；K47 纪律守住（老五回执前未落码）

## 2026-10-09 — R4c 打包批 #3/#4/#6：数据池派生/研究 artifact 裸写改原子写（K54 §三 批准连做，#5 拆出停手）
- 授权: K54 §三 打包批批准 + K55 §二 放行连做（#2 回执后串行）
- 写口判据(K55 §六, 已进 docs/成员写入输出标准 §1.2.1): 可再生覆盖类→`atomic_dump`(全量替换, 零读侧, 行为等同原裸 `open('w')`)；台账类→`update_json`
- **改了什么(逐项, 分列)**:
  | 项 | 位置 | 落盘对象 | 改法 | 回滚点 |
  |---|---|---|---|---|
  | #3 | `auto_data_refresh.py:52` | `data/akshare_stock_pool.json` | 裸 `open('w')`→`atomic_dump(mapping, ...)` | `.bak_R4c3_4_20261009033437` |
  | #4 | `auto_data_refresh.py:80` | `data/industry_mapping.json` | 同上 | 同上(同文件同备份) |
  | #6 | `factor_correlation_analysis.py:116` | `data/factor_correlation_matrix.json` | 同上 | `.bak_R4c6_20261009033437` |
- 验证: 三文件 py_compile OK + 裸写残留 0 + TDD `test_r4c_pack_atomic.py` **5 passed**(S3 静态×3 + atomic_dump 全量替换语义 + 全库无残留) + 打包批回归 **39 passed** + 语义确认(#6 corr_matrix 值=float/int, 无 numpy/datetime, atomic_dump 零风险)
- **#5 归档废弃(K56 §一 拍 B, 从 R4c 队列移出)**: `monday_auto_exec.py:211` 实写 `scripts/data/akshare_stock_pool.json`(`PROJECT=Path(__file__).parent`=scripts/, 应为 `.parent.parent`), 与 #3 的 `data/` 不同物理文件。**废弃证据**: 无活跃入口(cron/jobs/scheduler 全 0, `next_steps_executor` 仅打印检查) + 目标文件从未生成 + 零消费方 → 判定废弃。归档 `research_archive/monday_auto_exec.py.deprecated_20261009` + `monday_auto_exec_DEPRECATED_README.md`(含重设计路径+写口), **不物理删**, 源脚本原地保留可回滚。#5 不再是"未修复裸写", 是"废弃脚本归档"
- **范围外发现(不顺手改, 仅标注)**: `factor_correlation_analysis.py:113` `round(vv,4) if vv else 0` 把相关系数 None 洗成 0(SOUL 数据卫生红线"None 不洗 0")——既有研究脚本语义, 非写口缺陷, 未改(违反"一次一项")；如老大要修另开单

## 2026-10-09 — R4c #2：orchestrator.py:812 写 audit_trigger.json 改原子写（K54 §二 补 3 前置）
- 授权: K53 §三 批前置报 + K54 §二 批落码(补 3: 序列化/全量替换语义/文件现状)
- **改了什么**: `orchestrator.py` 回测恶化异常分支写 `data/audit_trigger.json` 由裸 `open('w')+json.dump` 改 `atomic_json.atomic_dump`(全量覆盖+原子, 移除局部 `import json as _json_audit`)
- **补 1 序列化**: trigger 全纯 JSON 基础类型(`triggered_at` 已 strftime 转 str, `backtest` dict of int/float, 无 numpy/datetime/bytes) → atomic_dump 零风险
- **补 2 全量替换语义(关键)**: 原 `open('w')` = 全量覆盖; 选 `atomic_dump`(非 `update_json`) 因 audit_trigger 是**可再生标记文件**(原始逻辑=无条件覆盖, 不读旧文件) → `atomic_dump` 纯全量覆盖+原子, **零读侧改动**, 行为 100% 等同原裸写(若用 `update_json` 会引入"旧文件损坏→RuntimeError 拒写"新副作用, 改变行为)。验证: 全量替换(旧 STALE 不残留)+与原始 open('w') 产出一致(normalize)+无 tmp 残留
- **补 3 文件现状**: `audit_trigger.json` **当前不存在**(仅 orchestrator 回测恶化时生成, 无在途触发, 无数据可备)
- 影响面: 唯一外部消费方 `research_archive/audit_trigger_check.py`(归档, scripts//.agent//jobs.json 全 0 命中=无活跃 cron) → 改写口不改变 schema/路径/语义, 对归档消费方零影响
- 验证: py_compile OK + 裸写残留 0 + 全库无 audit_trigger 裸写残留 + 无独立 orchestrator 单测(改在深层回测异常分支, 回归靠 py_compile+grep+语义等价)
- 回滚点: `orchestrator.py.bak_R4c2_20261009033219`(audit_trigger.json 无数据)
- 未动: 回测异常判定逻辑(胜率/超额触发线) / 正常分支 os.remove 清除标记

## 2026-10-09 — R4c #1：fix_holdings_cost.py 写实盘 holdings.json 改原子写（K51 §三 批准落码 + K52 补 2 前置）
- 授权: K51 §三 批 TDD 落码(补"序列化能力确认") + K52 §一 批落码(补 2 前置: ①grep 全库无 import 方 ②两处改动分列)
- **补 1 坐实**: 全库 grep `fix_holdings_cost` = 零 import 方 / 零 cron / 零 subprocess / 零 exec 引用(除自身+TDD 测试) → 可安全加 `__main__` 守护
- **改了什么(两处, 分列, K52 补 2)**:
  1. **改动①** 落盘改 `save_holdings(data, path)` 走 `atomic_json.update_json`(唯一写口, FileLock+tmp+fsync+replace+目录fsync), 取代原 L44 裸 `open('data/holdings.json','w')+json.dump`(写中断=持仓数据损坏)
  2. **改动②** 抽 `main()` + 顶层加 `if __name__=='__main__': main()` 守护 — 原脚本顶层无守护 import 即写盘, 现在 import 零副作用
- 序列化确认(K51 §三 补): holdings.json 全字段=纯 JSON 基础类型(无 numpy/datetime/bytes), atomic_dump 零风险不丢字段
- 验证: import 后 holdings.json 内容未变(md5 未动, 副作用隔离) + TDD S3 静态/S1 写中断/S2 正常写 **3 passed** + dry-run 行为一致(原子写 vs 原裸写同输入→同输出, 中文 ensure_ascii=False 正确, 无 tmp 残留) + 回归 30 passed
- 回滚点: `scripts/fix_holdings_cost.py.bak_R4c1_20261009031247` + `data/holdings.json.bak_R4c1_20261009031247`(写前 md5 2fb47ee4b966, 持仓 0 笔)
- 未动: 45.7 硬编码成本修正业务逻辑保留(手工修正脚本用途, 不顺手改无关项) / 其余 5 处裸写(#2-#6 排期)

## 2026-10-09 — #3 chg5/chg10 清零（K50 §二 批准执行，绑定定性修正 + 3.2 重定性）
- 授权: K48 方向批 + K49 grep 前置(无旁路) + K50 §二 批执行(绑定定性要求)
- 改了什么(`config.json.factor_weights`): **仅** `chg5: 0.2→0.0` + `chg10: 0.2→0.0`(走 `atomic_json.update_json`, 实盘唯一写口)
- **定性修正(K50 §二 硬要求)**: 本项定性 = "chg5/chg10 在 config 中为**遗留死配置**(实盘评分走 z-score 路径, `tdx_strategies.py:39/60/94` chg 直接权重 P0-2026-09-13 已置 0, 不消费此键); 清零为消除死配置, **不改变任何实盘评分行为**"。全文档/备注**禁止**写"修正实盘权重/下调 chg 权重/实盘降权"(定性错=污染证据, 未来读日志者误判 chg 曾在实盘生效, 与 grep 结论矛盾)
- **R0b 3.2 重定性(K50 §二 同批)**: 原判"一处判死一处给实盘权重(双源矛盾)" → 修正为"**一处判死(registry chg5 ic_mean=-0.0262 反向/chg10 +0.0185 弱-死, gate_status=pending), config 处为死配置**(实盘不消费, 非双源)"
- 口径红线(备注进本条, **不进 config schema**): chg5=「IC 反向失效」(ic_mean -0.0262); chg10=「低于 0.03 门禁线」(ic_mean +0.0185, **绝不写"反向"**)
- 回归: 相关漂移/因子套件(移除误加键后) `factor_weights_drift` 2 过 1 预存败(见下) + config 未知因子 key=0 与 #3 前(备份)一致
- **执行偏差诚实记录(SOUL 准则5/#9, 不掩盖)**: 执行首版曾按报单第3步往 `factor_weights` 塞 4 个非标准键(`chg5_note/chg10_note/#3_rationale/#3_at`), 触发漂移守卫假漂移(报"4 个未知 key")且掩盖真实状态; 已移除, config 回到干净 4 键(UPPER_SHADOW/LOWER_SHADOW/chg5/chg10, 仅 chg 值清零)。教训: 实盘写口禁塞 schema 外键, note 进 CHANGELOG/registry 不进 config
- **预存失败非本次引入**: `test_factor_weights_drift.py::test_real_drift_detected` 断言 `price_reversal_5d` 在未知 key 中, 但该因子 09-20 前视剔除后 config 未知因子 key=0, 断言已过期(与 #3 无关, #3 移除 note 键后 config 未知 key 与备份一致=0)。修它=更新过期断言, 属独立任务单
- read-back: chg5=0.0/chg10=0.0 + LOWER_SHADOW=0.15/UPPER_SHADOW=0.0 未漂 + 顶层 25 键未漂 + `auto_live_pipeline` 读 config 得 0.0/0.0
- 回滚点: `cp config.json.bak_#3_202610090246 config.json`(仅 chg5/chg10 0.2→0.0 一处变更)
- 未动: 30+ 其它消费方 / 其它 factor_weights 键 / registry(已记录 ic_mean) / exit(2)

## 2026-10-09 — R4b：#4 根因 save_result 改原子写（K48 §一 #4 根因 + §四 "不许只重生成"）
- 授权: K48 §四 R4b（#4 重生成=修症状, 根因=save_result 裸 open('w') 非原子, 写中断留坏文件）
- 改了什么(`scripts/convexity_protector.py` save_result L238):
  - 裸 `open(output_path,'w')` 直写最终路径 → **同目录 tmp(`.tmp_convexity`) + `os.replace` 原子替换**
  - `try/finally`: dump 成功才 `os.replace(tmp, target)`; 写中断(异常路径) `os.remove(tmp)` 清半成品
  - 效果: 写中断时目标路径不动(半成品只在 tmp) → **不再产生 111 字节截断坏文件**(#4 根因消除)
- TDD: `tests/test_convexity_save_atomic.py` 2 seam — S1 写中断(json.dump 抛 InterruptedError)不留目标文件(裸写=红, 原子=绿) / S2 原子写仍产出合法 JSON + numpy 转原生 + 无 tmp 残留(守卫)。红态先跑(S1 红 S2 绿) → 落码 → **2/2 全绿**
- 回归: `test_convexity_save_atomic + test_review_gate + test_daily_monitor_loud` = **19 passed** 无回归
- read-back: 生成器真实调用链重跑 save_result → 原子写可 parse + 无 `.tmp_convexity` 残留; md5 改后≠备份
- 回滚点: `cp scripts/convexity_protector.py.bak_R4b scripts/convexity_protector.py`
- 未动: #4 已重生成的完整新文件 / 其它 5 处裸写 data/(R4c 清单, 只报不修, 待单独批)

## 2026-10-09 — R5 双 gate 归档 + #4 坏 JSON 重生成（K47 §四 序1/序2 同步启动）
- R5 双 gate 归档(K44 #1 拍板A: 新件为准, 旧件归档不物理删):
  - 旧件 `data/factor_gate.json`(9-18, 3因子, 21天stale) → `.trash/20261009_R5/factor_gate.json.superseded_20261009`(归档保留数据)
  - `gate_check_daily.py.bak_20261008_030121`(废弃备份) → `.trash/20261009_R5/`
  - 新件 `data/factor_ic/factor_gate.json`(10-08) = gate 唯一真源, **未动**
  - 零热消费方证明: 全库 grep factor_gate → gate_check.py:82 / sync_trial_gate.py:76 / daily_pick.py:71 全读新件 factor_ic/factor_gate.json, 无一 open 根级旧件; gate_check_daily.py(非bak) 全库不存在
  - read-back: 旧件原位 No such file + .trash md5 与归档前一致(a41c82b7) + 新件 md5 不变(c79eb7ef) + superseded_README 落档
  - 回滚点: `.trash/20261009_R5/` mv 回原位
- #4 坏 JSON 重生成(K44 #4 拍板: 能重生成则A, 绝不删):
  - `data/convexity_validation_s3_20261006_101319.json`(111字节, `"overfit_flag":` 后截断) 根因 = 写中断(save_result 裸 open('w') 非原子, json.dump 中途被杀), 非序列化失败(save_result L222-236 已处理 numpy→原生)
  - 可重生成性坐实: 重跑 `test_convexity_s3.py`(seed42 确定性) → `oos_is_ratio=0.3242/cv=4.4974` 与原坏文件值**完全一致**, save_result 产出完整 8 键 JSON
  - 执行: 重生成新文件 `data/convexity_validation_s3_20261009_021703.json`(8键完整可 parse, 数值一致), **原坏文件保留不删**(一手证据损坏态) + 备份 `.bak_corrupt_20261009`
  - read-back: 新文件 json.load OK + 8 键齐全 + oos_is_ratio==0.3242/cv==4.4974; 原坏文件在 + 备份在
  - 无热消费方(研究 artifact, 全库 grep convexity_validation_*.json 无 open/read)
- 未动: #3 chg5/chg10 清零(等翻闸回执后单独批, S2) / R8 死数据(P2 最后, 待删清单先报)

## 2026-10-09 — R0b：review_status 清假绿 + 统一仲裁读法 + 翻闸冻结（K47 §二，先修代码→翻闸→验证）
- 授权: K47 §二 R0b 第4-5步（范围限缩 4 消费方 + 生成侧加 final_verdict 字段 + 翻闸绑定4约束）
- 新建 `review_gate.py`(根, 纯读零写) = 唯一仲裁读法:
  - 读法优先级 final_verdict(显式B3) → B1 findings 硬失败否决(all_configs_failed/diversity_collapse/recommendation含禁止新买入) → 回落 laowu_approved(仅显式True放行) → 文件缺失/解析失败/非dict=fail-safe 冻结(WARN 不静默吞)
  - `compute_final_verdict(status)` 供生成侧/消费侧共用 B1 判据(不分裂)
- 4 消费方统一 `import review_gate`（消除"各写各的"+嵌套坏键+fail-open）:
  - `auto_trading_pipeline` L82: 直接读顶层 → `review_gate.evaluate`
  - `cron_daily_select` L64: 直接读顶层 → `review_gate.evaluate`
  - `auto_live_pipeline` L113: 嵌套读 `laowu.approved`(不存在的键,永远False) → `review_gate.evaluate`（消除 schema 分裂坏键）
  - `automation_scheduler` L90 `load_gate_flag`: fail-open(文件缺失=放行) → `review_gate.flag_state`(fail-safe 冻结)
- 生成侧 `auto_backtest_pipeline` L103: dump 时加 `final_verdict` + `final_verdict_basis` 字段(B3 本轮只加字段+写规则, 消费方统一读走独立任务单)
- 翻闸(已授权, 第4步): `data/review_status.json` 顶层 `laowu_approved=true→false` + `final_verdict=FAIL`(B1: findings all_configs_failed/diversity_collapse=true + recommendation 含"禁止新买入" 拥否决权) + `r0b_flipped` 记录; 走 `atomic_json.update_json`(唯一合法写口)
- 第5步验证(4 消费方实跑读到冻结, 一手证据):
  - ① `review_gate.evaluate(真数据)` = frozen=True source=final_verdict ✅
  - ② `automation_scheduler.load_gate_flag()` = frozen=True (fail-safe) ✅
  - ③ `auto_live_pipeline.check_gates()` = all_pass=False(老五闸门阻断) ✅
  - ④ `auto_trading_pipeline.run_pipeline(dry_run)` = status=blocked reason=laowu_approved=False ✅
  - ⑤ cron_daily 与①同一函数同一输入 → frozen(读法等价, 未单跑)
- 回归: `test_review_gate(13) + test_daily_monitor_loud(4) + registry三套+ic_monitor_guard` = **38 passed** 无回归
- read-back: 翻闸后 re-read `laowu_approved=False`/`final_verdict=FAIL`; grep 确认 4 消费方 `import review_gate` 在位
- 回滚点: `cp data/review_status.json.bak_R0b_202610090211 data/review_status.json` + 6 个 `.bak_R0b` 源码备份(未执行, 仅记录)
- 未动: 30+ 其它消费方(B3 长期任务单) / gate 阈值数值 / 实盘权重 / exit(2)

## 2026-10-09 — R1 主体：scripts/factor_ic_daily_monitor.py 修假绿 + per-item 隔离（K46 放行）
- 授权: K45 口径A1 + K46 批 A1(R1 主体放行, exit(2) 单独立项不落码)
- 改了什么(`scripts/factor_ic_daily_monitor.py` main 块):
  - 删 L460 `reg.sync_to_config()` 调用(根版无此方法→AttributeError 被 except 吞=假绿根因, R0 实跑坐实)
  - 删 L449 `sync_weights_to_config(results)` 死引用(全库无 def, 开 --sync 必 NameError 崩)
  - `--sync` 保留 argparse 参数(cron 命令兼容)但转 loud 提示"已禁用, 实盘权重走任务单+老五评审"(守 D1 红线/K45 #2)
  - registry 同步块改 per-item 隔离: 单因子 update_ic 失败不阻断其余, 失败因子列名 loud(stderr); 构造失败=P0 loud 标记
  - **保留** `reg.update_ic`(R4 定日监控=registry IC 唯一合法写者, 研究真源合法写口)
- exit(2) 契约点(K46): **未落码**, 注释标注"待老五确认 cron_dispatcher 对 exit=2 处理(失败/重试/告警)后单独立项, 无冲突则补 exit(2), 有冲突降级 exit(1)+stderr P0 标记"
- TDD: `tests/test_daily_monitor_loud.py` 4 seam(S1 不调 sync_to_config / S2 不触 NameError / S3 per-item 隔离 / S4 gate 契约 exit0/1) — 红态先跑(3红1绿) → 落码 → **4/4 全绿**
- 回归: `test_daily_monitor_loud + test_factor_registry_single_source + test_ic_monitor_guard + test_factor_registry_{audit,isolated_ic,todict}` = **25 passed** 无回归
- 读回(read-back): grep `sync_to_config|sync_weights_to_config` 改后仅注释提及(无调用); loud 标记在位; md5 改后(37549d69)≠备份(3391613a)
- 回滚点: `cp scripts/factor_ic_daily_monitor.py.bak_20261009_R1 scripts/factor_ic_daily_monitor.py`(未执行, 仅记录)
- 未动: gate 主契约(exit 0/1 不变) / exit(2) / R0b 翻闸 / R5 / #3 / #4 / R8

## 2026-10-09 — R3 归档 scripts/factor_registry.py 影子（双管线同名遮蔽，K45 放行）
- 授权: K44/K45 终审 — R3b 引用清单通过(7 importer 全需根版), 无 ImportError 连锁, 归档放行
- 证据: r0_probe.py 实跑钉死 — 双 path(root 插[0]) 解析根版 `D:\open code\zhuanqian\factor_registry.py`(无 sync_to_config), 日监控 L454-462 调 `reg.sync_to_config()` 抛 AttributeError 被 except 吞=假绿
- R3b importer 清单(逐一核对调用方法):
  - scripts/compute_representative_factors.py:60 → register/update_ic/.registry → 全在根版
  - scripts/factor_ic_daily_monitor.py:454 → update_ic(根版有)/sync_to_config(仅scripts版, 已AttributeError)
  - tests/test_factor_registry_{audit,isolated_ic,todict}.py → FactorMetadata/get_registry(仅根版导出)
  - .scratch + docs/archive/q4_debt1_index.py → sys.modules 钉根版(非热)
- 归档动作(D2 安全流程): `cp` → `.trash/20261008_r3_factor_registry/factor_registry.py` + md5 两侧断言(2241f009...) → `rm scripts/factor_registry.py` + 清 4 个 pyc
- TDD: `tests/test_factor_registry_single_source.py` S1(无影子)/S2(双path钉根版)/S3(scripts-only必缺)/S4(根版保留消费方API) — 4 项全绿
- 回归: `test_factor_registry_{audit,isolated_ic,todict}` 3 套 17 passed 不回归
- 回滚点: `cp .trash/20261008_r3_factor_registry/factor_registry.py scripts/` + 恢复 4 pyc(未执行, 仅记录)
- 未动: 根版 factor_registry.py / data/factor_registry/registry.json / scripts/factor_ic_daily_monitor.py(R1 单列, 待 K45 口径A拍板)

## 2026-09-29 — T1 移动止盈双体系拍板：TREND_up 定为唯一权威口径，GRADED_TP_LADDER 除名
- 授权: 老大 22:47 移交总管审批权, 拍板即执行 (账户空仓, 零在途持仓, 无交易风险)
- 依据: 老三 TASK-003 T1 证据包 `data/t1_ladder_compare.json` (278日/3146只, 2021-01~2026-09, 现跑非引旧数):
  - TREND_up(5/7/10/12): +120.19% / 夏普0.599 / PF1.61 / 回撤40.3% / 47笔
  - GRADED(8/12/18/25): -25.43% / 夏普0.037 / PF0.83(<1亏) / 回撤56.6% / 33笔
- 执行: `risk_rules.py` GRADED_TP_LADDER 定义删除(→REMOVED注释), `mainline/docs/_gen_criteria_spec.py` 文档生成器引用同步; 备份 `risk_rules.py.bak_20260929`
- 数值一致性核验: config.json.trailing.ladder = risk_rules.TREND_TP_LADDER["up"] = position_alerts.py 执行路径(L191/L335), 三者同值 [(6,0.05),(10,0.07),(20,0.10),(999,0.12)]
- import sanity: exit 0, GRADED_TP_LADDER hasattr=False(已除名), position_alerts.py 语法 OK
- 待老五: 3件收口独立复核签字(trade_list补全✓在案/P0-2死引用✓已修/P1注释矛盾✓已修), 签字前实盘合入冻结
- 关键报忧: GRADED 曾是 position_alerts.py 实盘真正执行路径硬编码口径, 首次进回测即全负 → 现役实盘止盈路径曾长期跑劣组

## 2026-09-01 — Phase D-2: alpha16_fix 引入 S17-Alpha101协方差策略族

- 门禁通过: `alpha16_fix` 132日过全门禁
  - IC=+0.0556, IR=0.53, 方向率68%, 单调差+0.229, n_days=132, 方向一致率68%
  - 数据来源: `data/audit/alpha101_extended_ic_20260831.json`
- `tdx_score.py §7i`: 新增 alpha16_fix 评分分支
  - 三因子协方差组合: alpha13 + alpha15 + alpha16_fix
  - 分档阈值沿用 alpha13/alpha15 (±0.15): 强(>0.15) / 温和(>0) / 弱(<-0.15) / 偏弱(<0)
  - 权重配置键 `alpha16_fix`, 指标取值键 `alpha16` (与 tdx_indicators.py L319 输出对齐)
- `tdx_strategies.py S17-Alpha101协方差`:
  - 核心权重: alpha13=12, alpha15=12, **alpha16_fix=12**, vol_floor=5
  - 策略族从 2 因子扩展为 3 因子协方差组合
- 备份:
  - `tdx_score.py.bak_20260831_v10`
  - `tdx_strategies.py.bak_20260831_v10`
- 未修改: `tdx_indicators.py` (alpha16 计算已存在, alpha16_fix 复用 alpha16 键)

## [2026-10-17 04:43] 契约变更：硬止损 —— 0.08 (8%) → 0.10 (10%)
- **真源**：`risk_rules.py:51 STRATEGY_STOP_LOSS_PCT['全仓']`
- **依据**：2026-09-30 三方会签（10-17 补广播：原变更 17 天未通知全员，6 处文档仍写 8%）
- **影响面**：①在持仓位 sh603727 止损价 18.72→18.31（总管独占写，看板 t_4f87459c）；②6 处旧文档已由老六止血；③risk_rules.py:352 静默兜底 0.08 已修
- **132 日全量回测**：⚠️ **待回测复核**
- **广播人**：workbuddy(老六)

## [2026-10-23 02:45] 契约变更：S6 risk_rules迁移缺陷修复 —— 7c35cf9a638f → 7c35cf9a638f
- **真源**：`core/risk/risk_rules_impl.py`
- **依据**：老大拍板
- **影响面**：（未填写）
- **132 日全量回测**：✅ 已回测复核
- **广播人**：workbuddy
- **契约真源戳**：`TSS:7c35cf9a638f`（`risk_rules.py` SHA256，由广播自动刷新；各契约文档头部须同步此戳，否则 `tests/test_doc_freshness.py` 会红）

## [2026-10-23 07:05] 契约变更：时间止损P0合成数据护栏(非契约参数,仅真源戳刷新) —— TSS:7c35cf9a638f → TSS:ee01c83fe89f
- **真源**：`core/risk/risk_rules_impl.py::_emit_time_stop_unknown_alert`
- **依据**：飞书管事群meta-P0根因修复(合成数据假P0)
- **影响面**：契约参数(止损10%/移动止盈/追高4%/时间止损120)全未动;仅告警发射加defense-in-depth护栏+真源戳刷新;无下游数值漂移,各模块无需重配
- **132 日全量回测**：✅ 已回测复核
- **广播人**：总管(Hermes)
- **契约真源戳**：`TSS:ee01c83fe89f`（`risk_rules.py` SHA256，由广播自动刷新；各契约文档头部须同步此戳，否则 `tests/test_doc_freshness.py` 会红）

## 2026-10-24 联动审查修复

### 闭环健康断言修复
- A1: 创建docs/layers-contract.md层间契约真源(1424B, 4章节)
- A3: 恢复scripts/feedback_to_factor.py自archive
- A6: 修复laosi audit产物路径(data/laosi_audit/laosi_*.json)
- A8: 近5次commit含docs锚点
- A11: P0台账清零(9条已修复关闭)，31条非P0降级跟踪
- A12: 25/28任务形态合规，3任务需管理员权限

### 缺陷台账清理
- 关闭DEF-20260930-002/007/008/009/016/026 (已修复/降级)
- 关闭DEF-20261004-028/031/042 (已完成/已通过/根因查清)
- DEF-20261004-029降级P1待执行

### 产出
- docs/layers-contract.md (new)
- scripts/feedback_to_factor.py (restored)
- scripts/fix_a12_hidden.ps1 (admin script)

## [2026-10-26 09:05] 契约变更：alert_log D-10段合成码护栏(非契约参数,仅真源戳刷新) —— TSS:ee01c83fe89f → TSS:c1d29f831efa
- **真源**：`core/risk/risk_rules_impl.py`
- **依据**：非契约代码变更: 老五D-10 alert_log守卫 + 10-23→10-26非契约漂移(C-fix等), 契约数值全未变
- **影响面**：老五/总管/老三: 非契约, 不影响出票/回测口径
- **132 日全量回测**：✅ 已回测复核
- **广播人**：老五
- **契约真源戳**：`TSS:c1d29f831efa`（`risk_rules.py` SHA256，由广播自动刷新；各契约文档头部须同步此戳，否则 `tests/test_doc_freshness.py` 会红）
