# W8｜walk-forward 过拟合衰减 → 真正的阻断门禁（2026-10-17）

> 老大拍板：衰减不再只是"打日志 + exit 0"，升级为阻断门禁。
> 执行：general-purpose-1　｜　状态：**已实现并正反两面验证**
> 交付物：`scripts/walk_forward_gate.py`（新）、`config/walk_forward_gate.json`（新）、
> `data/walk_forward_gate.json`（产出）、`scripts/walk_forward_report.py`（改为门禁前门）、
> `scripts/Zhuanqian_WalkForward.bat`（注释同步，退出码传播逻辑本来就有、未改）

---

## 一、结论（先看这里）

| 项 | 结论 |
|---|---|
| 衰减现在阻断吗 | **是**。当前 894 窗实跑 `IS=0.9906 / OOS=0.2122`，相对衰减 **0.7858** > 阈值 0.50 → 阻断 |
| 退出码 | **3**（= 被门禁阻断；与 `daily_pick.py` 的 "3=被门禁暂停" 语义一致） |
| 门禁状态文件 | `data/walk_forward_gate.json`，`blocked: true` |
| 接到了哪个真实入口 | **接上了 1 个**：Windows 计划任务 `Zhuanqian_WalkForward`（`scripts/Zhuanqian_WalkForward.bat`） |
| 日常选股链路断了吗 | **没断**。`daily_pick.py` / `orchestrator.py` / `Zhuanqian_DailyAuto` 都不读这个门禁 |
| 需要老大拍板吗 | **需要**：是否把门禁接进日常链路（见第六节 4 个候选方案） |

**一句话**：门禁本身装好了、真的会 exit 非 0，但它目前只卡得住**季度跑一次**的那个计划任务；
日常每天 20:00 的选股链路**完全不受它影响**。要不要让它卡日常，是政策决定，我没擅自改。

---

## 二、衰减的确切公式与行号

### 2.1 原始定义（walk_forward_backtest.py:167）

```python
# scripts/walk_forward_backtest.py:167
"sharpe_drop": round(np.mean(is_sharpes) - np.mean(oos_sharpes), 4) if is_sharpes and oos_sharpes else 0,
```

**`decay_abs = mean_is_sharpe − mean_oos_sharpe` —— 是绝对差，不是比率。**

不是 `(IS-OOS)/IS`，也不是 `1 - OOS/IS`。这一点必须点名，因为老大的阈值语义
（"OOS 至少保留 IS 一半"）是**相对口径**，而脚本里的 `sharpe_drop` 是**绝对口径**，
两者不是同一个量：

| 口径 | 公式 | 当前 894 窗取值 |
|---|---|---|
| `decay_abs`（脚本原始 `sharpe_drop`） | `IS − OOS` | **0.7784** |
| `decay_ratio`（老大"保留一半"语义对应口径） | `(IS − OOS) / IS = 1 − OOS/IS` | **0.7858** |

当前 `IS ≈ 0.99`，两个口径数值几乎重合（差 0.0074），**所以当前判定对口径选择不敏感，两种都阻断**。
但它们是尺度无关的差别：若某次 `IS=3.0, OOS=1.5`，则 `abs=1.5`（在 0.5 阈值下阻断）、
`ratio=0.5`（恰好边界、不阻断）——会分叉。

**本门禁默认判定用 `ratio`（对应老大的语义），但 `abs` 也一并算出来写进 JSON 留证，
并支持 `--metric abs` 切换。**

### 2.2 相关行号清单

| 位置 | 作用 |
|---|---|
| `scripts/walk_forward_backtest.py:167` | 衰减唯一产地：`sharpe_drop = IS − OOS`（绝对差） |
| `scripts/walk_forward_backtest.py:208-212` | **唯一**读衰减做判断的地方：阈值 `overfit_threshold = 0.1`，只 `print`，不影响 `return True` |
| `scripts/walk_forward_backtest.py:244` | `sys.exit(0 if success else 1)` —— 衰减再大也是 `success=True` → **exit 0** |
| `scripts/walk_forward_report.py`（旧版 L44-53） | 读 `sharpe_drop`，沿用 0.1 打 `OVERFIT_RISK`，`return 0` |
| `scripts/walk_forward_report.py`（旧版 L10） | 注释原文："退出码: 恒为 0 …… 避免把'报告器故障'伪装成'回测失败'" |

### 2.3 改造前：有没有任何地方读衰减做判断？

**有且仅有一处，且它不阻断任何东西**：`walk_forward_backtest.py:209` 的 `print`。
`walk_forward_report.py` 也只是把结论打到日志里。
全仓检索确认：**改造前没有任何代码的退出路径受衰减影响**。

---

## 三、现有门禁入口清单（谁在读门禁）

这是我实测（grep + 读代码 + `Get-ScheduledTask`）拉出来的全量清单，
**不是**台账口述：

| # | 入口 | 读什么 | 失败后果 | 与 walk-forward 的关系 |
|---|---|---|---|---|
| 1 | `scripts/Zhuanqian_WalkForward.bat` → 计划任务 `Zhuanqian_WalkForward`（Ready，下次 **2027-01-01 06:30**，季度 1/4/7/10 月 1 日） | 先跑 `walk_forward_backtest.py`，再跑 `walk_forward_report.py`；末尾 `exit /b %RP_RC%` | 任务计划程序记 FAIL | ✅ **本次已接上**（report.py 现在透传门禁码） |
| 2 | `scripts/gate_check.py` | `data/factor_ic/factor_ic_latest.json`（132d 权威源），≥8 个 `valid` | `return 1`，写 `data/factor_ic/factor_gate.json` | ❌ 不读 walk-forward |
| 3 | `scripts/sync_trial_gate.py:72-83`（A 条件） | 实跑 `gate_check.py` + 读 `factor_gate.json` | A 不绿 → `dry_run` 不落仓 | ❌ 不读 walk-forward |
| 4 | `daily_pick.py:84-101` | `data/factor_ic/factor_gate.json` | 未通过 → **`return 3`**（被门禁暂停） | ❌ 不读 walk-forward |
| 5 | `orchestrator.py:217-240` | `data/gate_status.json`（**另一个**门禁：回测 sanity，非因子 IC） | 非 PASS → `dry_run=True` | ❌ 不读 walk-forward |
| 6 | `scripts/automation_scheduler.py:94-108` | `review_gate.flag_state()` —— **手工旗标文件** | 冻结 → 降 health 模式 | ❌ 与任何自动门禁无关 |
| 7 | `scripts/daily_auto.bat` → 计划任务 `Zhuanqian_DailyAuto`（每日 20:00） | 调 `automation_scheduler.py` | **bat 不传播退出码**（末行是 `echo`，退出码恒 0） | ❌ 不读 walk-forward |

### 三条必须说清的事实

1. **132d 因子门禁（#2/#3/#4）虽然会 `return 3` / `return 1`，但目前也不阻断任何自动化流程** ——
   没有任何计划任务调用根 `daily_pick.py`；每日 20:00 的 `Zhuanqian_DailyAuto` 走的是
   `review_gate` 手工旗标（#6）。这和老大给的线索一致。
2. 所以"把新门禁接进门禁聚合链路"这句话本身有个坑：**现有聚合链路（#2~#7）下游没有真正的执行者**，
   接进去也只是多一个红灯，不会让谁停下来。唯一一个"跑起来就是真跑、退出码会被操作系统记录"的，
   是 **#1 那个季度计划任务**。
3. 因此本次**只接了 #1**。接 #2~#7 属于改动 `daily_pick.py` / `sync_trial_gate.py` / 调度配置，
   **按老大约束我没动**，改列候选方案交拍板（第六节）。

---

## 四、改动内容

### 4.1 新增 `scripts/walk_forward_gate.py`（门禁本体）

- 读 `output/diagnostic/walk-forward-test-*.json` 中 **mtime 最新**的一份
- 计算 `decay_abs` 与 `decay_ratio`
- 判定：`decay > threshold` → `blocked=True` → **exit 3**
- 原子写 `data/walk_forward_gate.json`
- 阈值三级可配：**命令行 `--threshold/--metric` > `config/walk_forward_gate.json` > 内置默认 0.50**，
  判断里没有任何硬编码阈值
- 退出码：`0`=通过 / `3`=被门禁阻断 / `2`=无可用结果或数据不可读（**fail loud，绝不回退成"通过"**）

### 4.2 新增 `config/walk_forward_gate.json`

```json
"decay_threshold": { "value": 0.5, ... }
"metric":          { "value": "ratio", ... }
```

### 4.3 改 `scripts/walk_forward_report.py`

判定逻辑下沉到 `walk_forward_gate.py`，本文件保留原调用面并**如实透传退出码**。
这一步是必须的：bat 调的是 `report.py`，如果它还 `return 0`，门禁等于白装。

### 4.4 改 `scripts/Zhuanqian_WalkForward.bat`

**只改注释**（ASCII-only，遵守该文件自带的约定）。退出码传播逻辑原本就有
（`exit /b %RP_RC%`），一行没动。

### 4.5 备份（硬约束：动任何已有脚本先备份 `.bak_20261017_laoliu`）

```
scripts/walk_forward_report.py.bak_20261017_laoliu
scripts/walk_forward_backtest.py.bak_20261017_laoliu
scripts/Zhuanqian_WalkForward.bat.bak_20261017_laoliu
```

### 4.6 未动的东西

- `data/factor_ic/factor_ic_latest.json` **md5 校验通过**：
  `1703ff2f4899d48b78aac5caed1eb6ea`（改造前后一致，见 5.4）
- `daily_pick.py`、`orchestrator.py`、`sync_trial_gate.py`、`gate_check.py`、
  `cron_config.json`、任何计划任务注册 —— **全部未动**

---

## 五、验证结果（正反两面都验了）

所有命令均 `unset PYTHONPATH`，解释器用
`C:\Users\WIN10\.quant-stock-picker\.venv\Scripts\python.exe`。

### 5.1 正面：真实数据 → 必须阻断

```
$ python scripts/walk_forward_gate.py
[walk_forward_gate] is=0.9906 oos=0.2122 decay(ratio)=0.7858 (abs=0.7784 ratio=0.7858) threshold=0.5 windows=894 file=walk-forward-test-20261017_0634.json
[walk_forward_gate] 判定依据: 样本外夏普相对衰减 0.7858 (= (IS 0.9906 - OOS 0.2122) / IS 0.9906) > 阈值 0.5; OOS 保留 IS 的 21.4% 边际, 要求 >= 50%
[walk_forward_gate] 门禁结果: 阻断 -> data/walk_forward_gate.json
======================================================================
🔴 [walk_forward_gate] 门禁未通过 —— walk-forward 过拟合衰减超阈值
   指标    : 样本外夏普相对衰减(ratio) = 0.7858
   阈值    : 0.5
   依据    : 样本外夏普相对衰减 0.7858 ... > 阈值 0.5; OOS 保留 IS 的 21.4% 边际, 要求 >= 50%
   样本    : 894 个窗口, 来源 walk-forward-test-20261017_0634.json
   后果    : 退出码 3 (被门禁阻断), 调度层判 FAIL; 该策略的样本外泛化能力不足, 不得据此放行/加仓
======================================================================
EXIT_CODE=3
```

**✅ 阻断，exit 3。**

`scripts/walk_forward_report.py` 透传验证：`EXIT=3`（同一次真实数据）。

### 5.2 反面：健康假数据 → 必须不阻断

构造 `IS=1.0 / OOS=0.8`（ratio=0.2），写入 `output/diagnostic/walk-forward-test-20990101_0000.json`
并 `touch` 使其成为最新：

```
[walk_forward_gate] is=1.0 oos=0.8 decay(ratio)=0.2 (abs=0.2 ratio=0.2) threshold=0.5 windows=894
[walk_forward_gate] 判定依据: 样本外夏普相对衰减 0.2 (= (IS 1.0 - OOS 0.8) / IS 1.0) <= 阈值 0.5; OOS 保留 IS 的 80.0% 边际, 要求 >= 50%
[walk_forward_gate] 门禁结果: 通过 -> data/walk_forward_gate.json
✅ [walk_forward_gate] 门禁通过, 退出码 0
EXIT_CODE=0
```

**✅ 不阻断，exit 0。**（验证后假文件已删除，门禁状态已按真实数据重跑恢复）

### 5.3 补充边界验证

| 场景 | 输入 | 预期 | 实测 |
|---|---|---|---|
| 边界值 | `IS=1.0 OOS=0.5`（ratio 恰好 0.50） | 不阻断（`>` 才阻断） | `EXIT=0` ✅ |
| 命令行覆盖阈值 | 真实数据 + `--threshold 0.9` | 放行 | `EXIT=0` ✅ |
| 切换口径 | 真实数据 + `--metric abs --threshold 0.5`（abs=0.7784） | 阻断 | `EXIT=3` ✅ |
| IS≤0 fail-safe | `IS=-0.2 OOS=0.1` | 阻断（算不出指标不放行） | `EXIT=3` ✅ |
| 无结果文件 | 移走全部 `walk-forward-test-*.json` | `EXIT=2` fail loud | `EXIT=2` ✅ |

### 5.4 既有回归

```
$ python .agent/regression/__init__.py .
=== 汇总：PASS 18 / FAIL 0 / WARN 1（耗时 0.1s）===
回归结论：PASS（带提醒）
```

唯一 WARN 是**既有**的「因子权重漂移守卫：config.json 与 factor_weights.json 不同步」，
与本次改造无关（未触碰这两个文件）。

权威源完整性复核：

```
1703ff2f4899d48b78aac5caed1eb6ea *data/factor_ic/factor_ic_latest.json
```

md5 与要求值一致，**未被改动**。

### 5.5 关于 bat 的说明

`Zhuanqian_WalkForward.bat` 的退出码链路是**静态确认**、未实跑：
实跑它会触发 894 窗全量回测（老大约束禁止裸跑 >10 分钟的任务）。
链路本身是确定的 —— bat 末尾 `exit /b %RP_RC%`，而 `RP_RC` 就是
`walk_forward_report.py` 的退出码，实测为 3，故 bat 将 exit 3。

---

## 六、交老大拍板：要不要接进真正的日常阻断

### 6.1 先说清楚现状的"阻断"到底有多硬

`Zhuanqian_WalkForward` 是**季度**任务（下次 2027-01-01 06:30）。
它 FAIL 的后果是：任务计划程序记一次失败 + 日志一行。**它不会阻止第二天的选股。**

所以严格讲：门禁**装上了、真的 exit 非 0、真的会让一个已注册的计划任务 FAIL**，
但它**不卡日常**。老大要的如果是"过拟合就别买"，那还需要下面这一步。

### 6.2 四个候选方案（我没擅自实施任何一个）

| 方案 | 做法 | 影响面 | 风险 |
|---|---|---|---|
| **A. 维持现状**（本次已完成） | 只接季度计划任务 | 最小。一年响 4 次，只 FAIL 一个任务，不动选股、不改既有脚本 | 门禁形同季度体检报告，日常不设防 |
| **B. 加进 `sync_trial_gate.py` 的四重（A∧B∧C∧D）** | 新增 D 条件读 `data/walk_forward_gate.json`，任一不绿 → `dry_run` 不落仓 | 中。`daily_pick.py` 步骤 3b 会显示 D 状态；`trial_gate_status.json` 的顶层契约要扩键，`tests/test_trial_gate.py` 需同步 | 需改既有脚本 `sync_trial_gate.py` |
| **C. 在 `daily_pick.py` 步骤 3 加一道** | 与 `factor_gate.json` 并列读 `walk_forward_gate.json`，`blocked` → `return 3` | 大。日常选股会被直接暂停 | 需改 `daily_pick.py`；且必须解决"陈旧"问题（见下） |
| **D. 加进 `orchestrator.py daily`** | 与 `gate_status.json` 并列读，blocked → `dry_run` 不落库 | 大。实盘唯一推荐会转观察模式 | 需改 `orchestrator.py`；同样有陈旧问题 |

### 6.3 一个绕不开的坑：节奏错配（B/C/D 都要先解决）

walk-forward 是**季度**跑，而 B/C/D 是**日频**判定。
直接接进去，等于拿一份最多 90 天前的结果天天做生死判定：

- 若认旧账 → 一次坏结果会连卡 90 天（哪怕策略已修好）
- 若不认旧账 → 得先定 TTL（比如 30 天），过期怎么办：**判阻断**还是**判 WARN**？

这个 TTL 策略是政策决定，我不擅自定。**我的建议**：先落地 A（已完成），
节奏问题二选一由老大定 ——
① 把 walk-forward 从季度提频到月度；② 门禁加 `max_age_days`，过期判 **WARN 不阻断**
（避免"门禁自身失修"伪装成"策略过拟合"，也避免连卡 90 天）。

### 6.4 我的推荐

**A（已完成）+ 尽快定 B 的 TTL 策略**。
理由：B 是唯一有现成"任一不绿 → dry_run 不落仓"语义的聚合点，且 `daily_pick.py`
已经会打印它的三条件状态，加 D 是自然的；但它必须先把节奏错配解决，否则是定时炸弹。

---

## 七、遗留

1. **日常链路仍未设防** —— 等老大在 6.2 里选一个方案。
2. **节奏错配未解** —— walk-forward 季度 vs 日频判定，见 6.3。
3. **`cron_config.json` 的 `gate_semantics` 描述已过期**，原文：
   `"exit 0=跑完(含衰减告警, 当前不阻塞); 非0=回测失败"`。
   该字段是描述性文本（该条目本来就不被 cron 驱动执行，只被 `closedloop_health.py`
   检查存在性），但"当前不阻塞"现在是假的。**按"不擅自改调度配置"的约束我没动**，
   建议同步为：`"exit 0=通过; 2=无可用结果(fail loud); 3=被衰减门禁阻断"`。
4. **`walk_forward_backtest.py` 自身仍 exit 0** —— 它是度量脚本，判定放在
   `walk_forward_gate.py`，这个分工是有意的；如果老大希望度量脚本自己也 FAIL，另说。
5. **策略本身的问题没有被这次改造解决**：OOS Sharpe 只有 0.2122、IS 的 21.4%，
   这不是门禁的锅，是策略的锅。门禁只是让它不再被静默放行。
   同日 132d 因子门禁 28 个因子只有 1 个 valid —— 两条独立路径指向同一结论。
