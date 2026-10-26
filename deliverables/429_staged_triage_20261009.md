# 429 域外 staged 分诊清单（任务2 · 待老大拍板）

**审计人**: 总管 · 2026-10-09
**现状**: `git diff --cached` 现 index 暂存 **257 件**（429 批次域外文件），与已合入的 R0/d083ff2、P1双源归一/71809ac 完全隔离。
**处置原则**: 暂不动 git。本清单给"建议"，老一拍板后分批改。实盘数据（data/holdings.json·trade_log.json·review_status.json）= 只读红线，**永不提交**。

---

## 五分类总表

| 类 | 件数 | 文件 | 建议处置 |
|----|------|------|----------|
| **A 实盘数据（只读红线）** | 2 | `data/holdings.json` `data/review_status.json` | ❌ 永不 commit（总管独占写口，走 atomic_json，不入 git）；`git reset` 出 index，加 `.gitignore` |
| **B 纯临时垃圾** | 47 | `.scratch/*`(24: calculate_full_ic.corrupt/chg20_*×3/data_quality/factor_ic_scan/fast_ic_calc/kimi42_*×4/p1_optimization_task×3/pca240×2/q1_registry/q4_debt1/register_pca/sync_r2/vol_dryup×3/vol_factor_same/wu_r0_verify) · `.coverage` · `pytest.ini` · `.hermes/cron.yaml` · `.hermes/cron/s3_daily.json` · `dashboards/*`(7: dashboard.html/dashboard_v2.py/dynamic_dashboard.py/generate_dashboard.py/index.html) · `tdx_indicators.py.fixed_20261008` | `git reset HEAD` 取消暂存；`.scratch/` 整目录 + `.coverage` 加 `.gitignore`；`dashboards/` 若仍用则转 git，否则一并 ignore |
| **C 真源/代码（属429批次，各归各任务单）** | ~12 | `config.json` `config/factor_thresholds.json` `factor_registry.py` `factors/README.md` `factors/factor_index.json` `pca_factor_synthesis.py` `scripts/auto_backtest_pipeline.py` `tests/test_pca_factor_synthesis.py` `tests/test_backtest_execution.py` `tests/test_risk_engine.py` `tests/test_s3_data_hygiene.py` `tests/test_s3_ladder_config.py` `tests/__init__.py` | 各自有任务单归属（K44/config漂移/PCA/双源归一等）；**不进 R0/双源归一提交**；按归属批次分别 commit 或 reset 待定 |
| **D 历史归档文档（AGENTS.md §9.3 → docs/archive/）** | ~200 | `docs/*.md/*.json/*.png/*.svg`(S3部署配置表/S3选股信号监控/实盘启动SOP/S3全流程复盘/御龙决作战手册更新_清理验证/御龙决执行日报×3/御龙决系统执行记录/股票信号发布记录/系统执行标准优化/共识修复单/S3执行注意事项/技术触发点与板块经验总述/数据源切换测试验证/盘后数据导入/回测执行策略/回测记录/pca_*图表/laowu_review_*×14/task-*×8/execution-summary/system-*-report/skills-*×10 等) · `mainline/docs/*`(IC快扫/御龙决发布报/飞书event-config/s3-sign_stoploss/task-t66b完成报/aoci-daily.json) · `skills/zhuanqian/s3-auto-pipeline/references/dashboard-review-checklist.md` | 按 §9.3 归档：历史报告/诊断 → `docs/archive/`；仍在用的活文档（如 御龙决作战手册、盘后数据导入、股票信号发布记录）保留 `docs/` 根；过期重复件（如 gateway-fix ×3 多版本、system-status-report ×多版本）归 archive 或删 |
| **E 悬空/需人工** | ~5 | `mainline/docs/aoci-daily/aoci_daily_20261007.json`(AOCI 日报, 属 aoci-auto-maintenance cron) · 若干 `docs/` 中带密钥痕迹文件（见下） | 逐件问归属；带密钥的一律**不提交** |

---

## ⚠️ 安全红线（必须先处理，早于任何 429 commit）

`docs/task-laosan-…` 批次里有 `ta[REDACTED_SK_KEY].json` / `ta[REDACTED_SK_KEY].md`（脱敏后的 skill key 痕迹文件名）。**429 里若有任何未脱敏密钥/凭据文件，整批 commit 前必须先 grep 扫一遍**：
```
git diff --cached | grep -niE "(api[_-]?key|secret|token|password|Bearer |sk-)[^ ]{8,}" 
```
扫到即该文件单独 reset 不提交，并补 `.gitignore`。

---

## 推荐处置顺序（老一拍板后执行）

1. **安全扫描**（上条 grep）→ 有密钥先摘除
2. **A 类实盘数据** `git reset HEAD data/holdings.json data/review_status.json` + 写 `.gitignore`（红线，最先做）
3. **B 类临时垃圾** `git reset HEAD .scratch/ .coverage pytest.ini .hermes/ dashboards/ tdx_indicators.py.fixed_20261008` + `.gitignore` 加 `.scratch/` `.coverage`
4. **C 类真源** 按各自任务单归属拆 commit（不混 429 大包）
5. **D 类归档** `git mv docs/<历史报告>* docs/archive/` 后 commit 知识库归档
6. **E 类** 逐件拍板

**绝不**：一把 `git commit` 把 257 件混进主线（09-25 双bug教训：大包混提交 = 验收断言写不出证据）。
