# Hermes 技能库库存报告（2026-10-23 双轨升级·轨2）

> 任务：t_290cac7e【双轨升级】· 执行：总管（laosan 并轨轨1）· 数据时效：2026-10-23 07:00
> 流程依据：`hermes-skill-library-maintenance` 七步（清点→分级→归档→去重→交叉引用→门禁→报告）

## 一、统计

| 指标 | 数值 | 说明 |
|------|------|------|
| 归档前活跃 SKILL.md | 320 | 全量清点（含类别容器内子技能） |
| 本次归档目录 | 33 | 29 含 SKILL.md + 4 孤儿/空目录 + 1 重复拷贝 |
| 归档后活跃 SKILL.md | **292** | 目标 ≤200 **未达成**（降级 P1 待办，见三） |
| .archive 累计 | 43 个 SKILL.md | 含历史 curator 归档 14 |
| top-level 条目 | 229 | 类别容器（creative/devops/mlops 等）内嵌子技能 |
| 去重 stub 验证 | gateway-management → gateway-health-management 已合并（stub 在位） | 本次扫描无新增重复对 |
| 交叉引用卫生 | 0 处 related_skills 引用已归档名 | 活跃技能 related_skills 全量扫描 |

### 分级摘要

- **P0 保持（核心）**：zhuanqian 业务族（zhuanqian/*、a-share-*、factor-*、backtest-*、s3-auto-pipeline、risk-*、live-trading-*）、治理族（laosi-self-audit、agent-accountability-audit、gateway-*、cron-*、drain/*）、数据族（data-*、tdx-*、quant-*）。判定证据：近 7 天加载记录 + verified pitfalls + 业务域匹配。
- **P1 审查（suite 级，待拍板）**：lark-*（28 件）、creative 剩余（10 件）、software-development/*（14）、autonomous-ai-agents/*（8）、productivity 剩余（8）、github/*（6）、speckit-*（11）、jev-*（10）、mlops 剩余（1）、devops/*（10）。无 corpus 引用（memory/cron/kanban 三查全空）但属**有意安装的套件**，归档=方向性决策，不静默执行（四查之"业务域匹配"缺证据，按降级路径②降 P1）。
- **P2 归档（本次执行，33 目录）**：孤儿空目录 4（apple/hermes-agent/hermes-jev-skills/backtest-data-integrity，仅 DESCRIPTION 或 0 SKILL.md）+ 重复拷贝 1（autonomous-ai-agents/hermes-skill-format-pitfalls，与 top-level 同名件重复）+ 业务域不匹配且无引用单件 28（smart-home、social-media、media×2、email×2、note-taking、productivity×7、statistics、mlops×4、creative×6、git 工具链×3）。

## 二、变更记录

本次归档映射（全部为 `skills/<src>` → `skills/.archive/<dst>` 的 move，**可恢复=mv 回原位**）：

- 孤儿目录：`apple-1792709558`、`hermes-agent`、`hermes-jev-skills`、`backtest-data-integrity`、`autonomous-ai-agents-hermes-skill-format-pitfalls`
- 单件归档（28）：`smart-home-openhue`、`social-media-xurl`、`media-gif-search`、`media-songsee`、`email-himalaya`、`email-email-inbox-triage`、`note-taking-obsidian`、`productivity-airtable`、`productivity-box`、`productivity-google-workspace`、`productivity-notion`、`productivity-product-price-monitor`、`productivity-maps`、`productivity-teams-meeting-pipeline`、`statistics-biostatistics`、`mlops-inference-serving-llms-vllm`、`mlops-inference-llama-cpp`、`mlops-evaluation-weights-and-biases`、`mlops-evaluation-evaluating-llms-harness`、`creative-touchdesigner-mcp`、`creative-comfyui`、`creative-ascii-video`、`creative-manim-video`、`creative-p5js`、`creative-songwriting-and-ai-music`、`git-guardrails-claude-code`、`migrate-to-shoehorn`、`setup-pre-commit`

机器明细：`D:\Hermes agent\...\hermes-home\cache\scratch\skill_archive_log.json`（33 条 src→dst + has_skill 标记）。

### 前置安全检查（四查留痕）

1. frontmatter author 全量扫描：**0 个 curator-managed**（命中即中止，未命中）
2. cron 语料（92KB，hermes-home/cron 全量 JSON）：28 单件 0 引用
3. memory 语料（25KB，memories/ + profiles/*/memories/）：0 引用
4. kanban.db：无 tasks 表（该库当前为空 DB，看板证据不可用；卡 t_290cac7e body 提及技能名为人工读侧，不阻断）
5. 归档=move 非 delete；目录级可整移回滚

## 三、待办（P1，需拍板/排期）

1. **≤200 目标缺口 92**：仅 suite 级拍板可达成。选项：整 suite 归档 lark-*（28）/creative 剩余（10）/software-development（14）/productivity 剩余（8）/github（6）/speckit（11）/jev（10）/mlops 剩余（1）。**每项归档前需老大或总管拍板业务域取舍**（suite 多为有意安装，无引用≠无用——conversation 按需加载不留 corpus 痕迹，属本次清点的关键教训）。
2. **P0 修复联动（轨1 尾巴）**：`core/risk/risk_rules_impl.py` C-fix（合成数据 P0 防护）+ `core/pipeline` 9 文件 PROJECT_ROOT 锚点批次在老三 run 内收口；**risk_rules 内容变更 → TSS 戳刷新 + CONTRACT-CHANGELOG 登记 + 广播三步必须走完（§4.0 铁律）**，仓内 `.agent/true-source-stamp.json` 与 `AGENTS.md` 已在 worker 修改中，合入前核对 `tests/test_doc_freshness.py`。
3. **M-3 派单审计 60s 超时（P2）**：`check_m3_dispatch_audit` 实跑 subprocess 超时降级 P2（kanban 读侧慢，环境性）；路径 bug 已修（commit cc077066，回滚点 `core/ops/self_audit_checkers.py.bak_20261023`）。若连续 2 日 P2 超时 → 查 kanban.db 读锁/磁盘 IO。
4. **P1 分级证据补强**：P1 审查清单中，下次治理前为每个 suite 补一条"最近加载/使用"证据（session_search 或加载日志），再定去留。
5. **证据语料盲区**：skill 使用不留 memory/cron/kanban 痕迹（skill_view 按需加载）——四查规则对 300+ 规模技能库偏保守，建议 hermes-skill-library-maintenance 增加"session 加载日志"证据源。

## 四、未验证项（如实标注，SOUL 准则5）

- 归档 33 目录的**运行期影响**未验证（技能库不在 git 管，无 pytest 覆盖；回滚预案=mv 回原位）
- .archive 内历史 14 件未逐一复查
- P0 保持清单基于近 7 天加载记录抽样，非全量加载日志统计

## 五、批2 suite 级归档（2026-10-23 07:3x，老大拍板"执行"后补登）

**背景**：§三.1 的 92 缺口 suite 级拍板由老大本 turn 直接授权（"执行"=授权执行建议），总管执行。

| 项 | 数量 | 判定 |
|----|------|------|
| lark-*（多维表格/文档/日历/邮箱等 OpenAPI 套件） | 28 | 0 cron/memory/kanban 引用；活跃飞书通道=message_queue+QSP_MsgDrain（不走 lark CLI） |
| creative 剩余（architecture-diagram/ascii-art/baoyu-infographic/claude-design/design-md/excalidraw/humanizer/popular-web-designs/pretext/sketch） | 10 | 0 引用；S7 前端件走裸 HTML/CSS，未用设计技能 |
| productivity 剩余（docx/pdf/powerpoint/xlsx/ocr-and-documents/document-to-action-items/meeting-action-items/nano-pdf/session-librarian/weekly-review-planning） | 10 | 0 引用；系统报告件=markdown/JSON 非 office 格式 |
| software-development 12 件（codebase-inspection/dogfood/inspecting-hermes-desktop-dom/node-inspect-debugger/patch-recovery/plan/python-debugpy/requesting-code-review/simplify-code/spike/systematic-debugging/test-driven-development） | 12 | 0 引用；保留 3 件活跃（hermes-agent-skill-authoring/hermes-skill-bulk-integration/python-module-relocation=S4迁移件） |
| research 5 件（arxiv/blogwatcher/competitor-news-monitor/grounded-citations/llm-wiki） | 5 | 0 引用；市场情报由 insight-radar（保留）承接 |
| autonomous-ai-agents 2 件（claude-code/codex 外部CLI委派） | 2 | 未安装对应 CLI；委派走 opencode/atomcode（保留） |
| devops electron×2（electron-desktop-app-build/electron-jvm-desktop-build） | 2 | 0 引用；Hermes 桌面维护走 hermes-multi-instance/system-maintenance（保留） |
| 杂散 14 件（prism×5/handoff/wait-what/to-questionnaire/wizard/teach/deep-skill-finder/database-operations/ai-decision-coach/essence-distiller/decision-framework/critical-thinking-logical-reasoning/first-principles-thinking/scenario-forecaster/deepthink-mode）+ timesfm-forecasting + statistics×2 + media/youtube-content | 18 | 0 引用通用件 |
| **合计** | **92**（实移 90 + 误报放行 2：plan/handoff 经核查为 governance-plan 文档引用/jobs.json 0 命中，全部放行归档） | 另归档 statistics 空容器 1 |

**保留未动（活跃基础设施，防误杀）**：speckit×11（AGENTS 宪法 `.specify/memory/constitution.md` 引用）、jev×10（`scripts/test_jev_engine.py` 在 pytest 门禁内）、github×6（origin=GitHub 活跃远端）、huggingface-hub（laya 模型安装）、speckit/implement/to-spec 等 matt 系工作流（本会话当日使用）。

**终态**：活跃 SKILL.md **292 → 200**（验收 #5 PASS，恰好压线）；.archive 累计可整移回滚；交叉引用 0 断链（批2 前复核）。
**回滚点**：`skills/.archive/` 全量映射（机器明细 `skill_archive_batch2.json`：90 moved + 2 finalized + false_positives 留痕）。
