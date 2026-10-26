# D11 · integrated_picker 包/模块双实现合并报告

- 日期: 2026-10-19
- 执行: merge-integrated-picker（老大拍板 D11）
- 结论: **`apply_tradability_filter` 只剩一份** —— import 侧命中的就是根目录 `integrated_picker.py`。
- 未触碰: `data/review_status.json`、`scripts/s3_auto_pipeline.py`、任何阈值/窗口/池子。

---

## 一、改动文件清单（含备份名）

| 文件 | 动作 | 备份 |
|---|---|---|
| `integrated_picker/filters.py` | **删除**包内第二份 `apply_tradability_filter`(及仅供它使用的 `_is_main_board`、5 个 config 常量导入、`from tdx_core import is_st_stock`)；改为 **re-export 根模块那一份**（模块级 `__getattr__`）；ATR 守卫改为单源守卫 | `integrated_picker/filters.py.bak_20261019_laoliu_d11` |
| `integrated_picker/__init__.py` | ① 改写 2026-09-25 冻结警告（原文自称「生产权威入口 = 根目录 integrated_picker.py」，与 import 实测相反，是第二个真源）；② `apply_tradability_filter` 不再从 filters 直接导入，改为延迟 re-export | `integrated_picker/__init__.py.bak_20261019_laoliu_d11` |
| `integrated_picker/pipeline.py` | 模块级 `from integrated_picker.filters import ... apply_tradability_filter` 去掉；改为在函数体内（循环前）延迟取一次。**解包方式不变** | `integrated_picker/pipeline.py.bak_20261019_laoliu_d11` |
| `integrated_picker/_root_bridge.py` | **新增**（39 行）：按文件路径以别名 `integrated_picker_root` 加载根目录 `integrated_picker.py` 并做单例缓存 | 无（新文件） |
| `_diag_integrated_picker_shadow_20261019.py` | 末行写死的「[结论] import 侧活的是包版…」改为按实测算（写死的结论本身也是第二真源）。**注意：本文件 git 未跟踪**（与 `_diag_tdx_restore_20261012.py` 一致），未入库 | 无 |

> 备份后缀说明：`filters.py.bak_20261019_laoliu` / `config.py.bak_20261019_laoliu` 是当天更早（D9-3）的备份，本次**没有覆盖**它们，新备份加 `_d11` 后缀区分。`.bak_*` 已被 `.gitignore:154` 忽略，不入库。

---

## 二、包内被外部 import 的模块盘点（动手前 grep 结论）

**只删 `filters.py` 的重复实现，包本身保留**（老大硬风险点 1）。

| 包内模块 | 外部 import 点 | 本次 |
|---|---|---|
| `integrated_picker.helpers` | **`tdx_core.py:80` `from integrated_picker.helpers import get_industry_heat_bonus`** ← 这条是命脉 | **未动** |
| `integrated_picker.pipeline` | `tests/test_pipeline_equivalence.py:19,36,52,59,66,73,80` | 仅改 1 行导入 + 1 处调用点取值时机 |
| `integrated_picker.config` | `tests/test_pipeline_equivalence.py:91,96` | 未动 |
| `integrated_picker.gap_filter` | `tests/test_gap_filter.py:19,26,32,38` | 未动 |
| `integrated_picker.financial_filter` | `tests/test_pipeline_equivalence.py:131` | 未动 |
| `integrated_picker.pattern_filter` | `tests/test_pattern_filter.py:19,24,35`、`test_pipeline_equivalence.py:132` | 未动 |
| `integrated_picker.sequence_risk` | `tests/test_pipeline_equivalence.py:133` | 未动 |
| `integrated_picker.filters` | 仅包内 `pipeline.py` + 本包 `__init__.py`（**外部无直接 import，tests 目录无**） | 删重复实现 |
| `integrated_picker.output` | 仅本包 `__init__.py` | 未动 |

---

## 三、所有 `apply_tradability_filter` 调用点的解包方式核对（硬风险点 2）

| 调用点 | 解包 | 是否受本次影响 |
|---|---|---|
| `integrated_picker.py:570`（根模块内部） | `liq_ok, liq_reason = ...` 2 元组 | 否 |
| `integrated_picker/pipeline.py:225`（包版流水线） | `liq_ok, liq_reason = ...` 2 元组 | 否（只改取值时机，解包不变） |
| `tests/test_d8_d9_tradability_filters.py:160,163,166` | `ok, reason = ...` 2 元组 | 否 |
| `_diag_integrated_picker_shadow_20261019.py:78,79,92,93` | `ok_pkg, r_pkg = ...` 2 元组 | 否 |

⇒ **全仓 `apply_tradability_filter` 一律 2 元组，无长度分叉风险。**

> 关于「包版 11 元组 vs 根模块 20 元组」：那是 **`run_integrated_picker`** 的差异，不是 `apply_tradability_filter`。
> AST 实测：两边 `run_integrated_picker` 顶层**都返回 3 元组**，差别在第一元素（结果行）的字段数（根模块 `final_ranking` 行 20 字段 / 包版 `top50` 行 11 字段，沿用既有盘点结论，本次未重新数）。
> **本次刻意没有把 `run_integrated_picker` 也 re-export 到根模块** —— 那会让所有从 `integrated_picker` 取它的调用方（含 `tests/test_pipeline_equivalence.py:24`）立刻从 11 字段变成 20 字段，属于契约变更，要走 solution-architect 变更流程。见「六、遗留问题 #2」。

---

## 四、先红后绿证据（真实跑出来的输出）

### 4.1 改前 RED

```
$ PYTHONPATH= ./.venv/Scripts/python.exe -W always -c "import integrated_picker; print(...__module__)"
ip.__file__                                 = D:\open code\zhuanqian\integrated_picker\__init__.py
apply_tradability_filter.__module__         = integrated_picker.filters      ← 命中包版
srcfile                                     = D:\open code\zhuanqian\integrated_picker\filters.py
--- warnings captured: 1
  WARN: [fail-loud] integrated_picker ATR 判据分叉: 包版(本文件, import 时生效)=['atr_vandatr_v>0.08']
        vs 根目录 integrated_picker.py=['atr_vandcur_price>0and(atr_v/cur_price)>0.08']。…
```

`_diag_integrated_picker_shadow_20261019.py` 改前实测（行为级分叉）：

```
  ATR=0.5  (占价5%)     包版=剔:high_atr   根模块=留   ✗ 分叉
  收盘 10.0元: 误杀窗口 ATR∈(0.08, 0.80]  窗口内探针 包版=剔(误杀) / 根模块=留
```

### 4.2 改后 GREEN

```
$ PYTHONPATH= ./.venv/Scripts/python.exe -W always -c "import tdx_core; import integrated_picker; ..."
OK: import tdx_core
__module__         = integrated_picker_root                          ← 别名加载的根模块
srcfile            = D:\open code\zhuanqian\integrated_picker.py     ← 根目录生产权威入口
is root fn         = True                                            ← 与根模块函数同一对象
--- warnings: 0                                                      ← ATR 分叉告警自动消失
```

`_diag_...` 改后实测（同一份脚本、同一批探针）：

```
  integrated_picker.apply_tradability_filter 定义文件 = D:\open code\zhuanqian\integrated_picker.py
  __module__ = integrated_picker_root
  场景                    包版(活)        根模块        一致?
  ATR=0.05 (占价0.5%)     留             留            ✓
  ATR=0.5  (占价5%)       留             留            ✓   ← 原分叉点, 已消失
  ATR=2.0  (占价20%)      剔:high_atr    剔:high_atr    ✓
  收盘   5.0元 误杀窗口 ATR∈(0.08, 0.40]  窗口内探针 包版=留 / 根模块=留
  收盘  10.0元 误杀窗口 ATR∈(0.08, 0.80]  窗口内探针 包版=留 / 根模块=留
  收盘  50.0元 误杀窗口 ATR∈(0.08, 4.00]  窗口内探针 包版=留 / 根模块=留
  收盘 100.0元 误杀窗口 ATR∈(0.08, 8.00]  窗口内探针 包版=留 / 根模块=留
[结论] import 侧解析到: 根目录 integrated_picker.py (已与生产权威入口合并); 两版 ATR 判定全部一致
```

### 4.3 改前 / 改后 解析来源对照

| | 改前 | 改后 |
|---|---|---|
| `integrated_picker.apply_tradability_filter.__module__` | `integrated_picker.filters` | `integrated_picker_root` |
| `inspect.getsourcefile(...)` | `...\integrated_picker\filters.py` | `...\integrated_picker.py` |
| 与根模块函数同一对象 (`is`) | False | **True** |
| ATR 判据口径 | 裸 ATR 值 vs 8% | **ATR 占收盘价比 vs 8%** |
| import 时 fail-loud 告警 | 1 条（判据分叉） | **0 条** |

---

## 五、冒烟与 pytest 结果

### 5.1 冒烟（全绿）

| 命令 | 结果 |
|---|---|
| `python -c "import tdx_core"` | OK（`tdx_core OK`） |
| `python -c "import integrated_picker; ..."` | OK；`run_integrated_picker` 仍来自 `integrated_picker.pipeline`（未改契约），`apply_tradability_filter` 来自 `integrated_picker_root` |
| `python -c "from integrated_picker.filters import apply_tradability_filter"` / `from integrated_picker import apply_tradability_filter` | 两条路径取到**同一对象**（`same object: True`） |
| `python -c "import integrated_picker.pipeline"` | OK |
| `python -c "import daily_pick"` | `daily_pick import OK` |
| `python -m py_compile scripts/auto_live_pipeline.py` | `compile OK` |

### 5.2 定向 pytest

命令固定：`PYTHONPATH= ./.venv/Scripts/python.exe -m pytest -q --no-header -p no:cacheprovider`

| 批次 | 文件 | 结果 |
|---|---|---|
| 1 | `test_live_board_filter.py` `test_live_board_filter_integration.py` `test_daily_pick_selection.py` `test_d8_d9_tradability_filters.py` | **16 passed** |
| 2 | `test_pipeline_equivalence.py` `test_layers.py` `test_layers_contract.py` `test_pattern_filter.py` `test_gap_filter.py` | **60 passed, 1 failed** |
| 3 | `test_dl_integration.py` `test_factor_layer_sign.py` `test_scan_error_registry.py` `test_scan_range_zero.py` `test_aoci_maintenance.py` | **32 passed, 1 skipped, 1 failed** |
| 4 | `test_system.py` | **18 passed, 1 failed** |
| 5 | `test_plan_full_system.py` | `no tests ran`（该文件只有计划条目，无用例） |
| 复跑 | `test_d8_d9_tradability_filters.py` `test_pipeline_equivalence.py` `test_layers.py` `test_live_board_filter*.py` `test_daily_pick_selection.py` | **38 passed** |

### 5.3 三个失败项 —— 已逐个单独重跑，并**还原改动后复跑**确认为改前既有，与 D11 无因果关系

| 失败用例 | 单独重跑 | 还原 D11 改动后重跑 | 判定 |
|---|---|---|---|
| `test_layers_contract.py::TestL1HoldingsContract::test_risk_control_schema` — `risk_control 缺字段: {'tp_ladder'}` | 仍红 | **仍红** | 改前既有。该测试只 import `json/sys/pytest/pathlib/typing`，不碰 `integrated_picker`/`tdx_core`；断言对象是 `data/holdings.json`（`grep -c tp_ladder` = 0），`git diff -- data/holdings.json` 为空 |
| `test_factor_layer_sign.py::TestNWCaliberRegression::test_authority_source_factors_have_icir_nw` — 28/28 因子缺 `icir_nw`（`computed_at=2026-10-18 03:06:14`） | 仍红 | **仍红** | 改前既有。断言对象是 `data/factor_ic/factor_ic_latest.json`，对应任务清单 #1「ICIR 判定改 NW 等价门槛」尚未落地 |
| `test_system.py::TestDataFreshness::test_trade_log_freshness` — `trade_log过旧: 117.3小时前` | 仍红 | **仍红** | 改前既有。纯数据新鲜度断言，与代码无关 |

还原验证方法：把 3 个 `.bak_20261019_laoliu_d11` 拷回 + 移走 `_root_bridge.py`，重跑这 3 条 → **3 failed**（与改后一致），随后原样恢复并用 `is root fn = True` 复验恢复成功。

### 5.4 守卫活性自证（不是被我改成哑炮）

临时往 `integrated_picker/filters.py` 末尾追加一份 `def apply_tradability_filter(...)`，import 后：

```
guard warnings: 1
  [fail-loud] integrated_picker/filters.py 又落了一份 apply_tradability_filter: D11 已把唯一真源收敛到根目录 integrated_picker.py…
```

随后立即还原，干净 import OK。⇒ 守卫仍然 fail-loud，只是在「已收敛」状态下自然静默（不是手工删守卫）。

---

## 六、关键设计说明 / 遗留问题

### 为什么必须**延迟**加载根模块（这是本次最大的坑）

根目录 `integrated_picker.py` 与 `integrated_picker/` 包同名，FileFinder 里**包优先**，`import integrated_picker` 永远命中包，根模块只能按文件路径以别名加载。

但**不能在包 `__init__` / `filters` 被 import 时就加载根模块**：

```
import tdx_core                       # ① tdx_core 开始执行
  → tdx_core.py:80 from integrated_picker.helpers import ...   # ② 触发包 __init__
    → __init__:36 from integrated_picker.pipeline import ...    # ③ 触发 pipeline
      → pipeline:17 from integrated_picker.filters import ...apply_tradability_filter
        → 根模块 → `from tdx_core import STRATEGIES, ALLOWED_PREFIXES_*, load_industry_map, has_recent_gap`
          → 这些名字定义在 tdx_core.py:83/85/93，**都还没执行到** → ImportError
```

后果正是老大警告的「放倒所有 `import tdx_core` 的进程」（`scripts/auto_live_pipeline.py`、`daily_pick.py`、大部分 pytest）。
因此：根模块只在**真正取属性/调用时**才加载（此时 `tdx_core` 已完整，无循环）。`pipeline.py` 的调用点也相应改为循环前取一次。

### 遗留问题

1. **`layers/l1_tradability.py` 是第三份 `apply_tradability_filter`**（`tests/test_layers.py`、`tests/test_pipeline_equivalence.py:121` 用它的）。其 ATR 判据仍是**裸 ATR 值 vs 8%** —— 与根模块同款口径 bug 仍在那条路径上。本次**未动**（超出 D11 范围：包/模块双实现）。建议另开卡：要么删它走 re-export，要么把 ATR 改成占收盘价比。
2. **`run_integrated_picker` 仍是双实现**（包版简化版 11 字段 vs 根模块 20 字段）。本次只按老大指令合并 `apply_tradability_filter`；`__init__.py` 里那段警告已改写为准确描述（不再自称「生产权威入口 = 根目录」）。要彻底收敛需走 solution-architect 变更流程：先定调用方（`dojo_bridge`/`diagnose_screening`）的契约，再切。
3. `_diag_integrated_picker_shadow_20261019.py` 未入库（与仓库既有 `_diag_*` 脚本一致，均未跟踪）。如需长期保留先红后绿脚本，建议让它进 git。
4. 未跑全量 pytest（机器上有并发 pytest 进程，且有 3 个与本次无关的既有红）。只跑了定向集 + 上述复跑验证。
