# P1#5 断层主升浪因子族 — 132日全量门禁报告 (NOT-PASS)

**任务**: t_c575000e | **执行**: 老三 | **日期**: 2026-10-23
**引擎锚点(SOUL#7)**: `pure_python_v10_exact_132d@0aec0775` (github-main, 含本次 7421f09c+35985d0d 合入)

---

## 结论 (先行)

🔴 **门禁四项 NOT-PASS → 按契约降级路径: 不强行合入, 如实记录。**

| 因子 | G1 IC≥0.03 | G2 IR_nw≥0.3 | G3 单调 | G4 全量132日 | 判定 |
|---|---|---|---|---|---|
| STARTUP_ACCEL | ✅ 0.0428 | ❌ 0.0846 | ✅ (1逆序) | ✅ 132/132 | **FAIL (G2)** |
| GAP_UP_CNT20 | ❌ -0.0249 | ❌ 0.0648 | ❌ (2逆序) | ✅ 132/132 | **FAIL (全)** |
| GAP_UP_X_ACCEL | ❌ -0.0090 | ❌ 0.0552 | ❌ (2逆序) | ✅ 132/132 | **FAIL (全)** |

主因: **IR (NW口径) 全线不及格** — 3因子 IC 序列不稳定 (NW-ICIR 0.06~0.09 ≪ 0.3)。
同窗对照: 31个因子 132日全量 valid=0 — 与老六 W14 (10-18) 裁定一致 (NW 口径下 0.3 门槛极严,
现存唯一在用的 AMIHUD 亦站不住), 属**系统级现象**而非 P1#5 单因子缺陷。

## 数据窗口与口径 (证据链要素)

- 窗口: 132 截面日, **2026-03-27 ~ 2026-10-13** (IC截面日), 数据末日 2026-10-20, forward=5日, align=0
- 样本: 500 只 (管线默认口径, 与权威源 factor_ic_latest.json 默认 run 同参) × 132 日 = 有效截面 132/132
- **含退市股**: ✅ 池=data/history_daily (9442文件, 含TDX已删代码); delisted_audit verdict=delisted_in_pool=true, exclusive=157, survivorship_gap=0 (10-23 04:37快照)
- 权威源: factor_ic_132d_refresh 管线 (老六 W1 机制, W14 NW口径), dry-run 未触碰权威源
- 单调性方法: 逐截面5分位(按当日秩位置分桶)池化平均前瞻收益, 方向不限, 相邻逆序≤1 判单调

## 前后对照 (10-21权威源 vs 本次, 窗口平移~1周, 仅参考)

| 重叠因子 | IC 10-21 | IC 10-23 | 备注 |
|---|---|---|---|
| value_proxy | +0.0851 | -0.0195 | 窗口漂移 |
| chg10 | +0.0644 | +0.0443 | 方向稳定 |
| PRICE_VOL_RANK | -0.0382 | +0.0517 | 方向翻转 |
| P1#5族 | (未登记) | 见上表 | 本次新登记 |

## 旧证据重评 (SOUL#5: 旧数字不得作为新验证)

- **IC=+0.5252 (10-10)**: 单截面日单样本 (ic_test_P1-5.json scan count=1), 该文件自身门禁即
  🔴FAIL (ICIR=N/A, 方向=unknown)。本次 132日全量 IC=+0.0428 → **0.5252 判为窗口过拟合假象, 废止引用**。
- 20日快跑 (本次 v2, 标"未全量确认"): STARTUP_ACCEL IC=+0.0557/IR_nw=0.627 "valid" — 与 132日
  (0.0428/0.0846) 差异巨大 → 正是铁律"20日改善须132日全量确认"要拦的场景。

## 悲观损失 (未合入前)

零。P1#5 因子族**未写入**权威源/STRATEGIES权重/实盘评分 — 本次仅:
① 管线登记 (FACTOR_FUNCTIONS +3, 纯只读取证路径) ② 门禁脚本 (新文件) ③ 报告。
实盘链路 0 改动。

## 风险标记 (R0 需裁定)

⚠️ **10-10 已在树内启用**: `core/pipeline/integrated_picker.py` `ENABLE_GAP_STRATEGY=True` +
`ENABLE_STARTUP_DETECTOR=True` (Layer 5c +5分主升浪加分, 当时依据=单样本IC 0.5252 "门禁通过")。
现 132日全量门禁未过 (G2 全线 0.06~0.09) → 该加分项当前依据不足, **属死因子带加分状态**。
R0 选项: (A) 摘除加分项 (回滚10-10开关) (B) 保留观察+重标定 (C) 维持现状记录风险。
(老三不擅自动实盘开关 — 红线: 只读 risk_rules, 加分链开关需 R0 拍板。)

## 失效条件 (契约 degradation_path)

任一 P1#5 因子滚动 20 日 |IC|<0.03 → 判失效退回因子池; 本次 132日 G2 未过即已触发"不强行合入"。
因子族保留在管线 FACTOR_FUNCTIONS (登记≠合入), 下季度 132d 刷新重测; 若 STARTUP_ACCEL
连续两季 IR_nw≥0.3 再走合入评审。

## 轮动回测 on/off 对照说明 (未跑, 已代码核验)

契约字面 "python backtest_rotation.py 全量" 与四项门禁的映射: 门禁四项为**因子级**统计
(IC/IR/单调/全量), 由 132d 因子IC管线产出 (权威口径, 老六W1); 轮动回测引擎
(backtest_rotation.py) 评分走 tdx_core.score_stock, **不引用** integrated_picker 的
P1#5 加分链 (grep 0处引用) → 轮动 on/off 恒零差, 无判定力。已如实标注, 未跑多时轮动回测
(避免覆盖 P2 止损扫描证据文件; 该文件 sanity gate 13/13 PASS 于 10-23 06:4x 复验通过)。

## 回滚点

```
git revert 35985d0d   # 单调性逐截面法 (纯方法变更)
git revert 7421f09c   # 因子族登记 + 门禁脚本 (纯新增)
```
两 commit 均 additive (不动既有 28 因子/权威源/实盘链路), 回滚零实盘影响。

## 交付物清单

- `data/factor_ic/factor_ic_132d_refresh_20261023_063700.json` — 132d dry-run (31因子 IC/IR_nw/status)
- `data/factor_ic/p1_5_mono_132d_20261023.json` — 5分位单调性 (P1#5族)
- `data/factor_ic/p1_5_ic_series_132d_20261023.json` — 逐日IC序列 (walk-forward 留证)
- `deliverables/P1_5_gate_evidence_20261023.json` — 门禁证据链 (check_p1_5_gate.py 产出, exit=4)
- 20日快跑: `factor_ic_132d_refresh_20261023_063537.json` + `p1_5_mono_quick20d_v2_20261023.json` (标"未全量确认")
