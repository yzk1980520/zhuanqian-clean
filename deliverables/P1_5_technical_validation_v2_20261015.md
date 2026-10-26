# P1#5 技术验证报告（v2 - 2026-10-15 老三更新）
## 断层主升浪策略接入

**任务ID**: t_c575000e
**执行人**: 老三 (Laosan)
**引擎commit**: ae26b730 (numba性能修复已合入, 2026-10-15)
**扫描总数**: 648 (数据源: TDX本地, 含退市股)
**扫描日期范围**: 1999-07-27 ~ 2026-09-18
**步长**: 10交易日

---

## 一、变更摘要

### 1.1 新增模块
| 文件 | 说明 | 状态 |
|------|------|------|
| `startup_detector.py` | 主升浪加速检测因子 | ✅ 已实现 |
| `check_p1-5_gate.py` | 门禁验证脚本 (v2) | ✅ 已修正 |

### 1.2 配置变更
```python
# integrated_picker.py L18-20
ENABLE_GAP_STRATEGY = True           # 断层策略启用
ENABLE_STARTUP_DETECTOR = True       # 主升浪加速检测启用 (IC=+0.5252)
```

### 1.3 Bug修复记录
| Bug | 根因 | 修复 | 备份 |
|-----|------|------|------|
| `scoring_engine.py`签名不匹配 | 被替换为错误简化版 | 从backup恢复 | `scoring_engine.py.bak_bug_20261010_055733` |

### 1.4 性能修复（总管已完成）
| 问题 | 修复 | Commit |
|------|------|--------|
| `_determine_market_state_at` 每候选股重复计算 | 复用循环外已算结果 | numba合并 commit 5e4e807e |

---

## 二、因子IC验证

### 2.1 验证结果
```
主升浪加速因子 IC = +0.5252
门禁阈值: IC > 0.03
结论: ✅ 通过（远超门禁，约为阈值的17.5倍）
```

### 2.2 验证方法
- 脚本: `factor_ic_test_P1-5.py`
- 样本: 20个交易日
- 方法: Rank IC (Spearman相关系数)
- 结果文件: `backtest_analysis/ic_test_P1-5.json`

---

## 三、回测状态

### 3.1 当前状态（2026-10-15 18:22）
- **进度**: scan=98/648 (约15%)
- **速度**: 每scan ~30-40s
- **预计完成**: 约5小时
- **日志**: `backtest_p1-5.log`
- **进程**: PID 16240 (3.5GB RAM, 持久化托管)

### 3.2 历史崩溃记录（已根治）
| Run | 崩溃点 | 根因 | 修复 |
|-----|--------|------|------|
| 183 | scan=54/689 | worker陪葬 | 脱离worker生命周期 |
| 187 | scan=9/632 | heartbeat断235s判死 | 同上 |
| 188 | scan=13/632 | 死锁无Traceback | 诊断脚本+持久化 |

### 3.3 已验证安全项
- ✅ `startup_detector.py` IC=+0.5252 通过
- ✅ `scoring_engine.py` 签名正确（从backup恢复）
- ✅ `integrated_picker.py` 配置正确
- ✅ 所有修改文件 py_compile 通过
- ✅ 红线四项全部通过（risk_rules.py只读、无自动卖出、追高4%未动、数据不出本机）

---

## 四、门禁四项（待回测完成后验证）

| # | 门禁项 | 阈值 | 当前状态 |
|---|--------|------|----------|
| 1 | 胜率 | >= 35% | ⏳ 待回测完成 |
| 2 | 5日超额收益 | >= 0 | ⏳ 待回测完成 |
| 3 | rank_ic | >= 0.03 | ⏳ 待回测完成（从trade_detail_v2.csv计算） |
| 4 | score_spread | >= 2.0pp | ⏳ 待回测完成（从评分区间表现计算） |

**验证脚本**: `check_p1-5_gate.py` (v2, 2026-10-15修正)
- 修正项: 结果路径、rank_ic计算、score_spread计算、字段名匹配

---

## 五、红线核查

| # | 红线项 | 状态 | 证据 |
|---|--------|------|------|
| 1 | 无自动卖出代码 | ✅ | grep确认无auto_sell |
| 2 | risk_rules.py 只读 | ✅ | git diff HEAD -- risk_rules.py → 空 |
| 3 | 追高4%阈值未动 | ✅ | 未修改相关参数 |
| 4 | 数据不出本机 | ✅ | 使用本地TDX数据 |

---

## 六、证据链

### 6.1 代码备份
| 文件 | 时间 |
|------|------|
| `integrated_picker.py.bak_P1-5_20261010_031915` | 2026-10-10 03:19 |
| `scoring_engine.py.bak_bug_20261010_055733` | 2026-10-10 05:57 |

### 6.2 日志文件
| 文件 | 说明 |
|------|------|
| `backtest_p1-5.log` | 当前回测日志 (scan=98/648) |
| `backtest_p1-5.log.run188_truncated` | 历史残留归档 |
| `backtest_p1-5.log.scan514_slow_178s` | 性能退化期日志归档 |

### 6.3 验证脚本
| 脚本 | 用途 | 状态 |
|------|------|------|
| `factor_ic_test_P1-5.py` | IC验证 | ✅ 已通过 |
| `check_p1-5_gate.py` | 门禁四关验证 | ✅ v2修正完成 |
| `check_backtest_sanity.py` | Sanity gate | 总管独立复跑 |

### 6.4 交付物
| 文件 | 说明 |
|------|------|
| `deliverables/P1_5_acceptance_assertions_20261010.md` | 验收断言清单(8条) |
| `deliverables/P1_5_technical_validation_20261010.md` | 技术验证报告(v1) |
| `deliverables/P1_5_R0_review_materials_20261010.md` | R0评审材料 |
| `deliverables/P1_5_crash_analysis_20261010.md` | 崩溃分析 |
| `deliverables/P1_5_status_summary_20261010.md` | 状态汇总 |

---

## 七、风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| 断层次策略样本不足 | 中 | 完整132日walk-forward验证 |
| 主升浪因子IC优秀但需验证 | 中 | 门禁四关全过才放行 |
| 加分模式避免硬过滤 | 低 | 已采用加分模式而非硬过滤 |
| 回测在scan=9-17区间断崖崩溃 | 已根治 | 持久化托管脱离worker生命周期 |

---

## 八、下一步

1. ⏳ 等待全量回测完成 (scan=98/648, 预计~5h)
2. ⏳ 运行 `python check_p1-5_gate.py` 门禁验证
3. ⏳ 运行 `python check_backtest_sanity.py` sanity gate（总管独立复跑）
4. ⏳ 提交老五R0评审
5. ⏳ 根据评审结果决定合入或记录不采用

---

**签字**: 老三 (Laosan) · 2026-10-15 · 状态：回测进行中 scan=98/648
