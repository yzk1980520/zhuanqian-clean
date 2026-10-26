# D-15② PV_CORR20 与 vol_price_corr_20 计算等价性独立核验（老五·R1 只读评审）

**任务**: t_09b7f561 ｜ **评审人**: 老五（数据回测专家）｜ **日期**: 2026-10-27
**呈报对象**: 老大（供 D-15② 并入拍板）
**风险分级**: R1（因子等价性裁定材料；零代码改动，diff 空）

---

## 〇、结论先行

✅ **等价（计算等价）**。`PV_CORR20`（132d 权威源注册表因子）与 `vol_price_corr_20`（config 因子，引擎实现）在公式、窗口、符号约定、数据源四个维度**逐项一致**；在 132 日全量真实数据上，两实现的**逐日 IC 序列 30/30 抽样日 Δ=0.000000**，真实引擎函数交叉验证 30/30 只 absdiff=0.0。

→ D-15 材料 L42 的"候选等价 PV_CORR20 有数据：ic=-0.0487 / icir_nw=-0.2874 / t_nw=-3.30 / status=dead"**可作 vol_price_corr_20 的代理证据引用**，"同源等价性需 R0 裁定"项可以关闭。

两项**差异项**（历史长度门槛 ≥21 vs ≥20；零方差时 None 剔除 vs 0.0 填充）在 132 日真实数据上**零次触发**（Σ n_rnone=0），且在生产路径约束下（refresh MIN_BARS=60；引擎调用方要求 ≥30 根）**不可达**，不影响等价结论。

【悲观场景】若不等价被裁定成立，代价仅为 vol_price_corr_20 需单独补跑 132d 才能入注册表（现权重 0 已失活，对实盘零影响）；本裁定不改变任何现网行为。

---

## 一、数据口径声明（SOUL 准则 7：引擎 commit + 数据截至日）

| 项 | 值 | 证据 |
|---|---|---|
| 引擎 commit（仓 HEAD） | `e1ac573f`（D:/open code/zhuanqian） | `git rev-parse HEAD`，probe 自动取证 |
| 引擎解释器 | repo `.venv` Python 3.11.9（numpy 2.4.6，= 生产周调度同一解释器） | `scripts/Zhuanqian_FactorIC132d.bat` 指向 `.venv\Scripts\python.exe` |
| 数据截至日 | 2026-10-23（权威源 asof/last_date）；last_ic_date=2026-10-16 | `data/factor_ic/factor_ic_latest.json` 顶层字段 |
| 权威源 PV_CORR20 | ic=-0.0487, icir_nw=-0.2874, t_nw=-3.30, status=dead, sample_size=132 | 同上（computed_at=2026-10-25 06:43:26, source=pure_python_v10_exact_132d） |
| universe | 1556 槽 A 股 ∩ 当日可读文件 = **1484 只**（72 只文件缺失，见 §六.2） | `data/audit/aa_universe_probe_old_20261026.json`（10-26 老五审计探针，2000 槽 code 列表）+ 读盘 |
| 窗口/前瞻/截面门 | 132 日 / forward 5 日 / align=0 / min_section=50 / min_bars=60 | refresh 模块常量（WINDOW_DAYS=132, FORWARD_DAYS=5, MIN_SECTION=50, MIN_BARS=60） |
| IC 算术源 | `core/scoring/factor_gate_v2.spearman_ic`（仓内单一算术源约定） | refresh L62-64 注释"禁止在本文件重复实现" |

---

## 二、两实现逐项 diff（公式/窗口/归一化/缺失值/分母）

### 2.1 R = PV_CORR20（`scripts/factor_ic_132d_refresh.py` L514-528，注册表 L1008）

```python
def _pv_corr20(v, c):
    if len(c) < 21 or len(v) < 21:      # 总根数门槛 ≥21
        return None                      # 缺失值语义: None → 该行整行剔除出 IC 截面
    cv = c[-20:]; vv = v[-20:]          # 窗口 = 最后 20 根
    mc = sum(cv)/20; mv = sum(vv)/20
    num = sum((cv[i]-mc)*(vv[i]-mv) for i in range(20))
    den = (sum((x-mc)**2 for x in cv) * sum((x-mv)**2 for x in vv)) ** 0.5
    if den == 0:
        return None
    return num / den                    # 原始和形式 Pearson
```
调用：`'PV_CORR20': lambda c, o, h, l, v, a: _pv_corr20(v, c)`（只用 close、volume 两个字段）

### 2.2 E = vol_price_corr_20（`core/scoring/tdx_indicators.py` L362-375 局部函数，调用点 L398）

```python
def _correlation(x, y, window):
    if len(x) < window or len(y) < window:   # 总根数门槛 ≥20
        return 0.0                            # 缺失值语义: 填 0.0 留在截面
    x_w = x[-window:]; y_w = y[-window:]      # 窗口 = 最后 20 根
    mx = sum(x_w)/window; my = sum(y_w)/window
    cov = sum((x_w[i]-mx)*(y_w[i]-my) for i in range(window)) / window
    sx = (sum((v-mx)**2 for v in x_w) / window) ** 0.5
    sy = (sum((v-my)**2 for v in y_w) / window) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return cov / (sx * sy)                   # 归一化形式 Pearson
```
调用：`vol_price_corr_20 = _correlation(c, v, 20) if len(c) >= 20 and len(v) >= 20 else 0.0`

### 2.3 逐项对照表

| 维度 | R（PV_CORR20） | E（vol_price_corr_20） | 判定 |
|---|---|---|---|
| 窗口 | 最后 20 根 | 最后 20 根 | ✅ 同 |
| 公式 | Σdev²/√(Σc²·Σv²)（原始和） | (Σdev²/w)/(√(Σc²/w)·√(Σv²/w))（归一化） | ✅ 代数恒等（同分母 w 约去，两式逐字段同） |
| 价格序列 | close 原始值 | close 原始值 | ✅ 同（均无 rank/标准化） |
| 量能序列 | volume 原始值（股） | volume 原始值（TDX .day，股） | ✅ 同（§三.E4 实证 vol 比=1.0） |
| 符号约定 | 原始相关，不取负 | 原始相关，不取负 | ✅ 同（tdx_score_original L1002 注释"已取负号"系陈旧错误注释，代码 L398 无负号，见 §六.1） |
| 历史长度门槛 | ≥21 根（len<21→None） | ≥20 根（len<20→0.0） | ⚠️ 边界差异，生产不可达（refresh MIN_BARS=60；引擎调用方 stock_picker_v3 L257 要求 ≥30 根） |
| 零方差处理 | den==0→None，行剔除 | sx/sy==0→0.0 填充留截面 | ⚠️ 缺失值语义差异，132 日真实数据 0 次触发（Σ n_rnone=0） |
| 截取长度 | 至多 250 根窗口 | 生产 200 根（`get_tdx_data(code,200)`） | ✅ 无影响（因子只取最后 20 根，两窗口末 20 根相同） |
| 数据源 | data/history_daily/*.json（TDX 同源） | D:\TDX\vipdoc *.day（通达信日线） | ✅ 同源（§三.E4 实证） |

---

## 三、数值证据（全部一手，可复跑）

### E1 真实引擎函数交叉验证（公式等价·最强证据）
- 对 30 只股票 × 末截面日 2026-10-16，用 **200 根 records（生产 `get_tdx_data(code,200)` 口径）** 实调仓内 `tdx_indicators.compute_indicators()`，取其返回值 `inds["vol_price_corr_20"]`，与（a）老五复刻的引擎语义 E_corr、（b）refresh 注册表函数 R_fn 三方对照：
- **30/30 absdiff=0.0**（如 sh600000：engine_fn=0.401803748443 = e_copy = r_fn），`r_defined=30/30`。
- 命令：`.venv/Scripts/python.exe probe_d15_2.py phase1` → `phase1_evidence.json :: A3_real_engine_xcheck`
- 含义：**生产引擎实际运行代码**与 132d 注册表函数在相同数据上产出逐位相同的因子值。

### E2 30 日抽样 IC 对照（验收口径·机判）
- 132 日全量逐日计算三序列：ic_r（R 官方口径：R 有定义∩fwd 有效）、ic_e_incl（E 全量：含 0.0 填充行）、Δ=ic_e_incl−ic_r。
- **末 30 日（2026-08-28 ~ 2026-10-16）逐日 Δ=+0.000000，30/30 日一致**；30 日中无一日 |Δ|>0.005。
- 逐日样本量 n_both≈1468~1476（均值 1471.9），n_rnone=0。
- 30 日抽样表（节选全表见 `phase2_per_date.json :: last30`）：

| 截面日 | ic_r（=ic_e_incl） | Δ | n |
|---|---|---|---|
| 2026-08-28 | -0.0289 | +0.000000 | 1476 |
| 2026-09-14 | +0.1450 | +0.000000 | 1470 |
| 2026-09-21 | -0.2161 | +0.000000 | 1471 |
| 2026-09-22 | -0.2592 | +0.000000 | 1471 |
| 2026-10-08 | -0.0835 | +0.000000 | 1472 |
| 2026-10-15 | -0.1380 | +0.000000 | 1471 |
| 2026-10-16 | -0.0902 | +0.000000 | 1470 |

- 含义：缺失值语义差（0.0 填充）在本数据上**未改变任何一日 IC**（无触发行）；即便语义差异成立，30 日实测 Δ 仍为 0。

### E3 132 日均值 IC vs 权威源（harness 校验）
- 老五复算 mean IC_R(132d) = **-0.0536**；权威源 ic=-0.0487；Δ=-0.0049。
- 差值归因（非公式差，公式已由 E1 逐位证同）：① 老五复算截面=「PV_CORR20 有定义∩fwd 有效」，权威源截面另加 74 因子全 gate（单日对照 2026-10-16：74-gate IC=-0.0974, n=1379 vs 无 gate IC=-0.0902, n=1470，gate 剔 ~6% 行使单日 IC 偏 0.007）；② 72 只 universe 文件缺失（1484/1556）。
- 判定：Δ=0.0049 在归因幅度内 → 复算 harness 与权威源同口径，自洽。

### E4 数据源交叉（TDX .day vs JSON history_daily）
- 5 只（sh600000/0004/0006/0007/0008）× 20 bar：匹配 bar 19/20（未匹配 1 根=2026-10-23 截断后日期，已标记 post_cutoff），**匹配 bar close 严格相等 100%，volume 比值=1.0（同单位，股）**。
- 含义：refresh 的 JSON 与引擎的 TDX .day 是同一 TDX 日线数据源的两种载体，因子输入值同源。

### E5 harness 自测（复算循环 ≡ 官方管线）
- 复刻循环（含 74 因子 row_ok gate + T1 hook 等效 + align=0）vs 仓内 `refresh.compute()` 官方调用，10 个截面日（首 5+末 5）逐日 IC **10/10 逐位相等**（如 2026-04-01：0.07978338325897986=0.07978338325897986；2026-10-16：-0.09741811828341787 两侧相等）。
- 含义：E2/E3 所用逐日循环与官方 132d 管线行为一致，数值可比。

### 证据文件
- `D:/.../kanban/workspaces/t_09b7f561/probe_d15_2.py`（probe 本体，只读仓代码）
- `phase1_evidence.json`（A2 公式逐案 + A3 实函数 30/30 + A4 数据源 + S 自测 10/10）
- `phase2_per_date.json`（132 日逐日三序列 + last30 抽样 + gate_date_74 对照）

---

## 四、差异项定位（验收准则 3，等价情形下的残留差异清单）

| # | 差异项 | R 行为 | E 行为 | 生产可达性 | 实测触发（132d×1484 只） |
|---|---|---|---|---|---|
| D1 | 历史长度门槛 | 总根数 <21 → None（剔除） | <20 → 0.0 | 不可达：refresh MIN_BARS=60；引擎调用方（stock_picker_v3 L257 等）要求 ≥30 根 | 0 次 |
| D2 | 零方差/退化日 | den==0 → None（剔除） | sx/sy==0 → 0.0（留截面） | 仅 20 根全零方差窗口（长期停牌等） | Σ n_rnone=0 |
| D3 | 缺失值截面影响 | 剔除行 | 填 0.0 行 | 同 D2 触发条件 | 30 日抽样 Δ 全 0 |

D1/D2/D3 均**不影响"等价"结论**：差异只在定义域边界上，而边界在生产约束下不可达，且 132 日全量实测零触发。

---

## 五、对 D-15② 拍板的量化建议

1. **可裁定等价**：PV_CORR20 的 132d 数据（ic=-0.0487 / icir_nw=-0.2874 / t_nw=-3.30 / status=dead，权威源 @e1ac573f 数据截至 2026-10-23）可作 vol_price_corr_20 的代理证据，D-15 材料 §五.3 的"候选等价，需 R0 裁定"关闭。
2. 代理证据仍只覆盖 IC/IR 两门：单调性（5 分位池化）权威源未覆盖 PV_CORR20 → D-15 材料 §二 第 5 行"③单调性未证实"维持，若拍板保留该因子须补单调性复跑（材料 §四 已列前置）。
3. 失效触发条件（反例自检）：本等价结论在以下任一事件发生时作废并需复验——`_pv_corr20` 或 `tdx_indicators._correlation` 或调用点 L398 出现任何代码 hunk；数据源从 TDX 日线切换（换源/换单位）；refresh MIN_BARS 或引擎调用方最小根数变更使 20-21 根边界可达。
4. 现网影响面：vol_price_corr_20 权重 0（失活），本裁定**不改变任何实盘行为**；影响面仅限因子去留决策的数据引用。

---

## 六、附带发现（P2 文档缺陷 + 数据缺口，不阻塞本裁定）

1. **陈旧注释两处**（建议顺手清理，R2 级）：
   - refresh L515 `_pv_corr20` docstring 称"Spearman 近似：用秩和 Pearson 估算"——实际代码是**原始值 Pearson，无任何 rank**，docstring 失真；
   - `tdx_score_original.py` L1002 注释"compute_indicators 中 alpha13/vol_price_corr_20 已取负号"——`tdx_indicators.py` L398 对 vol_price_corr_20 **未取负号**（仅 alpha13 取负），注释错误，易误导后续调权重方向。
2. **72 只 universe 文件缺失**（1556→1484，如 sh600068/sh600070/sh600077…，10-26 探针在册、当前 data/history_daily 无文件）：建议老三排查数据目录清理/下载链；影响面=132d 复算 universe 4.6% 缩水（§三.E3 已量化进 Δ 归因）。
3. **槽窗位移**（记录在案）：今日 `_load_universe(2000)` 仅得 1226 只 A 股（新增文件使 2000 槽关窗点前移）——周调度 `--max-stocks 1000` 与权威源 2000 槽口径本就不同，若调度日刷新将产生 universe 收缩漂移，建议总管在下次 132d 周刷新的 G-B 守卫（同名因子覆盖率≥80%）判读时注意。

---

## 七、验收对照（本卡 acceptance_criteria）

1. ✅ 结论二选一：**等价**；≥2 一手证据：E1（实函数 30/30 diff=0）+ E2（30 日抽样 IC 对照 30/30 Δ=0.000000）+ 公式逐项 diff（§二.3 表）——超配。
2. ✅ 引擎 commit：仓 HEAD `e1ac573f`（`.venv` Python 3.11.9），数据截至 2026-10-23，universe 1484（1556 在册 ∩ 72 缺失），全量 132 日口径。
3. ✅ 差异项逐一定位：D1 窗口门槛 / D2 零方差分母 / D3 缺失值语义（§四），均标注生产不可达 + 实测 0 触发。
4. ✅ 报告 1 件 md（本件，deliverables/）；**零代码改动**：probe 仅读仓代码/数据（仓内无任何写操作），仓 git working tree 变更清单（18 条）全部为生产 cron 既有产物，与本卡无关（快照 `git_status_before.txt`，前后一致）。

---
*老五 · 数据回测专家 ｜ 证据链：probe_d15_2.py → phase1_evidence.json / phase2_per_date.json → 本报告*
