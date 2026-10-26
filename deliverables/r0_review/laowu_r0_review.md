# R0 独立评审报告 — 实盘风控接 S3 权威源（移动止盈阶梯 + 时间止损）

**评审人**: 老五（独立评审/合规/风控守门，只读，签字权）
**评审时间**: 2026-10-09（周五）
**任务单真源**: `docs/R0任务单-实盘风控接S3权威源-20261009.md`
**评审对象**: `risk_monitor.py` 新增 `check_trailing_take_profit()`(L302-387) + `check_time_stop()`(L390-481)，接进 `generate_daily_report()` [5/5] 段（第5段移动止盈 L885-915 / 第6段时间止损 L917-955）；S7 circuit_breaker 段已被总管打回剔除。
**评审方式**: 全程只读（git diff/blame、grep、pytest、独立复跑 sanity、python -c 读文件/内存级 monkeypatch）；除本报告外零写。

---

## 结论总表

| # | 断言 | 结论 | 关键证据 |
|---|------|------|----------|
| 1 | 红线合规 risk_rules.py 零改 | ✅ | `git diff HEAD -- risk_rules.py` 空 + staged 清单无此文件 |
| 2 | 实盘数据零写 | ✅ | save_json 唯一调用点 L1049→仅 risk_report_latest.json；--report 前后 trade_log/holdings mtime 逐字节相同 |
| 3 | S7 drive-by 剔除干净 | ✅ | `grep -nE "circuit_breaker\|circuit_level\|S7 熔断\|S7熔断" risk_monitor.py` → No matches；报告 JSON circuit/S7 计数=0 |
| 4 | 阶梯档位边界（重点） | ❌ **P1 打回** | 浮盈恰=6% 实测 tier=0/lock=None（浮点 5.9999999999999964<6 漏档，无告警）；10%/25%/4% 边界正确 |
| 5 | 峰值口径 + peak_fallback 告警 | ✅ | L346-348 缺 peak→现价近似+warnings 含 peak_fallback；实测 3 处可见（banner/JSON/all_signals），非静默 |
| 6 | 时间止损 + calendar_fallback 告警 | ✅ | L466-467 阈值消费权威源；降级双告警（risk_rules L187 print + warnings 含 calendar_fallback）实测生效 |
| 7 | 接线在活模块 | ✅ | orchestrator.py:493 每日 subprocess 跑 risk_monitor.py --report；cron/daily_monitor.py diff 空；有持仓端到端实测第5/6段真算 |
| 8 | 测试质量（防假绿） | ❌ **P3 打回** | 6 例断言均为独立手判字面值（非回读实现）✅，但边界覆盖缺恰=6/10/25%、entry恰=115/120 日；118/121 例 mock 后未还原全局 |
| 9 | SOUL#9 扫雷 | ✅ | 12 处 except 逐处过：新增 2 处（L427/L459）均有显式 warning 标记，无静默吞异常；存量 L71 隐患单独留痕（非 R0 引入） |
| 10 | 等价性（--report 实跑） | ✅（含 P2 发现） | 新字段 trailing_take_profit/time_stop 出现；既有 4 项输出未破坏；S7 消失；**但第5段 banner 实打 "×100%" 错误（P2，见下）** |
| 11 | sanity 独立复跑 | ✅ | `python check_backtest_sanity.py` → 结论: PASS — 全部通过，exit 0（独立复跑 2 次均 PASS） |
| 12 | drive-by 全审 | ✅（风险范围内干净） | 357 行 diff 逐段过：5 组改动全在任务单 spec 内，无夹带；staged 区 7 个 R0 域外文件单独留痕待总管核归属 |

**最终结论**: ❌ **打回**（1×P1 + 1×P2 + 1×P3，均为具体可执行修复项，非架构问题；红线合规/零写/S7剔除/等价性/sanity 全部干净）

---

## 逐项断言详情

### #1 红线合规：risk_rules.py 本体零改 — ✅

命令与输出（实跑）：

```
$ git --no-pager diff HEAD -- risk_rules.py        → (空, exit 0)
$ git --no-pager diff -- risk_rules.py             → (空, exit 0)
$ git --no-pager diff --cached --stat -- risk_rules.py config.json factor_weights.json data/
→ config.json | 28 ±
→ data/holdings.json | 30 ±
→ data/review_status.json | 867 ±
（risk_rules.py 未出现在 staged 清单 = staged+工作区双向零改）
```

消费侧确认：`risk_monitor.py` L11-17 仅 `from risk_rules import (TREND_TP_LADDER, DEFAULT_TP_LADDER, TIME_STOP_TRADING_DAYS, TIME_STOP_WARNING_DAYS, count_trading_days)` 只读导入；L456 函数内 `from risk_rules import _load_trade_dates` 只读。`grep -n "risk_monitor" risk_rules.py` → No matches（权威源无反向依赖，单向消费成立）。

### #2 实盘数据零写（trade_log/holdings）— ✅

**代码面**：
- 全文件 `save_json(` 仅 2 处命中：L75（函数定义）+ **L1049 `save_json(RISK_REPORT_FILE, report)`（唯一写路径，目标 `data/risk_report_latest.json`）**。
- 新增两函数（L302-481）为纯函数：只读入参 dict，返回 dict，无任何 open/write/dump 调用。
- [5/5] 段对 holdings 的访问全部走 `load_json(HOLDINGS_FILE)`（L887，只读）；`TRADE_LOG_FILE` 仅被存量 `check_losing_streak` L215 只读消费。

**运行面**（实跑 `python risk_monitor.py --report` 前后）：

```
BEFORE: data/trade_log.json  mtime=2026-10-09 19:06:35.434949900 +0800
        data/holdings.json   mtime=2026-10-07 06:46:06.300979400 +0800
AFTER:  两者逐字节相同（未变）
```

测试面：`tests/test_risk_monitor_s3.py::test_zero_write_to_trade_data PASSED`（该用例内含 `generate_daily_report()` 全量调用 + 1.1s 睡眠后 mtime 断言）。

### #3 S7 drive-by 剔除干净 — ✅

```
$ grep -nE "circuit_breaker|circuit_level|S7 熔断|S7熔断" risk_monitor.py
→ No matches found (1 files searched)
```

报告产物面：`--report` 实跑后 `data/risk_report_latest.json` 全文 JSON 序列化串中 `circuit` 出现次数=0、`S7` 出现次数=0。stdout 输出无熔断段。剔除干净。

### #4 阶梯档位正确性（重点边界）— ❌ **P1 打回：浮盈恰=6% 浮点漏档**

**独立手判期望**（按任务单 S3 五档 `[(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]` 手算，非取实现值；cost=10.0，peak=cost×(1+pnl)）：

| 浮盈 | 手判应命中档/容忍 | 手判锁价 | 实测(实现输出) | 判定 |
|------|------------------|----------|----------------|------|
| 4% (peak=10.4) | 档0，未达首档激活 | None | tier=0 lock=None | ✅ 一致 |
| **恰=6% (peak=10.6)** | **档1，容0.15** | **10.6×0.85=9.01** | **tier=0 lock=None（漏档）** | ❌ **不一致** |
| 恰=10% (peak=11.0) | 档2，容0.05 | 11.0×0.95=10.45 | tier=2 lock=10.45 | ✅ 一致 |
| 恰=25% (peak=12.5) | 档4，容0.09 | 12.5×0.91=11.375→round=11.38 | tier=4 lock=11.38 | ✅ 一致 |
| 12% (peak=11.2，参考) | 档2，容0.05 | 11.2×0.95=10.64 | tier=2 lock=10.64 | ✅ 一致 |

**根因（浮点证据，实跑）**：

```
(10.6-10.0)/10.0*100 → repr=5.9999999999999964  >=6? False   ← 6% 价(10.0→10.6) 漏档
(106.0-100.0)/100.0*100 → 6.0                       >=6? True    ← 6% 价(100→106) 命中档1 lock=90.1
(10.600000000001-10.0)/10.0*100 → 6.000000000009997            >=6? True  ← 6%+ε 命中
```

实现 L351-360 用裸 `floating_pnl_pct >= activate_pct` 比较，无容差。**同一逻辑 6% 因价格量级（10 元 vs 100 元档）触发结果不一致**，且漏档时 `warnings` 为空、无任何提示——正是任务单第五节悲观场景点名的"该锁没锁（漏锁=吐回风险）"。10%/25% 边界恰为二进制精确值（10.0/25.0），当前侥幸正确，但 6% 这类不可表示值无保护。

**可执行修复建议（P1）**：档位命中比较加浮点容差，如 `if floating_pnl_pct + 1e-9 >= activate_pct:`（或百分比转整数基点 `round(pnl*10000) >= activate_pct*10000` 比较）；并在 TDD 表中补"恰=6%"边界用例（该用例在当前代码上必 RED，正是防假绿所缺的那条）。

### #5 峰值口径 + peak_fallback 告警不静默 — ✅

- 代码：L331 取 `holding.get("peak_price")`；L346-348 `if peak_price is None or peak_price <= 0: peak_price = current_price; warnings.append("peak_fallback")`——缺 peak 用当前价近似且**有告警标记**。
- 浮盈口径：L351 `floating_pnl_pct = (peak_price - cost) / cost * 100`，以峰值计浮盈（与任务单"当前浮盈落在哪一档"一致，peak 创高后浮盈只增不减，符合移动止盈语义）。
- 实测：`check_trailing_take_profit({cost:10.0, current_price:11.2, 无peak_price})` → `peak=11.2 lock=10.64 warnings=['peak_fallback']` ✅
- 告警可见性（非静默，3 条路径）：① L906-913 生成 `⚪ info` 信号入 `all_signals`；② L979-988 写入报告 JSON `trailing_take_profit[].warnings`；③ 面板可查。注：`risk_signals`（L968）按 severity 过滤只留 emergency/warning，peak_fallback(info) 不进 risk_signals，但 JSON+banner 路径完整，不构成交付缺陷。

### #6 时间止损正确性 + calendar_fallback 告警不静默 — ✅

**逻辑核对**（消费权威源，无硬编码）：
- L414/L430/L442/L464：`remaining_days = TIME_STOP_TRADING_DAYS - held_days`（=120，risk_rules.py:104，零硬编码副本）。
- L466：`time_stop_warning = remaining_days <= TIME_STOP_WARNING_DAYS`（=5，risk_rules.py:107）→ 剩≤5日 warning ✅
- L467：`time_stop_reached = held_days >= TIME_STOP_TRADING_DAYS` → ≥120日 reached ✅

**日历降级路径（非静默，双告警）**：
- 代码 L452-462：`count_trading_days` 成功后再查 `_load_trade_dates()` 为空 → `calendar_fallback=True`；except 最终回退 `(today-entry_date).days` 自然日 + `calendar_fallback=True`。L469-471 将标记入 `warnings`。
- 底层 risk_rules `_load_trade_dates()`（L174-188）三级降级各有 print 告警（读失败→"⚠️ 交易日历读取失败"；TDX 回退成功→"⚠️ 已回退TDX指数日历"；全败→"⚠️ 时间止损将按工作日近似计算…请尽快重建日历!"）——降级必有声音。

**实测**（内存级降级，不碰磁盘日历文件）：

```
正常日历: {'held_days': 367, 'remaining_days': -247, 'warning': True, 'reached': True, 'calendar_fallback': False, 'warnings': []}
日历缺失(内存置空): calendar_fallback=True warnings=['calendar_fallback'] held=398(自然日) warning=True reached=True
无entry_date: warnings=['no_entry_date']
畸形entry_date: warnings=['invalid_entry_date_format']
```

阈值边界手判：held=115 → remaining=5 → warning=True（≤5 含等号）；held=114 → remaining=6 → warning=False；held=119 → warning=True 且 reached=False；held=120 → warning=True 且 reached=True。实现 L466-467 语义与手判一致（`<=`/`>=` 均含等号，与任务单"剩≤5日/超120日"契约吻合）。

**留痕观察（非打回项）**：① `remaining_days` 在 held>120 时为负数（如 -247），banner L925 会打印"剩余-247日"——语义冗余但不误导（reached 已同时亮 🔴）；② 日历文件部分覆盖（实测覆盖 1990-12-19→2026-10-08）时 `count_trading_days` 对超出区间的日期漏计，该口径问题属 risk_rules 存量行为，非 R0 引入，建议后续单独立项。

### #7 接线位置：活模块 generate_daily_report，非死模块 — ✅

**活链路证据**（任务单缺口证据链同一链路）：
- `orchestrator.py:493` 实读：`r = subprocess.run([sys.executable, os.path.join(PROJECT, "risk_monitor.py"), "--report"], ...)` —— 每日 [5/5] 跑的活模块就是 risk_monitor.py。
- `git diff HEAD --stat -- cron/daily_monitor.py` → 空（死模块未触碰，接线没走错地方）。
- 死模块 `cron/daily_monitor.py` 内无 S3 消费点（diff 空即未加）。

**有持仓时第5/6段真会算（端到端实测）**：内存级 monkeypatch `rm.load_json` 注入 1 只合成持仓（peak=11.2/cost=10.0 浮盈12%，entry=2025-04-01），仅 patch 模块属性不写任何磁盘文件，实跑 `generate_daily_report()` 后还原：

```
stdout 第5段: "合成测试股(sh600000) 浮盈12.0% → 第2档 锁价=10.64 (峰值11.20×100%)"   ← "×100%"为P2缺陷, 见#10
stdout 第6段: "合成测试股(sh600000) 持有367日 剩余-247日 → 🔴 已达120日时间止损"
report JSON: trailing_take_profit=[{...lock_price:10.64, current_tier:2, triggered_tiers:2...}]
             time_stop=[{...held_days:367, time_stop_reached:True...}]
             all_signals 含 S3 信号 1 条（🔴 reached）
空仓时（真实 holdings.json=空仓）: 第5/6段打印"无持仓，跳过…"并落空数组 [] —— 分支覆盖正确
```

注：`generate_daily_report()` 末尾 L1059-1064 `trigger_debate` 仅在 total_pnl<-15/max_dd<-20/streak>=5 时触发（存量逻辑），本次实跑条件未满足未触发；合成持仓实验后已重跑 `--report` 恢复基线报告。

### #8 测试质量（防假绿）— ❌ **P3 打回：边界覆盖缺口 + mock 未还原**

**实跑**：`python -m pytest tests/test_risk_monitor_s3.py -v`（`-o addopts=""` 绕开 pytest.ini 的 --cov 插件缺失）→ **6 passed in 14.62s**。

**逐例审查**（断言是否为独立手判字面期望）：

| 用例 | 断言字面值 | 独立手判核对 | 判定 |
|------|-----------|--------------|------|
| 12% up | `lock≈10.64`(=11.2×0.95 手算)、`triggered_tiers≥2`、`abs(lock-11.2×0.85)>0.01`（显式排除误用首档15%容） | 11.2×0.95=10.64 ✅ 字面手算非回读实现 | ✅ 质量好（含防错用断言） |
| 4% 未达首档 | `lock is None`、`triggered_tiers==0`、`not alert_triggered` | 4%<6% → None/0 ✅ | ✅ |
| 缺peak | `lock is not None`、`"peak_fallback" in warnings` | 近似+告警 ✅ | ✅ |
| 118交易日 | mock `count_trading_days→118`，断言 warning=True/reached=False | 120-118=2≤5 ✅ 手判 | ⚠️ 见下 |
| 121交易日 | mock→121，断言 reached=True/warning=True | 121≥120 ✅ 手判 | ⚠️ 见下 |
| 零写 | 前后 mtime 断言（含 generate_daily_report 全量） | — | ✅ |

**打回项（P3，两条）**：

1. **边界覆盖缺口**：任务单第四节明确点名评审关注"阶梯档位边界（浮盈恰=10%/25%）"，TDD 表亦含 entry 118/121 两例。现 6 例**无一覆盖恰=6% / 恰=10% / 恰=25%**（浮盈侧只有 12% 与 4% 两个非边界点），entry 侧**无恰=115/120 日**（warning 阈值与 reached 阈值的等号边界）。正是 #4 的 6% 浮点漏档能一路 GREEN 混过测试的直接原因——缺的恰是那条必 RED 的边界用例。可执行修复：补 `test_trailing_tp_exactly_6pct`（cost=100, peak=106，断言 tier=1/lock=90.10，当前代码上因 10.6 量级浮点行为此用例需配合 P1 容差修复后转 GREEN，量级选择上建议同时覆盖 10.0→10.6 与 100→106 两组价）、`test_trailing_tp_exactly_10pct`（lock=10.45）、`test_trailing_tp_exactly_25pct`（lock=11.38）、`test_time_stop_115_days_warning`、`test_time_stop_120_days_reached`。
2. **mock 污染全局状态**：例4/例5 直接 `rm.count_trading_days = mock` 且**无 try/finally 还原**（L120-124/L152-153），pytest 顺序执行后模块级 `count_trading_days` 被替换为带"特判 start==entry and end==today"的 mock——对后续测试（例6零写）恰好无害（特判不命中即回落真函数），但属全局可变状态污染，换执行顺序即假绿/假红。可执行修复：改 `unittest.mock.patch.object` 上下文管理器，或 finally 还原。

### #9 SOUL#9 扫雷：except 逐处 — ✅

`grep -n "except" risk_monitor.py` 全量 12 处，逐处裁定（仅评 R0 交付面，存量行为留痕不追责）：

| 行 | 位置 | 行为 | 裁定 |
|----|------|------|------|
| L6 | 文件头 stdout reconfigure | `except: pass` | 存量，纯显示防御，可接受 |
| L71 | `load_json` | `except (JSONDecodeError, Exception): pass → None` | **存量隐患留痕**：`JSONDecodeError` 本身是 `Exception` 子类，并集写法冗余且吞掉一切（含权限错误）；调用方无法区分"文件不存在/坏JSON/被锁"。非 R0 引入，建议单独立项（本次不动） |
| L134 | `check_drawdown` TDX 取价 | `except: pass` 后走 0 价 | 存量，回撤监控侧，留痕 |
| **L427** | **check_time_stop entry_date 解析** | `except → 返回 warnings=['invalid_entry_date_format']` | ✅ **新增，非静默**：显式 warning 标记，且告警经 L946-953 入 all_signals + L991-1000 入报告 JSON |
| **L459** | **check_time_stop 日历计数降级** | `except → 自然日近似 + calendar_fallback=True + warnings` | ✅ **新增，非静默**：三层暴露——底层 risk_rules L187-188 print（"⚠️…按工作日近似计算…请尽快重建日历!"）+ 返回 dict `calendar_fallback` 布尔 + warnings 列表（实测均生效，见#6） |
| L563 | `_fetch_mcp_index_sector_data` | `except → return None` | 存量，MCP 数据侧，留痕 |
| L710 | `check_position_limit._resolve_price` | `except: pass → return 0` | 存量，留痕 |
| L745 | market_state 缓存读取 | `except: pass` 后走回退 | 存量，留痕 |
| L1116/L1143/L1165/L1197 | health_check/推送 | 均带 print/logger.warning 暴露 | 存量，非静默 |

**结论**：R0 新增代码零 `except: 默认值` 静默吞异常；两处新增 except 均为"降级+显式标记"，且标记沿 JSON/banner/all_signals 全链路可见。总管指名的 S7 埋雷（str/str 被 except 吞）随 S7 段剔除已不存在（#3 佐证）。

### #10 等价性：`--report` 实跑 — ✅（附带 P2 缺陷发现）

**实跑** `python risk_monitor.py --report`（exit 0），对照 `data/risk_report_latest.json`：

1. **新字段出现**：顶层 keys 含 `trailing_take_profit`、`time_stop`（当前空仓 → `[]`/`[]`；有持仓时内容正确见 #7 端到端实测）✅
2. **既有 4 项检查未破坏**（实跑输出逐项核）：
   - 1.回撤监控：正常打印（空仓 stock_count=0）✅
   - 2.连续亏损检测：`⚪ 交易记录不足 (0笔, 需≥3笔)` ✅
   - 3.市场风格检测：`当前市场风格: 科技成长` + 占比 dict ✅
   - 4.仓位合规检查：`当前仓位: 0.0% / 弱市 / 建议上限50% / ✅合规` ✅
   - `account_status/drawdown/losing_streak/position_control/market` 各子对象键齐全，`risk_score=100/100` 计算链未断 ✅
3. **S7 段消失**：stdout 无熔断段；报告 JSON `circuit`/`S7` 计数=0 ✅
4. **评分语义**：S3 信号（emergency/warning）并入 `all_signals` 参与 `calculate_risk_score`（L958-964 + L970），与既有 4 项同级参与扣分，符合任务单"接进主流程"spec ✅

**P2 缺陷（本项实跑现形，打回）**：第5段 banner L896：

```python
print(f"... 锁价={tp_result['lock_price']:.2f} (峰值{tp_result['peak_price']:.2f}×{1-tp_result.get('lock_tolerance',0):.0%})")
```

`check_trailing_take_profit` 返回 dict **无 `lock_tolerance` 键**（L379-387 返回字段清单核实），`.get('lock_tolerance',0)` 恒取默认 0 → `1-0=100%` → **每次有锁价时 banner 恒定打印 `×100%`**（实跑现形：`浮盈12.0% → 第2档 锁价=10.64 (峰值11.20×100%)`，正确应为 `×95%`）。锁价数值本身正确（10.64=11.2×0.95），但容忍度展示对读 banner 的人是错误信息——风控面板"显示值≠真实值"属风控纪律问题（SOUL#9 同源：决策感知失真），且该 bug 只会在**有持仓**时现形，当前空仓态下永远测不到。可执行修复：`check_trailing_take_profit` 返回 dict 补 `lock_tolerance` 字段（L379 处加一行），或 L896 改用 `1 - (ladder该档容)` 现算；并补一条有持仓的 banner 渲染用例。

### #11 sanity 独立复跑 — ✅

未采纳总管/老三结论，独立执行 `python check_backtest_sanity.py`（2 次，结果一致）：

```
PASS  变体数量>=2  (实际 8)
PASS  各变体成交笔数(8/8)  PASS  去重>=3(7种)  PASS  单票占比<=30%(3.2%)
PASS  不同股票>=10(115只)  PASS  平均持有>=5(36.6天)
------------------------------------------------------------
结论: PASS — 全部通过，可进入人工评审。   (exit 0)
```

输入 `data/rotation_backtest_result.json` 与本次 R0 改动无数据依赖（R0 不触回测产物），sanity 门 PASS。

### #12 drive-by 全审：`git diff risk_monitor.py` 逐段 — ✅（风险范围内干净）

diff 总量 357 行（`wc -l` 核实，`head -420` 已含全量，尾部为空）。逐段裁定：

| 改动块 | 内容 | 是否在任务单 spec 内 |
|--------|------|---------------------|
| ① L9-17 头部 | `from risk_rules import ...` 只读导入 5 个符号 + `from datetime import date` | ✅ spec §二"只 import，不改 risk_rules 本体" |
| ② L302-387 | `check_trailing_take_profit` 全文 | ✅ spec §二.1 |
| ③ L390-481 | `check_time_stop` 全文 | ✅ spec §二.2 |
| ④ L885-955 + L958-964 | [5/5] 第5/6段 + all_signals 并入 trailing/time alerts | ✅ spec §二"接进主流程"（实现为第5/6段而非 banner 两行，语义一致且信息更完整） |
| ⑤ L973-1001 + L1040-1041 | trailing_summary/time_stop_summary 汇总 + report 两个新字段 | ✅ spec §二"写入 risk_report_latest.json" |
| ⑥ L1062-1063 | 一行空行 diff（`-    \n+`，无实质内容） | 中性，无夹带 |

无第 7 块改动，**无任务单外夹带**；S7 段确认已被剔除干净（#3）。

**staged 区 R0 域外文件留痕**（非 risk_monitor.py 本体，未混入本次代码 diff，但同属未提交工作区，归属待总管核，**不在老五 R0 放行范围**）：`.hermes/cron.yaml`(M，timeout 300→120 + 新增 gate_check/trade_log_update 两 job)、`.hermes/cron/s3_daily.json`(A，新增 8:00 s3_auto_pipeline job)、`risk_rules_engine.py`(M，**"up"阶梯四档→五档对齐 risk_rules.py**，注释自称"与risk_rules.py对齐"——该文件自带副本 TREND_TP_LADDER 仍是潜在双源隐患，建议后续立项收敛)、`tests/test_risk_engine.py`(M，4→5 档断言配套)、`tests/` 多个新增/修改测试（P1 分诊/IC drift/PCA 等，296 行未提交清单内）、`data/holdings.json`(M，S3实盘启动空仓初始化)、`config.json`(M，factor_weights 大幅变更 21 因子→4 因子 + ic 日期推进)、`data/review_status.json`(M，867 行)。这些与 R0 交付无关，**本报告不做放行裁定**，提请总管确认其各自任务单归属后再议。

---

## 打回项汇总（可执行）

| 级别 | 项 | 位置 | 具体可执行修复 |
|------|-----|------|----------------|
| **P1** | 浮盈恰=6% 浮点漏档（5.9999999999999964<6，tier=0/lock=None 无告警），同逻辑 6% 因价格量级触发不一致，=任务单悲观场景"该锁没锁" | risk_monitor.py L351-360 | 比较加容差 `floating_pnl_pct + 1e-9 >= activate_pct`（或基点整数比较）；补恰=6% TDD 用例（10.0→10.6 与 100→106 两组价） |
| **P2** | 第5段 banner 恒定打印 `×100%`：`tp_result.get('lock_tolerance',0)` 键不存在，容忍度展示恒错（锁价数值本身对）；空仓态永远测不到 | risk_monitor.py L896 + L379-387 | 返回 dict 补 `lock_tolerance` 键（或 L896 现算）；补有持仓 banner 渲染用例 |
| **P3** | 测试边界覆盖缺口：无恰=6/10/25%、无 entry 恰=115/120 日用例（P1 因此能假绿）；例4/5 mock `rm.count_trading_days` 未 finally 还原（全局状态污染） | tests/test_risk_monitor_s3.py | 补 5 条边界用例；mock 改 `patch.object` 上下文或 finally 还原 |

## 放行范围声明

- 本报告仅放行/打回 **R0 任务单交付面**（risk_monitor.py 新增两函数 + [5/5] 接线 + tests/test_risk_monitor_s3.py + S7 剔除核验）。
- staged 区 7 个域外文件（cron.yaml/s3_daily.json/risk_rules_engine.py/test_risk_engine.py/config.json/holdings.json/review_status.json 等）**不在本次放行范围**，已留痕待总管核归属。
- 老五全程只读：除本报告文件外未写任何代码/配置/数据（含 data/ 下各文件）；`--report` 与端到端实验仅经 risk_monitor 自身写 risk_report_latest.json（允许路径），实验后已重跑恢复空仓基线报告。

---

**末行结论**：❌ 打回: ①[P1] risk_monitor.py L351-360 浮盈恰=6% 因浮点(5.9999999999999964<6)漏掉第1档(实测 tier=0/lock=None 无告警，同逻辑6%因价格量级触发不一致=任务单"该锁没锁"漏锁风险)→比较加1e-9容差并补恰=6%TDD用例；②[P2] L896 banner 引用不存在的 lock_tolerance 键，.get默认0致有持仓时恒定误显"×100%"(实跑现形，应为×95%/×85%)→返回dict补该键或改现算，并补有持仓渲染用例；③[P3] tests/test_risk_monitor_s3.py 边界覆盖缺恰=6/10/25%与entry恰=115/120日(致P1假绿)、例4/5 mock count_trading_days 未还原全局→补5条边界用例+patch.object/finally还原。红线合规/实盘零写/S7剔除干净/等价性/sanity PASS 均干净，修完三项重提复审即可。

（签字: 老五 · 2026-10-09 · 状态：❌ 打回，待老三修复后复审）
