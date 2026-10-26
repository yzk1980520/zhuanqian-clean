# T1 因子池扩自由度 — 132d IC 证据包 (t_5457c400)

**日期**: 2026-10-26　**执行**: 老三 (opencode)　**状态**: ✅ 证据包完成 / ⚠️ AC2 未达标(如实) / ⚠️ AC3 回归非全绿(存量红, T1 零引入)
**引擎 commit 声明**: `pure_python_v10_exact_132d@b3cabc4a` (runner = T1 commit b3cabc4a, 父提交 f91fcc6d = 会签件基线; 权威卡既有 71 条目 ic 值在 b3cabc4a 下重跑 bit-exact 复现, 集群表 A1b PASS n_compared=74)

---

## 一、交付物清单 (全部本地, 数据不出本机)

| 文件 | 说明 |
|---|---|
| `scripts/factor_ic_132d_refresh.py` | runner 增 3 因子 + 截面 hook (仅改 RESID_MOM_20/RSRS_TREND 两列, 既有 71 因子零影响) @e1567cec+@b3cabc4a |
| `scripts/t1_build_industry_mapping.py` | SW31 行业映射 (akshare 公开成分 + mainline/sw_names.json), atomic_json 写 |
| `data/industry_mapping.json` | 31 行业 / **5220 只可映射股**; 未映射(含退市)入 UNMAPPED 组组内去均值 |
| `scripts/t1_build_rsrs_trend.py` | 上证 RSRS 10日斜率 (本地 TDX sh000001), 序列 `data/factor_ic/rsrs_trend_132d.json` |
| `scripts/t1_six_quantile_qmeans.py` | 6分位 q_means 取证 (复用于 runner 同源 universe/compute) |
| `data/factor_ic/factor_ic_q6_t1_20261026.json` | 3 因子 q5+q6 q_means (n_pairs=226400, 132d) |
| `scripts/factor_ic_132d_refresh.py --max-stocks 2000` 全量 run | `data/factor_ic/factor_ic_132d_refresh_20261026_040710.json` (74 因子, asof 2026-10-23) |
| `data/factor_ic/factor_ic_latest.json` | 权威卡 71→74 追加 (既有 71 条目逐条 JSON 等价, 未改写), total_samples 同步 71→74 |
| `data/factor_ic/factor_registry.json` | 因子登记 4→7 (atomic_json R3 合规 + 写后读回断言) |
| `data/factor_ic/factor_cluster_table_20261026.json` | 集群表重算 (74 因子 ic-series, A1a/A1b PASS) |
| `data/factor_ic/factor_gate.json` | gate_check 再生: 17 valid 不变, 3 新 dead 因子入 frozen_list |

## 二、逐因子 132d 结果 (asof 2026-10-23, universe=2000, 含退市口径)

门禁阈值真源 `core/scoring/factor_gate_v2.GATE_CONFIG`: ic≥0.03, ir≥0.3。

| 因子 | ic | icir | icir_nw | t_nw | q_means (6分位) | q6 单调 | 门禁判定 |
|---|---|---|---|---|---|---|---|
| **RSRS_TREND** | None (退化) | - | - | - | [-0.1452,-0.3266,-0.4733,-0.4065,-0.3135,-0.2949] | False (设计使然) | **dead** |
| **RESID_MOM_20** | -0.0295 | 0.2055 | -0.1081 | -1.2418 | [-0.2612,-0.208,-0.2235,-0.2542,-0.3018,-0.7118] | True (负向) | **dead** (\|ic\|=0.0295 < 0.03, 临界未过) |
| **REV_5D** | -0.0097 | 0.0576 | -0.0365 | -0.4192 | [-0.3811,-0.1217,-0.1888,-0.2197,-0.4009,-0.6478] | True (负向) | **dead** (\|ic\|=0.0097 < 0.03) |

- **RSRS_TREND**: 全市场常数信号 (截面零方差), Spearman IC 无定义 → ic=None 如实留痕; 其作为**择时**输入的证据在 `rsrs_trend_132d.json` 序列 (132 日斜率), 横截面管线不判其入池, 后续作择时 overlay 由三方裁定。
- **RESID_MOM_20**: 行业中性残差 = 20日收益 − 行业组均值 (OLS 哑变量+截距 等价形式); 未映射股入 UNMAPPED 组。**临界未过门禁** (0.0295 vs 0.03, ICIR_nw 0.108 vs 0.3), 方向负 (高分位残差动量 → 低前瞻收益), 与 A 股短期反转外部研究一致。
- **REV_5D = -(chg5)**: 对应存量 chg5 的精确镜像, IC 互为相反数 (chg5 卡 ic=+0.0096 → REV_5D −0.0097, 镜像差 0.0001 = 排名平局浮点误差, 数值互验闭合); 对应 factor_weights.json 既有 0.0 权重键 `chg5_rev` (registry 已挂 weight_key_mapping, 转正可复用该键, 本卡未改权重)。

## 三、A2 有效自由度 (AC2)

| | 20261025 集群表 | 20261026 集群表 (含 3 新因子) |
|---|---|---|
| A2_effective_dof | 2 | **2 (未达标, 目标 ≥4)** |
| 族1 | AMT_5D/10D/15D/20D/30D/AMT_TOTAL5 (ρ=1.0 重复对) | 同 |
| 族2 | AMT_PER_C + LIQ_* + VOL_* + TURN5 + V_MEAN20 (11 因子) | 同 |

**未达标原因 (机制性, 非口径漂移)**: A2 只对 **strict-valid 池 (17)** 做族聚类 (union-find, 族阈值 0.9 不变)。3 新因子全部 dead, 不进 valid 池 → 贡献 0 自由度。
**反事实证据 (74 因子 ic-series 逐对 pearson)**: 3 新因子与 17 valid 全部 |ρ|<0.7 (互验: RESID_MOM_20↔REV_5D ρ=−0.43; RSRS_TREND 零方差, ρ 无定义) → 若三者过门禁将各自成族, dof 可至 2+3=**5**。即病根确认: 自由度瓶颈在**门禁通过率** (valid 池 17/74), 不在族冗余。

## 四、AC 合规清单

| AC | 要求 | 判定 | 证据 |
|---|---|---|---|
| AC1 | 新因子≥3, 每个产出 132d 精确卡 (ic/icir/icir_nw/t_nw/q_means), source 含 engine commit | **PASS** (RSRS 卡 ic=None 为设计退化, 序列证据另档) | 权威卡 74 条目, source `@b3cabc4a [t_5457c400 T1 追加]`; q6 证据 `q6_evidence` 字段 + q6 专件 |
| AC2 | 集群表重算 A2: 2→≥4, 不达标如实报 | **未达标 (2→2)** | 上文 §三; 阈值 0.9 未动; 反事实 dof 上限 5 已取证 |
| AC3 | 双源原子登记 + 回归全绿 0 失败; factor_weights diff=0 | **登记 PASS / 回归 非全绿 (存量红, T1 引入=0) / 权重 diff=0 PASS** | 双源: 权威卡追加 (逐条等价断言) + registry 4→7 + frozen_list; 回归: 全量 1769 passed, 17 failed+3 errors 全部为基线存量 (f91fcc6d 基线 45F+3E ⊇ 现 17F+3E, T1 新增失败=0, 见 §五); `git diff --stat factor_weights.json` = 空 |
| AC4 | 报告入 docs/ + R0 老五评审立场回填会签件签字格 | **报告 PASS / 回填 PENDING** | 本报告 docs/ 副本; R0 老五 (atomcode) 回填为其评审流程产物, 证据包已备齐 |

## 五、回归测试 (T1 零引入证明)

命令: `C:/Users/WIN10/.quant-stock-picker/.venv/Scripts/python.exe -m pytest tests/ -m "not slow" --timeout=120`

| 运行 | 环境 | 结果 |
|---|---|---|
| 基线 | f91fcc6d + 预 T1 数据 | **45 failed, 1737 passed, 3 errors** (48 个失败测试) |
| T1 最终 | b3cabc4a + T1 数据 | **17 failed, 1769 passed, 3 errors** (19 个失败测试) |

失败集差 (T1 − 基线) = **∅** (19 ⊆ 48): 现存 17F+3E 全部在基线已红, 主因 = 环境/数据面存量 (feishu cron 配置、hermes config、L1 财务缓存缺失、model config、trade_log 新鲜度、weekly fake-positive、quick_ic_sample.json 缺失、TestFactorWeights 3 errors、test_factor_ic 存量红)。T1 变更 (runner +3 因子 hook + 双源登记 + 集群表) **零引入失败**, 且 K/L 组 (门禁/双源一致性) 全绿。
日志: `.scratch/t1_regression_final.log` / 基线 `.scratch/t1_base_regression_full.log` (scratch 目录内)。

## 六、风险与未验证项 (如实)

1. **RSRS_TREND 择时效用未测**: 本卡仅横截面管线, 斜率序列对指数收益的择时 IC 未计算 (需 T3/后续单); 当前证据仅 132 日序列本身。
2. **行业映射时变缺口**: industry_mapping.json 为 akshare 拉取时点成分 (5220 只/31 行业), 132d 窗口内的退市股/换入换出映射为 UNMAPPED 组处理, 行业中性度含时变偏差; 若 RESID_MOM_20 临界转正, 需补 point-in-time 映射复核。
3. **回归非全绿**: 存量红 19 项 (基线 48 项) 未在本卡范围内修复 (非 T1 引入), 建议另开数据面/环境任务单清账。
4. **REVIEW/R0**: 老五 (atomcode) 评审立场未回填会签件签字格 (AC4 后半), 证据包已备。

## 七、结论

- 3 因子族全部入库 + 132d 精确证据 (权威卡/registry/集群表/gate 双源一致, 门禁通过)。
- **自由度未扩开 (A2 仍=2)**: 3 新因子全部 dead, 扩自由度需先过门禁 —— RESID_MOM_20 最接近 (ic −0.0295 临界 0.03), 建议三方裁定是否给行业中性残差族单独放行口径或补 point-in-time 映射复算; RSRS 转择时通道; REV_5D 与存量 chg5 镜像重复, 价值有限。
- 下一步球在三方: 门禁裁定 + 老五 R0 回填 + 存量红清账排期。
