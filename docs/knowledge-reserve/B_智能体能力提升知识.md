# 方向 B · 智能体（AI Agent）能力提升知识

**作者**：总管 ｜ **日期**：2026-08-31 ｜ **用途**：储备知识，供三方评审时参考

---

## 摘要（100 字内）

本方向聚焦 LLM Agent 的记忆架构、Skill 系统、多 Agent 协作。核心洞察：Procedural Memory（程序记忆）是 Agent 能力复利层，Anthropic Skills + Memento-Skills 已验证"Skill-as-Memory"可行；ClawHavoc 攻击警示供应链风险，需信任分层。

---

## 核心知识点（5 条）

### 1. Procedural Memory 是 Agent 能力复利的关键层
CoALA 记忆分类学：Working / Episodic / Semantic / Procedural 四类。Procedural Memory（"如何做"）包含 system prompt 规则、playbook、skills、runbook。**关键洞察**：Explicit procedural memory（agent 自己的代码和 prompts）是唯一能"设计表面"的层——隐式的在 LLM 权重里改不了。Anthropic Agent Skills 就是这个层的最佳实现：progressive disclosure（先加载描述，触发时才加载完整内容）。

**zhuanqian 现状**：106 skills 已装（builtin 72 + zhuanqian 33 + community 3），但未建立"从成功案例提取 procedural memory"的自动化 pipeline。

来源：https://hidekazu-konishi.com/entry/ai_agent_memory_design_guide.html

### 2. Memento-Skills 证明"Skill-as-Memory"可行
Memento-Teams 2026 论文（arxiv 2603.18743）：skill folder（code + prompts + declarative specs）作为持久记忆单元，Read-Write Reflective Learning 闭环让 agent 从经验中自进化。**实验结果**：GAIA benchmark +26.2%，HLE benchmark +116.2%，全程无需更新 LLM 参数。

**zhuanqian 现状**：v2 evolution 是"因子权重自进化"，但 skill 库本身是静态的。建议 09-30 前评估是否引入"skill 库自进化"（每次三方讨论后自动更新 SKILL.md）。

来源：https://www.arxiv.org/pdf/2603.18743

### 3. Agentic Memory（ACL 2026）：LTM+STM 统一管理
Yu et al. 2026 提出 Agentic Memory 框架：把 memory 操作（store/retrieve/update/summarize/discard）暴露为 tool-based actions，让 LLM 自主决定何时读写。三阶段 progressive RL + 步进式 GRPO 训练。**zhuanqian 现状**：memory-management 被 DANGEROUS 拦截未装，但 Hermes 自带 memory 工具已够用；建议不装，避免过度工程。

来源：https://aclanthology.org/2026.acl-long.981/

### 4. ClawHavoc 攻击警示：Skill 供应链是头号风险
arxiv 2602.20867 论文映射 7 种 skill 设计模式（metadata / code-as-skill / workflow / self-evolving / hybrid / marketplace 等）。**ClawHub 攻击案例**：1200 个恶意 skill 侵入主流 marketplace，恶意率 36.8%，窃取 API keys/加密钱包/浏览器凭证。**信任分层模型**：Tier-1（内置）/ Tier-2（社区）/ Tier-3（用户生成），Tier-2 instruction access 最易被 prompt injection 攻击。

**zhuanqian 现状**：R2 HARD_RED_LINES 自审计 SHA256 已覆盖内置 skill，但 community skill（code-review / reason / critical-thinking）未做供应链审计。建议 09-30 前给 3 个 community skill 做人工审查 + hash 锁。

来源：https://arxiv.org/html/2602.20867v1

### 5. Anthropic 官方 Claude for Financial Services（10 个金融 skill）
anthropics/financial-services 仓库 2026-05-05 发布，48 小时 9.3k stars。7 个垂直 skill bundle：financial-analysis（核心）/ investment-banking / equity-research / private-equity / wealth-management / fund-admin / operations。11 个 MCP 数据连接器（Daloopa / Morningstar / S&P / FactSet / Moody's 等）。**zhuanqian 现状**：自建 zhuanqian skill 24 个，方向偏 A 股专属，与官方金融 skill 无直接重叠。建议不装（数据源不匹配），但可参考其 equity-research skill 的 earnings note / thesis tracking 模板设计。

来源：https://repos.skila.ai/skills/claude-for-financial-services

---

## 对 zhuanqian 的可落地建议（3 条）

### 建议 B1（P1）：给 3 个 community skill 做供应链审计
- **动作**：code-review / reason / critical-thinking 做人工审查，SHA256 hash 锁进 red_lines_hash.json
- **验收**：篡改任一 skill → evolution_v2.py 自审计 exit 1
- **优先级依据**：ClawHavoc 攻击已发生，社区 skill 是最大风险面

### 建议 B2（P2）：评估 skill 库自进化（09-30 前）
- **动作**：三方讨论后自动生成 SKILL.md 补丁建议（不自动应用）
- **验收**：三方评审前人工确认
- **优先级依据**：Memento-Skills 证明可行，但需人工 gate 防止自进化失控

### 建议 B3（P0）：不装 memory-management，保持 Hermes 自带
- **动作**：老大已拍板不装，保持现状
- **验收**：已完成
- **优先级依据**：Agentic Memory 论文虽新，但 Hermes 自带 memory 工具够用，避免过度工程

---

## 参考链接

1. https://hidekazu-konishi.com/entry/ai_agent_memory_design_guide.html — AI Agent Memory Design Guide
2. https://www.arxiv.org/pdf/2603.18743 — Memento-Skills 论文
3. https://aclanthology.org/2026.acl-long.981/ — Agentic Memory（ACL 2026）
4. https://arxiv.org/html/2602.20867v1 — SoK: Agentic Skills（含 ClawHavoc 案例）
5. https://aclanthology.org/2026.acl-long.1709.pdf — MAGMA 多图记忆架构
