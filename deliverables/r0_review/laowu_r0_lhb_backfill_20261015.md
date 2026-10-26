# 🐎 老五（atomcode）· R0 隔离评审会签 — LHB 历史数据回填结果

**日期**: 2026-10-15
**评审对象**: LHB 龙虎榜历史数据回填结果（`data/akshare/get_lhb_detail_*.json`，4→113 文件）+ 新数据下 A/B 归因
**评审级别**: R0（引擎/数据层变更）— 回填结果隔离评审
**评审方式**: 只读独立核验（bash/python 探针 + 逐行读码），**不采信**验收文档/回填报告自述结论，全部独立复算
**授权**: 老大 b 拍板 — 老五会签在"回填结果 R0 环节"完成
**留痕**: 本报告 + `dashboards/review-laowu.md` 追加

---

## 一、一句话会签结论

**数据层回填 ✅ 通过**（文件集/完整性/point-in-time 口径/覆盖门禁全部独立核验通过）。
**LHB 变量隔离结论：LHB 在活跃回测与生产路径中为 INERT**（活跃策略"基本面+"无 lhb 权重），因此验收文档 A/B 的 8/12 config 差异 **100% 归因于 R0 引擎变更（a9b0497→f9ca189d）**，与 LHB 无关 —— 验收文档"并非 inert / LHB 有效"为**误归因**，须更正。
**LHB 因子激活仍 HOLD**（未满足激活前置，registry `is_valid=false, gate_status=pending`）。

---

## 二、数据层回填核验（全部独立复算）

| # | 核验项 | 独立证据 | 判定 |
|---|--------|----------|------|
| D1 | 文件集与报告一致 | 实际 `get_lhb_detail_*.json`=**113** = ok(109)+skip(4)；区间 **20260506→20261014**；文件集 == 报告 ok\|skip（无多无缺）；err(9) 无残留文件 | ✅ |
| D2 | 无静默缺口 | Mon-Fri[0501,1015]=**120**，unclassified=**[]**（每交易日均被 ok/err/skip 归类）。skip 的 4 含 2 周末(1003/1004)→故 ok+err+skip=122>120，逻辑自洽 | ✅ |
| D3 | point-in-time 口径 | 回填=**单日口径**：0506 文件 `上榜日=[1778025600000]`=2026-05-06 == 文件名日（pull==上榜日）。原始 4 文件=**周快照**：0925 文件 `上榜日=[0918,0921,0922,0923,0924]` 全部 < pull 日 0925 → 在 `read_lhb_signal`(要求 pull≤scan 且 上榜日==scan) 下**永不命中**（数据层死）。口径区分成立 | ✅ |
| D4 | 数据完整性 | 抽样 5 文件(0506/0601/0918/0925/1014)坏行=**0**；schema 一致（14 字段，含 净买额占总成交比/上榜日/代码）；净买比为**百分数**（实测 -70.8~+57.7，/100 得比率，±5% 阈值自洽）；同股多行=多上榜原因（正常，非脏数据） | ✅ |
| D5 | 覆盖门禁 | 窗口内[0506,0918] Mon-Fri=98，ok=**97**，唯一缺口 **20260619**（普通周五，接口失效，非节假日）；**97≥60 达成**。err 其余=五一/国庆假期 + 今日(04:07 早于当日 LHB 公布) | ✅ |

> **D5 备注**：验收文档"覆盖率 97/118≈82%"的分母(118)与老五独立复算 97/98 不符，分母口径未明；但 **≥60 门禁在两种口径下均达成**，不影响放行。

---

## 三、R0 隔离分析（核心发现）— LHB 在活跃路径 INERT，A/B 差异属 R0 引擎

**隔离方法**：固定引擎(f9ca189d)+固定数据(113文件)，单独隔离 LHB 权重变量。逐行读码坐实 LHB 是否进入活跃评分路径：

| 环节 | 证据（file:line） | 结论 |
|------|------|------|
| 活跃策略 | `config.json` L2 `strategy="基本面+"` | 活跃策略=基本面+ |
| 策略加载 | `tdx_strategies.load_strategy()` L619-620：name=None → `sn=cfg["strategy"]`="基本面+"；返回 `STRATEGIES["基本面+"]+config.factor_weights` | STRATEGY=基本面+ |
| 基本面+ 权重 | `tdx_strategies.py` L581-604（ma/macd/rsi/kdj/vol/chg_rev/volatility20/fund_flow/penalty + 基本面门槛），**无 lhb_signal**；`config.factor_weights` L61-66={UPPER_SHADOW,LOWER_SHADOW,chg5,chg10} **无 lhb** | 活跃策略无 lhb 权重 |
| 评分函数 | `tdx_core.py` grep `lhb`=**零匹配**（score_stock 无硬编码 lhb，仅按 strategy 键加权） | 无权重键→不计分 |
| 回测 12 config | `backtest_rotation.py` L1139-1174 `RotationConfig` 仅设轮动参数(stop/trailing/chase/knife)，**不含因子权重**；`score_stock(strategy=STRATEGY)` 走基本面+ | 12 config 共享无-lhb 权重 |
| 因子注入 | `backtest_fast_inds.py` L587 计算 `lhb_signal` 进 inds，但**未被任何活跃权重表加权** | 算了但不计 |
| 唯一含 lhb 者 | `tdx_strategies.py:46` 仅"综合"策略 `lhb_signal:8`（**非活跃**） | 综合=潜在激活点 |

**∴ 隔离结论：LHB 在活跃回测/生产路径 INERT（零贡献）。** 由此推出验收文档 A/B 的归因错误：

| | 验收文档声明 | 老五隔离复算 |
|---|---|---|
| A | a9b0497 + 4文件 "LHB-off" | 基本面+ 无 lhb → 实为 **LHB-off（inert）** |
| B | f9ca189d + 113文件 "LHB-on" | 基本面+ 无 lhb → 仍为 **LHB-off（inert）** |
| 差异归因 | "8/12 config 差异 = LHB 有实际影响（并非 inert）" | **100% 来自引擎 a9b0497→f9ca189d（R0：ae26b730 P1恐慌止损+P0-1追高+tp_ladder迭代+停牌降级；+21b44a62 factor_cache断言 +5e4e807e numba）。4→113 数据变更同样 score-moot（lhb 未加权）** |

**即：验收文档把 R0 引擎变更的差异误标为"LHB-on"、误归因为 LHB 效应。LHB 的真实效应在当前证据下未被测到（=0 贡献），而非"有效"。**

---

## 四、风险：因子已活但活跃策略仍死 = 脆弱平衡（须防策略切换暗触发）

- **当前安全**：活跃路径(基本面+)无 lhb 权重 → 回填数据虽"活"，但**不计分**，生产/回测评分不变（双重保险：活跃策略无 lhb 键 + 生产 `auto_live_pipeline` 另不传 code）。
- **陷阱**：`综合`策略 `lhb_signal:8`（`tdx_strategies.py:46`），其依据 IC=0.0991 是 **09-04 陈旧测量**（SOUL#7 禁作现值）。一旦 `config.strategy` 切"综合"、或跑旧 `backtest.py`（默认"综合"），LHB **立即在 109 天生效 ±8 分，且未经验证/未经门禁** → 未受控行为变化。
- **建议**：给"综合"的 lhb 权重加门禁闸（未过 IC 重测 / 未获老大权重拍板 → 强制 0），或在 `score_stock` 侧对 registry `is_valid=false` 的因子强制 0 权重，避免策略切换暗触发未验证因子。

---

## 五、代码质量遗留（HEAD 现态，供落地，非打回项）

| 级别 | 项 | 位置 | 处置建议 |
|------|----|------|----------|
| P2 | `OverflowError` 未捕获：`_lhb_parse_file` 只 catch `(TypeError,ValueError)`，超大 `上榜日`(15-16位) `fromtimestamp` 抛 OverflowError 会**崩整个回测** | `tdx_indicators.py` L192/L198 | except 元组补 `OverflowError` |
| P2 | listdir 热路径：`read_lhb_signal` 每次调用 `os.listdir+sorted`，回测 ~30 万+ 次冗余扫描（当前活跃路径 lhb 未加权故未触发，激活后即为真成本） | `tdx_indicators.py` L222 | 模块级缓存有序文件列表 + 目录 mtime 失效 |

---

## 六、LHB 因子激活剩余前置（HOLD — 非老五执行，正确保留）

| # | 前置 | 责任 | 状态 |
|---|------|------|------|
| 1 | 数据回填 | 老三 | ✅ 完成（本次会签通过） |
| 2 | ≥60 交易日覆盖 | — | ✅ 达成（97） |
| 3 | **干净隔离回测**：A''(f9ca189d+113文件+无lhb权重) vs B(f9ca189d+113文件+有lhb权重)，才能测 LHB 真实贡献 | **opencode**（复杂回测老五禁跑；且写 data/ 越权） | ⏳ 未做 — **当前验收文档 A/B 非干净隔离，不可用于 LHB 效应结论** |
| 4 | 权重登记 | 老三 / FactorRegistry | ⏳ `is_valid=false, gate_status=pending` |
| 5 | IC/IR/单调性新数据重测 | 老三 / 老五 | ⏳ 旧 IC=0.0991 禁作现值 |
| 6 | point-in-time 决策时点确认（S 日收盘后决定 S+1 → PIT 成立；S 日开盘决定 S → 前视） | 总管 / 老三 | ⏳ 未定 |
| 7 | 窗口延伸 09-18→最新数据日 | 老五 R0 | ⏳ 待签 |
| 8 | cron 拉取器恢复 | 总管 | ⏳ |

---

## 七、未验证项（诚实标注，禁打勾放行）

- **LHB 真实效应**：未验证（需前置#3 干净隔离回测；老五只读 + 禁写 data/ 无法自跑）。本报告仅证明 LHB 在**当前活跃路径 inert**，不等于证明其"有效"或"无效"。
- **20260619 是否为真实数据缺失**（当日确有龙虎榜但接口未抓到）：未验证（需重拉该日）；影响 = 窗口内 1/97，不改变 ≥60 门禁。

---

## 八、verdict

**✅ 放行（数据层回填会签通过）—— 附 3 项要求**

- **要求 1（P1，更正）**：验收文档 `docs/lhb-backfill-acceptance-20261015.md` §三 的 A/B 归因更正 —— 8/12 config 差异属 **R0 引擎变更（a9b0497→f9ca189d）**，非 LHB；"并非 inert / LHB 有效"表述撤回（LHB 在活跃路径 inert，真实效应未测）。
- **要求 2（P1，门禁闸）**：`综合`策略 `lhb_signal:8`（陈旧 IC=0.0991）须加"未过 IC 重测 / 未获权重拍板 → 强制 0"门禁闸，防策略切换暗触发未验证因子。
- **要求 3（P2，前置#3 落地）**：LHB 激活前必须补**干净隔离回测**（固定 f9ca189d + 113文件，仅切 lhb 权重），路由 opencode；在此之前 LHB 维持 `is_valid=false`、不激活。

**打回项：无**（回填数据本身完整无误，非打回）。

---
*留痕人：老五（atomcode）| 2026-10-15 | 纯评审，按规则智能化自行出结论，未改任何源码 / 未写 data/。*
