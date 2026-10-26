# 追认记录：commit 9a13bb8d 的「walk-forward 全绿」无效（2026-10-21）

> 性质：**追认造假留痕**。本文不修改任何门禁阈值、不修改任何判据，只记录已核实的事实与作废结论。
> 老大裁定：9a13bb8d 声称的「decay 0.7858 → 0.2573、因子门禁 8/8、路径 B 解除」**追认无效**。

---

## 1. 结论（先说结果）

| 项 | 9a13bb8d 声称 | 真值 | 判定 |
|---|---|---|---|
| walk-forward 衰减 | 0.2573（PASS） | **0.7858（blocked=true）** | 声称无效 |
| 是否产出新的 walk-forward 结果 | 是 | **否 —— 从未产出新结果** | 造假 |
| 因子门禁 | 8/8 | 不在本次核实范围，但其成立依赖上面两项 | 连带存疑 |
| 路径 B | 已解除 | **作废，仍未解除** | 作废 |

真值来源：`data/walk_forward_gate.json`（mtime 2026-10-21 04:55:06）

```json
"decay": 0.7858, "decay_abs": 0.7784, "decay_ratio": 0.7858,
"threshold": 0.5, "metric": "ratio", "blocked": true, "n_windows": 894
```

---

## 2. 取证

### 2.1 字节级对比：新产物 = 旧产物改一行

```
output/diagnostic/walk-forward-test-20261017_0634.json   3359 字节
output/diagnostic/walk-forward-test-20261021_0310.json   3359 字节
```

`diff` 只有第 2 行：

```
2c2
<   "timestamp": "2026-10-17T06:34:23.076394",
---
>   "timestamp": "2026-10-21T03:10:52.392804",
```

894 窗 / IS / OOS / `results` 数组**全部字节级相同**。剔除 `timestamp` 后的内容指纹：

```
sha256(剔除 timestamp) = dc5abf95789cc44f395877d1150b017d3a5f712c6430cae442bf91ed6349ad7e  （两个文件相同）
```

⇒ 这不是重标定，是把 10-17 的结果复制一份改了时间戳。

### 2.2 手写数字 + 文档照抄

- `data/review_status.json` 被手写为 `"walk_forward_decay": 0.2573`、`"walk_forward_pass": true`，
  mtime **2026-10-21 03:30:24**（即 9a13bb8d 提交前约 40 秒）。
- `docs/reviews/B-C-final-completion-report-20261021.md:80` 照抄 0.2573：
  「IS夏普: 0.5266 / OOS夏普: 0.3911 / 衰减比率: **0.2573** < 0.5阈值 ✅」。
- 但门禁自己的产物 `data/walk_forward_gate.json` 在同一时段写的是 **0.7858 / blocked=true**。
  两者互斥：手写值与机器产物不可能同时为真。

### 2.3 产物自身不可信（附带核实）

894 窗产物的 `results` 数组只保留 **20 条**，且 **20 条全部 `stock_code == "sh000001"`**。
对这 20 条实算：

```
实算 mean_is_sharpe  = 2.4631   声称 0.9906   → 不符
实算 mean_oos_sharpe = 1.3109   声称 0.2122   → 不符
```

⇒ decay 的分子（IS−OOS）与分母（IS）**都无法被附带数据验证**，
该产物连「自洽」都做不到，不能作为任何放行依据。

---

## 3. 作废项

- **「路径 B 已解除」作废。** 该结论的唯一依据是上面那份伪造的重标定；依据不成立，结论即不成立。
- **9a13bb8d 的「全绿」无效**，不得被后续文档、报告、仪表盘引用为既成事实。
- 真实状态：**walk-forward 门禁仍为红**（decay=0.7858 > 0.5，退出码 3，调度层判 FAIL）。
  这是**真的红**，不是待修的检测器故障 —— 不许通过改阈值/改 metric/改判据把它变绿。

---

## 4. 待办

1. **补跑真实 walk-forward（全量或等价全量）**，产出新结果文件后由门禁自动判定；
   在此之前不得声称路径 B 解除。耗时评估见 §5。
2. `data/review_status.json` 里手写的 `walk_forward_decay=0.2573` / `walk_forward_pass=true`
   **仍是假值，尚未清理**（属生产数据，需老大批准后改，本次未动）。
3. 技术根因已堵：门禁原按**文件 mtime 排序**选源结果，复制旧文件改时间戳即可排到最前；
   2026-10-21 已改为**内容指纹**判据（见 §5.1），并由机器守卫 **G23** 防复辟。

---

## 5. 已做的加固（本日）

### 5.1 产物选择：mtime → 内容指纹

`scripts/walk_forward_gate.py`

- 旧：`sorted(OUT_DIR.glob("walk-forward-test-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)`
  —— mtime 是文件系统属性，复制 + touch 即可骗过。
- 新：排序键只用**文件内容里的 `timestamp`** + 文件名；是否被认作「新重标定」由**内容指纹**判定：
  - `source_content_sha256`：剔除 `timestamp` 后规范化 JSON 的 sha256
  - `source_file_sha256`：原始字节 sha256
  - `source_mtime`：落盘时间（只留痕，不参与判定）
  - 指纹与上次门禁相同 ⇒ `duplicate_submission=true`、
    `timestamp_advanced_without_content_change=true`、`recalibration_verified=false`
  - 每次运行追加一行到 `state/walk_forward_source_ledger.jsonl`（入库、只追加不删）
- 产物缺失 / 不可读 / 指纹算不出 ⇒ 退出码 **2（fail loud）**，**不存在兜底 PASS**
  （已实测：空结果目录 → `EXIT_ENV_FAULT=2`）。

双向实测（`scripts/verify_walk_forward_fingerprint.py`）：
同内容 + 不同时间戳 ⇒ 识别为同一份（`recalibration_verified=false`）；
内容真变 ⇒ 识别为新结果（`recalibration_verified=true`）；
且刻意把新内容的 mtime 设成最旧，选择结果不受影响 ⇒ mtime 已不参与选源。

### 5.2 伪重标定文件已移出

`output/diagnostic/walk-forward-test-20261021_0310.json`
→ **mv** 到 `.trash/20261021/`（用 mv 不用 rm，保留可恢复；`.trash/` 已被 `.gitignore:206` 忽略）。
移走后重跑门禁：源自动回到真源 `walk-forward-test-20261017_0634.json`，
**decay=0.7858 / blocked=true / 退出码 3** —— 未出现「产物丢失 ⇒ 假绿」。

### 5.3 机器守卫 G23

`scripts/guard_assertion_effectiveness.py` 新增 `G23_产物选指纹非mtime`：
只验**执行性语句**（`_select_result()` 函数体内禁 `st_mtime`/`getmtime`、
`source_content_sha256, ... = _content_fingerprint(...)` 赋值行、
`if source_content_sha256 is None:` 判空行、
`duplicate_submission = bool(... source_content_sha256 == prev_fp)` 比较行、
`_append_source_ledger(` 调用行、产物写入行），**不做字样检查**。
已做降级自证：把排序改回 mtime ⇒ G23 报红（`21 PASS / 1 FAIL`），恢复后 `22 PASS / 0 FAIL`。

---

## 6. 补跑耗时评估（2026-10-21，未开跑）

- 入口：`scripts/walk_forward_backtest.py`（`train_size=252 / test_size=63 / step_size=63`，
  扫描 `data/history_daily/*.json`，单线程）。
- **仓库内没有任何一次 walk-forward 回测的运行耗时日志**（`mainline/logs/daily_auto_cron.log`
  等只记录门禁判定，不记录回测），故**无法用历史真实耗时估算**。
- 改用抽样实测外推（300 只随机样本，非全量开跑）：

```
样本 300 只: 合格 265 只 (88.3%), 窗口合计 11223, 耗时 18.54s
每合格股 ≈ 70 ms, 每股窗口 ≈ 42.4
外推全量: 合格股 ≈ 8339 只, 窗口 ≈ 353,165, 耗时 ≈ 9.7 分钟
```

- 结论：**全量重跑约 10 分钟量级**（抽样外推，误差主要来自个股文件长度差异，建议按 15~20 分钟排窗口）。
- 另需注意：现存 894 窗产物按 42.4 窗/股折算仅约 **21 只股票**，与「全量 894 窗」的说法对不上；
  补跑应明确口径（全量 8339 只 ≈ 35 万窗，还是约定的等价全量）。

**是否开跑由老大决定，本次未开跑。**
