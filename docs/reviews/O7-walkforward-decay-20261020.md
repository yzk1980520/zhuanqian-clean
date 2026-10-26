# 【O7 独立立项评估】walk-forward 衰减（H 组）+ G6/G7 断言降级（I 组）

评估人：老三（技术验证）
时间：2026-10-20 21:55–22:05 一手实测
触发：老五 R0 复审 t_7819f7e3/t_26cc78fb 附观察 O7（docs/reviews/laowu-t26cc78fb-r0-t2a-t2b-review-20261020.md L85）
只读约束：本单未修改 walk_forward_gate.json / guard_assertion_effectiveness.py / cron_message_sender.py（git status 核对：cron_message_sender.py 的 ` M` +5 行 GBK 修复为他人 18:09 未提交 WIP，非本单产物）

## 〇、结论摘要（给老大的决策建议）

| 项 | 根因（一手证据） | 建议 | 拒绝项 |
|---|---|---|---|
| H 组 walk-forward 衰减 0.7858 | **测体错位**：门禁消费的是 MVP mock 引擎（10 只沪深指数 + 朴素 5/10/20d 动量 + IS 最佳参数选择），生产因子/环境门/成交模型 3 条通路在引擎中**全部缺席**（grep=0）。衰减 0.7858 不是策略衰减，是"指数动量代理 + 参数选择偏误 + 尾部高 IS 窗主导"的度量产物 | **短期继续观察**（红项已由 2 次 R0 归类遗留，不阻塞主流程）；**中期换测体**（立 P2 单：生产 S3 策略 walk-forward 替换门禁输入，Task#3 132d 权威源刷新 + P1-O4 落地后重跑；阈值 0.5 维持） | **拒绝调参**：在 mock 上抬高阈值 = 用假数字掩盖假数字 |
| I 组 G6/G7 "断言降级" | 标签不准确：守卫 G6/G7 判据要求的新代合同（`_priority_of` + `SUPPRESS_WINDOW_P0_MIN` + skey `"#"` 拼接）**从未在 cron_message_sender.py 实现**（git 全历史 4 采样 commit blob grep=0，无 WIP 幸存）；现存为第一代合同（5ee02ef9：60min 扁平窗口 + `[Pn]` 标签键）。守卫工作正常，红是"未实现合同"不是"判据被降级" | **立 P1 单：sender 端实现新代合同**（~30 行 + TDD；先处理 18:09 GBK WIP 归属再动文件） | **拒绝放宽守卫判据**（守卫 docstring 明示：其他 worker 见红即"修复"= 最省事的假绿复辟路径，项目头号病史 12 次）；拒绝继续观察（regression 永久 2 FAIL → 每单 R0 归因成本 + P0 投递真实缺口） |

---

## 一、H 组 walk-forward 衰减：根因 = 测体错位

### 1.1 数据链（全部一手）

| 环节 | 实物 | 关键值 | 证据 |
|---|---|---|---|
| 门禁产物 | `data/walk_forward_gate.json`（md5 c9b9f159） | decay 0.7858 / IS 0.9906 / OOS 0.2122 / n=894 / blocked=true / exit 3 / computed_at **2026-10-20 20:00:02** | `cat data/walk_forward_gate.json`（21:52 实测） |
| 门禁输入 | `output/diagnostic/walk-forward-test-20261017_0634.json`（md5 5f4917f4，mtime 10-17 06:34） | 同组 mean 值 + `sharpe_drop 0.7784` | 门禁 JSON 内 `source_file` 字段逐字 |
| 门禁选择逻辑 | `scripts/walk_forward_gate.py` L109 `sorted(OUT_DIR.glob("walk-forward-test-*.json"))` 取最新 → 10-17 文件 | 02:13 版与 20:00 版**数值不变**（同源文件 10-17 未动） | 本单两次读取对比 |
| 生成引擎 | `scripts/walk_forward_backtest.py`（8783B，头部自述 "MVP"，L89 `TODO: 替换为S3真实策略`） | 朴素动量代理 | 代码审阅 |
| 对照组 | `output/diagnostic/walk-forward-test-20261005_2033.json` | 894 窗全 0（当时数据不足），10-17 是唯一有效数据点 | 同命令对照 |

### 1.2 引擎与生产系统的通路缺席（衰减贡献分解）

任务单要求的分解维度（因子漂移 vs 环境门 vs 成交模型）在引擎中的实测结果：

| 通路 | 引擎内证据（grep 计数） | 对 0.7858 的贡献 |
|---|---|---|
| 因子漂移 | `walk_forward_backtest.py` 中 factor_weights / z-score / 因子层引用 = **0**（L87-131 仅 close.pct_change 动量） | 0（通路缺席，不可分解） |
| 环境门 | MA250 / 环境门 / soft 模式逻辑引用 = **0** | 0（通路缺席） |
| 成交模型 | 滑点 / 退市整理期 / 价格地板 / ADV 地板引用 = **0**（引擎 19 年跨度无成交过滤） | 0（通路缺席） |
| **参数选择偏误** | L93 `lookback_periods=[5,10,20]` + L108-112 取 IS 最佳 3 选 1 → max-of-3 选择抬升 IS | **主因之一**（见 1.3 尾部数据） |
| **测体错位（universe）** | L181 `HISTORY_DIR.glob("*.json")[:50]`（文件系统序）→ L137 `stock_codes[:10]`：取前 10 个文件 = **sh000001…sh000xxx 沪深指数族**（目录序实测 L1-15 全为 sh0000xx + download_errors.json） | **主因之二**（非生产股票宇宙；894 窗 = 10 指数 × 89-133 窗，sh000001 自 **1990-12-19** 起 8741 bar） |

**结论：0.7858 的"真实"归因 = 指数长历史（1990s-2026）上 3 候选动量 IS 最佳选择偏误 + 指数动量 regime 漂移；生产系统的真实衰减风险不在该数字里。**

### 1.3 尾部主导（同窗口同口径分解，样本 n=20，全为 sh000001 首页）

- 20 窗 IS∈[-0.11, 12.94]，OOS∈[-2.84, 8.77]；**OOS≥IS 的窗 7/20，OOS<0 的窗 5/20** → 单窗信号方向混杂，非系统性 OOS 失效。
- 桶级分解：IS≤1（n=6）mean IS 0.575 / OOS 0.674 —— **无衰减甚至 OOS>IS**；1<IS≤3（n=12）1.674/0.895；**IS>3（n=2，占比 10%）mean IS 12.862 / OOS 5.714，缺口 7.148 = 全部正向缺口的 90.2%**（7.148/7.927）。
- 即：平均口径 decay_ratio 0.7858 由 ~10% 的超高 IS 尾窗主导（max-of-3 选择偏误直接抬高这些窗的 IS），mean-based 指标对尾选择天然敏感 → **该数字系统性高估"真实衰减"**。
- 局限声明：894 窗仅 20 窗落盘（引擎 L168 `results[:20]`），全局 mean 值（0.9906/0.2122）为引擎内 894 窗计算，样本分解仅作方向性佐证。

### 1.4 生产侧真实衰减信号（不在 H 组红里，另有监控）

v2.6 四活跃因子中 3 个 132d IR<0.3（chg10 0.2118 / chg5 0.1836 / momentum_20 0.144，O3 报告在案）+ 20d 窗口 2 方向翻转 + chg5 衰减 42.4% —— 已由 **P2-O3 factor_decay_monitor**（commit 2ab6eb0e，10-20 20:45 挂表，gate_20d as-of 10-20）承载监控，触发线：20d 方向翻转持续 20 交易日 / 保留率连续 2 周 <40% → 重裁 v2.7。P1-O4（tdx_indicators 3 因子重建，commit 3e94e529，10-20 20:14）已补齐 v2.6 生产失效 2 因子前置条件。
→ 生产因子漂移有监控器 + 触发线；**H 组 mock 红无任何触发线，纯门禁噪声源**（regression H 组 1 FAIL + check_all backtest-gate exit 3 持续挂红）。

---

## 二、I 组 G6/G7："断言降级"标签不成立，实为"合同未实现"

### 2.1 现状实测（10-20 21:55，主树工作区）

`python scripts/guard_assertion_effectiveness.py --json` → **exit=1，16 项中 14 PASS / 2 FAIL**：
- G6_抑制窗口分层 FAIL：`优先级分层窗口常量缺失（P0 会与 P2 共享窗口）`
- G7_抑制键含优先级 FAIL：`缺少 _priority_of，P0 优先级未并入抑制键`
- 其余 G1-G5/G8-G16 全 PASS（含 G9-G16 10-20 03:56 新增的 wscript 静默链判据）

### 2.2 根因（代码 + git 双向核实）

**守卫判据（scripts/guard_assertion_effectiveness.py，17514B，mtime 10-20 03:56，树外不入 git）：**
- G6（L105-113）：要求 sender 含 `SUPPRESS_WINDOW_P0_MIN = <int>` 且 P0 < P2（`SUPPRESS_WINDOW_MIN`）
- G7（L116-122）：要求 `_priority_of` 存在且 `skey = prio + "#" + _suppress_key`

**sender 现状（cron_message_sender.py，197121B/19712B，mtime 10-20 18:09）：**
- L68：`SUPPRESS_WINDOW_MIN = 60`（唯一窗口常量，扁平，无 P0 分层）
- L323-328：`_suppress_key` = 第一代合同（`[Pn]` 标签 + checker 名 + 前 80 字；无标签消息走 `plain|` 前缀 = 优先级盲）
- grep 实测：`SUPPRESS_WINDOW_P0_MIN` 计数 **0**；`_priority_of` 计数 **0**（工作区与 6adbea0a commit blob 双 0）
- git 全历史：`git log -S "_priority_of" --all` 对 cron_message_sender.py `--follow` = 空；4 个采样 commit（6adbea0a/0a312528/8cdc0295/5ee02ef9）blob grep 全 0 → **新代合同代码从未存在过任何 commit，无 WIP 幸存**（.bak 目录无 guard/sender 相关备份件，stash 空）

**定性：不是"判据被降级回存在性检查"（守卫 docstring 防的那种病），而是守卫按设计监视一个从未实现的合同 → 持续红。守卫行为正确，不应改。**

### 2.3 实际影响量化

1. **门禁噪声成本（每单固定）**：`.agent/regression` I 组子进程跑守卫 → FAIL 即 `rpt.fail("断言降级 G6/G7…")`（L318-330）→ regression 汇总 FAIL≥2 恒定（本次 R0 实测 PASS 17/FAIL 3 = H 1 + I 2）。实证：老五 15:40 R0 报告 AC#3 单为 G6/G7 做了独立溯源归因（`git show --name-only 3ddac836 | grep -c = 0` 级证据）= 每单重复审查成本。
2. **P0 投递真实缺口（业务面）**：
   - G6 面：P0/P2 共享 60min 抑制窗（L68+L401）→ 同 key P0 告警复报间隔 ≥60min（旧行为 15min 级重复 → 60min 抑制下 P0 复报最坏延迟 60min）
   - G7 面：带 `[Pn]` 标签消息的键已含优先级（`[Pn]|checker|前80字`，跨优先级抑制已防住）；缺口在 **plain 无标签消息优先级盲**（同文案 P2 先到 → 同 key 后到 P0 被压 60min）
3. 当前 ` M cron_message_sender.py` +5 行（UTF-8 reconfigure 防 GBK 崩退，18:09 未提交）与 G6/G7 无关（改动区 L13-20 vs G6/G7 判定区 L68/L323+），但**立新单动该文件前须先确认 GBK WIP 归属**，避免混脏。

---

## 三、决策矩阵（请老大拍板）

**H 组（三选项）：**
1. ✅ **继续观察（短期）+ 换测体（中期）**：红项维持现状归类"遗留"（连续 2 次 R0 已归因完毕，成本可控）；立 P2 单「生产 S3 walk-forward 门禁替换」——条件：Task#3 132d 权威源刷新 + P1-O4/P2-O3 稳定 ≥1 周后，用生产策略（因子层 + 环境门 + D9-2 全套过滤 + 9441 股确定性 universe）重跑 walk-forward 并替换门禁输入；阈值 0.5（"OOS 至少保留 IS 一半的边"，10-17 老大拍板语义）维持不动。
2. ❌ 调参（抬高 decay 阈值）：mock 数字上调阈值 = 掩盖错位而非修复，且 OOS/IS=21.4% 在换测体前无决策含义。
3. ❌ 立即重构引擎（无前置条件）：生产 walk-forward 依赖 132d 权威源 + 监控器稳定，直接重构缺对照基准。

**I 组（三选项）：**
1. ✅ **立 P1 单实现 sender 端新代合同**：`SUPPRESS_WINDOW_P0_MIN=15`（建议值，<60）+ `_priority_of()` + `skey=prio+"#"+_suffix` + 按 key 选窗；TDD 先行，回归全绿（G6/G7 转绿即 regression FAIL 3→1 仅余 H）；前置：GBK WIP +5 行归属确认并入同一提交。
2. ❌ 放宽守卫判据匹配现状 `[Pn]` 设计：违反守卫设计意图（"最省事的修复=判据改回存在性=假绿复辟"，12 次病史），且 G6 的 P0 窗口缺口真实存在，放宽后无人盯。
3. ❌ 继续观察：regression 永久 2 FAIL + P0 投递缺口无触发线。

**立项建议（总管建单）：**
- P1「I 组 G6/G7 sender 端合同实现」（~30 行 + 单测，含 GBK WIP 收编）
- P2「H 组 walk-forward 门禁输入替换：生产 S3 策略」（依赖 Task#3 刷新，阈值 0.5 不动）

---

## 四、未验证项与反例自检

**未验证项：**
- H 组 894 窗中 874 窗未落盘（引擎仅存前 20），桶级 90.2% 尾贡献率基于 n=20 样本，仅作方向性佐证（非 894 窗精算）。
- 20:00 gate 重算的触发主体未溯源（check_all backtest-gate 4 项自动执行含 walk_forward_gate，疑似 20:00 某流程触发；不影响数值结论——同源文件 10-17 未动，数值 02:13 与 20:00 两次一致）。

**反例自检（什么证据能推翻本评估）：**
1. "0.7858 是生产策略衰减" → 反证：若 walk_forward_backtest.py 在 10-17 后已替换为 S3 真实策略，其输出 schema 必变（因子权重键/过滤统计字段）；现 schema 与代码 L161-169 逐字段吻合（oos_sharpe/is_sharpe/best_period/status/stock_code），且 L89 TODO 在位 → 不成立。
2. "G6/G7 实现曾经存在后被覆盖丢失"（W3 06:14 覆盖事故路径）→ 反证：`git log -S --all` 全历史 + 4 采样 blob 全 0，W3 覆盖只可能丢**未提交** WIP（事故档案在案：老六死信修复曾被 W3 覆盖丢失），未提交 WIP 无实物可溯；若老六持有本地副本（.worktrees/ 已查 5 处无 guard 相关改动），需老六确认一次。此条列为残余不确定性，不阻断 I 组结论（"从未入树"事实成立）。
3. "P0 共享 60min 窗无实际影响" → 反证：若 P0 告警全部带 `[Pn]` 标签且同 key 复报间隔 <60min 在业务上可接受，则 G6 降级为形式项；需老六按告警台账（data/alert_log.jsonl）统计 P0 同 key 复报频次后复核。

## 五、证据索引（命令 + 输出 + 时间戳，10-20 21:52–22:05 一手实测）

| 项 | 命令 | 关键输出 |
|---|---|---|
| 门禁产物 | `cat data/walk_forward_gate.json` | decay 0.7858 / IS 0.9906 / OOS 0.2122 / n=894 / computed_at 2026-10-20 20:00:02 / source_file=walk-forward-test-20261017_0634.json |
| 门禁输入 | `cat output/diagnostic/walk-forward-test-20261017_0634.json` | mean_is 0.9906 / mean_oos 0.2122 / total_windows 894 / 对照 10-05 文件全 0 |
| 引擎定性 | `sed -n '87,137p;181p' scripts/walk_forward_backtest.py` | L89 `TODO: 替换为S3真实策略` / L137 `stock_codes[:10]` / L181 `glob("*.json")[:50]` |
| universe 错位 | `ls data/history_daily | head -15` | 前 15 文件 = sh000001…sh000037 指数族 + download_errors.json |
| 数据深度 | python 读 sh000001/sh000002 json | 8741 bar，1990-12-19 → 2026-10-14 |
| 尾分解 | python 20 窗样本桶统计 | IS>3 桶 n=2（10%）正向缺口占比 90.2%；OOS≥IS 7/20；OOS<0 5/20 |
| G6/G7 现状 | `.venv/Scripts/python.exe scripts/guard_assertion_effectiveness.py --json` | exit=1，14 PASS / 2 FAIL（G6 常量缺失、G7 `_priority_of` 缺失） |
| sender grep | `grep -c "SUPPRESS_WINDOW_P0_MIN\|_priority_of" cron_message_sender.py` | 0（工作区） |
| git 历史 | `git log --follow -S "_priority_of" --all -- cron_message_sender.py`；`git show <4 commits>:cron_message_sender.py \| grep -c` | 空 / 全 0 |
| regression 消费 | `.agent/regression/__init__.py` L305-330 | I 组子进程跑守卫，FAIL 逐项 rpt.fail（R0 实测 FAIL 3 = H1+I2） |
| 文件指纹 | `md5sum`（21:57） | gate=c9b9f159… / wf-test=5f4917f4… / guard=917a3d7b… |
