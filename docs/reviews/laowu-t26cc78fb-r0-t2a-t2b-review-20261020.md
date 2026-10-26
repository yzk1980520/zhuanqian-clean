# 【评审报告】t_26cc78fb — T2a/T2b 因子断链重做 R0 独立复审（commit 3ddac836）

评审人：老五（数据回测专家，独立评审，不与老三协商）
时间：2026-10-20 15:40（复审全程 15:14–15:40，均为 10-20 一手实测，不采信自报）
口径：R0（回测引擎/评分函数/数据合并 = 最高风险级；实物证据，不信自报）
引擎声明：**当前主树工作区 HEAD=ce263a74；本单 5 文件与评分链路 6 文件在 3ddac836..HEAD 区间 git log 为空（逐字节未动）→ 行为等价 3ddac836**。唯一后续差异 = 891d0a78 删除 scripts/tdx_core.py（已核该文件为 re-export shim：`from tdx_data import …`/`from tdx_indicators import …`/`from tdx_score import …`，重导根目录符号，实现零变化）。
数据截至日：data/history_daily 9441 文件中 9436 个 mtime ≤ 10-19、6 个为 10-20（末 bar 抽样=10-14~10-19）；picks 产物 15:25:18。

## 结论：✅ 放行（本单可闭环；附 7 项观察/路由项 O1–O7）

---

## 一、契约验收项（逐条一手证据）

### AC#1 `python -m py_compile config_loader.py` → EXIT=0
- 命令：`.venv/Scripts/python.exe -m py_compile config_loader.py`
- 输出：`py_compile config_loader EXIT=0`（10-20 15:18 实测）✅

### AC#2 主树实测复跑 → EXIT=0 且 TOP10 factor_score 10/10 非零
- 命令（15:18 启动，15:25:18 完成）：`.venv/Scripts/python.exe -c "…from auto_live_pipeline import run_stock_selection; run_stock_selection(top_n=10, scan_range=3000, factor_layer=True)"`
- 日志：`data/picks_latest.json`（15:25:18）+ 存证副本 `docs/reviews/t26cc78fb_live_run_log_20261020_1525.txt`（md5 368c3633d365cef83fce016eda22de4a，151 行）
- 证据断言：
  - `LIVE_RUN_EXIT=0`（日志末行）✅
  - 日志 L4：`因子权重真源: factor_weights.json (version=2.6, updated_at=2026-10-20, 22键 / 4个活跃因子)` ✅（§4 声称行逐字复现）
  - picks_latest.json：`factor_weights_source = "factor_weights.json:weights (v2.6)"`、`factor_weights_count=22`、`factor_dead_universe=['overnight_sum20','momentum_20']` ✅
  - TOP10 factor_score 10/10 非零：sh600892=-3.5102 / sz000690=-3.9911 / sh600621=-4.0142 / sh600229=-1.4733 / sh600028=-2.8742 / sh601599=-2.129 / sh600026=-4.1602 / sz002232=-4.213 / sh600629=-3.5091 / sz000516=-2.4235 ✅（全负值 = 符号通道按 10-18 权威表负 IC 取负权重所致，属 Task#4 设计行为，非缺陷，见 O5）
  - 死因子双 loud 登记：stdout 告警（`[告警] 以下 2 个因子…compute_indicators 未产出对应键`）+ `scan_errors.factor_exceptions` 两条 `factor_dead_all_universe`（overnight_sum20 权重 1.6 / momentum_20 权重 -0.5，1498/1498 无键，z 全置 0）✅ 不静默吞
  - **有效候选 1498（非任务单 §4 声称的 2935）→ 见 O1（数字保真旗标，非引擎回归）**

### AC#3 回归 → "全绿"（按本单 §6 口径：H/I = 遗留，非本单引入）
- 命令：`.venv/Scripts/python.exe .agent/regression/__init__.py .`（15:19 实测）
- 输出：`汇总：PASS 17 / FAIL 3 / WARN 2`；A/B/C/D/E/G 全 PASS（G 组 48 因子 key 漂移守卫 PASS，含 v2.6 22 键基线）✅
- H 组 FAIL：walk-forward 衰减 0.7858（OOS 保 IS 21.4%）→ 归因独立核实：H 输入 `data/walk_forward_gate.json` mtime=2026-10-20 02:13:55（内 computed_at 同戳），**早于本单重做窗口（05:43 起）与 commit 3ddac836（06:07）**，且不在该 commit 的 11 文件内 → 归类**遗留** ✅（同意 §6 归类）
- I 组 FAIL（G6/G7）：独立溯源 = `scripts/guard_assertion_effectiveness.py` 对 `cron_message_sender.py` 的静态检查（`SUPPRESS_WINDOW_P0_MIN`/`_priority_of` 缺失）。核实：3ddac836 及后续 3 commit 均未触碰 cron_message_sender.py / scripts/closedloop_health.py（`git show --name-only 3ddac836 | grep -c … = 0`）；cron_message_sender.py mtime 05:14 早于重做窗口 → 与本单 3 文件交集为零 → 归类**遗留** ✅（同意 §6 归类）
- G 组 WARN（config.json↔factor_weights.json 不同步）：T2a 设计态（config.json factor_weights 段为 tdx_strategies.load_strategy() 独立通道，config_loader docstring 已声明），WARN 不阻断，见 O6。
- **R0 附加门禁**：`python check_backtest_sanity.py` → `结论: PASS — 全部通过`，`SANITY_EXIT=0`（15:20 实测）✅

---

## 二、复核清单 1–6（任务单 §1–§6）

1. **T2a 单源** ✅
   - 代码层：`git show 3ddac836 -- config_loader.py` diff 实证——旧版 `cfg = load_config(); return cfg.get('factor_weights', {})` 已删除，新 `get_factor_weights()` 读 `Path(PROJECT)/'factor_weights.json'` 的 `weights` 段；缺失/JSON 损坏/顶层非 dict/weights 缺失空/非数值 全部 `raise RuntimeError`（loud fail，禁静默回退）；`get_factor_weights_meta()` 复用校验后返回真源文档；`clear_config_cache()` 同步清双缓存。
   - 探针（缺文件 → RuntimeError，15:17 实测）：`mv factor_weights.json …_probe` 后 import 调 `get_factor_weights()` → `RAISED RuntimeError: Loud fail (因子权重单一真源缺失): D:\open code\zhuanqian\factor_weights.json 不存在。禁止静默回退 config.json`；还原后 md5 前后一致（9b1b9784386911e58f6452072e2abf7a）✅ 无副作用。
   - 损坏/非数值路径 = 代码审查实证（JSONDecodeError/OSError → RuntimeError；`float(v)` TypeError/ValueError → RuntimeError）。
   - 对照 `.bak_T2rework_20261017`（7309B，04:06）存在 ✅。
2. **v2.6 落地** ✅
   - `factor_weights.json`（15:16 解析）：version=**2.6**，n_weights=**22**，active={chg10:2.0, overnight_sum20:1.6, chg5:1.4, momentum_20:0.5}，**净和=5.5**，18 键置零，无非数值权重；顶层键 = [disabled_factors, effective_weight, evidence, metadata, note, total_weight, updated_at, version, weights]。
   - bak（`.bak_T2rework_20261017`）= version **2.5** / 20 键；bak 顶层污染键 {pos_vs_ma20, rsi14, std20, unlocked_pressure, vol_price_corr_20, vol_ratio} + 字符串键 `updated` 在现版**全部消失** ✅。
   - 键集血缘：bak 20 键 ⊂ 现 22 键；现新增 = {momentum_20, overnight_sum20}（新活跃因子进权重表）；bak 的活跃键中仅 chg10/chg5 在现版非零（=1.4/2.0），其余 14 个旧活跃键全部置 0 保留 ✅。
   - 起点血缘：active 4 因子 IC 起点 = `data/factor_ic/factor_ic_diagnostic_132d_exact_20261015_042130.json`（engine=pure_python_v10_exact_132d, n=85）：chg10 +0.0539 / overnight_sum20 +0.0428 / chg5 +0.0397 / momentum_20 +0.0382 —— 与 20d json 的 baseline_ic 段逐值一致 ✅（4/4 因子 |IC|≥0.03；IR 仅 overnight_sum20=0.3593≥0.3，其余 3 因子 132d IR<0.3 → 见 O3）
3. **假报修复** ✅
   - `scripts/auto_live_pipeline.py` L342-345：`print(f"因子权重真源: factor_weights.json (version={_fw_meta.get('version')}, …)")`，元数据 L596-599：`'factor_weights_source': f"factor_weights.json:weights (v…)"` + 显式 note（config.json 段不再是生产真源）；`_fw_meta` 来自 `get_factor_weights_meta()`（读 factor_weights.json，先触发 loud-fail 校验）——真源闭环 ✅。15:25 实测日志/产物断言与代码逐字一致。
4. **主树实测** ✅（见 AC#2；差异项归 O1/O2/O4）
5. **20d 对照重跑** ✅
   - `data/factor_ic/t2b_gate_20d_check.json`：mtime=generated_at=**2026-10-20 05:57:34**（原件归档 .bak_T2rework_20261017 存在）；每因子 n_days=**27**；summary=PARTIAL_FAIL（3 CONFLICT + 1 PASS）→ adjudicated=**ALL_4_RETAINED_PER_132D**。
   - 数值核对（20d vs 132d，逐值对照文件）：chg10 -0.037352 vs +0.0539（方向翻转，保留率 69.3%）→保留 ✅；momentum_20 -0.047512 vs +0.0382（方向翻转）→保留 ✅；chg5 0.016841 vs 0.0397（衰减 42.4%）→保留（衰减挂监控不作停用依据）✅；overnight_sum20 0.040463（PASS，保留率 94.5%）✅。adjudication 规则段 = "铁律: 132d 证据优先于 20d 窗口, 20d 仅作稳定性监控" ✅。
6. **回归** ✅（见 AC#3；H/I 遗留归类经独立归因链核实后**同意**）

## 三、红线核对

- **负 IC 负填** ✅：v2.6 权重起点全正（132d 证据）；符号通道=运行时 `apply_ic_sign()` 按 `data/factor_ic/factor_ic_latest.json`（10-18 03:06，28 因子 {name,ic,status} 表）定号——15:25 实测：chg10 -0.0087→权重取负、chg5 -0.0049→取负、momentum_20 -0.0534→取负（日志 -0.5）、overnight_sum20 +0.021→保持正；缺失/0 → 置 0+登记（sign_skipped 路径，本次无命中）。负 IC 因子未按正权重加分。
- **registry 双管隔离** ✅：3ddac836 的 11 文件不含 registry.json；后续 3 commit 亦未动；G 组 48 因子 key 基线 PASS。
- **risk_rules 未动** ✅：B 组 AST 只读解析 PASS（CHASE_BAN_PCT=4.0 / TIME_STOP_TRADING_DAYS=120 / STRATEGY_STOP_LOSS_PCT 含 10% 七档）。
- **异常吞噬** ✅：本次 diff 未见 `except: 默认值` 类埋雷；死因子/符号未知/数据损坏均 loud 登记（SOUL#9 路径在位：factor_exceptions 随产物落盘，scan_errors 含 logic_errors/data_skipped/samples）。

## 四、回滚点核对（7/7 实物在位）
- config_loader.py.bak_T2rework_20261017（7309B, 04:06）/ .bak_T2rework2_20261020（7309B, 05:43）
- factor_weights.json.bak_T2rework_20261017（1326B, 04:06）/ .bak_T2rework2_20261020（1326B, 05:43）
- scripts/auto_live_pipeline.py.bak_T2rework_20261017（33225B, 04:06）
- scripts/t2b_20d_ic_check.py.bak_T2rework_20261017（10287B, 04:06）
- tdx_indicators.py.bak_T2rework_20261017（38009B, 04:06；与现 tdx_indicators.py 同 38009B → ZERO_DIFF，无幸存 3 新因子副本，见 O4）
- git：3ddac836 入树确认（`git merge-base --is-ancestor` = ancestor of HEAD ce263a74）；混合 commit 含 P0-2，外科式回滚需 cherry-pick 反向补丁（与任务单一致）

---

## 五、观察与路由项（非本单阻断，交总管路由）

- **O1【数字保真旗标】** §4 声称"2935 有效候选"在 15:25 复跑中**不可复现**（实际 1498）。核算：当前确定性分层抽样 3000 样本 = sh60:993/sz00:879/sz30:784/sh68:344，D8 白名单（创业板/科创不进评分）→ 可评板配额上限 1872，2935 在 scan=3000 口径下算术不可达；2935 量级与全量 9441 扫描（可评板 ≈3367，88.8% 有效比 → ≈2690–2990）吻合。**疑似父单将全量口径数字误标为 scan=3000**。处理：合同 AC 不含该数字，不阻断；作废数字"2935"自本报告起不得再引用，后续报告以"15:25 复跑：3000 抽样/1663 处理/1498 有效（数据截至 10-19/10-20 快照）"为准。
- **O2【任务单描述失准（不阻断）】** §4 称死因子将产生 `factor_ic_sign_unknown`（"10-18 权威表无此二因子 IC"）——**该前提不成立**：factor_ic_latest.json 明确含 overnight_sum20 ic=+0.021 / momentum_20 ic=-0.0534 → 符号已知 → 不触发 sign_unknown 分支（实测无此登记，与设计一致）。实际行为 = 符号应用 + factor_dead_all_universe 双 loud 登记，符合红线。建议任务单勘误。
- **O3【数据质量·重要】132d 权威表 gate_passed=False / effective_factors=1**：v2.6 四个活跃因子中 3 个 132d IR<0.3（chg10 0.2118 / chg5 0.1836 / momentum_20 0.144），仅 overnight_sum20 0.3593 达 IR 线；且 20d 窗口已示 2 方向翻转 + 1 衰减 42.4%。权重起点虽按任务铁律取 132d 精确证据，但 **4 因子中 3 个未达老五 IR≥0.3 标准** → 路由总管：挂因子衰减监控，失效触发条件建议：chg10/momentum_20 20d 方向翻转持续 20 个交易日，或 chg5 20d 保留率连续 2 周 <40%，即重裁 v2.7（IC<0.03 连续 20 日亦为停用触发）。
- **O4【遗留·必须路由】tdx_indicators.py 缺 3 新因子实现**（overnight_sum20/momentum_20/chg5_rev，ZERO_DIFF bak 无幸存副本）→ v2.6 四活跃因子中 **2 个生产实际失效**（z 全 0 双 loud 登记在案），因子层实际有效 = chg10(2.0)+chg5(1.4) 净和 3.4。重建 tdx_indicators 3 实现为 v2.6 真正生效的前置条件。
- **O5【观察】TOP10 factor_score 全负（-1.47~-4.21）**：符号通道把 chg10/chg5 取负权重（10-18 权威表负 IC）→ 因子层当前实质做"高 chg 惩罚"，与追高门（CHASE_BAN 4%）方向一致。设计行为，非缺陷；但主管需知悉因子层当下是逆动量语义。
- **O6【观察·设计态】G 组 WARN：config.json↔factor_weights.json 不同步**（fw 有 config 无 20 键 / config 有 fw 无 {LOWER_SHADOW, UPPER_SHADOW}）= T2a 切源后预期状态（config.json factor_weights 段仍供 tdx_strategies.load_strategy() 独立通道），不阻断；建议后续把该 WARN 文案升级为"已知设计态"注释，防误读。
- **O7【遗留·系统红项】H 组 walk-forward 衰减 0.7858（OOS 保 IS 21.4%，阈值 0.5）+ I 组 G6/G7 断言降级**（cron_message_sender.py 缺 SUPPRESS_WINDOW_P0_MIN/_priority_of）= 本单独立归因核实后的既有遗留，非 3ddac836 引入，路由总管单独立项。

## 六、反例自检（什么证据能推翻本 verdict）
1. 后续 commit 再动 T2 5 文件/评分链路 → 本报告已核 3ddac836..HEAD（ce263a74）区间 git log 为空；若 15:40 后再有新 commit 触碰，本报告结论仅在 ce263a74 及前有效。
2. 15:25 复跑与 06:34 复跑引擎不等价 → 已核：链路 6 文件逐字节相同 + scripts/tdx_core.py 为纯 shim；不等价证据需 diff 出上述文件差异，现无。
3. 1498 vs 2935 是引擎回归而非口径差异 → 已核：9441 库中 9436 文件 mtime ≤10-19（盘中刷新仅 6 文件）、代码未变、抽样确定性；若复现出"同数据快照下 2935"，则本报告 O1 归因错误（当前无此证据）。

## 七、判定
- 合同 AC#1 ✅ / AC#2 ✅（引擎声明=3ddac836 等价，ce263a74 树）/ AC#3 ✅（H/I 遗留归类经独立归因核实，同意 §6）。
- 红线 3/3 通过；sanity gate PASS；回滚点 7/7 在位。
- **老五 R0 判定：✅ 放行（本单 t_26cc78fb 可闭环）。O1–O7 + 遗留（tdx_indicators 3 因子重建 / H 组 walk-forward / I 组 G6/G7）交总管路由。**

---
### 证据索引（可复跑）
| 项 | 命令 | 时间戳 |
|---|---|---|
| 血缘 | `git merge-base --is-ancestor 3ddac836 HEAD`；`git log 3ddac836..HEAD -- <5+6文件>` | 15:14 |
| T2a diff | `git show 3ddac836 -- config_loader.py` | 15:15 |
| 探针 | `mv factor_weights.json …_probe; python -c get_factor_weights()` → RuntimeError；md5 还原核对 | 15:17 |
| py_compile | `.venv/Scripts/python.exe -m py_compile config_loader.py` → 0 | 15:18 |
| v2.6 血缘 | python json 解析 factor_weights.json/bak/132d 诊断/20d json | 15:16–15:22 |
| 主树实测 | run_stock_selection(top_n=10, scan_range=3000, factor_layer=True) → LIVE_RUN_EXIT=0 | 15:18–15:25 |
| 回归 | `python .agent/regression/__init__.py .` → PASS 17/FAIL 3/WARN 2 | 15:19 |
| sanity | `python check_backtest_sanity.py` → PASS exit 0 | 15:20 |
| 存证 | docs/reviews/t26cc78fb_live_run_log_20261020_1525.txt（md5 368c3633…） | 15:30 |
