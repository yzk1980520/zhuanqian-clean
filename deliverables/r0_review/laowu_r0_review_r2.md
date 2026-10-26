# R0 复审报告（R2）— 老三 3 项返修聚焦核验

**评审人**: 老五（R0 守门签字权，只读）
**复审时间**: 2026-10-09（周五，R1 打回后）
**复审范围**: 仅核 R1 打回的 3 项（P1 浮点6%漏档 / P2 L898 lock_tolerance 静默错 / P3 测试边界缺口+mock未还原）是否真修好 + 红线未破。R1 已 ✅ 的 #1/#2/#3/#5/#6/#7/#9/#11/#12 不重跑，维持 R1 结论。
**前情**: R1 报告 `deliverables/r0_review/laowu_r0_review.md` 打回 3 项（P1/P2/P3），红线合规/实盘零写/S7剔除/等价性/sanity 均干净。

---

## 结论总表

| 项 | R1 打回内容 | R2 核验 | 结论 |
|----|------------|---------|------|
| P1 | 浮盈恰=6% 浮点漏档（裸 `>=`，5.9999999999999964<6 → tier=0 无告警） | L360 加 `+1e-9` 容差；两组价量级实测均命中 tier=1 | ✅ 修好 |
| P2 | L898 banner 恒显 `×100%`（lock_tolerance 键不存在，.get 默认0） | 返回 dict L388 补键；banner 实渲染 `×95%`；未命中档 else 分支无 TypeError | ✅ 修好 |
| P3 | 测试缺恰=6/10/25%、entry恰=115/120 边界；mock 直赋全局未还原 | 补 5 边界例（独立字面断言）；4 处 mock 全改 `patch.object` 上下文自动还原；11 例全绿；6 旧例断言未削弱 | ✅ 修好 |
| 红线 | risk_rules 零改 / 交易数据零写 / S7 干净 / 无新夹带 | 四项全净（证据见下） | ✅ 未破 |

**最终结论**: ✅ **通过 R0 复审（3 项全修好 + 红线未破）**

---

## P1 复审：浮点 1e-9 容差 — ✅ 修好

**修复真身**（risk_monitor.py 实读）：
- L357 注释：`# 加 1e-9 容差防浮点漏档（如 10.0→10.6 算出 5.9999999999999964 < 6）`
- L361：`if floating_pnl_pct + 1e-9 >= activate_pct:`（原裸 `>=` 已替换，diff 中为 `+` 行确认非追加）

**独立探针**（`python -c` 实跑，期望为独立手判非回读实现；S3 五档 `[(6,0.15),(10,0.05),(15,0.07),(25,0.09),(999,0.12)]`）：

| 场景 | 手判期望(tier/lock/tol) | 实测 | 判定 |
|------|------------------------|------|------|
| **恰6% 百元股 100→106** | tier1 / 106×0.85=90.10 / 0.15 | tier1 / 90.1 / 0.15 | ✅ |
| **恰6% 十元股 10→10.6（R1漏档点）** | tier1 / 10.6×0.85=9.01 / 0.15 | tier1 / 9.01 / 0.15 | ✅（R1 此点 tier0/None，现修复） |
| 4% 10→10.4 | tier0 / None / None | tier0 / None / None | ✅ 不误进档（容差未过宽） |
| 恰10% 10→11.0 | tier2 / 10.45 / 0.05 | tier2 / 10.45 / 0.05 | ✅ 不回退 |
| 恰15% 10→11.5 | tier3 / 10.70 / 0.07 | tier3 / 10.69(=round(10.695,2)银行家舍入) / 0.07 | ✅ 差异<0.01，在锁价容差内 |
| 恰25% 10→12.5 | tier4 / 11.38 / 0.09 | tier4 / 11.38 / 0.09 | ✅ |
| 12% 参考 10→11.2 | tier2 / 10.64 / 0.05 | tier2 / 10.64 / 0.05 | ✅ |

7/7 PASS。容差 1e-9 量级正确：只吞浮点表示误差，4% 与档位间隙（4%→6% 差 2pp）不会被误吞。

## P2 复审：lock_tolerance 键 + banner 真容忍显示 — ✅ 修好

**修复真身**（risk_monitor.py 实读）：
- L363：命中档时 `lock_tolerance = tolerance` 赋值（循环内既有路径保留）。
- L388：返回 dict 新增 `"lock_tolerance": lock_tolerance`（未命中档 = None，与 lock_price=None 同构）。
- L898：banner `.get('lock_tolerance',0)` 现拿到真值。

**banner 端到端探针**（内存级 monkeypatch `rm.load_json` 注入 2 只合成持仓，不写磁盘，跑完还原并复跑 --report 恢复空仓基线）：

```
BANNER> 十二盈(sh600000) 浮盈12.0% → 第2档 锁价=10.64 (峰值11.20×95%)   ← R1 此处置恒显 ×100%，现正确 ×95%（=1-0.05）
BANNER> 四盈(sh600001) 浮盈4.0% → 未达首档激活(6%)                      ← 未命中档走 else 分支，不打印容忍
TypeError: 未发生（两行 banner 均渲染成功，generate_daily_report 完整返回）
```

**安全性论证**（非仅实测）：lock_price 仅在 lock_tolerance 非 None 时计算（L368-370），故 L898 进入 if 分支时 `lock_tolerance` 必然非 None，`.get(...,0)` 的默认 0 永不可能被取到 → 结构上排除 TypeError 与 ×100% 复发。

**留痕观察（非打回项）**：报告 JSON 的 `trailing_summary`（L981-991）未把 `lock_tolerance` 列入汇总字段（探针见 `report trailing[12%]: tol None` 为 .get 缺省值，非错值）。JSON 无错误展示、仅缺该信息字段，banner 才是 R1 点名的错误展示位且已修复；建议后续顺手补入，不阻塞放行。

## P3 复审：5 边界例 + patch.object 自动还原 — ✅ 修好

**实跑**（老五独立执行，非采信总管/老三输出）：`python -m pytest tests/test_risk_monitor_s3.py -v -o addopts=""` → **11 passed in 3.68s**（R1 为 6 passed，新增 5 例全部收集并 PASS）。

**5 条新边界例逐条核**（全文件 339 行实读，断言均为独立字面期望）：

| 用例 | 断言（实读行号） | 独立性核对 | 判定 |
|------|-----------------|-----------|------|
| `test_trailing_tp_exactly_6pct` (L90-130) | 组1 100→106：`tier==1`、`abs(lock-106.0*0.85)<0.01`、`tol==0.15`；组2 10→10.6：同构三断言（L107-110/L126-129） | 手算字面（106×0.85 内联乘积），**双价量级正是 R1 点名的浮点分化场景**，当前代码上必 RED→现 GREEN | ✅ |
| `test_trailing_tp_exactly_10pct` (L133-151) | `tier==2`、`abs(lock-11.0*0.95)<0.01`、`tol==0.05` | 手算字面 10.45 | ✅ |
| `test_trailing_tp_exactly_25pct` (L154-172) | `tier==4`、`abs(lock-12.5*0.91)<0.01`、`tol==0.09` | 手算字面 11.375≈11.38 | ✅ |
| `test_time_stop_115_days_warning` (L175-196) | mock→115，`warning is True`、`reached is False` | 120-115=5 恰压 `<=5` 等号边界 | ✅ |
| `test_time_stop_120_days_reached` (L199-219) | mock→120，`reached is True`、`warning is True` | 恰压 `>=120` 等号边界 | ✅ |

**mock 还原机制核**（R1 打回点：直赋 `rm.count_trading_days = mock` 无还原）：
- 4 处时间止损用例（115/120/118/121）现全部改为 `with patch.object(rm, 'count_trading_days', side_effect=lambda s,e: N if s==entry and e==today else rm.count_trading_days(s,e)):`（L189/L212/L235/L258），L11 新增 `from unittest.mock import patch`。
- `patch.object` 上下文管理器在 `with` 退出时（含异常路径）自动还原原函数 → **无全局污染**，用例间/与零写用例间状态隔离。✅
- 旧例 118/121 的直赋 mock 已被同构替换（L235/L258），R1 污染路径全部消除。✅

**6 旧例防假绿断言未被削弱核**（逐行比对 R1 记录）：
- 12% 例 L40-44：`lock is not None` / `abs(lock-10.64)<0.01` / `triggered_tiers>=2` / **`abs(lock-11.2*0.85)>0.01`（防错用首档15%容的关键断言，原样保留）** ✅
- 4% 例 L63-65：`lock is None` / `triggered_tiers==0` / `not alert_triggered` 原样 ✅
- peak_fallback 例 L85-86：`lock is not None` / `"peak_fallback" in warnings` 原样 ✅
- 零写例 L268-307：mtime 前后断言 + 含 `generate_daily_report()` 全量调用，原样 ✅

**留痕观察（非打回项）**：patch 的 side_effect 回退分支 `rm.count_trading_days(s,e)` 在 with 块内取到的是 mock 自身——若入参不匹配（s≠entry 或 e≠today）将递归进 mock。当前用例入参恒匹配（L453 唯一调用点传 (entry_date, today)），该分支实际不可达，11 例全绿已证无运行时影响；建议后续改为预先捕获真函数（`_real = rm.count_trading_days` 于 patch 前）再入 side_effect，消除潜在递归。不阻塞放行。

## 红线复核（签字前必核）— ✅ 全部未破

| 红线 | 命令与输出（老五实跑） | 判定 |
|------|----------------------|------|
| risk_rules.py 本体零改 | `git --no-pager diff HEAD -- risk_rules.py` → 空，EXIT=0 | ✅ |
| trade_log.json 零写 | `git status --porcelain -- data/trade_log.json` → 空；磁盘 mtime=2026-10-09 19:06:35（与 R1 评审时逐字节相同，返修轮未动） | ✅ |
| holdings.json 零写 | 磁盘 mtime=2026-10-07 06:46:06（停 10-07，与 R1 相同）；`M data/holdings.json` 为 429 既有 staged（S3 实盘启动空仓初始化，R1 已留痕归因，非本次返修产生） | ✅ |
| S7 仍剔除干净 | `grep -nE "circuit_breaker\|circuit_level\|S7" risk_monitor.py` → 无命中，GREP_EXIT=1 | ✅ |
| 返修无新夹带 | `git diff -- risk_monitor.py` 全量 `+` 行过滤复查：除 R0 原 5 块（R1 #12 已逐段裁定）外，新增行仅为 `1e-9` 容差行（L361 替换原裸 `>=`）、`lock_tolerance` 赋值/返回键（L363/L388）、L898 banner 行（R0 原有行的容差键修正），无第 6 块任务单外改动；diffstat 308 行（306+/2-），与"R1 306 行 + 2 处修复净增"吻合 | ✅ |
| 回归/pytest/sanity | pytest 老五独立跑 11 passed；`check_backtest_sanity.py` 老五独立复跑 → `结论: PASS — 全部通过，可进入人工评审。` exit 0（总管代跑结论未采信，以本次独立输出为准） | ✅ |

---

## 放行声明

- 3 项 R1 打回项（P1/P2/P3）经老五独立探针 + 逐行读盘 + 独立 pytest 核验，**全部真修好**；红线四项 + 无新夹带复核未破。
- 两处留痕观察（JSON summary 缺 lock_tolerance 字段 / patch side_effect 回退分支潜在递归）均为非阻塞改进建议，已记录在案，建议并入后续技术债清单，不影响本次签字。
- 老五 R2 复审全程只读：除本报告外零写（banner 探针经 risk_monitor 自身写 risk_report_latest.json 属允许路径，实验后已复跑 --report 恢复空仓基线：`trailing_take_profit=[] time_stop=[]`）。
- R1 报告中 #1/#2/#3/#5/#6/#7/#9/#11/#12 的 ✅ 结论在 R2 红线复核范围内持续成立（risk_rules 零改/零写/S7 干净为同一红线，本复核实跑复核）。

---

**末行结论**：✅ 通过 R0 复审(签字:老五)

（签字: 老五 · 2026-10-09 · 状态：✅ R0 放行，可交总管验收合入）
