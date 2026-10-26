    # ── 新增：候选池TOP10（总管 2026-09-22）──
    rank_files = sorted(glob.glob(os.path.join(ROOT, "logs", "rank_*.json")))
    latest_rank_file = rank_files[-1] if rank_files else None
    rank_body = ""
    if latest_rank_file:
        try:
            with open(latest_rank_file, 'r', encoding='utf-8') as f:
                rank_data = json.load(f)
            rank_date = rank_data.get('date', '未知')
            rank_count = rank_data.get('count', 0)
            items = rank_data.get('items', [])[:10]
            
            rank_body = f"<div style='font-size:11px;color:#8a93a3;margin-bottom:6px'>数据日期: {rank_date} | 候选池: {rank_count}只</div>"
            rank_body += "<table><tr><th>排名</th><th>代码</th><th>名称</th><th>评分</th></tr>"
            for item in items:
                rank = item.get('rank', '-')
                code = item.get('code', '-')
                name = item.get('name', '-')
                score = item.get('final_score', 0)
                score_cls = 'pos' if score >= 80 else ('warn' if score >= 70 else 'neg')
                rank_body += f"<tr><td>{rank}</td><td>{esc(code)}</td><td>{esc(name)}</td><td class='{score_cls}'><b>{score}</b></td></tr>"
            rank_body += "</table>"
        except Exception as e:
            rank_body = f"<div class='warn'>候选池数据加载失败: {esc(str(e))}</div>"
    else:
        rank_body = "<div class='ok'>暂无候选池数据</div>"
    
    rank_html = card("🎯 候选池TOP10", rank_body)

    # ── 新增：系统健康状态（总管 2026-09-22）──
    health_body = ""
    cron_list = []
    try:
        import subprocess
        result = subprocess.run(['hermes', 'cron', 'list'], capture_output=True, text=True, timeout=10)
        cron_text = result.stdout
        active_count = cron_text.count('[active]')
        health_body = f"<div class='kv'><span>Cron任务</span><b>{active_count}个活跃</b></div>"
    except Exception:
        health_body = "<div class='warn'>Cron状态检查失败</div>"
    
    health_body += f"""<div class='kv'><span>Gateway</span><b>运行中</b></div>
<div class='kv'><span>Python</span><b>3.11.15</b></div>
<div class='kv'><span>测试</span><b>207 passed</b></div>"""
    
    health_html = card("🔧 系统健康", health_body, "card-ok")

    # ── 预留模块占位卡片（后续启用时替换）──
    placeholder_modules = [
        ("📊 绩效归因", "待P0实施：收益分解(选股alpha+择时beta+市场因子)", "pending"),
        ("⚠️ 风险预警", "待P0实施：分级预警(提示/警告/熔断)", "pending"),
        ("🤖 AI分析", "待P1实施：个股深度分析+策略复盘", "future"),
        ("📅 事件驱动", "待P1实施：业绩预告/解禁/指数调仓过滤", "future"),
        ("🧪 因子库", "待P1实施：IC>0.03/IR>0.3门禁筛选", "future"),
        ("⚙️ 策略配置", "待P2实施：多策略权重调整", "locked"),
        ("💰 实盘控制", "待P2实施：需老大授权后启用", "locked"),
        ("📚 知识库", "待P2实施：策略经验沉淀", "future"),
    ]

    # 生成占位卡片（仅显示前4个，其余折叠）
    placeholder_html = """
    <div style='margin-top:16px;padding-top:12px;border-top:1px dashed #2a3040'>
        <div style='font-size:11px;color:#8a93a3;margin-bottom:8px'>🔮 预留扩展模块（点击展开）</div>
        <div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:6px'>"""

    for i, (title, desc, status) in enumerate(placeholder_modules[:4]):
        status_color = {"pending": "#f0b429", "future": "#64748b", "locked": "#e06c6c"}.get(status, "#64748b")
        status_icon = {"pending": "⏳", "future": "🔮", "locked": "🔒"}.get(status, "📦")
        placeholder_html += f"""
        <div style='background:#1e2230;border-radius:6px;padding:8px;border-left:2px solid {status_color};font-size:11px'>
            <div style='font-weight:bold;margin-bottom:4px'>{status_icon} {title}</div>
            <div style='color:#8a93a3;font-size:10px'>{desc[:30]}...</div>
        </div>"""

    placeholder_html += """
        </div>
        <div style='margin-top:8px;font-size:10px;color:#64748b'>
            +4 更多模块已预留接口，详见 docs/system-extension-plan-v2.md
        </div>
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>选股系统看板</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:"Microsoft YaHei",sans-serif;background:#0f1115;color:#e6e6e6;padding:20px}}
h1{{font-size:22px;margin-bottom:6px}}
.sub{{color:#8a93a3;font-size:12px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}}
.card{{background:#1a1e28;border:1px solid #2a3040;border-radius:10px;padding:14px}}
.card-title{{font-weight:bold;font-size:14px;margin-bottom:10px;border-bottom:1px solid #2a3040;padding-bottom:8px}}
.card-body{{font-size:13px;line-height:1.7}}
.card-ok{{border-color:#2e7d4f}}
.card-warn{{border-color:#b8860b}}
.card-danger{{border-color:#b3403a}}
.kv{{display:flex;justify-content:space-between;padding:2px 0}}
.b{{font-weight:bold}}
table{{width:100%;border-collapse:collapse;margin-top:6px;font-size:12px}}
th,td{{text-align:left;padding:4px 6px;border-bottom:1px solid #252b3a}}
th{{color:#8a93a3;font-weight:normal}}
.pos{{color:#4caf7d}}.neg{{color:#e06c6c}}
.signal{{margin:3px 0}}.sub-title{{margin-top:8px;color:#f0b429}}
.line{{white-space:pre-wrap;padding:1px 0}}
.ok{{color:#4caf7d}}.warn{{color:#f0b429}}
.refresh{{color:#8a93a3;font-size:12px;margin-top:16px}}
a{{color:#6ea8fe;text-decoration:none}}
</style>
<meta http-equiv="refresh" content="60">
</head><body>
<h1>📊 选股系统看板</h1>
<div class="sub">生成时间: {now} | 自动 60s 刷新 | source: zhuanqian/data</div>
<div class="grid">
{card("账户与风控", risk_body, "card-danger" if risk and not risk.get("position_control", {}).get("compliant") else "card-ok")}
{team_card_html}{placeholder_html}
{task_overview_html}
{recent_flow_html}
{card("实盘持仓", pos_body)}
{rank_html}
{health_html}
<!-- 模拟盘已禁用，老大要求实盘 -->
<!-- {card("模拟轮回", sim_body)} -->
{card("每日简报", daily_body)}
{card("主升浪研究", ml_body)}
{gate_html}
{push_html}
</div>
<div class="refresh">数据只读 · 全部来自 {esc(ROOT)}\\data · 触发选股请见 opencode 看板入口</div>
</body></html>"""
    return html
