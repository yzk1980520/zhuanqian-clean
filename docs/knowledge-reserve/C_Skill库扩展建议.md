# 方向 C · Skill 库扩展建议

**作者**：总管 ｜ **日期**：2026-08-31 ｜ **用途**：储备知识，供三方评审时参考

---

## 摘要（100 字内）

Anthropic 官方已发布 17 个 Claude Skills（504+ 生态），A 股量化专属 skill 生态尚未成型。本方向给出"值得装/不值得装/自建"三分法建议，避免重复造轮子也避免供应链风险。核心原则：内置 skill 优先，community skill 需审查，自建 skill 需走门禁。

---

## 核心知识点（4 条）

### 1. Anthropic 官方 Skills（17 个，Apache 2.0）
anthropics/skills 仓库 135k+ stars，17 个官方 skill 覆盖：文档创建（pdf/docx/pptx/xlsx）、设计（canvas/brand/theme）、工程（API helper/MCP builder/webapp testing）、内容（algorithmic-art/internal-comms/slack-gif）。**zhuanqian 现状**：未装任何官方 skill。建议装 3 个：pdf（报告导出）+ xlsx（回测数据导出）+ canvas（可视化）。

来源：https://mastering-claude.com/skills

### 2. Claude Code Skills Library（504+ 生态）
除了 anthropics/skills 官方 17 个，社区已扩展到 504+ skill。obra/superpowers（14 个流程 skill：brainstorm/plan/TDD/debug/review/verify）是参考实现。**zhuanqian 现状**：已装 3 个 community skill（code-review / reason / critical-thinking），覆盖了 review/decision/analysis 三大场景，暂不需要再加。

来源：https://mastering-claude.com/skills

### 3. A 股量化专属 Skill 生态尚未成型
QuantsPlaybook（22+ 策略）+ 优矿（600+ 因子）是开源参考，但无成熟的"量化 skill 库"。zhuanqian 自建 24 个 skill（stock-screening / factor-gate / risk-management / rollback-playbook 等）已是 A 股量化 skill 生态最完整的实现。**建议**：不主动扩展社区量化 skill，专注自建 zhuanqian skill 深化。

### 4. Anthropic Claude for Financial Services（10 个金融 skill）
2026-05-05 发布，Apache 2.0，48h 9.3k stars。7 个垂直 bundle + 11 个 MCP 数据连接器。但**数据源不匹配**：Daloopa/Morningstar/S&P/FactSet 全是美股数据源，zhuanqian 用 TDX + akshare + FTShare，无法直接用。**建议**：不装，但可参考其 skill 设计模式（modular / versioned / with test cases）。

来源：https://repos.skila.ai/skills/claude-for-financial-services

---

## 对 zhuanqian 的可落地建议（3 条）

### 建议 C1（P1）：装 3 个 Anthropic 官方 skill
- **动作**：pdf（报告导出）+ xlsx（回测数据导出）+ canvas（可视化）
- **验收**：evolution_v2.py 每季度白皮书能直接导出 PDF/XLSX
- **优先级依据**：官方 Apache 2.0，无供应链风险，直接提升报告质量
- **预计工时**：0.5 日（总管派单执行）

### 建议 C2（P0）：不装 Claude for Financial Services
- **动作**：老大已确认方向，数据源不匹配
- **验收**：已决
- **优先级依据**：Daloopa/Morningstar 是美股数据源，zhuanqian 用 TDX，装了也用不上

### 建议 C3（P2）：聚焦自建 zhuanqian skill 深化
- **动作**：R5 atomic_json（09-05 前）+ R7 walk-forward（09-30 前）+ R8 结构化字段（09-30 前）
- **验收**：evolution_v2.py 从 73.9K 演进到 80K+，覆盖 6 大能力
- **优先级依据**：自建 skill 是 zhuanqian 护城河，社区量化 skill 生态不成熟

---

## 参考链接

1. https://mastering-claude.com/skills — Claude Code Skills Library 504+
2. https://beginnersinai.org/anthropic-skills-library — Anthropic 官方 Skills 全目录
3. https://usingclaude.com/en/library/skills/claude-skills-library — Claude Skills 来源指南
4. https://repos.skila.ai/skills/claude-for-financial-services — Claude for Financial Services
5. https://getaleph.com/answers/claude-skills-finance-guide — Claude Skills for Finance 实用指南
