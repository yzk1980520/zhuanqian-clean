# Hermes cron 脚本漂移诊断与处置

- 日期：2026-10-17
- 处置人：老六（WorkBuddy）
- 触发：老大选定「先清 Hermes 3 个报错 job」
- 结论：**3 个报错 job 全部清零**（实跑 exit 0），并**额外挖出并修掉 1 个假警报**（老四每日自审）
- 数据时效：所有实跑均为 2026-10-17 05:45–05:48 本机实测

---

## 一、根因：一句话

**Hermes 只在 `<hermes-home>/scripts/` 找脚本，于是历史上把项目脚本"拷一份"进去跑。**
副本既会过期，又携带了路径解析错误：

```python
PROJECT_ROOT = Path(__file__).parent.parent   # 脚本在 hermes-home/scripts/ 下
# → 解析结果是  <hermes-home>                ❌
# → 而不是      D:\open code\zhuanqian       ✅
```

后果分两类，都是**静默的**：
- 读不到文件 → 报「xxx 不存在」的**假红**
- 产物写进 `hermes-home/data/` → 项目里那份冻结不动，job 状态照样 `ok` 的**假绿**

全仓共 **8 个脚本同病**：`cooldown_eval` / `gate_check` / `gateway_guardian` / `laosi_audit` /
`market_signal_monitor` / `team_discussion` / `team_health_check` / `weekly_review`。

---

## 二、解法：转发器模式（不改业务逻辑）

新建 `data/hermes-home/scripts/zq_shim.py`：

| 能力 | 说明 |
|---|---|
| `get_project_root()` | env `ZQ_ROOT` 优先，默认 `D:\open code\zhuanqian`；用 `AGENTS.md` + `risk_rules.py` 两个标记文件校验，指错就响亮失败 |
| `run_project_script(relpath)` | runpy 同进程执行项目内唯一副本；stdout/stderr 原样透出（Hermes 抓日志不受影响）；`sys.exit(n)` 原样传播 → cron 看到真实退出码；目标缺失 **exit 2**，绝不静默降级 |

**系统里本来就有先例**：`daily_pick.py`（468B）早就是「硬编码项目根 + subprocess 转发」，本次与既有约定一致，不是新发明。

### 已改动的 profile 脚本（均留 `.bak_20261017_laoliu`）

| 脚本 | 处理方式 |
|---|---|
| `gate_check.py` | 转发器 → `scripts/gate_check.py` |
| `auto_tdx_refresh.py` | 转发器 → `scripts/auto_tdx_refresh.py` |
| `lhb_backfill.py` | 转发器 → `scripts/lhb_backfill.py` |
| `laosi_audit.py` | 转发器 → `scripts/laosi_audit.py` |
| `weekly_review.py` | profile-only（项目无同名），改用 `zq_shim.get_project_root()` |

---

## 三、三个报错 job 的处置结论

### 1. `f97800f5` S3因子门禁日检 —— 路径错，不是没算

- 报错：`❌ factor_ic.json 不存在`
- 真相：`data/factor_ic.json` **一直都在**（1734B）。是副本把项目根解析成了 `hermes-home`。
- 处置后实跑：**exit 0**，有效因子 12 个 ≥ 阈值 8 ✅

### 2. `3498d272` TDX数据每日刷新 —— 不是数据灾难

- 报错：`No module named 'numpy'`，0/6 成功，并衍生「滞后 9181 天」的误导性告警
- 真相：**项目版早就修好了**（`scripts/auto_tdx_refresh.py` 含"缺 numpy 自动重跑到 venv"自举），
  profile 那份是 10-15 的旧副本，没有这个修复。TDX 源数据本身是好的（最新 2026-10-16）。
- 处置后实跑：**exit 0**，`✅ 数据新鲜，无需刷新`
- 环境事实：系统 python **无 numpy**；`C:\Users\WIN10\.quant-stock-picker\.venv`（numpy 1.26.4）
  与项目 `.venv`（numpy 2.4.6）都有 → **不需要装任何全局依赖**

### 3. `c7e3f9a2b104` LHB每日拉取器 —— 文案误导

- 报错：`Script not found: ...\lhb_daily_fetch.bat`
- 真相：job 的 `script` 字段**当前是 `lhb_backfill.py` 且该文件存在**，报错是历史残留。
  已同步为转发器。**job 本身 `enabled=false(paused)`，是否启用由老大/总管决定**，本次未改其开关。

> `jobs.json` 的 `last_error` 字段**未手改**（Hermes 守护进程持有并会抢写）。
> 下周一（2026-10-19）自然跑批会覆盖清空。

---

## 四、额外挖出并修掉的假警报（比三个报错更值钱）

`77b60cf80400 老四每日自审` —— cron 状态一直是 `ok`，实际：

| 项 | 旧副本（6035B，项目里已是 7872B） | 改用项目版后 |
|---|---|---|
| 检查项 | **只跑 3 项**，`factor_ic` / `signal` 恒为 `na` | 6 项全跑，全 pass |
| 告警 | 每天报 **P0「holdings.json 不存在」**（项目里明明有，它去 hermes-home 找了） | 无假 P0 |
| 报告落点 | `hermes-home/data/laosi_audit_report.json`，项目里那份**冻在 10-16 04:39** | 正常写入项目 |
| 结果 | — | 闭环完整率 100%，发现 4 条（含 IC 反向因子 10 个） |

误放的旧报告**未删除**，改名隔离为
`hermes-home/data/laosi_audit_report.json.MISPLACED_stale_20261017`。

---

## 五、剩余风险（未处理，待老大定）

| 项 | 现状 | 建议 |
|---|---|---|
| `worktree_regression.py` | profile 与项目**同尺寸 13210B 双份** | 现在没漂移，以后会。建议一并转转发器 |
| `worktree_leak_detector` / `evolution_first_pass` / `laosi_p0_poll` / `laosi_daily_digest` | 仅 profile 有，且**不在** `parent.parent` 病害名单 | 暂判安全，观察 |
| **S3 门禁口径打架** | 门禁读的 `data/factor_ic.json` 停在 **10-08**，给 12 个有效因子、舒服通过；而 10-16 的最新计算 `factor_ic/factor_ic_latest.json`（132d 精确口径）几乎把因子全判 dead | **门禁的"通过"建立在 9 天前的旧账上。** 需老大/老五定：门禁认哪一份口径、谁来定期刷新它 |

---

## 六、本轮验证

- 三个转发目标全部命中项目唯一副本：`gate_check` 3554 / `auto_tdx_refresh` 7356 / `lhb_backfill` 6078
- `gate_check` 实跑 **exit 0**；`auto_tdx_refresh` 实跑 **exit 0**；`laosi_audit` 实跑 **exit 0**（6 项）
- `weekly_review` 导入已指向 `D:\open code\zhuanqian\scripts\team_discussion.py` ✅
- 项目回归套件：**PASS 18 / FAIL 0 / WARN 1**（WARN 为既有的因子权重不同步，与本次无关）

## 七、回滚方式

任一脚本：`cp <name>.py.bak_20261017_laoliu <name>.py`
