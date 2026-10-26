# P1#5 验收断言清单（总管独立核 · 回测结束后逐项执行）
**任务**: t_c575000e 断层主升浪策略接入 · run 187 · 2026-10-10
**纪律**: SOUL#5 每个"正常✅"挂一手证据；SOUL#7 结论声明引擎 commit；不全信老三的表

## 验收 8 条断言（全过才放行）

| # | 断言 | 核验命令/位置 | 通过判据 |
|---|------|--------------|---------|
| 1 | 132日回测完整跑完 | `backtest_p1-5.log` 尾部 | `565/565` 扫描完成行 + 无 crash/exception 标记 |
| 2 | sanity gate 独立复跑 | 总管本人重跑 `python check_backtest_sanity.py`（不信老三的表） | PASS + 输出原文存档 |
| 3 | 门禁四项数值 | 回测结果 JSON（老三指定路径） | 胜率≥35% 且 5日超额≥0 且 rank_ic≥0.03 且 score_spread≥2.0pp，**四项实际值全部写出** |
| 4 | 132日 walk-forward 全量确认（铁律：20日改善必须132日全量） | 结果 JSON 的窗口字段 | 窗口=全量132日，非快速20日 |
| 5 | 证据链完整 | 结果 JSON + 报告 | 含退市股标记 / 前后指标对照 / 悲观场景损失 / 失效触发条件 |
| 6 | 老五 R0 签字 | `deliverables/` 或 kanban 老五任务 | 老五评审报告「✅ 放行」落盘，P0 静默吞异常零命中 |
| 7 | 红线四项 | `git diff` 核对 | `risk_rules.py` 零改动 / 无自动卖出代码 / 追高4%未动 / 数据未出本机 |
| 8 | 引擎 commit 声明 | 老三回执 metadata | 声明结论来自哪个 git commit 的引擎（SOUL#7 旧数字≠新验证） |

## 失败处置
- 任一项不过 → 打回老三（挂证据），不进老五评审
- 门禁单项失败但 IC 优秀 → 记「不采用也诚实记录」（AGENTS §4.1.9），结果归档 `docs/archive/`
- 回测超时/崩 → kanban_block(transient)，附最后扫描进度

## 进度锚点（2026-10-10 05:54 更新）
- 回测由**总管持久化拉起**（Hermes 托管 proc_080297da22d2，persist_on_release=true，worker 崩不再杀它）
- 引擎锚点：commit `e3ffa631`；扫描总数 **689**（历次 run 有 565→641→689 漂移——验收结论必须声明本 run 引擎 commit，SOUL#7）
- 回测命令：`python.exe backtest.py --strict-top1 > backtest_p1-5.log 2>&1`（Python311）
- 旧 188 残留 log 已归档 `backtest_p1-5.log.run188_truncated`（留证）
- 连环崩史：run 183(provider 401 已修) → 187(pid not alive 心跳断235s判死) → 根因=回测子进程随 worker 陪葬+无断点，**已根治**（脱离 worker 生命周期）

## 老三 worker 边界（comment #647 已发）
- 老三**不得自行重启回测**；只查进度/跑门禁/sanity/备老五材料
- 回测进程若死 → 报总管重起+查因，不自行拉起
