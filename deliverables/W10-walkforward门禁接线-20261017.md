# W10｜walk-forward 衰减门禁接入回归与每日链（2026-10-17）

## 一、结论

- 已接入 `.agent/regression/__init__.py`：门禁阻断时回归 `FAIL`；通过时 `PASS`；文件缺失时 `WARN`，明确显示“未判定（门禁从未运行），非通过”。
- 已接入 `scripts/automation_scheduler.py` 的 requested mode=`daily` 每日链：门禁输出进入调度日志与状态摘要，门禁 rc 非 0 时调度器总 rc=`1`；原有 orchestrator 巡检仍继续执行。
- 未修改 `daily_pick.py` 的任何下单逻辑。
- TTL 为 90 个自然日，失败安全：`data_age_days > ttl_days` 仍阻断，不降级为 WARN。
- 当前权威回测结果时间为 `2026-10-17T06:34:23.076394`；以 2026-10-18 计算，数据年龄 **1 天**，未过 TTL。
- 当前 894 窗：`IS=0.9906`、`OOS=0.2122`、绝对衰减 `0.7784`、相对衰减 `0.7858`。门禁实际配置 `metric=ratio`，故判定值为 `0.7858 > 0.50`，阻断。
- 完整回归如期 `FAIL`：`PASS 18 / FAIL 1 / WARN 1 / rc=1`。唯一 FAIL 是本次 walk-forward 门禁；WARN 是既有因子权重漂移提醒。

## 二、现状核对与 TTL 真源选择

实际工作区与任务说明中的函数名略有出入：当前门禁本体在 `scripts/walk_forward_gate.py`，`walk_forward_backtest.py` 仍是度量脚本；W8 通过 `walk_forward_report.py` 将门禁接进季度链。本次沿用既有门禁本体，没有重写回测引擎。

TTL 采用最新 walk-forward 结果 JSON 内的 `timestamp`，理由：

1. `timestamp` 由 `walk_forward_backtest.py` 实际完成回测时写入，能代表结果生成时间。
2. `data/walk_forward_gate.json` 的 `computed_at` 是每次读取门禁时刷新；若拿它做 TTL，跑批停摆后只要门禁检查还在跑就会持续假新鲜。
3. walk-forward 结果没有单独记录“参与回测的最新行情日期”，因此当前可用且不会自刷新的可信字段只有结果 `timestamp`。

实现位置：`scripts/walk_forward_gate.py:123-138` 解析时间，`scripts/walk_forward_gate.py:182-225` 执行 TTL 与衰减的 fail-safe 合并判定。

## 三、改动

### 3.1 TTL 失败安全

- `scripts/walk_forward_gate.py:62-68`：默认阈值仍为 `0.50`，新增默认 TTL `90`。
- `scripts/walk_forward_gate.py:92-97`：阈值、口径、TTL 都从配置读取；判断没有硬编码阈值。
- `scripts/walk_forward_gate.py:213-225`：TTL 过期、时间缺失/非法、衰减超阈值三类原因分开；TTL 过期理由精确写为：
  `数据过旧无法判定（age=N 天 > 90 天）`。
- `scripts/walk_forward_gate.py:227-249`：门禁产物新增 `data_age_days`、`ttl_days`、`block_reason`，并保留 `decay_reason` 便于区分 TTL 与衰减原因。
- `config/walk_forward_gate.json:9-27`：阈值保持 `0.50` 可配置，新增 `ttl_days.value=90`。

### 3.2 回归接线

- `.agent/regression/__init__.py:181-219`：新增 H 组检查。
- `.agent/regression/__init__.py:315-318`：完整回归固定执行该组。
- 状态语义：
  - `blocked == true`：FAIL，输出 metric、decay、threshold、IS/OOS、年龄、阻断理由和后果。
  - `blocked == false`：PASS。
  - 文件缺失：WARN，文字明确为“未判定（门禁从未运行），非通过”。
  - JSON 损坏或 `blocked` 非布尔：FAIL，不能伪装为通过。

### 3.3 每日链接线

- `scripts/automation_scheduler.py:47-48`：注册门禁脚本与 120 秒超时。
- `scripts/automation_scheduler.py:96-137`：以当前 Python 子进程运行门禁；使用 `CREATE_NO_WINDOW`，不会弹终端面板；stdout/stderr 同时写入调度输出和 `automation_daily.json` 摘要。
- `scripts/automation_scheduler.py:184-198`：requested mode=`daily` 时运行门禁；即使 A2 冻结把 orchestrator 降为 health，门禁仍运行。门禁报红不跳过原巡检，但进入总 rc。
- `scripts/automation_scheduler.py:200-215`：状态摘要新增 `walk_forward_gate`，任一门禁/原巡检失败则调度器总 rc=`1`。
- 未修改 `daily_pick.py`。

## 四、门禁产物新字段样例

当前 `data/walk_forward_gate.json`：

```json
{
  "is_sharpe": 0.9906,
  "oos_sharpe": 0.2122,
  "decay": 0.7858,
  "decay_abs": 0.7784,
  "decay_ratio": 0.7858,
  "threshold": 0.5,
  "metric": "ratio",
  "blocked": true,
  "n_windows": 894,
  "source_timestamp": "2026-10-17T06:34:23.076394",
  "data_age_days": 1,
  "ttl_days": 90,
  "block_reason": "衰减超阈值：样本外夏普相对衰减 0.7858 ... > 阈值 0.5",
  "exit_code": 3
}
```

## 五、实测输出

所有 Python 命令执行前均清空 `PYTHONPATH`，解释器为：
`C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe`。

### 5.1 当前真实数据：阻断，rc 非 0

```text
[walk_forward_gate] is=0.9906 oos=0.2122 decay(ratio)=0.7858 (abs=0.7784 ratio=0.7858) threshold=0.5 windows=894
[walk_forward_gate] 数据年龄: 1 天 (TTL=90 天, 真源=2026-10-17T06:34:23.076394)
[walk_forward_gate] 判定依据: 衰减超阈值：样本外夏普相对衰减 0.7858 ... > 阈值 0.5
[walk_forward_gate] 门禁结果: 阻断 -> data/walk_forward_gate.json
阻断理由: 衰减超阈值：样本外夏普相对衰减 0.7858 ... > 阈值 0.5
后果: 退出码 3 (被门禁阻断), 调度层判 FAIL
GATE_RC=3
```

### 5.2 TTL 过期：低衰减也必须阻断

构造 `IS=1.0 / OOS=0.9 / decay_ratio=0.1`，结果时间设为 2026-06-30，专门隔离验证 TTL：

```text
[walk_forward_gate] is=1.0 oos=0.9 decay(ratio)=0.1 threshold=0.5 windows=10
[walk_forward_gate] 数据年龄: 110 天 (TTL=90 天, 真源=2026-06-30T06:34:23)
[walk_forward_gate] 判定依据: 数据过旧无法判定（age=110 天 > 90 天）
[walk_forward_gate] 门禁结果: 阻断 -> data/walk_forward_gate.json
阻断理由: 数据过旧无法判定（age=110 天 > 90 天）
TTL_EXPIRED_RC=3
```

结论：TTL 确实是失败安全，衰减健康也不会让过期数据放行。

### 5.3 健康场景：低衰减且未过期，rc=0

同一隔离样本改为 2026-10-18：

```text
[walk_forward_gate] is=1.0 oos=0.9 decay(ratio)=0.1 threshold=0.5 windows=10
[walk_forward_gate] 数据年龄: 0 天 (TTL=90 天, 真源=2026-10-18T06:34:23)
[walk_forward_gate] 判定依据: 样本外夏普相对衰减 0.1 ... <= 阈值 0.5
[walk_forward_gate] 门禁结果: 通过 -> data/walk_forward_gate.json
[walk_forward_gate] 门禁通过, 退出码 0
HEALTHY_RC=0
```

临时结果文件随后已删除，并按真实 894 窗数据重跑恢复 `blocked=true / exit_code=3`。

### 5.4 回归检查三态

```text
=== 状态1：真实阻断 ===
[FAIL] walk-forward 衰减门禁——metric=ratio, decay=0.7858, threshold=0.5,
IS=0.9906, OOS=0.2122, age=1天/TTL=90天；
阻断理由：衰减超阈值 ...；后果：拦截提交，必须重跑或修复策略后再合入
计数 PASS=0 FAIL=1 WARN=0

=== 状态2：健康通过 ===
[PASS] walk-forward 衰减门禁（metric=ratio, decay=0.2, threshold=0.5,
IS=1.0, OOS=0.8, age=0天/TTL=90天；门禁已运行且通过）
计数 PASS=1 FAIL=0 WARN=0

=== 状态3：文件缺失 ===
[WARN] walk-forward 衰减门禁——未判定（门禁从未运行），非通过；
请先运行 scripts/walk_forward_gate.py
计数 PASS=0 FAIL=0 WARN=1
```

### 5.5 每日链 rc 与可见日志

为避免前台启动可能长达一小时的真实 orchestrator，测试中只把 `run_orchestrator` 替换为成功桩；门禁子进程、daily 分支、状态聚合和总 rc 均为真实代码。验证后已恢复 `data/automation_daily.json` 的生产快照。

```text
zhuanqian 每日调度 [2026-10-18 03:13:59]
[daily] 运行 walk-forward 衰减门禁 ...
[walk_forward_gate] 数据年龄: 1 天 (TTL=90 天, 真源=2026-10-17T06:34:23.076394)
[walk_forward_gate] 门禁结果: 阻断 -> data/walk_forward_gate.json
walk-forward 衰减门禁退出码=3
本次调度: ERROR
AUTOMATION_DAILY_RC=1
```

说明：真实 `scripts/daily_auto.bat` 已将 scheduler stdout/stderr 重定向到 `mainline/logs/daily_auto_cron.log`，因此上述门禁明细会进入既有每日链日志；本次没有修改 bat 或计划任务。

### 5.6 完整回归

```text
【H 组】walk-forward 衰减门禁
[FAIL] walk-forward 衰减门禁——metric=ratio, decay=0.7858, threshold=0.5,
IS=0.9906, OOS=0.2122, age=1天/TTL=90天；阻断理由：衰减超阈值 ...；
后果：拦截提交，必须重跑或修复策略后再合入

=== 汇总：PASS 18 / FAIL 1 / WARN 1（耗时 0.3s）===
回归结论：FAIL
REGRESSION_RC=1
```

WARN 为既有 `config.json` 与 `factor_weights.json` 漂移提醒；不是本次改动造成。本次预期新增 FAIL 已准确出现。

## 六、备份与清理

修改/覆盖前备份：

```text
scripts/walk_forward_gate.py.bak_20261017_laoliu
.agent/regression/__init__.py.bak_20261017_laoliu
scripts/automation_scheduler.py.bak_20261017_laoliu
config/walk_forward_gate.json.bak_20261017_laoliu
data/walk_forward_gate.json.bak_20261017_laoliu
data/automation_daily.json.bak_20261017_laoliu
```

验证用临时 walk-forward 结果已删除；测试桩产生的 `automation_daily.json` 已恢复生产快照。最终 `data/walk_forward_gate.json` 为真实 894 窗阻断结果。

## 七、并发与边界

- 未触碰 `data/factor_ic/`、`docs/`、`cron_config.json`、`deliverables/待老大拍板清单-20261017.md`。
- 未触碰 `daily_pick.py`。
- 工作区中上述 W9 路径及 `daily_pick.py` 已有其他未提交改动，但与本任务目标文件不重叠；未发生覆盖或冲突。
- `scripts/automation_scheduler.py` 中已有 W3 的 `CREATE_NO_WINDOW` 改动，本次在其现状上保留并复用，没有回退。
