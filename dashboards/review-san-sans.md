# 御龙决 · 持仓日报交付质量审查

**审查人**: 审查官 (独立子代理)
**审查时间**: 2026-09-02
**审查范围**:
- `dashboards/warroom.html` — VChart 作战台
- `scripts/position_card.py` — 边框盒日报生成器
- `scripts/daily_stock_report_v2.py` — 日报组装器
- `scripts/send_to_feishu.py` — 飞书发送通道
- `scripts/vchart_feishu.py` — VChart → PNG → 飞书图片

---

## 总评分：58 / 100

| 维度 | 权重 | 得分 | 说明 |
|------|------|------|------|
| 数据一致性 | 25% | 12 | 存在死代码（`get_tdx_peak_high` 未定义）、持仓K线数值未标注数据源新鲜度 |
| 渲染完整性 | 20% | 14 | warroom.html 是**静态 HTML 内嵌值**，非动态生成，超过 24h 即过时 |
| 飞书送达 | 25% | 17 | **P0**：`format_card_boxed` 调用未定义函数会崩溃；emoji 破坏 monospace 边框对齐 |
| 安全合规 | 10% | 8  | Chat ID 明文写在代码里（非密钥级问题但不可告人） |
| 生成器健壮性 | 20% | 7  | 有 TDX 兜底但存在函数签名漂移（`format_all_cards` 被覆盖），空持仓/网络失败兜底不够完整 |

---

## 问题清单

### P0（阻断级 — 立即修复）

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| P0-1 | `position_card.py:438` | **`format_card_boxed()` 中调用了不存在的 `get_tdx_peak_high(code)` 函数**，脚本范围内搜索 `def get_tdx_peak_high` 结果为 0 个匹配 | 当持仓当前价 > 0 但 `holding.get('high')` 为 0 时，代码会执行到 `NameError: name 'get_tdx_peak_high' is not defined`，**整个日报渲染直接崩溃** |
| P0-2 | `position_card.py:513` | **函数名复用覆盖**：`format_all_cards` 在 `:276` 定义（emoji 版，签名 `format_all_cards(today=None)`），又在 `:513` 重新定义（boxed 版，签名 `format_all_cards(today=None, *, use_boxed=True)`），后者覆盖前者 | `daily_stock_report_v2.py:29` import 的 `format_all_cards` 是后者 boxed 版，会经过 P0-1 的死代码路径；`--all` 单跑也能崩 |
| P0-3 | `send_to_feishu.py:70` | **`--` 开头的行被正则剥离**：`lines = [l for l in lines if not re.match(r'^\s*--', l)]` | 飞书消息正文中的合法横线/删除线/代码块行首的 `--` 会被误删；报告内 markdown 表格分隔行 `|---|---|` 也受影响 |

### P1（严重 — 应尽快修复）

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| P1-1 | `warroom.html` 全文 | **HTML 是全静态内嵌**：所有 K 线数据、雷达值、WF 表、市场评分、环境门状态都是直接写死的 JS 数组，没有 `fetch()` 也没有外部 JSON | 超过 24 小时数据即过时；`meta` 显示 "生成 2026-09-02 04:28" 但无任何数据刷新机制；无法通过 cron 自动更新 |
| P1-2 | `send_to_feishu.py:54` | **函数签名漂移**：`send_to_feishu.py:54` 定义为 `def send_to_feishu(text) -> bool`（单参），但 `daily_stock_report_v2.py:97` 调用时传了 `send_to_feishu(markdown_report, markdown=True)`（带 `markdown=True` 关键字） | 该调用 **TypeError: unexpected keyword argument 'markdown'**，日报永远不会发飞书 |
| P1-3 | `vchart_feishu.py:134` | **`lark-cli --image` 路径契约违背**：脚本 docstring 声明"lark-cli --image 只接受 cwd 相对路径"，但实际传的是裸文件名 `png_rel_path`（如 `sh600195_position_chart.png`），并依赖 `cwd=PROJECT_DIR`；然而 `subprocess.run` 的 `cwd` 是工作目录而非"图片路径的基目录"——只要 `PROJECT_DIR` 与图片文件实际路径一致即可，但如果后续把 PNG 存到子目录就会失效 | 单看当前逻辑能跑通（PNG 存在 PROJECT_DIR 根目录），但脆弱、无测试、注释承诺不兑现 |
| P1-4 | `position_card.py:102-105` | **`get_active_ladder()` 最后一档返回类型漂移**：循环体内返回 `(upper, tol * 100)`（`tol=0.25` → 25.0），但函数末尾 `return GRADED_TP_LADDER[-1]` 直接返回原始 `(999, 0.25)`（`tol` 未乘 100，是浮点数 0.25 而非 25.0） | 当 `pnl_pct >= 999`（实际不可能，但逻辑存在）时 `active_tol=0.25`，所有 `drawdown_pct >= 0.25` 都会误触发移动止盈 |
| P1-5 | `position_card.py:326-392` | **`draw_box()` 边框盒对齐只处理了 ASCII 半角和 CJK 全角的宽度**，但报告里大量使用 **emoji**（✅ ❌ ⚠️ 🟢 🔴 🟡 💰 📊 📦 📭），这些在飞书 monospace 渲染中占位不可预测 | 边框盒的 `│ ... │` 列对齐会乱，用户看到的飞书卡片视觉错位、边框断裂 |

### P2（一般 — 建议改进）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| P2-1 | `send_to_feishu.py:37` | `CHAT_ID_DEFAULT = "oc_14afb6be0ca08917aca8083036835d9c"` 明文写在源码 | 通过环境变量/配置文件注入，或写入 `data/feishu_config.json`（.gitignore 已排除） |
| P2-2 | `vchart_feishu.py:28,29` | 同样的 `LARK_CLI` 和 `CHAT_ID` 常量重复硬编码 | 与 `send_to_feishu.py` 共用配置模块 |
| P2-3 | `send_to_feishu.py:64` | **3000 字符硬截断**：`text = text[:3000] + "\n…[已截断]"` | 日报含边框盒+持仓+汇总时很容易超 3000 字，应改为按消息段拆分发送或用飞书富文本 |
| P2-4 | `vchart_feishu.py:113` | PNG 文件名仅含股票代码（`sh600195_position_chart.png`），**每次运行覆盖** | 加日期戳 `sh600195_20260902.png`，方便历史回溯和飞书消息去重 |
| P2-5 | `daily_stock_report_v2.py:35` | `FEISHU_ENABLED` 读取 `SEND_TO_FEISHU` 环境变量，但脚本 docstring 未列出此变量 | docstring 补齐 |
| P2-6 | `warroom.html` | footer 声明 "数据源：TDX + holdings + market_state_cache + backtest_result + walk_forward"，但 HTML 无任何动态数据拉取逻辑 | 应改成服务端渲染（模板引擎），或在页首加 `last_updated` 时间戳 + 手动刷新按钮 |
| P2-7 | `position_card.py:52,67-69` | `get_tdx_price()` 失败时打印到 stderr，但**不记录到日志文件** | 加 `logging` 模块并输出到 `logs/position_card.log` |
| P2-8 | `send_to_feishu.py` 导出给 `daily_stock_report_v2` 用，但函数名 + 包名冲突（脚本名 = 函数名），Python 中 `import send_to_feishu` 会触发模块自身的 `if __name__ == "__main__": main()` 守卫——**实际不会**因为 `__name__` 是模块名而非 `"__main__"` | 命名冲突有隐患，建议改名为 `feishu_sender.py` 或内部函数改名为 `dispatch_to_feishu()` |

---

## 改进建议

### 立即修复（P0/P1）

1. **补全 `get_tdx_peak_high()` 或删除调用**（P0-1）
   - 最简单方案：删除 `:438` 这行，让 `peak_high` 保持 `tdx_peak` 或 `current` fallback
   - 或新增函数：`def get_tdx_peak_high(code): data = get_tdx_data(code, days=30); return max(d["high"] for d in data) if data else 0`

2. **拆分 `format_all_cards` 两个实现**（P0-2）
   - 改名为 `format_all_cards_emoji()` 和 `format_all_cards_boxed()`，避免覆盖

3. **修正 `send_to_feishu` 签名**（P1-2）
   - `send_to_feishu.py:54` 加 `*, markdown: bool = False` 参数，或修改 `daily_stock_report_v2.py:97` 去掉 `markdown=True`
   - 当前 `markdown=True` 参数完全无效（函数不支持），代码块围栏 ````` 包裹是手动做的，说明设计意图存在但实现断裂

4. **移除 P0-3 的 `--` 清洗规则**，或仅对 `lark-cli` 参数位置做保护（lark-cli 的 `--text` 之后的文本不应被二次解析为 flag）

5. **`draw_box()` 改用等宽宽度更稳定的排版**：把 emoji 状态图标移到行首或行尾的独立列，不参与边框盒内对齐计算

### 中期改进（P1 渲染 + 架构）

6. **`warroom.html` 改为服务端模板渲染**：`build_dashboard.py` 已存在，应检查它是否负责注入数据；若没有，则新建 `build_warroom.py` 从 `data/*.json` 读数据、渲染 Jinja2 模板输出 HTML

7. **统一飞书配置模块**：新建 `config/feishu.py` 集中管理 `CHAT_ID`、`LARK_CLI`、超时秒数

8. **日报发送做幂等+分段**：消息 > 1500 字符时分段发送；发送成功后返回 `message_id` 供 cron 断言

### 长期

9. **VChart 作战台数据契约**：明确 warroom.html 应该消费哪个 JSON 文件、cron 由谁触发、刷新频率

10. **端到端测试**：`test_position_card.py` 已存在但应覆盖 `format_card_boxed()` 路径和 `get_tdx_peak_high` 缺失边界

---

## 代码级关键片段标注

```
# P0-1: position_card.py:438  — get_tdx_peak_high 未定义
    if peak_high <= 0:
        peak_high = get_tdx_peak_high(code)  # ← NameError

# P0-2: position_card.py:276 vs :513 — 同名函数覆盖
    def format_all_cards(today: date = None) -> str:           # :276 emoji 版
    ...
    def format_all_cards(today=None, *, use_boxed: bool = True):  # :513 boxed 版 ← 被 import 的

# P1-2: daily_stock_report_v2.py:97 vs send_to_feishu.py:54
    result = send_to_feishu(markdown_report, markdown=True)   # ← TypeError
    def send_to_feishu(text: str) -> bool:                    # ← 只有 text 参数
```

---

## 结论

**当前交付不可用于生产飞书日报**：P0-1/P0-2/P1-2 三个问题中任意一个都会导致 `daily_stock_report_v2.py` 运行时崩溃，飞书消息根本发不出去。VChart 作战台数据是静态内嵌，无法自动刷新。

建议先修复 P0 三项（约 20 行代码改动），再解决 P1-1/3/5（约 80 行改动），然后日报链路才能真正稳定运行。修复后重审评分预估可达 **85+**。
