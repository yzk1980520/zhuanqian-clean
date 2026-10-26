# 老五 R0 评审报告 — LHB复活 + P0同类路径修复
**生成**: 2026-10-15 04:22（会话 76aa8e66 round 42，atomcode 52 分钟）
**落盘说明**: 老五会话正常结束但报告未落盘（bridge 输出层缺陷所致，见下）；总管从会话转录
`.atomcode/sessions/981daa2d8916f9f1/76aa8e66-70c6-47de-bc00-eb8c53f062a3.events` round 42
assistant_message 完整转录，逐字核对无删改。
**磁盘交叉核验（总管 04:4x）**: data/akshare/ LHB 文件 113 个（20260506→20261014）= 报告数字 ✓；
tests/test_lhb_revival.py 已被回填 worker 并发更新字面量（113/109/≥60 达成）✓。

---


# R0 评审结论 — LHB复活 + P0同类路径修复（ee923718 + fd432bf）

## 一句话结论
**两个 commit 本身评审通过**（代码正确、测试在 commit 时刻成立）。但**今日完成的数据回填已推翻 commit 的"零贡献/门禁 HOLDS"前提**——因子现已 active，需补激活前置才能正式启用。已挂看板留痕（`dashboards/review-laowu.md` 第六～十一节）。

## 两个 commit 本身 — ✅ 通过
| commit | 内容 | 评审 |
|---|---|---|
| **ee923718** | P0 路径修复 4 处 | 正确。4 文件均在仓库根，单层 dirname 对；py_compile PASS |
| **fd432bfb** | LHB 复活（单一读点+接线） | 正确。①单位百分数 `/100.0` 对（真实数据 1.6847=1.68%）②ms-epoch 换算对 ③point-in-time 不前视 ④code 键控 ⑤生产/回测共用单一读点防双源漂移 ⑥坏行打警告不静默吞。py_compile PASS，LHB 测试 5/6 过 |

我逐项独立复算了：单位、日期换算（1790035200000→2026-09-22）、point-in-time、调用链（既有调用方 `code=None`→0.0 零破坏）。

## 🔴 最关键发现：回填推翻"零贡献"前提
| 指标 | commit 时 | 现在 |
|---|---|---|
| LHB 文件 | 4 | **113**（0506→1014） |
| point-in-time 有效日 | 0 | **109**（132 日窗口内 97） |
| ≥60 交易日门禁 | ❌ | ✅ **达成** |
| 因子值 | 全 0.0（数据层死） | **非零 ±1** |

回填文件是**当日口径 `pull==上榜日`**（原 4 文件是 `pull>上榜日`），这正是因子从"死"转"活"的机制。工作区 `test_lhb_revival.py`（未提交）已被**另一 agent 并发更新**为"113/109/≥60 达成"——此状态变化非意外，是正在进行中的回填处理。

## 当前风险：因子已活但评分层仍"死" = 脆弱平衡
- **无即时评分影响**：活跃策略（config.json=`基本面+`，回测+生产共用）**无 lhb 权重** → 因子算出但不加权。生产 `auto_live_pipeline` 另不传 code，双重保险。
- **但脆弱**：`综合` 策略有 `lhb_signal: 8`，旧 `backtest.py` 默认用"综合"。一旦切到"综合"，LHB 立刻在 109 天贡献 ±8 分——**未经验证、未经门禁**。
- 故 commit 的"权重表无 lhb 键（策略层亦死）**不准确**——准确说是"活跃策略（基本面+）无 lhb 键"。

## 激活剩余前置（回填后更新）
1. ~~数据回填~~ ✅ 今日完成
2. ~~≥60 交易日~~ ✅ 达成（109 天）
3. **权重登记**（老三/FactorRegistry）— 未做
4. **132 日 on/off 对照重跑**（"零差异"前提已被回填推翻，将现差异须评估）— 未做
5. **point-in-time 口径确认**：当日口径仅在"S 日收盘后决定 S+1 持仓"时成立，否则构成前视——需总管/老三明确决策时点

## 代码质量遗留（HEAD 现态，供落地）
- **P2 OverflowError 未捕获**：`_lhb_parse_file` L198 只 catch `(TypeError,ValueError)`，超大 `上榜日` 抛 `OverflowError` 会崩整个回测 → 建议补进 except
- **P2 listdir 热路径**：`read_lhb_signal` 每次调用都 `os.listdir`+`sorted`，回测 ~30 万+ 次冗余扫描 → 建议模块级缓存 + mtime 失效
- ~~P2 缓存 mtime~~ ✅ a9b0497a 已修

## 范围外发现（deep review 顺带，来自中间 commit ca844c23，非本次两目标）
- **P1** `board_server.py` `_approved` NameError：review_status.json 缺失/损坏时整看板 500（旧代码能优雅降级）
- **P2** `generate_dashboard.py` L442 f-string else 分支缺 `f` 前缀 → `{max_dd}` 原样渲染
- P3 死 `review` load、重复 `_rg.evaluate`

**路由建议**：ca844c23 的 bug 不在本 R0 范围，建议总管裁定并入"回填+132日门禁"批次或另开单。

---
*纯评审，按规则智能化自行出结论，未改任何代码；留痕于 `dashboards/review-laowu.md`。*